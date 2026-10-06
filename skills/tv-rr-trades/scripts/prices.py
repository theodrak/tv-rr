"""Price data for any instrument, built from TradingView chart exports (and, optionally, bars from the TradingView MCP).

usage: prices.py ingest [--rebuild]          read every export in the configured folders (only changed files cost time)
       prices.py status                      what data is held, per symbol and bar size
       prices.py add SYMBOL INTERVAL FILE    merge bars saved from the TradingView MCP (any usual JSON shape: mcp_bars)
       prices.py export SYMBOL INTERVAL OUT.csv [--no-built]   one CSV of the stored bars and indicator columns
       prices.py snapshot OUT.db             a clean single-file copy of the database, e.g. to share

Exports: in TradingView, open the chart, then "Export chart data…" (CSV). The file name TradingView gives it
("OANDA_DE30EUR, 5.csv", "BINANCE_BTCUSDT, 1 (2).csv") names the symbol; the bar size is read from the data. Any extra
columns on the chart travel with it: a "Volume", "VWAP" or "Kernel Regression Estimate" column is used when present,
and every other indicator column (RSI, MAs, levels…) is kept under the plot's name, for exports of 5 minutes and up
(1-minute too with config indicators_1m). Where exports overlap, the newest file wins, except for its last bar, which
may still have been forming. Everything lives in one SQLite database, <TV_RR_HOME>/data/prices.db (WAL mode; see
"storage" below), which DB Browser for SQLite or any SQLite tool can open.

Bars are KEPT once ingested: deleting an old export does not remove its history. `ingest --rebuild` starts again from
the files present (MCP top-ups are kept). Where 1m bars exist but coarser ones don't (a gap in the 5m exports, or no 5m exports at all), 5m,
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
    """Column names, made unique: a second "EMA" becomes "EMA (2)". With lower=False the names keep their case and
    only an exact repeat counts, so a plot called "LOW" (prior week low) stays "LOW" beside the price column "low"."""
    seen, out = {}, []
    for c in header:
        k = c.strip().lower() if lower else c.strip(); seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k} ({seen[k]})")
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
    # the price columns are the first time/open/high/low/close (and volume, VWAP, kernel); everything else, including a
    # later "LOW" or "High" plot, is an indicator
    base = {ix[k] for k in BASE_COLS if k in ix}
    ind_cols = [(i, names[i]) for i in range(len(head)) if i not in base]
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


# ---- storage: one SQLite database, ~/.tv-rr/data/prices.db, in WAL mode ------------------------------------------------
# symbols     id ↔ name ("OANDA:DE30EUR"), so the big tables store a small number instead of the text.
# bars        one row per symbol, bar size (tf, minutes) and bar time (t, UTC seconds). src: 0 export, 1 MCP top-up,
#             2 built from 1m. `rank` says which source wins a clash: an export's file mtime (a newer export beats an older
#             one), RANK_MIGRATED for bars carried over from the old JSON store, RANK_MCP for MCP top-ups, RANK_BUILT for
#             bars built from 1m. A write only replaces a row of equal or lower rank, so exports > MCP > built, whatever
#             order things arrive in.
# series      id ↔ (symbol, bar size, plot name) of an exported indicator column.
# indicators  one row per series and bar time: every exported indicator value, same ranks.
# exports     the export files already read (path, mtime, size, symbol, bar size), so unchanged files cost nothing.
# Views for people (DB Browser for SQLite or any SQLite tool): `prices` and `indicator_values`, with symbol and plot
# names and readable UTC times.
RANK_BUILT, RANK_MCP, RANK_MIGRATED = -2, -1, 1
SRC = {"export": 0, "mcp": 1, "1m": 2}
SYNCED = ("Mobile Documents", "CloudStorage", "Google Drive", "GoogleDrive", "Dropbox", "OneDrive", "iCloud")
SCHEMA = """
create table if not exists symbols (id integer primary key, name text unique not null);
create table if not exists bars (sid integer, tf integer, t integer, o real, h real, l real, c real, v real, vwap real,
    kr real, src integer, rank integer, primary key (sid, tf, t)) without rowid;
create table if not exists series (id integer primary key, sid integer, tf integer, name text, unique (sid, tf, name));
create table if not exists indicators (series integer, t integer, value real, rank integer, primary key (series, t))
    without rowid;
create table if not exists exports (path text primary key, mtime real, size integer, symbol text, tf integer);
create view if not exists prices as select s.name as symbol, b.tf as minutes, datetime(b.t, 'unixepoch') as time_utc,
    b.o as open, b.h as high, b.l as low, b.c as close, b.v as volume, b.vwap, b.kr as kernel,
    case b.src when 0 then 'export' when 1 then 'mcp' else 'built from 1m' end as source
    from bars b join symbols s on s.id = b.sid;
