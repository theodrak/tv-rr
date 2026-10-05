"""Chart every trade in the log twice — as it stood at the entry, and its follow-through — with the risk/reward tool drawn
on, plus a Markdown page showing them all.

usage: gallery.py [--file WORKBOOK] [--note NOTE.md] [--title TITLE] [--only YYYY-MM-DD …] [--symbol SYMBOL] [--format pdf,html,markdown]

Charts use gallery.timeframe (e.g. 5) when set, otherwise the trade's own timeframe when its bars are stored (else 5m,
else the nearest held). "At entry" shows only
what was visible at the fill: with 1m data the entry candle is rebuilt up to the fill minute; without it, the entry
candle is drawn from its open to the entry price. Which overlays appear is config gallery.elements. Images go to
gallery.images_dir (default: a "Charts" folder beside the workbook); the page to gallery.notes_dir (default: beside the
workbook), linked Obsidian-style or as plain Markdown (gallery.link_style). gallery.format (or --format) picks the
outputs: "markdown" (the page), "html" (one page that opens in any browser) and/or "pdf" (a summary page, then one
page per trade), all beside each other with the same name.
"""
import argparse, datetime as dt, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tv-rr-trades" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, indicators, prices  # noqa: E402
from extract import UTC, candle_path, legacy_name  # noqa: E402
from chart import decimals, draw  # noqa: E402

BEFORE, AFTER = 144, 24  # chart bars before the entry candle and after the exit
_series = {}


def chart_minutes(sym, interval):
    tfs = prices.timeframes(sym)
    if not tfs: return None
    try: want = int(str(interval).rstrip("mM")) if str(interval).rstrip("mM").isdigit() else None
    except ValueError: want = None
    if want in tfs: return want
    if 5 in tfs: return 5
    return min(tfs, key=lambda m: abs(m - (want or 5)))


def overlays_for(sym, m, bars):
    k = (sym, m)
    if k not in _series:
        c = [b["c"] for b in bars]
        ser = {f"sma{n}": indicators.sma(c, n) for n in (50, 100, 200, 500, 1000)}
        ser["ema9"] = indicators.ema(c, 9); ser["kernel"] = indicators.kernel_series(bars); ser["vwap"] = indicators.vwap_series(sym, bars)
        _series[k] = ser
    return _series[k]


