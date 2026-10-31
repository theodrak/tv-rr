"""Indicators at a moment, for any instrument in the price store: ATR(14) on 5m/15m/4h/daily, the session VWAP and the
Lorentzian Classification kernel line, plus SMA/EMA series for the charts.

Higher timeframes are built from the finest stored bars the way TradingView builds them: 15m on the clock, 4h and daily
from the symbol's session start (config `session_start`, default 17:00 New York, the FX/CFD rollover). ATR is
TradingView's ta.atr: Wilder's RMA of the true range, seeded with the mean of the first 14. Values at a moment come
from the last bar that had CLOSED by then, so nothing after an entry is used.

VWAP uses the export's own "VWAP" column when there is one (exactly what the chart showed); otherwise it is computed from
"Volume", anchored at the session start. With neither, there is no VWAP. The kernel line likewise prefers the export's
"Kernel Regression Estimate" column and otherwise computes the indicator's default (rational quadratic, lookback 8,
relative weight 8, regression start 25).
"""
import bisect, datetime as dt, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tv-rr-trades" / "scripts"))
import config, prices  # noqa: E402

N = 14
FRAMES = {"5m": 5, "15m": 15, "4h": 240, "D": 1440}
_cache = {}


def day_start(sym, t):
    h, m, z = config.session_start(sym)
    local = dt.datetime.fromtimestamp(t, z)
    s = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if local < s: s -= dt.timedelta(days=1)
    return int(s.timestamp())


def bucket(sym, minutes, t):
    if minutes <= 60: return t - t % (minutes * 60)
    s = day_start(sym, t)
    return s if minutes >= 1440 else s + (t - s) // (minutes * 60) * minutes * 60


def base(sym):
    """The bars higher timeframes are built from: 5m when held, otherwise the finest available."""
    tfs = prices.timeframes(sym)
    if not tfs: return None, None
    m = 5 if 5 in tfs else min(tfs)
    return prices.load(sym, m), m


def resample(sym, minutes):
    k = ("rs", sym, minutes)
    if k in _cache: return _cache[k]
    bars, bm = base(sym)
    if not bars or bm > minutes: _cache[k] = None; return None
    out = []
    for b in bars:
        key = bucket(sym, minutes, b["t"]); end = b["t"] + bm * 60
        if out and out[-1]["t"] == key:
            o = out[-1]; o["h"] = max(o["h"], b["h"]); o["l"] = min(o["l"], b["l"]); o["c"] = b["c"]; o["end"] = end
        else:
            out.append({"t": key, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "end": end})
    _cache[k] = out
    return out


def _atr_series(sym, minutes):
    k = ("atr", sym, minutes)
    if k in _cache: return _cache[k]
    bars = resample(sym, minutes)
    if not bars: _cache[k] = None; return None
    ends, vals, prev, trs, atr = [], [], None, [], None
    for b in bars:
        tr = b["h"] - b["l"] if prev is None else max(b["h"] - b["l"], abs(b["h"] - prev), abs(b["l"] - prev)); prev = b["c"]
        if atr is None:
            trs.append(tr)
            if len(trs) == N: atr = sum(trs) / N
        else:
            atr = (atr * (N - 1) + tr) / N
        if atr is not None: ends.append(b["end"]); vals.append(atr)
    _cache[k] = (ends, vals)
    return _cache[k]


def atr_at(sym, t):
    """{"5m": …, "15m": …, "4h": …, "D": …}: ATR of the last bar of each timeframe closed by t (None without data)."""
    out = {}
    for name, m in FRAMES.items():
        s = _atr_series(sym, m)
        if not s: out[name] = None; continue
        i = bisect.bisect_right(s[0], t) - 1
        out[name] = s[1][i] if i >= 0 and t - s[0][i] < 4 * 86400 else None
    return out


def vwap_series(sym, bars):
    """Session VWAP per bar (None where it cannot be known)."""
    if all("vwap" in b for b in bars): return [b["vwap"] for b in bars]
    out, day, pv, vv = [], None, 0.0, 0.0
    for b in bars:
        d = day_start(sym, b["t"])
        if d != day: day, pv, vv = d, 0.0, 0.0
        if "v" in b: pv += (b["h"] + b["l"] + b["c"]) / 3 * b["v"]; vv += b["v"]
        out.append(b["vwap"] if "vwap" in b else pv / vv if vv and "v" in b else None)
    return out


