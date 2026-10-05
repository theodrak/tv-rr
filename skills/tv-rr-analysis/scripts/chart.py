"""A TradingView-style candle chart for any instrument, with the overlays the user chose (config gallery.elements).

draw(sym, minutes, bars, overlays, …) renders bars (dicts t/o/h/l/c) with:
  vwap, kernel, sma50 … sma1000, ema9     line overlays (series aligned with bars; None = not drawn there)
  prior_day, prior_week, prior_value      horizontal levels from the previous session / week
  sessions                                Asia / Europe / US markers along the top
  round_numbers                           round-number price lines in the right margin
extra(ax, ymin, ymax) draws on top (the risk/reward tool). Times are shown in the configured timezone.
"""
import datetime as dt, math, sys
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tv-rr-trades" / "scripts"))
import config  # noqa: E402

C = dict(up_fill="#b9e4bc", up_edge="#1b5e20", dn_fill="#111111", dn_edge="#111111", wick="#222222",
         sma50=(0.129, 0.588, 0.953, 0.35), sma100=(1.0, 0.322, 0.322, 0.35), sma200=(0.984, 0.753, 0.176, 0.35),
         sma500=(0.482, 0.725, 0.451, 0.35), sma1000=(0.667, 0.667, 0.667, 0.35),
         ema9="#26c6da", vwap="#e57373", kern_dn="#d32f2f", kern_up="#26a69a",
         prior_day="#2962ff", prior_week="#3a5a18", va="#9e9e9e", poc="#616161")
SMAS = ((1000, 3.2), (500, 3.2), (200, 3.2), (100, 1.2), (50, 1.2))
# (label, start, end, market timezone, colour); later rows win where sessions overlap
SESSIONS = [("Asia", (9, 0), (15, 0), "Asia/Tokyo", "#8e7cc3"),
            ("EU Pre", (8, 0), (9, 0), "Europe/Berlin", "#e93232"), ("EU Open", (9, 0), (10, 30), "Europe/Berlin", "#ecb23d"),
            ("EU Aftn", (10, 30), (17, 30), "Europe/Berlin", "#d2a1a1"), ("US Pre", (8, 30), (9, 30), "America/New_York", "#7de495"),
            ("US Open", (9, 30), (10, 30), "America/New_York", "#5ea76f"), ("US Aftn", (10, 30), (16, 0), "America/New_York", "#cfe7d5")]
rgb = lambda c: c if isinstance(c, str) else c[:3]


def decimals(sym, price):
    return config.decimals(sym, price)


def nice_step(span, lines=8):
    raw = span / lines; e = 10 ** math.floor(math.log10(raw)); m = raw / e
    return (1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10) * e