create view if not exists indicator_values as select s.name as symbol, r.tf as minutes, r.name as indicator,
    datetime(i.t, 'unixepoch') as time_utc, i.value
    from indicators i join series r on r.id = i.series join symbols s on s.id = r.sid;
"""
_db = None
_ids = {}


def db_path():
    return config.DATA / "prices.db"


def db():
    """The price database, opened once per run in WAL mode (readers never wait for a writer)."""
    global _db
    if _db is None:
        import sqlite3
        path = db_path()
        if any(x in str(path) for x in SYNCED):
            sys.exit(f"The price database can't live in a synced folder ({path}): WAL mode needs a local disk. "
                     "Point TV_RR_HOME somewhere local.")
        path.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(path, timeout=60)
        _db.execute("pragma journal_mode=wal"); _db.execute("pragma synchronous=normal")
        _db.executescript(SCHEMA)
        migrate_json(_db)
    return _db


def sid(sym, create=False):
    """The symbol's id (None when unknown and not created)."""
    if sym not in _ids:
        r = db().execute("select id from symbols where name=?", (sym,)).fetchone()
        if not r and create: db().execute("insert into symbols (name) values (?)", (sym,)); r = db().execute("select last_insert_rowid()").fetchone()
        if not r: return None
        _ids[sym] = r[0]
    return _ids[sym]


def series_id(sym, m, name):
    k = ("series", sym, m, name)
    if k not in _ids:
        s_ = sid(sym, create=True)
        db().execute("insert or ignore into series (sid, tf, name) values (?,?,?)", (s_, m, name))
        _ids[k] = db().execute("select id from series where sid=? and tf=? and name=?", (s_, m, name)).fetchone()[0]
    return _ids[k]


def put_bars(sym, m, bars, rank, src, keep_last=False):
    """Upsert bars; a row is only replaced by one of equal or higher rank. keep_last: the last bar never replaces an
    existing one (an export's last bar may still have been forming)."""
    # a source without a column (e.g. an export saved without the Volume plot) never blanks the stored value
    q = ("insert into bars values (?,?,?,?,?,?,?,?,?,?,?,?) on conflict (sid, tf, t) do update set o=excluded.o, "
         "h=excluded.h, l=excluded.l, c=excluded.c, v=coalesce(excluded.v, bars.v), "
         "vwap=coalesce(excluded.vwap, bars.vwap), kr=coalesce(excluded.kr, bars.kr), src=excluded.src, "
         "rank=excluded.rank where excluded.rank >= bars.rank")
    fill = "update bars set v=? where sid=? and tf=? and t=? and v is null"
    s_, code, rank = sid(sym, create=True), SRC[src], int(rank)
    rows = [(s_, m, b["t"], b["o"], b["h"], b["l"], b["c"], b.get("v"), b.get("vwap"), b.get("kr"), code, rank) for b in bars]
    if keep_last and rows:
        db().execute("insert or ignore into bars values (?,?,?,?,?,?,?,?,?,?,?,?)", rows.pop())
    db().executemany(q, rows)
    db().executemany(fill, [(r[7], r[0], r[1], r[2]) for r in rows if r[7] is not None])  # lower-ranked sources fill missing volume
    for k in ((sym, m), (sym, m, "no built"), ("ranges", sym)): _cache.pop(k, None)


def put_indicators(sym, m, rows, rank, keep_last=False):
    """Upsert indicator values (same ranks as bars). keep_last: the last row never replaces stored values (an
    export's last bar may still have been forming)."""
    q = ("insert into indicators values (?,?,?,?) on conflict (series, t) do update set value=excluded.value, "
         "rank=excluded.rank where excluded.rank >= indicators.rank")
    rank = int(rank)
    if keep_last and rows:
        last = rows[-1]; rows = rows[:-1]
        db().executemany("insert or ignore into indicators values (?,?,?,?)",
                         [(series_id(sym, m, k), last["t"], v, rank) for k, v in last.items() if k != "t"])
    db().executemany(q, ((series_id(sym, m, k), r["t"], v, rank) for r in rows for k, v in r.items() if k != "t"))
    _cache.pop(("ind", sym, m), None)