def vwap_at(sym, t, minutes=30):
    """(VWAP, VWAP `minutes` earlier in the same session, close) at the last bar closed by t, or None."""
    bars, m = base(sym)
    if not bars: return None
    k = ("ts", sym)
    if k not in _cache: _cache[k] = [b["t"] for b in bars]
    ts = _cache[k]
    i = bisect.bisect_right(ts, t - m * 60) - 1
    if i < 0: return None
    j0 = bisect.bisect_left(ts, day_start(sym, bars[i]["t"]))
    vw = vwap_series(sym, bars[j0:i + 1])
    back_i = i - minutes // m
    back = vw[back_i - j0] if back_i >= j0 else None
    return (vw[-1], back, bars[i]["c"]) if vw[-1] is not None else None


def sma_at(sym, t, n):
    """SMA(n) of the base bars' closes (5m when held, as on the charts) at the last bar closed by t, or None."""
    bars, m = base(sym)
    if not bars: return None
    k = ("cum", sym)
    if k not in _cache:
        cum = [0.0]
        for b in bars: cum.append(cum[-1] + b["c"])
        _cache[k] = ([b["t"] for b in bars], cum)
    ts, cum = _cache[k]
    i = bisect.bisect_right(ts, t - m * 60) - 1
    return (cum[i + 1] - cum[i + 1 - n]) / n if i + 1 >= n else None


def _closed_index(sym, t):
    bars, m = base(sym)
    if not bars: return None, None, None
    k = ("ts", sym)
    if k not in _cache: _cache[k] = [b["t"] for b in bars]
    return bars, m, bisect.bisect_right(_cache[k], t - m * 60) - 1


def ema_at(sym, t, n):
    """EMA(n) of the base bars' closes at the last bar closed by t (seeded with the first close, like ema()), or None."""
    bars, m, i = _closed_index(sym, t)
    if bars is None or i < n: return None
    k = ("ema", sym, n)
    if k not in _cache: _cache[k] = ema([b["c"] for b in bars], n)
    return _cache[k][i]


def prior_day_hl(sym, t):
    """(high, low) of the previous session (from the symbol's session start) before the bar closed by t, or None."""
    bars, m, i = _closed_index(sym, t)
    if bars is None or i < 0: return None
    ts = _cache[("ts", sym)]
    ds = day_start(sym, bars[i]["t"]); prev = day_start(sym, ds - 1)
    day = bars[bisect.bisect_left(ts, prev):bisect.bisect_left(ts, ds)]
    return (max(b["h"] for b in day), min(b["l"] for b in day)) if day else None


