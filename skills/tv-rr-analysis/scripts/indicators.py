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
import bisect, datetime as dt, sys
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
        if "vwap" in b: out.append(b["vwap"]); continue
        if "v" not in b: out.append(None); continue
        d = day_start(sym, b["t"])
        if d != day: day, pv, vv = d, 0.0, 0.0
        pv += (b["h"] + b["l"] + b["c"]) / 3 * b["v"]; vv += b["v"]
        out.append(pv / vv if vv else None)
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