def migrate_json(con):
    """One-time move from the old JSON store (<symbol>/<size>m.json, <size>m.indicators.json, mcp_<size>m.json,
    _exports.json). The JSON files are left where they are."""
    if con.execute("select 1 from bars limit 1").fetchone() or not config.DATA.exists(): return
    dirs = [d for d in config.DATA.iterdir() if d.is_dir() and list(d.glob("*m.json"))]
    if not dirs: return
    global _db
    _db = con
    print("moving the price data into prices.db (one time)…", file=sys.stderr)
    for d in dirs:
        for f in d.glob("*m.json"):
            j = json.loads(f.read_text()); sym = j.get("symbol"); bars = j["bars"]
            if f.name.startswith("mcp_"):
                if not sym: continue  # older MCP files carry no symbol: their bars are already in the merged files
                put_bars(sym, int(re.sub(r"\D", "", f.stem)), bars, RANK_MCP, "mcp")
                continue
            m = j["minutes"]
            put_bars(sym, m, [b for b in bars if not b.get("from")], RANK_MIGRATED, "export")
            put_bars(sym, m, [b for b in bars if b.get("from")], RANK_BUILT, "1m")
        for f in d.glob("*m.indicators.json"):
            j = json.loads(f.read_text()); put_indicators(j["symbol"], j["minutes"], j["bars"], RANK_MIGRATED)
    reg = config.DATA / "_exports.json"
    if reg.exists():
        con.executemany("insert or replace into exports values (?,?,?,?,?)",
                        [(k, e["sig"][0], e["sig"][1], e["symbol"], e["minutes"]) for k, e in json.loads(reg.read_text()).items()])
    con.commit()


def ingest(verbose=True, fresh=False):
    """Read new or changed exports. Only those files are read: their bars and indicator columns are upserted with the
    file's mtime as rank, so the newest file wins where exports overlap. fresh (--rebuild) forgets every export bar and
    reads all files present again (MCP top-ups are kept)."""
    con = db(); known = set(config.load()["symbols"])
    if fresh:
        con.execute("delete from bars where src in (0, 2)")  # exports and the bars built from them; MCP top-ups stay
        con.execute("delete from indicators"); con.execute("delete from exports"); _cache.clear()
    seen = {r[0]: (r[1], r[2]) for r in con.execute("select path, mtime, size from exports")}
    changed = {}
    for p in sorted(exports(), key=lambda p: p.stat().st_mtime):
        sig = (p.stat().st_mtime, p.stat().st_size)
        if seen.get(str(p)) == sig: continue
        sym = symbol_from_name(p.name, known)
        bars, m, ind = read_export(p, indicators=True) if sym else (None, None, None)
        if not sym or not bars or not m:
            if verbose: print(f"skipped {p.name}: not a TradingView export (no symbol in the name or no time column)")
            continue
        put_bars(sym, m, bars, sig[0], "export", keep_last=True)
        if ind and (m >= 5 or config.load().get("indicators_1m")): put_indicators(sym, m, ind, sig[0], keep_last=True)
        con.execute("insert or replace into exports values (?,?,?,?,?)", (str(p), sig[0], sig[1], sym, m))
        first = changed.get((sym, m)); changed[(sym, m)] = min(first, bars[0]["t"]) if first else bars[0]["t"]
        if verbose: print(f"read {p.name}: {sym} {label(m)}, {len(bars):,} bars")
    con.commit()
    for sym in sorted({s_ for s_, _ in changed}):
        if (sym, 1) in changed or fresh: derive(sym, verbose, since=None if fresh else changed[(sym, 1)])
    if verbose:
        for (sym, m) in sorted(changed): summary(sym, m)
    return set(changed)


def summary(sym, m, note=""):
    n, a, z = db().execute("select count(*), min(t), max(t) from bars where sid=? and tf=?", (sid(sym), m)).fetchone()
    if n:
        a, z = (dt.datetime.fromtimestamp(x, config.tz()) for x in (a, z))
        print(f"{sym} {label(m)}: {n:,} bars, {a:%d %b %Y %H:%M} → {z:%d %b %Y %H:%M}{note}")


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