def levels_for(sym, bars, i, m, elements):
    """Prior session high/low, prior week high/low and the prior session's value area, as of bar i."""
    per_day = max(1, 1440 // m); out = {}
    ds = indicators.day_start(sym, bars[i]["t"]); prev = indicators.day_start(sym, ds - 1)
    day = [b for b in bars[max(0, i - 3 * per_day):i] if prev <= b["t"] < ds]
    if day and {"prior_day", "prior_value"} & set(elements):
        out["prior_day"] = (max(b["h"] for b in day), min(b["l"] for b in day))
        if all("v" in b for b in day):
            hi, lo = out["prior_day"]; nb = 60; step = (hi - lo) / nb or 1; vol = [0.0] * (nb + 1)
            for b in day:
                a, z = int((b["l"] - lo) / step), int((b["h"] - lo) / step)
                for j in range(a, z + 1): vol[min(j, nb)] += b["v"] / (z - a + 1)
            poc = max(range(len(vol)), key=vol.__getitem__); tot = sum(vol); acc = vol[poc]; a = z = poc
            while acc < 0.7 * tot and (a > 0 or z < nb):
                up = vol[z + 1] if z < nb else -1; dn = vol[a - 1] if a > 0 else -1
                if up >= dn: z += 1; acc += up
                else: a -= 1; acc += dn
            out["value"] = (lo + a * step, lo + (z + 1) * step, lo + (poc + 0.5) * step)
    if "prior_week" in elements:
        week = lambda t: dt.datetime.fromtimestamp(indicators.day_start(sym, t) + 43200, UTC).isocalendar()[:2]
        cur = week(bars[i]["t"]); back = [b for b in bars[max(0, i - 16 * per_day):i] if week(b["t"]) < cur]
        if back:
            pk = max(week(b["t"]) for b in back); pw = [b for b in back if week(b["t"]) == pk]
            out["prior_week"] = (max(b["h"] for b in pw), min(b["l"] for b in pw))
    return out


def fill_point(fine, t0, e):
    """First bar from the drawing's time whose path crosses the entry; returns (bar, path up to the fill)."""
    for b in (x for x in fine if x["t"] >= t0):
        p = candle_path(b)
        for k in range(3):
            if min(p[k], p[k + 1]) <= e <= max(p[k], p[k + 1]): return b, p[:k + 1] + [e]
    return None, None


def draw_pair(r, label, tag, images_dir, elements):
    sym = r["Symbol"]; long_ = r["Direction"] == "Long"; e, sl, tp = r["Entry"], r["Stop"], r["TP planned"]
    t0 = int(r["Entry (UTC)"].replace(tzinfo=UTC).timestamp())
    m = chart_minutes(sym, config.load()["gallery"].get("timeframe") or r.get("Timeframe"))
    if m is None: return None
    bars = prices.load(sym, m); fine, ftf = prices.bars_for(sym, t0)
    if not bars or not fine: return None
    fb, path = fill_point(fine, t0, e)
    if fb is None: return None
    sec = m * 60; bucket = fb["t"] - fb["t"] % sec if m <= 60 else indicators.bucket(sym, m, fb["t"])
    ts = [b["t"] for b in bars]
    if bucket not in ts: return None
    i = ts.index(bucket)
    exit_t = int(r["Exit time"].replace(tzinfo=config.tz()).timestamp()) if r.get("Exit time") else None
    j = next((k for k in range(i, len(bars)) if exit_t is not None and bars[k]["t"] <= exit_t < bars[k]["t"] + sec), i)
    win = r["Outcome"] == "TP"; tz = config.tz()
    fill_l = dt.datetime.fromtimestamp(fb["t"], tz); nd = decimals(sym, e)
    f = lambda v: f"{v:,.{nd}f}"
    head = (f"{r['Direction']} · entry {f(e)} at {fill_l:%H:%M} · stop {f(sl)} · TP {f(tp)} · {r['Outcome']} {r['Result R']:+.1f}R"
            + (f" at {r['Exit time']:%H:%M}" if r.get("Exit time") else "")
            + (f" · MAE {r['MAE pts']:.1f}" if r.get("MAE pts") is not None else "")
            + (f" · MFE {r['MFE pts']:.1f}" if r.get("MFE pts") is not None else ""))
    ser = overlays_for(sym, m, bars); lv = levels_for(sym, bars, i, m, elements); PAD = 24

    def rr(ax, x0, x_end, n, exit_k=None, span=None):
        from matplotlib.patches import Rectangle
        ax.add_patch(Rectangle((x0, min(e, tp)), x_end - x0, abs(tp - e), color="#26a69a", alpha=0.20, lw=0, zorder=2))
        ax.add_patch(Rectangle((x0, min(e, sl)), x_end - x0, abs(sl - e), color="#ef5350", alpha=0.20, lw=0, zorder=2))
        ax.plot([x0, x_end], [e, e], color="#424242", lw=1.6, zorder=9)
        lx = n + 1.0
        for y, txt, col in ((tp, f"TP {f(tp)}  (+{f(abs(tp - e))})", "#00796b"), (e, f"Entry {f(e)}  {fill_l:%H:%M}", "#212121"),
                            (sl, f"Stop {f(sl)}  (−{f(abs(sl - e))})", "#c62828")):
            ax.plot([x_end, lx], [y, y], color=col, lw=0.9, ls=(0, (2, 2)), zorder=8)
            ax.text(lx, y, txt, fontsize=12, color=col, weight="bold", va="center", zorder=12, bbox=dict(fc="white", ec=col, lw=1.0, pad=3))
        if exit_k is not None and r.get("Exit time"):
            px = tp if win else sl; col = "#00796b" if win else "#c62828"
            ax.plot(exit_k, px, marker="o", ms=14, mfc="none", mec=col, mew=2.6, zorder=13)
            ax.text(lx, px + (1 if px > e else -1) * 0.045 * span, f"{'TP hit' if win else 'Stopped'} {r['Exit time']:%H:%M}  ({r['Result R']:+.1f}R)",
                    fontsize=12, color=col, weight="bold", va="center", zorder=12, bbox=dict(fc="white", ec="#9e9e9e", pad=3))

    start = max(0, i - BEFORE)
    # at entry: the entry candle as it stood at the fill, and nothing after it
    win_bars = [dict(b) for b in bars[start:i + 1]]
    if ftf == "1m":
        pre = [b for b in fine if bucket <= b["t"] < fb["t"]]
        px = [x for b in pre for x in (b["o"], b["h"], b["l"], b["c"])] + path
        win_bars[-1].update(o=pre[0]["o"] if pre else path[0], h=max(px), l=min(px), c=path[-1])
    else:
        o = win_bars[-1]["o"]; win_bars[-1].update(h=max(o, e), l=min(o, e), c=e)
    ov = {k: list(v[start:i + 1]) for k, v in ser.items()}
    pc, fc = win_bars[-1]["c"], bars[i]["c"]
    for n_ in (50, 100, 200, 500, 1000):
        if ov[f"sma{n_}"][-1] is not None: ov[f"sma{n_}"][-1] += (pc - fc) / n_
    if len(ov["ema9"]) > 1: ov["ema9"][-1] = 0.2 * pc + 0.8 * ov["ema9"][-2]
    ov["kernel"][-1] = ov["kernel"][-2] if len(ov["kernel"]) > 1 else None  # the line is only known at a candle's close
    ov["vwap"][-1] = ov["vwap"][-2] if len(ov["vwap"]) > 1 else None
    title_d = f"{fill_l:%a} {fill_l.day} {fill_l:%b %Y}"
    p1 = draw(sym, m, win_bars, ov, images_dir / f"{prices.safe(sym)} {label} {tag} entry.png", elements, lv,
              extra=lambda ax, ymin, ymax: (rr(ax, len(win_bars) - 1.5, len(win_bars) + 0.5, len(win_bars)),
                                            ax.text(len(win_bars) - 1, ymax - 0.11 * (ymax - ymin), "entry candle as\nit stood at the fill",
                                                    ha="center", va="top", fontsize=10, color="#6a1b9a", zorder=12)),
              title=f"{title_d} — {label}: the chart at the entry ({fill_l:%H:%M})", subtitle=head, pad_after=PAD)
    end = min(len(bars), j + AFTER + 1)
    fol = bars[start:end]; ov2 = {k: v[start:end] for k, v in ser.items()}
    p2 = draw(sym, m, fol, ov2, images_dir / f"{prices.safe(sym)} {label} {tag} follow.png", elements, lv,
              extra=lambda ax, ymin, ymax: rr(ax, i - start - 0.5, j - start + 0.5, len(fol), exit_k=j - start, span=ymax - ymin),
              title=f"{title_d} — {label}: follow-through ({r['Outcome']})", subtitle=head, pad_after=PAD)
    return p1, p2


def link(p, note_dir, style):
    if style == "obsidian": return f"![[{p.name}]]"
    try: rel = p.relative_to(note_dir)
    except ValueError: rel = p
    return f"![]({str(rel).replace(' ', '%20')})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file"); ap.add_argument("--note"); ap.add_argument("--title"); ap.add_argument("--only", nargs="*"); ap.add_argument("--symbol"); ap.add_argument("--format")
    a = ap.parse_args(); wbp = config.workbook(a.file); label = a.title or wbp.stem
    g = config.load()["gallery"]; elements = g["elements"]
    images = config.path(g["images_dir"]) or wbp.parent / "Charts"
    from openpyxl import load_workbook
    rows = list(load_workbook(wbp, read_only=True)["Trades"].iter_rows(values_only=True))
    head = [legacy_name(h) for h in rows[0]]; trades = [dict(zip(head, x)) for x in rows[1:] if any(v is not None for v in x)]
    trades = [t for t in trades if t.get("Outcome") in ("TP", "Stop") and None not in (t.get("Entry"), t.get("Stop"), t.get("TP planned"))]
    if a.only: trades = [t for t in trades if t["Entry time"].strftime("%Y-%m-%d") in a.only]
    if a.symbol: trades = [t for t in trades if t["Symbol"] == a.symbol]
    made = []
    for t in sorted(trades, key=lambda t: t["Entry (UTC)"]):
        tag = t["Entry time"].strftime("%Y-%m-%d %H%M")
        pr = draw_pair(t, label, tag, images, elements)
        if pr: made.append((t, pr)); print(f"{tag} {t['Symbol']} {t['Direction']:5} {t['Outcome']:4} → {pr[0].name}")
        else: print(f"{tag} {t['Symbol']}: skipped (no price data around the entry — add exports and run prices.py ingest)")
    if not made: sys.exit("no trades could be charted")
    note = Path(a.note).expanduser() if a.note else (config.path(g["notes_dir"]) or wbp.parent) / f"{label} - trade gallery.md"
    fmts = [f.strip() for f in a.format.split(",")] if a.format else (g.get("format") or ["html"])
    if isinstance(fmts, str): fmts = [fmts]
    if "markdown" in fmts: write_note(note, label, wbp, made, g["link_style"]); print(f"page: {note}")
    if "html" in fmts:
        p = write_html(note.with_suffix(".html"), label, wbp, made); print(f"html: {p}")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent)); from enrich import add_chart_links
            n = add_chart_links(wbp, p); print(f"workbook: {n} trades linked to the gallery (Chart column)")
            if n and sys.platform == "darwin":
                print(f"Excel for Mac asks permission for each linked file. The first time it does, choose the folder "
                      f"\"{p.parent.name}\" in the Grant File Access dialog (not the single file) and click Grant Access; "
                      f"every other link then opens without asking.")
        except PermissionError:
            print("workbook is open in Excel — close it and run gallery.py again to add the Chart links")
    if "pdf" in fmts: p = write_pdf(note.with_suffix(".pdf"), label, wbp, made); print(f"pdf: {p}")


