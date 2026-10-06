"""Price data for any instrument, built from TradingView chart exports (and, optionally, bars from the TradingView MCP).

usage: prices.py ingest [--rebuild]          read every export in the configured folders (only changed files cost time)
       prices.py status                      what data is held, per symbol and bar size
       prices.py add SYMBOL INTERVAL FILE    merge bars saved from the TradingView MCP (any usual JSON shape: mcp_bars)
       prices.py export SYMBOL INTERVAL OUT.csv   write one merged CSV of the stored bars (e.g. 1m, 5m)

Exports: in TradingView, open the chart, then "Export chart data…" (CSV). The file name TradingView gives it
("OANDA_DE30EUR, 5.csv", "BINANCE_BTCUSDT, 1 (2).csv") names the symbol; the bar size is read from the data. Any extra
columns on the chart travel with it: a "Volume", "VWAP" or "Kernel Regression Estimate" column is used when present,
and every other indicator column (RSI, MAs, levels…) is kept, under the plot's name, in a separate
"<size>m.indicators.json" beside the bars, for exports of 5 minutes and up (1-minute too with config indicators_1m).
Where exports overlap, the newest file wins, except for its last bar, which may still have been forming.

Bars are KEPT once ingested: deleting an old export does not remove its history. `ingest --rebuild` starts again from
the files present. Where 1m bars exist but coarser ones don't (a gap in the 5m exports, or no 5m exports at all), 5m,
15m, 30m, 60m and 4h bars are built from the 1m bars (4h from the session start: see DERIVED); an exported bar always
wins over a built one.
"""
import bisect, csv, datetime as dt, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

EXTRA = {"volume": "v", "vwap": "vwap", "kernel regression estimate": "kr"}
BASE_COLS = {"time", "open", "high", "low", "close", *EXTRA}
DERIVED = (5, 15, 30, 60, 240)  # bar sizes built from 1m where the exports leave gaps
# 5m-60m are on the clock. 4h is anchored at the symbol's session start (config session_start, default 17:00 New York,
# the FX/CFD rollover), as TradingView builds it: 17:00, 21:00, 01:00 … New York. The day's first and last 4h bar hold
# only the trading inside them (a market that opens at 02:15 or closes at 22:00 gives shorter bars there), and no bar
# crosses into the next trading day.
_cache = {}


def safe(sym):
    return re.sub(r"[^A-Za-z0-9._!-]", "_", sym)


def symbol_from_name(name, known=()):
    """'OANDA_DE30EUR, 5 (1).csv' → 'OANDA:DE30EUR'. An exchange can itself contain an underscore ('CME_MINI_ES1!'),
    so a split that names a symbol already in the config wins; otherwise the first underscore separates."""
    stem = name.rsplit(",", 1)[0].strip() if "," in name else Path(name).stem
    cuts = [m.start() for m in re.finditer("_", stem)]
    cands = [f"{stem[:c]}:{stem[c + 1:]}" for c in cuts]
    return next((c for c in cands if c in known), cands[0] if cands else None)


def _parse_time(s):
    s = s.strip()
    return int(float(s)) if re.fullmatch(r"\d+(\.\d+)?", s) else int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _columns(header, lower=True):
    """Column names, made unique: a second "EMA" becomes "EMA (2)"."""
    seen, out = {}, []
    for c in header:
        k = c.strip().lower() if lower else c.strip(); key = k.lower(); seen[key] = seen.get(key, 0) + 1
        out.append(k if seen[key] == 1 else f"{k} ({seen[key]})")
    return out