def derive(sym, verbose=True, since=None):
    """Build 5m/15m/30m/60m/4h bars from 1m wherever no exported or MCP bar exists (they outrank built bars), from the
    start of the trading day before `since` (every bar size starts afresh at a day start, so the first rebuilt bar is
    whole), or over all the 1m history. A bar is built only once a later 1m bar shows it has closed. Built bars have
    src "1m"; VWAP and the kernel line are not copied, because they depend on the bar size (indicators.py recomputes
    them from the volume)."""
    lo = day_start(sym, since) - 86400 if since else 0
    one = [dict(zip("tohlcv", r)) for r in db().execute(
        "select t, o, h, l, c, v from bars where sid=? and tf=1 and t >= ? order by t", (sid(sym), lo))]
    if not one: return
    for m in DERIVED:
        built = {}
        for b in one:
            k = bucket(sym, m, b["t"])
            if k not in built: built[k] = {"t": k, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "_v": []}
            x = built[k]; x["h"] = max(x["h"], b["h"]); x["l"] = min(x["l"], b["l"]); x["c"] = b["c"]
            x["_v"].append(b.get("v"))
        last_k = bucket(sym, m, one[-1]["t"]); out = []
        for k, x in built.items():
            if k >= last_k: continue  # still forming: closed once a later 1m bar falls in a later bar (a short 4h bar too)
            v = x.pop("_v")
            if v and all(y is not None for y in v): x["v"] = sum(v)
            out.append(x)
        put_bars(sym, m, out, RANK_BUILT, "1m")
    db().commit()


def export_csv(sym, interval, out, built=True):
    """One CSV of the stored bars: UTC and local time, OHLC, volume, VWAP, kernel line, then every stored indicator
    column (in the order they were first exported), then where each bar came from."""
    m = int(re.sub(r"\D", "", interval) or 0) * (60 if interval.lower().endswith("h") else 1)
    bars = load(sym, m, built)
    if not bars: sys.exit(f"no {interval} bars stored for {sym} (prices.py status lists what is held)")
    tz = config.tz(); cols = [c for c in ("v", "vwap", "kr") if any(c in b for b in bars)]
    names = {"v": "volume", "vwap": "vwap", "kr": "kernel regression estimate"}
    ind = [r[0] for r in db().execute("select name from series where sid=? and tf=? order by id", (sid(sym), m))]
    vals = {r["t"]: r for r in indicator_rows(sym, m)} if ind else {}
    src = {t: s_ for t, s_ in db().execute("select t, src from bars where sid=? and tf=?", (sid(sym), m))}
    out = Path(out).expanduser(); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_utc", f"time_{config.tz_name()}", "open", "high", "low", "close"] + [names[c] for c in cols]
                   + ind + ["source"])
        for b in bars:
            u = dt.datetime.fromtimestamp(b["t"], dt.timezone.utc); v = vals.get(b["t"], {})
            w.writerow([u.strftime("%Y-%m-%d %H:%M"), u.astimezone(tz).strftime("%Y-%m-%d %H:%M"), b["o"], b["h"], b["l"], b["c"]]
                       + [b.get(c, "") for c in cols] + [v.get(n, "") for n in ind]
                       + [{0: "export", 1: "mcp", 2: "built from 1m"}[src[b["t"]]]])
    print(f"wrote {len(bars):,} {interval} bars for {sym}, {len(ind)} indicator columns → {out}")


def snapshot(out):
    """A clean single-file copy of the database to hand to someone (VACUUM INTO: consistent even while in WAL mode,
    with nothing left in -wal / -shm side files)."""
    out = Path(out).expanduser().resolve()
    if out.exists(): sys.exit(f"{out} already exists: choose another name or delete it first")
    out.parent.mkdir(parents=True, exist_ok=True)
    db().execute("vacuum into ?", (str(out),))
    print(f"snapshot: {out} ({out.stat().st_size / 1e6:,.0f} MB). Open it in any SQLite tool; the views prices and "
          "indicator_values show symbols, plot names and UTC times.")


def ranges(sym):
    """[(minutes, first t, last t)] of the bars held for sym, smallest size first; remembered until bars change."""
    k = ("ranges", sym)
    if k not in _cache:
        _cache[k] = db().execute("select tf, min(t), max(t) from bars where sid=? group by tf order by tf", (sid(sym),)).fetchall()
    return _cache[k]


def timeframes(sym):
    return [m for m, _, _ in ranges(sym)]


def since(bars, t, after=False):
    """The bars from time t on (after=True: strictly after t), found by bisection instead of a scan."""
    k = ("ts", id(bars), len(bars))
    if k not in _cache: _cache[k] = [b["t"] for b in bars]
    ts = _cache[k]
    return bars[(bisect.bisect_right if after else bisect.bisect_left)(ts, t):]


def load(sym, m, built=True):
    """Every bar held for this symbol and size, oldest first, as {t, o, h, l, c, v?, vwap?, kr?, from?} (from = "1m"
    for built bars); None when there are none. built=False leaves out the bars built from 1m (exports and MCP only)."""
    k = (sym, m) if built else (sym, m, "no built")
    if k not in _cache:
        out = []
        for t, o, h, l, c, v, vw, kr, src in db().execute(
                "select t, o, h, l, c, v, vwap, kr, src from bars where sid=? and tf=? and src <= ? order by t",
                (sid(sym), m, 2 if built else 1)):
            b = {"t": t, "o": o, "h": h, "l": l, "c": c}
            if v is not None: b["v"] = v
            if vw is not None: b["vwap"] = vw
            if kr is not None: b["kr"] = kr
            if src == 2: b["from"] = "1m"
            out.append(b)
        _cache[k] = out or None
    return _cache[k]