def prior_value_area(sym, t):
    """(POC, VAH, VAL) of the previous session before t, or None. The session comes from the symbol's config
    value_area {"session": "09:00-17:35 Europe/Berlin", "step": 5}: its 5m bars (exports and MCP; volume, or 1 where a
    bar has none), each bar's volume spread over the rows it spans, the POC the busiest row (its middle), the value area
    70% of the volume grown one row at a time towards the bigger neighbour. VAH is the top of its top row, VAL the bottom
    of its bottom row (as de30-open-review's profile). The previous session is the latest one on an earlier date, in
    the session's own time zone, than t."""
    import math
    import numpy as np
    from zoneinfo import ZoneInfo
    va = config.symbol(sym).get("value_area")
    if not va: return None
    k = ("pva", sym, t)
    if k in _cache: return _cache[k]
    (a_hm, b_hm), zone = va["session"].split()[0].split("-"), ZoneInfo(va["session"].split()[1])
    step = float(va.get("step", 5)); bars = prices.load(sym, 5, built=False) or []
    if not bars: return None
    ts = [b["t"] for b in bars]; day = dt.datetime.fromtimestamp(t, zone).date(); res = None
    for back in range(1, 8):
        d = day - dt.timedelta(days=back)
        at_ = lambda hm: int(dt.datetime.combine(d, dt.time(*map(int, hm.split(":"))), zone).timestamp())
        win = bars[bisect.bisect_left(ts, at_(a_hm)):bisect.bisect_left(ts, at_(b_hm))]
        if not win: continue
        lo = math.floor(min(b["l"] for b in win) / step) * step; hi = math.ceil(max(b["h"] for b in win) / step) * step
        edges = np.arange(lo, hi + step, step); vol = np.zeros(len(edges))
        for b in win:
            i0, i1 = int((b["l"] - lo) // step), int((b["h"] - lo) // step); w = b.get("v") or 1.0
            vol[i0:i1 + 1] += w / (i1 - i0 + 1)
        poc = int(np.argmax(vol)); acc, lo_i, hi_i = vol[poc], poc, poc
        while acc < 0.7 * vol.sum():
            up = vol[hi_i + 1] if hi_i + 1 < len(vol) else -1; dn = vol[lo_i - 1] if lo_i - 1 >= 0 else -1
            if up >= dn: hi_i += 1; acc += up
            else: lo_i -= 1; acc += dn
        res = (float(edges[poc] + step / 2), float(edges[hi_i] + step), float(edges[lo_i])); break
    _cache[k] = res
    return res


def vwap_recent(sym, t, minutes=10, steps=2):
    """VWAP at the last bar closed by t and then every `minutes` before it, `steps` times, all in the same session:
    [now, `minutes` ago, 2×`minutes` ago, …]. Entries that would fall before the session start are None."""
    bars, m = base(sym)
    if not bars: return None
    k = ("ts", sym)
    if k not in _cache: _cache[k] = [b["t"] for b in bars]
    ts = _cache[k]
    i = bisect.bisect_right(ts, t - m * 60) - 1
    if i < 0: return None
    j0 = bisect.bisect_left(ts, day_start(sym, bars[i]["t"]))
    vw = vwap_series(sym, bars[j0:i + 1])
    n = max(1, minutes // m)
    return [vw[i - j0 - s * n] if i - s * n >= j0 else None for s in range(steps + 1)]


MA_NAME = re.compile(r"(EMA|SMA|MA|Moving Average(?: Exponential| Simple)?)(?: \(\d+\))?", re.I)


def ma_length(sym, m, name, rows, max_len=500):
    """("EMA" | "SMA", length) when the exported column `name` matches a moving average of the closes exactly, else
    None. Only plain names ("EMA", "MA", "EMA (2)") are tried; a name that already says its length is left alone."""
    k = ("malen", sym, m, name)
    if k in _cache: return _cache[k]
    _cache[k] = None
    if not MA_NAME.fullmatch(name): return None
    bars = prices.load(sym, m)
    if not bars: return None
    tail = bars[-(6 * max_len + 2000):]; at = {b["t"]: i for i, b in enumerate(tail)}
    pts = [(at[r["t"]], r[name]) for r in rows[-3000:] if name in r and r["t"] in at and at[r["t"]] >= 5 * max_len][-1000:]
    if len(pts) < 50: return None
    closes = [b["c"] for b in tail]
    tol = 1e-6 * abs(pts[-1][1])  # the same line to rounding (a neighbouring length is ~100x further off)
    kinds = ("EMA",) if name.upper().startswith("E") or "EXPONENTIAL" in name.upper() else ("SMA",) if name.upper().startswith("S") or "SIMPLE" in name.upper() else ("EMA", "SMA")
    best = None
    for kind in kinds:
        for n in range(2, max_len + 1):
            line = ema(closes, n) if kind == "EMA" else sma(closes, n)
            if any(line[i] is None for i, _ in pts): continue
            err = sum(abs(line[i] - v) for i, v in pts) / len(pts)
            if best is None or err < best[0]: best = (err, kind, n)
    if best and best[0] <= tol: _cache[k] = (best[1], best[2])
    return _cache[k]


def kernel_series(bars, h=8, r=8.0, x=25):
    if all("kr" in b for b in bars): return [b["kr"] for b in bars]
    w = [(1 + i * i / (h * h * 2 * r)) ** -r for i in range(x + 2)]
    c = [b["c"] for b in bars]; out = []
    for t in range(len(c)):
        n = min(t + 1, len(w)); num = sum(c[t - i] * w[i] for i in range(n)); den = sum(w[:n])
        out.append(bars[t]["kr"] if "kr" in bars[t] else num / den)
    return out


def sma(vals, n):
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(vals, n):
    a, out = 2 / (n + 1), []
    for i, v in enumerate(vals): out.append(v if i == 0 else a * v + (1 - a) * out[-1])
    return out