def draw(sym, minutes, bars, overlays, out, elements, levels=None, extra=None, title=None, subtitle=None, pad_after=0):
    tz = config.tz(); n = len(bars)
    O = [b["o"] for b in bars]; H = [b["h"] for b in bars]; L = [b["l"] for b in bars]; Cl = [b["c"] for b in bars]
    T = [dt.datetime.fromtimestamp(b["t"], tz) for b in bars]
    nd = decimals(sym, Cl[-1]); fmt = lambda v: f"{v:,.{nd}f}"

    fig, ax = plt.subplots(figsize=(26, 14), dpi=140)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    for s in ("top", "left"): ax.spines[s].set_visible(False)
    for s in ("right", "bottom"): ax.spines[s].set_color("#bdbdbd")
    ax.yaxis.tick_right(); ax.tick_params(colors="#333333", labelsize=11)
    lo, hi = min(L), max(H); span = (hi - lo) or abs(hi) * 0.001 or 1
    ymin, ymax = lo - 0.08 * span, hi + 0.14 * span
    margin = int(n * 0.16); right = n + pad_after + margin
    labels, legend = [], []

    lv = levels or {}
    if "prior_value" in elements and lv.get("value"):
        val, vah, poc = lv["value"]
        ax.add_patch(Rectangle((-0.5, val), n, vah - val, color=C["va"], alpha=0.10, lw=0, zorder=0))
        ax.plot([-0.5, n - 0.5], [poc] * 2, color=C["poc"], lw=1.0, zorder=1)
        for nm, v in (("pVAH", vah), ("pVAL", val), ("pPOC", poc)):
            if ymin <= v <= ymax: labels.append([v, f"{nm} {fmt(v)}", C["poc"]])
        legend += [Patch(fc=C["va"], alpha=0.25, label="Prior value area"), Line2D([], [], color=C["poc"], lw=1, label="Prior POC")]
    for key, (a, b), w, txt in (("prior_day", ("PDH", "PDL"), 1.2, "Prior session high / low"), ("prior_week", ("PWH", "PWL"), 3.0, "Prior week high / low")):
        if key in elements and lv.get(key):
            for nm, v in zip((a, b), lv[key]):
                ax.plot([-0.5, n - 0.5], [v, v], color=C[key], lw=w, zorder=3)
                if ymin <= v <= ymax: labels.append([v, f"{nm} {fmt(v)}", C[key]])
            legend.append(Line2D([], [], color=C[key], lw=w, label=txt))

    for m, w in SMAS:
        k = f"sma{m}"
        if k not in elements or k not in overlays: continue
        ys = overlays[k]; xs = [x for x, y in enumerate(ys) if y is not None]
        if not xs: continue
        ax.plot(xs, [ys[x] for x in xs], color=C[k], lw=w, zorder=2, solid_capstyle="butt")
        if ymin <= ys[xs[-1]] <= ymax: ax.text(n + pad_after + 0.3, ys[xs[-1]], str(m), color=rgb(C[k]), alpha=0.7, fontsize=9, va="center")
        legend.append(Line2D([], [], color=rgb(C[k]), lw=w, alpha=0.5, label=f"SMA {m}"))
    if "ema9" in elements and "ema9" in overlays:
        ax.plot(range(n), overlays["ema9"], color=C["ema9"], lw=1.4, zorder=5)
        legend.append(Line2D([], [], color=C["ema9"], lw=1.5, label="EMA 9"))
    if "vwap" in elements and overlays.get("vwap") and any(v is not None for v in overlays["vwap"]):
        ys = overlays["vwap"]
        for k in range(1, n):  # break the line at session resets
            if ys[k] is None or ys[k - 1] is None or abs(ys[k] - ys[k - 1]) > 0.25 * span: continue
            ax.plot([k - 1, k], [ys[k - 1], ys[k]], color=C["vwap"], lw=1.3, ls=(0, (5, 4)), zorder=5)
        legend.append(Line2D([], [], color=C["vwap"], lw=1.4, ls=(0, (5, 4)), label="VWAP"))
    if "kernel" in elements and overlays.get("kernel"):
        kr = overlays["kernel"]
        for k in range(1, n):
            if kr[k] is None or kr[k - 1] is None: continue
            ax.plot([k - 1, k], [kr[k - 1], kr[k]], color=C["kern_up"] if kr[k] >= kr[k - 1] else C["kern_dn"],
                    lw=2.4, ls=(0, (4, 3)), zorder=6, solid_capstyle="butt")
        legend.append(Line2D([], [], color=C["kern_dn"], lw=2.4, ls=(0, (4, 3)), label="Kernel regression (red ↓ / teal ↑)"))

    body_min = span * 0.002
    for k in range(n):
        up = Cl[k] >= O[k]
        ax.plot([k, k], [L[k], H[k]], color=C["wick"], lw=0.9, zorder=7)
        ax.add_patch(Rectangle((k - 0.34, min(O[k], Cl[k])), 0.68, max(abs(Cl[k] - O[k]), body_min),
                               fc=C["up_fill"] if up else C["dn_fill"], ec=C["up_edge"] if up else C["dn_edge"], lw=0.7, zorder=8))

    labels.sort(key=lambda s: s[0]); g = 0.022 * (ymax - ymin)
    for a in range(1, len(labels)):
        if labels[a][0] - labels[a - 1][0] < g: labels[a][0] = labels[a - 1][0] + g
    for y, t, c in labels: ax.text(n + pad_after + 3.0, y, t, color=rgb(c), fontsize=10, va="center", zorder=9)

    if "round_numbers" in elements:
        step = nice_step(ymax - ymin); xs = n + pad_after + margin * 0.55
        v = math.floor(ymin / step) * step
        while v < ymax:
            big = abs(round(v / step) % 5) == 0
            ax.plot([xs, right], [v, v], color="#e53935" if big else "#9e9e9e", lw=1.6 if big else 0.8,
                    ls="-" if big else (0, (6, 4)), zorder=1)
            v += step

    if "sessions" in elements:
        ys = ymax - 0.035 * span; first = {}
        for k, t in enumerate(T):
            col = None
            for nm, a, b, zn, cc in SESSIONS:
                z = ZoneInfo(zn); lt = t.astimezone(z)
                if lt.replace(hour=a[0], minute=a[1]) <= lt < lt.replace(hour=b[0], minute=b[1]): col = cc; first.setdefault(nm, (k, cc))
            if col: ax.plot(k, ys, "o", ms=4.2, color=col, alpha=0.9, zorder=4)
        for nm, (k, cc) in first.items(): ax.text(k, ys - 0.025 * span, nm, color=cc, fontsize=10.5, va="top")

    if extra: extra(ax, ymin, ymax)

    hour_step = 1 if minutes <= 5 else 4 if minutes <= 30 else 24
    ticks, tl = [], []
    for k, t in enumerate(T):
        if t.minute == 0 and t.hour % hour_step == 0 and (k == 0 or T[k - 1].hour != t.hour):
            ticks.append(k); tl.append(f"{t.day} {t:%b}" if t.hour == 0 else t.strftime("%H:%M"))
    ax.set_xticks(ticks); ax.set_xticklabels(tl); ax.set_xlim(-1, right); ax.set_ylim(ymin, ymax)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v)))
    ax.set_xlabel(f"Time ({config.tz_name()})", color="#555555", fontsize=11)
    ax.text(0.5, 0.012, f"H: {fmt(hi)}      L: {fmt(lo)}", transform=ax.transAxes, ha="center", fontsize=12, color="#1e88e5")
    exch, _, tick = sym.partition(":")
    fig.text(0.012, 0.975, f"{tick or exch} · {minutes} · {exch if tick else ''}", fontsize=12, color="#555555", va="top")
    if title: fig.text(0.012, 0.955, title, fontsize=17, color="#111111", va="top", weight="bold")
    if subtitle: fig.text(0.012, 0.93, subtitle, fontsize=12, color="#555555", va="top")
    if legend: ax.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.045), ncol=7, fontsize=10.5, frameon=False)
    fig.subplots_adjust(left=0.012, right=0.955, top=0.9, bottom=0.12)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="white"); plt.close(fig)
    return out