def indicator_sizes(sym):
    return [r[0] for r in db().execute("select distinct tf from series where sid=? order by tf", (sid(sym),))]


def indicator_rows(sym, m):
    """Every stored indicator bar for this symbol and size, oldest first, as {"t", <plot name>: value}."""
    k = ("ind", sym, m)
    if k not in _cache:
        rows = {}
        for t, name, value in db().execute(
                "select i.t, r.name, i.value from indicators i join series r on r.id = i.series "
                "where r.sid=? and r.tf=? order by i.t", (sid(sym), m)):
            rows.setdefault(t, {"t": t})[name] = value
        _cache[k] = sorted(rows.values(), key=lambda r: r["t"])
    return _cache[k]


def indicators_at(sym, t, prefer=None):
    """(minutes, {plot name: value}) from the last bar of stored indicator columns that had closed by t: on the
    `prefer` bar size when held, otherwise the smallest held. (None, {}) without indicator data."""
    sizes = indicator_sizes(sym)
    if not sizes: return None, {}
    m = prefer if prefer in sizes else sizes[0]
    ids = [r[0] for r in db().execute("select id from series where sid=? and tf=?", (sid(sym), m))]
    marks = ",".join("?" * len(ids))
    row = db().execute(f"select max(t) from indicators where series in ({marks}) and t <= ?", (*ids, t - m * 60)).fetchone()
    if not row or row[0] is None or t - row[0] > 4 * 86400: return m, {}
    return m, dict(db().execute(f"select r.name, i.value from indicators i join series r on r.id = i.series "
                                f"where i.series in ({marks}) and i.t = ?", (*ids, row[0])).fetchall())


def bars_for(sym, t0=None):
    """(bars, "1m" | "5m" | …): the finest bars that cover the trade's entry time."""
    for m, a, z in ranges(sym):
        if t0 is None or a <= t0 <= z: return load(sym, m), label(m)
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
    put_bars(sym, m, new, RANK_MCP, "mcp"); db().commit()  # exports outrank MCP bars, so overlaps keep the export
    if m == 1: derive(sym, since=new[0]["t"])
    print(f"added {len(new):,} {label(m)} bars for {sym} from {Path(file).name}"
          + (f" (left out {len(forming)} still forming)" if forming else ""))


def status():
    con = db(); rows = con.execute("select s.name, b.tf, count(*), min(t), max(t), sum(src=2), sum(src=1), count(v), "
                                   "count(vwap), count(kr) from bars b join symbols s on s.id = b.sid "
                                   "group by s.name, b.tf order by s.name, b.tf").fetchall()
    if not rows: print("no price data yet"); return
    print(f"{db_path()}  ({db_path().stat().st_size / 1e6:,.0f} MB)")
    for sym, m, n, a, z, nb, nm, nv, nvw, nkr in rows:
        a, z = (dt.datetime.fromtimestamp(x, config.tz()) for x in (a, z))
        extra = [x for x, k in (("v", nv), ("vwap", nvw), ("kr", nkr)) if k]
        print(f"{sym:24} {label(m):5} {n:>9,} bars  {a:%d %b %Y} → {z:%d %b %Y %H:%M}"
              + (f"  (+{', '.join(extra)})" if extra else "") + (f"  [{nb:,} built from 1m]" if nb else "")
              + (f"  [{nm:,} from the MCP]" if nm else ""))
        names = [r[0] for r in con.execute("select name from series where sid=? and tf=? order by name", (sid(sym), m))]
        if names: print(f"{'':30} indicator columns: {', '.join(names)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["ingest"]:
        if not config.load()["exports_dirs"]: sys.exit("No export folders set: config.py set exports_dirs '[\"~/path/to/exports\"]'")
        if not ingest(fresh="--rebuild" in a): print("no new or changed exports")
    elif a[:1] == ["status"]: status()
    elif a[:1] == ["add"] and len(a) == 4: add(a[1], a[2], a[3])
    elif a[:1] == ["export"] and len(a) in (4, 5): export_csv(a[1], a[2], a[3], built="--no-built" not in a)
    elif a[:1] == ["snapshot"] and len(a) == 2: snapshot(a[1])
    else: sys.exit(__doc__)