def minutes_of(ts):
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    return round(gaps[len(gaps) // 2] / 60) if gaps else None


def label(m):
    return f"{m}m"


def read_export(p, indicators=False):
    """(bars, minutes); with indicators=True, (bars, minutes, rows) where rows are {"t", <plot name>: value} for every
    indicator column other than the ones kept on the bars."""
    with open(p, newline="") as fh:
        r = csv.reader(fh); raw = next(r); head = _columns(raw); names = _columns(raw, lower=False); rows = [x for x in r if x]
    ix = {k: i for i, k in enumerate(head)}
    ind_cols = [(i, names[i]) for i, k in enumerate(head) if k not in BASE_COLS and k.split(" (")[0] not in BASE_COLS]
    ind_rows = []
    if not all(k in ix for k in ("time", "open", "high", "low", "close")): return None, None
    bars = []
    for row in rows:
        try:
            b = {"t": _parse_time(row[ix["time"]]), **{x: float(row[ix[k]]) for x, k in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}}
        except (ValueError, IndexError): continue
        for col, key in EXTRA.items():
            if col in ix and ix[col] < len(row) and row[ix[col]] not in ("", "NaN"):
                try: b[key] = float(row[ix[col]])
                except ValueError: pass
        bars.append(b)
        if indicators and ind_cols:
            x = {"t": b["t"]}
            for i, name in ind_cols:
                if i < len(row) and row[i] not in ("", "NaN"):
                    try: x[name] = round(float(row[i]), 6)
                    except ValueError: pass
            if len(x) > 1: ind_rows.append(x)
    m = minutes_of([b["t"] for b in bars[:200]])
    return (bars, m, ind_rows) if indicators else (bars, m)


def exports():
    out = []
    for d in config.load()["exports_dirs"]:
        d = config.path(d)
        if d and d.exists(): out += [p for p in d.rglob("*.csv") if not p.name.startswith(("~", "."))]
    return out


def _group_file(sym, m): return config.DATA / safe(sym) / f"{label(m)}.json"
def _ind_file(sym, m): return config.DATA / safe(sym) / f"{label(m)}.indicators.json"
def _mcp_file(sym, m): return config.DATA / safe(sym) / f"mcp_{label(m)}.json"


def _merge(sources):
    """sources: [(bars, mtime)] — later mtimes win, except a newer file's last bar never replaces an existing one."""
    out = {}
    for bars, _ in sorted(sources, key=lambda s: s[1]):
        for n, b in enumerate(bars):
            if n == len(bars) - 1 and b["t"] in out: continue
            out[b["t"]] = b
    return [out[t] for t in sorted(out)]


def ingest(verbose=True, fresh=False):
    reg = {} if fresh else load_registry(); known = set(config.load()["symbols"])
    files = exports(); changed = set(); entries = {}
    for p in files:
        sig = [p.stat().st_mtime, p.stat().st_size]; prev = reg.get(str(p))
        if prev and prev["sig"] == sig and prev.get("ind"): entries[str(p)] = prev; continue  # "ind": indicator columns read
        sym = symbol_from_name(p.name, known)
        with open(p, newline="") as fh:
            r = csv.reader(fh); head = _columns(next(r, []))
            ts = []
            for row in r:
                if len(ts) >= 200: break
                try: ts.append(_parse_time(row[head.index("time")]))
                except (ValueError, IndexError): pass
        m = minutes_of(ts)
        if not sym or not m:
            if verbose: print(f"skipped {p.name}: not a TradingView export (no symbol in the name or no time column)")
            continue
        entries[str(p)] = {"sig": sig, "symbol": sym, "minutes": m, "ind": 1}; changed.add((sym, m))
    if fresh:
        for d in (config.DATA.iterdir() if config.DATA.exists() else []):
            for f in (d.glob("*m.json") if d.is_dir() else []):
                if not f.name.startswith("mcp_"): f.unlink()
    for sym, m in sorted(changed): rebuild(sym, m, entries, verbose, keep=not fresh)
    for sym in sorted({s_ for s_, _ in changed}):  # a rebuilt group drops its built bars, so build them again
        derive(sym, verbose)
    save_registry(entries); _cache.clear()
    return changed


def rebuild(sym, m, entries, verbose=True, keep=True):
    """Merge every export of this symbol and bar size, newest last. With keep, the bars already stored are the base,
    so history from exports that have since been deleted survives."""
    gf = _group_file(sym, m); sources = []
    if keep and gf.exists(): sources.append(([b for b in json.loads(gf.read_text())["bars"] if not b.get("from")], -1))
    mf = _mcp_file(sym, m)
    if mf.exists(): sources.append((json.loads(mf.read_text())["bars"], 0))
    keep_ind = m >= 5 or config.load().get("indicators_1m")
    inf = _ind_file(sym, m); ind_sources = []
    if keep and keep_ind and inf.exists(): ind_sources.append((json.loads(inf.read_text())["bars"], -1))
    for k, e in entries.items():
        if e["symbol"] == sym and e["minutes"] == m and Path(k).exists():
            bars, _, ind = read_export(k, indicators=True)
            if bars: sources.append((bars, os.path.getmtime(k)))
            if ind and keep_ind: ind_sources.append((ind, os.path.getmtime(k)))
    write_group(sym, m, _merge(sources), verbose)
    if ind_sources:
        rows = _merge(ind_sources)
        tmp = inf.with_suffix(".tmp"); tmp.write_text(json.dumps({"symbol": sym, "minutes": m, "bars": rows})); tmp.replace(inf)
        _cache.pop(("ind", sym, m), None)
    elif not keep and inf.exists(): inf.unlink()


def write_group(sym, m, bars, verbose=True, note=""):
    gf = _group_file(sym, m); gf.parent.mkdir(parents=True, exist_ok=True)
    tmp = gf.with_suffix(".tmp"); tmp.write_text(json.dumps({"symbol": sym, "minutes": m, "bars": bars})); tmp.replace(gf)
    if verbose and bars:
        a, b = (dt.datetime.fromtimestamp(x, config.tz()) for x in (bars[0]["t"], bars[-1]["t"]))
        print(f"{sym} {label(m)}: {len(bars):,} bars, {a:%d %b %Y %H:%M} → {b:%d %b %Y %H:%M}{note}")
    _cache.pop((sym, m), None)


def day_start(sym, t):
    """Start (UTC seconds) of the trading day containing t, from the symbol's session start."""
    h, mi, z = config.session_start(sym)
    local = dt.datetime.fromtimestamp(t, z)
    s = local.replace(hour=h, minute=mi, second=0, microsecond=0)
    if local < s: s -= dt.timedelta(days=1)
    return int(s.timestamp())


def bucket(sym, m, t):
    """The bar of size m (minutes) that t falls in: on the clock up to 60m, from the session start above that."""
    if m <= 60: return t - t % (m * 60)
    s = day_start(sym, t)
    return s + (t - s) // (m * 60) * m * 60


def derive(sym, verbose=True):
    """Fill 5m/15m/30m/60m bars from 1m wherever no exported bar exists. A bucket is built only once a later 1m bar
    shows it has closed. Built bars carry "from": "1m"; VWAP and the kernel line are not copied, because they depend
    on the bar size (indicators.py recomputes them from the volume)."""
    one = load(sym, 1)
    if not one: return
    for m in DERIVED:
        gf = _group_file(sym, m)
        have = [b for b in json.loads(gf.read_text())["bars"] if not b.get("from")] if gf.exists() else []
        real = {b["t"] for b in have}; built = {}
        for b in one:
            k = bucket(sym, m, b["t"])
            if k in real: continue
            if k not in built: built[k] = {"t": k, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "from": "1m", "_v": []}
            x = built[k]; x["h"] = max(x["h"], b["h"]); x["l"] = min(x["l"], b["l"]); x["c"] = b["c"]
            x["_v"].append(b.get("v"))
        last_k = bucket(sym, m, one[-1]["t"]); out = []
        for k, x in built.items():
            if k >= last_k: continue  # still forming: closed once a later 1m bar falls in a later bar (a short 4h bar too)
            v = x.pop("_v")
            if v and all(y is not None for y in v): x["v"] = sum(v)
            out.append(x)
        if not out and gf.exists(): continue
        if not out and not have: continue
        merged = sorted(have + out, key=lambda b: b["t"])
        write_group(sym, m, merged, verbose, f" ({len(out):,} built from 1m)" if out else "")


def export_csv(sym, interval, out):
    m = int(re.sub(r"\D", "", interval) or 0)
    bars = load(sym, m)
    if not bars: sys.exit(f"no {interval} bars stored for {sym} (prices.py status lists what is held)")
    tz = config.tz(); cols = [c for c in ("v", "vwap", "kr") if any(c in b for b in bars)]
    names = {"v": "volume", "vwap": "vwap", "kr": "kernel regression estimate"}
    out = Path(out).expanduser(); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_utc", f"time_{config.tz_name()}", "open", "high", "low", "close"] + [names[c] for c in cols] + ["source"])
        for b in bars:
            u = dt.datetime.fromtimestamp(b["t"], dt.timezone.utc)
            w.writerow([u.strftime("%Y-%m-%d %H:%M"), u.astimezone(tz).strftime("%Y-%m-%d %H:%M"), b["o"], b["h"], b["l"], b["c"]]
                       + [b.get(c, "") for c in cols] + [f"built from {b['from']}" if b.get("from") else "export"])
    print(f"wrote {len(bars):,} {interval} bars for {sym} → {out}")


def load_registry():
    f = config.DATA / "_exports.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_registry(entries):
    config.DATA.mkdir(parents=True, exist_ok=True); (config.DATA / "_exports.json").write_text(json.dumps(entries))


def timeframes(sym):
    d = config.DATA / safe(sym)
    return sorted(int(p.stem[:-1]) for p in d.glob("*m.json") if not p.name.startswith("mcp_")) if d.exists() else []


def load(sym, m):
    k = (sym, m)
    if k not in _cache:
        f = _group_file(sym, m)
        _cache[k] = json.loads(f.read_text())["bars"] if f.exists() else None
    return _cache[k]


def indicator_sizes(sym):
    d = config.DATA / safe(sym)
    return sorted(int(p.name.split("m.")[0]) for p in d.glob("*m.indicators.json")) if d.exists() else []


def indicator_rows(sym, m):
    k = ("ind", sym, m)
    if k not in _cache:
        f = _ind_file(sym, m)
        rows = json.loads(f.read_text())["bars"] if f.exists() else []; _cache[k] = ([r["t"] for r in rows], rows)
    return _cache[k][1]


def indicators_at(sym, t, prefer=None):
    """(minutes, {plot name: value}) from the last bar of stored indicator columns that had closed by t: on the
    `prefer` bar size when held, otherwise the smallest held. (None, {}) without indicator data."""
    sizes = indicator_sizes(sym)
    if not sizes: return None, {}
    m = prefer if prefer in sizes else sizes[0]
    indicator_rows(sym, m); ts, rows = _cache[("ind", sym, m)]
    i = bisect.bisect_right(ts, t - m * 60) - 1
    if i < 0 or t - ts[i] > 4 * 86400: return m, {}
    return m, {n: v for n, v in rows[i].items() if n != "t"}


def bars_for(sym, t0=None):
    """(bars, "1m" | "5m" | …): the finest bars that cover the trade's entry time."""
    for m in timeframes(sym):
        b = load(sym, m)
        if b and (t0 is None or b[0]["t"] <= t0 <= b[-1]["t"]): return b, label(m)
    return None, None


def at_or_before(bars, t):
    i = bisect.bisect_right([b["t"] for b in bars], t) - 1
    return i


def mcp_bars(raw):
    """Bars from whatever shape a TradingView MCP / API returns, as [{t, o, h, l, c, v?}] with t in UTC seconds:
    {"bars": [...]}, {"data": [...]}, a plain list, a list of [time, open, high, low, close, volume?] rows, or columns
    ({"t": [...], "o": [...], ...} as TradingView's UDF API gives). Times may be seconds, milliseconds or ISO text."""
    if isinstance(raw, dict):
        for key in ("bars", "data", "candles", "ohlcv", "result", "values"):
            if key in raw: return mcp_bars(raw[key])
        if isinstance(raw.get("t") or raw.get("time"), list):  # columns
            cols = {k: raw[k] for k in raw if isinstance(raw[k], list)}
            n = len(cols.get("t") or cols.get("time"))
            return mcp_bars([{k: v[i] for k, v in cols.items() if i < len(v)} for i in range(n)])
        return []
    out = []
    names = {"t": ("t", "time", "timestamp", "datetime", "date"), "o": ("o", "open"), "h": ("h", "high"),
             "l": ("l", "low"), "c": ("c", "close"), "v": ("v", "volume")}
    for b in raw or []:
        if isinstance(b, (list, tuple)): b = dict(zip("tohlcv", b))
        get = lambda k: next((b[x] for x in names[k] if x in b and b[x] is not None), None)
        t = get("t")
        if t is None: continue
        if isinstance(t, str) and not re.fullmatch(r"\d+(\.\d+)?", t): t = _parse_time(t)
        t = float(t); t = int(t / 1000) if t > 1e11 else int(t)  # milliseconds → seconds
        try: x = {"t": t, **{k: float(get(k)) for k in "ohlc"}}
        except (TypeError, ValueError): continue
        if get("v") is not None: x["v"] = float(get("v"))
        out.append(x)
    return sorted(out, key=lambda x: x["t"])


def add(sym, interval, file):
    m = int(re.sub(r"\D", "", interval) or 0) * (60 if interval.lower().endswith("h") else 1440 if interval.upper().endswith("D") else 1)
    new = mcp_bars(json.loads(Path(file).read_text()))
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    forming = [b for b in new if b["t"] + m * 60 > now]  # the MCP's last bar is still forming and would be kept as is
    new = [b for b in new if b not in forming]
    if not new: sys.exit(f"no closed bars found in {file}: expected time/open/high/low/close values")
    mf = _mcp_file(sym, m); mf.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(mf.read_text())["bars"] if mf.exists() else []
    mf.write_text(json.dumps({"bars": _merge([(old, 0), (new, 1)])}))
    rebuild(sym, m, load_registry())
    if m == 1: derive(sym)
    print(f"added {len(new):,} {label(m)} bars for {sym} from {Path(file).name}"
          + (f" (left out {len(forming)} still forming)" if forming else ""))


def status():
    if not config.DATA.exists(): print("no price data yet"); return
    for d in sorted(p for p in config.DATA.iterdir() if p.is_dir()):
        for f in sorted(d.glob("*m.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)):
            if f.name.startswith("mcp_"): continue
            j = json.loads(f.read_text()); b = j["bars"]
            if not b: continue
            a, z = (dt.datetime.fromtimestamp(x, config.tz()) for x in (b[0]["t"], b[-1]["t"]))
            extra = sorted({k for x in b[-50:] for k in x} - {"t", "o", "h", "l", "c", "from"})
            nb = sum(1 for x in b if x.get("from"))
            print(f"{j['symbol']:24} {label(j['minutes']):5} {len(b):>9,} bars  {a:%d %b %Y} → {z:%d %b %Y %H:%M}"
                  + (f"  (+{', '.join(extra)})" if extra else "") + (f"  [{nb:,} built from 1m]" if nb else ""))
            inf = _ind_file(j["symbol"], j["minutes"])
            if inf.exists():
                rows = json.loads(inf.read_text())["bars"]
                names = sorted({k for r in rows[-500:] for k in r} - {"t"})
                if names: print(f"{'':30} indicator columns: {', '.join(names)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["ingest"]:
        if not config.load()["exports_dirs"]: sys.exit("No export folders set: config.py set exports_dirs '[\"~/path/to/exports\"]'")
        if not ingest(fresh="--rebuild" in a): print("no new or changed exports")
    elif a[:1] == ["status"]: status()
    elif a[:1] == ["add"] and len(a) == 4: add(a[1], a[2], a[3])
    elif a[:1] == ["export"] and len(a) == 4: export_csv(a[1], a[2], a[3])
    else: sys.exit(__doc__)