def summary(made):
    """[(group, trades, won, win %, avg MAE, avg MFE)] for All, Long, Short and each symbol when there are several."""
    avg = lambda xs: f"{statistics.mean(xs):.1f}" if xs else "–"
    ex = lambda ts, k: [t[k] for t in ts if t.get(k) is not None]
    syms = sorted({t["Symbol"] for t, _ in made}); out = []
    for grp in ("All", "Long", "Short") + (tuple(syms) if len(syms) > 1 else ()):
        s = [t for t, _ in made if grp == "All" or grp in (t["Direction"], t["Symbol"])]
        if not s: continue
        w = sum(t["Outcome"] == "TP" for t in s); r = sum(t.get("Result R") or 0 for t in s)
        out.append((grp, len(s), w, f"{100 * w / len(s):.0f}%", f"{r:+.1f}R", avg(ex(s, "MAE pts")), avg(ex(s, "MFE pts"))))
    return out


def trade_line(t):
    return (f"Entry {t['Entry']:,} · stop {t['Stop']:,} · TP {t['TP planned']:,} · {t['Result R']:+.1f}R"
            + (f" · MAE {t['MAE pts']:.1f}" if t.get("MAE pts") is not None else "")
            + (f" · MFE {t['MFE pts']:.1f}" if t.get("MFE pts") is not None else ""))


def heading(t):
    d = t["Entry time"]; res = "✅ TP" if t["Outcome"] == "TP" else "❌ Stop"
    return f"{d:%a} {d.day} {d:%b %Y} {d:%H:%M} · {t['Symbol']} · {t['Direction']} · {res}"


def write_pdf(path, label, wbp, made):
    """A4 portrait: a summary page, then one page per trade with its at-entry and follow-through charts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    first, last = made[0][0]["Entry time"], made[-1][0]["Entry time"]
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69)); fig.text(0.07, 0.93, f"{label} — trade gallery", fontsize=20, weight="bold")
        fig.text(0.07, 0.905, f"{len(made)} trades · {first.day} {first:%b %Y} → {last.day} {last:%b %Y} · times {config.tz_name()} · from {wbp.name}",
                 fontsize=10, color="#555555")
        rows = summary(made); hdr = ("", "Trades", "Won", "Win %", "Net R", "Avg MAE", "Avg MFE")
        tb = fig.add_axes([0.07, 0.86 - 0.03 * (len(rows) + 1), 0.86, 0.03 * (len(rows) + 1)]); tb.axis("off")
        t_ = tb.table(cellText=[list(map(str, r)) for r in rows], colLabels=hdr, loc="upper left", cellLoc="center")
        t_.auto_set_font_size(False); t_.set_fontsize(10); t_.scale(1, 1.4)
        y = 0.80 - 0.03 * len(rows)
        fig.text(0.07, y, "Each trade has two charts: at entry (only what was visible at the fill) and the follow-through, both with\n"
                 "the risk/reward tool: the entry line, the green TP zone and the red stop zone.", fontsize=9.5, color="#333333", va="top")
        y -= 0.06
        for t, _ in made:
            if y < 0.05: pdf.savefig(fig); plt.close(fig); fig = plt.figure(figsize=(8.27, 11.69)); y = 0.95
            fig.text(0.07, y, heading(t).replace("✅ ", "").replace("❌ ", ""), fontsize=8.5, color="#2e7d32" if t["Outcome"] == "TP" else "#c62828")
            y -= 0.017
        pdf.savefig(fig); plt.close(fig)
        for t, (p1, p2) in made:
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.05, 0.965, heading(t).replace("✅ ", "").replace("❌ ", ""), fontsize=13, weight="bold",
                     color="#2e7d32" if t["Outcome"] == "TP" else "#c62828")
            fig.text(0.05, 0.945, trade_line(t), fontsize=9.5, color="#555555")
            img = [plt.imread(p) for p in (p1, p2)]
            h = 0.96 * 8.27 * img[0].shape[0] / img[0].shape[1] / 11.69  # page fraction one full-width chart needs
            for k, im in enumerate(img):
                ax = fig.add_axes([0.02, 0.925 - (k + 1) * h - k * 0.02, 0.96, h]); ax.imshow(im, interpolation="lanczos"); ax.axis("off")
            pdf.savefig(fig, dpi=200); plt.close(fig)
    return path


def anchor(t):
    """A stable id for a trade's section: its symbol and TradingView drawing id (the workbook's key for the trade)."""
    import re
    key = t.get("Drawing id") or t["Entry time"].strftime("%Y%m%d%H%M")
    return "t-" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{t['Symbol']}-{key}")


def trade_links_dir(page):
    return page.with_name(page.stem + "_files") / "trades"


def write_html(path, label, wbp, made):
    """One self-contained page for any browser; images are linked relative to the page, clicking one opens it full size.
    Each trade's section has an id (anchor()), and a one-line page per trade in <page>_files/trades/ jumps to it: Excel
    drops the #anchor from links to local files, so the workbook's Chart column links to those pages instead."""
    import html as h, os
    first, last = made[0][0]["Entry time"], made[-1][0]["Entry time"]
    rel = lambda p: os.path.relpath(p, path.parent).replace(os.sep, "/")
    rows = "".join("<tr>" + "".join(f"<td>{h.escape(str(c))}</td>" for c in r) + "</tr>" for r in summary(made))
    body = "".join(
        f'<section id="{anchor(t)}"><h2 class="{"tp" if t["Outcome"] == "TP" else "sl"}">{h.escape(heading(t))}</h2><p>{h.escape(trade_line(t))}</p>'
        f'<a href="{rel(p1)}"><img src="{rel(p1)}" loading="lazy" alt="at entry"></a>'
        f'<a href="{rel(p2)}"><img src="{rel(p2)}" loading="lazy" alt="follow-through"></a></section>' for t, (p1, p2) in made)
    path.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h.escape(label)} — trade gallery</title><style>
body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#222;background:#fff}}
h1{{margin:0 0 4px}} .sub{{color:#666}} table{{border-collapse:collapse;margin:16px 0}} td,th{{border:1px solid #ddd;padding:4px 12px;text-align:center}}
section{{border-top:1px solid #eee;padding:16px 0}} h2{{font-size:17px;margin:0}} .tp{{color:#2e7d32}} .sl{{color:#c62828}}
img{{width:100%;margin:6px 0;border:1px solid #eee}}</style></head><body>
<h1>{h.escape(label)} — trade gallery</h1><p class="sub">{len(made)} trades · {first.day} {first:%b %Y} → {last.day} {last:%b %Y} · times {h.escape(config.tz_name())} · from {h.escape(wbp.name)}</p>
<table><tr><th></th><th>Trades</th><th>Won</th><th>Win %</th><th>Net R</th><th>Avg MAE</th><th>Avg MFE</th></tr>{rows}</table>
<p>Each trade has two charts: at entry (only what was visible at the fill) and the follow-through. Click a chart to open it full size.</p>
{body}</body></html>""")
    d = trade_links_dir(path); d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.html"): old.unlink()
    for t, _ in made:
        to = f"../../{path.name}#{anchor(t)}".replace(" ", "%20")
        (d / f"{anchor(t)}.html").write_text(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={to}">'
                                            f'<script>location.replace("{to}")</script><a href="{to}">Open the trade in the gallery</a>')
    return path


def write_note(note, label, wbp, made, style):
    wins = [t for t, _ in made if t["Outcome"] == "TP"]
    avg = lambda xs: f"{statistics.mean(xs):.1f}" if xs else "–"
    ex = lambda ts, k: [t[k] for t in ts if t.get(k) is not None]
    first, last = made[0][0]["Entry time"], made[-1][0]["Entry time"]
    syms = sorted({t["Symbol"] for t, _ in made})
    L = ["---", "tags: [trading, backtest, trade-gallery]", f"source: \"{wbp.name}\"", f"trades: {len(made)}",
         f"period: {first:%Y-%m-%d} to {last:%Y-%m-%d}", "---", "",
         f"# {label} — every trade at entry and after", "",
         f"From `{wbp.name}` · {len(made)} trades, {first.day} {first:%b} → {last.day} {last:%b %Y} · {', '.join(syms)} · times {config.tz_name()}.", "",
         "Each trade has two charts: **at entry** (only what was visible at the fill) and **follow-through** (to the exit, plus a little after). "
         "Both carry the risk/reward tool: the entry line, the green TP zone and the red stop zone.", "",
         "| | Trades | Won | Win % | Avg MAE | Avg MFE |", "|---|---|---|---|---|---|",
         f"| All | {len(made)} | {len(wins)} | {100 * len(wins) / len(made):.0f}% | {avg(ex([t for t, _ in made], 'MAE pts'))} | {avg(ex([t for t, _ in made], 'MFE pts'))} |"]
    for grp in ("Long", "Short") + (tuple(syms) if len(syms) > 1 else ()):
        s = [t for t, _ in made if grp in (t["Direction"], t["Symbol"])]
        if s:
            w = sum(t["Outcome"] == "TP" for t in s)
            L.append(f"| {grp} | {len(s)} | {w} | {100 * w / len(s):.0f}% | {avg(ex(s, 'MAE pts'))} | {avg(ex(s, 'MFE pts'))} |")
    L += ["", "## Trades", ""]
    for t, (p1, p2) in made:
        d = t["Entry time"]; res = "✅ TP" if t["Outcome"] == "TP" else "❌ Stop"
        L += [f"### {d:%a} {d.day} {d:%b} {d:%H:%M} · {t['Symbol']} · {t['Direction']} · {res}", "",
              f"Entry {t['Entry']:,} · stop {t['Stop']:,} · TP {t['TP planned']:,} · {t['Result R']:+.1f}R"
              + (f" · MAE {t['MAE pts']:.1f}" if t.get("MAE pts") is not None else "") + (f" · MFE {t['MFE pts']:.1f}" if t.get("MFE pts") is not None else ""), "",
              link(p1, note.parent, style), "", link(p2, note.parent, style), ""]
    note.parent.mkdir(parents=True, exist_ok=True); note.write_text("\n".join(L))


if __name__ == "__main__":
    main()
