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
import importlib.util  # noqa: E402
# loaded by path, so another skill's own "chart" module on sys.path can never be picked up instead
_spec = importlib.util.spec_from_file_location("tvrr_chart", Path(__file__).resolve().parent / "chart.py")
_chart = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_chart)
decimals, draw = _chart.decimals, _chart.draw

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
            be = r["Outcome"] == "BE"
            px = e if be else tp if win else sl; col = "#616161" if be else "#00796b" if win else "#c62828"
            ax.plot(exit_k, px, marker="o", ms=14, mfc="none", mec=col, mew=2.6, zorder=13)
            ax.text(lx, (px + (1 if tp > e else -1) * 0.09 * span) if be else px + (1 if px > e else -1) * 0.045 * span,
                    f"{'Break-even' if be else 'TP hit' if win else 'Stopped'} {r['Exit time']:%H:%M}  ({r['Result R']:+.1f}R)",
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
    g = config.gallery_for(wbp); elements = g["elements"]
    images = config.path(g["images_dir"]) or wbp.parent / "Charts"
    from openpyxl import load_workbook
    rows = list(load_workbook(wbp, read_only=True)["Trades"].iter_rows(values_only=True))
    head = [legacy_name(h) for h in rows[0]]; trades = [dict(zip(head, x)) for x in rows[1:] if any(v is not None for v in x)]
    trades = [t for t in trades if t.get("Outcome") in ("TP", "Stop", "BE") and None not in (t.get("Entry"), t.get("Stop"), t.get("TP planned"))]
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
                print("Excel for Mac: the links open Office's own copy of a jump page for each trade, so Excel shouldn't ask "
                      "permission. If the gallery folder moves, run the gallery again to refresh the links.")
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


FACTS = ("Risk", "5m ATR", "1/2 stop", "1R", "1.5R", "MAE", "MFE", "Decision", "Grade", "TV chart")
NOTES = ("Filter notes", "Grade notes", "General notes")
RESULT_MARK = {"Win": "✅ Win", "Loss": "❌ Loss", "BE": "⚪ BE"}
# Outcome → (CSS class, heading mark, sidebar word, colour). BE: the stop had been moved to the entry and price came back to it
OUTCOMES = {"TP": ("tp", "✅ TP", "Win", "#2e7d32"), "Stop": ("sl", "❌ Stop", "Loss", "#c62828"), "BE": ("be", "⚪ BE", "BE", "#616161")}
res_of = lambda t: OUTCOMES.get(t["Outcome"], OUTCOMES["Stop"])


def tv_links(wbp):
    """{drawing id: URL} from the workbook's TV chart column (the hyperlink's target when the cell shows text)."""
    from openpyxl import load_workbook
    try: ws = load_workbook(wbp)["Trades"]
    except Exception: return {}
    head = [c.value for c in ws[1]]
    if "TV chart" not in head or "Drawing id" not in head: return {}
    c_tv, c_id = head.index("TV chart") + 1, head.index("Drawing id") + 1; out = {}
    for i in range(2, ws.max_row + 1):
        cell = ws.cell(i, c_tv); url = cell.hyperlink.target if cell.hyperlink is not None else cell.value
        if isinstance(url, str) and url.startswith(("http://", "https://")): out[ws.cell(i, c_id).value] = url
    return out


def facts(t, links):
    """([(name, text, url)], [(note name, text)]) for each trade: the top row (risk in points, or pips for 5-decimal FX;
    the 5m ATR; the half-stop and 1R / 1.5R what-ifs; MAE / MFE; decision, grade and the TradingView link) and the
    notes, which go on their own line. Empty values show as "–"."""
    tick = config.symbol(t["Symbol"]).get("tick")
    risk = t.get("Risk pts")
    if risk is None: rtxt = "–"
    elif tick and tick < 0.001: rtxt = f"{risk / (tick * 10):,.1f} pips"
    else: rtxt = f"{risk:,.1f} pts"
    num = lambda k: "–" if t.get(k) is None else f"{t[k]:,.1f}"
    txt = lambda k: "–" if t.get(k) in (None, "") else str(t[k])
    url = links.get(t.get("Drawing id"))
    top = [("Risk", rtxt, None), ("5m ATR", num("ATR 5m"), None), ("1/2 stop", txt("1/2 stop"), None), ("1R", txt("TP 1R"), None),
           ("1.5R", txt("TP 1.5R"), None), ("MAE", num("MAE pts"), None), ("MFE", num("MFE pts"), None),
           ("Decision", txt("Decision"), None), ("Grade", txt("Grade"), None), ("TV chart", "open" if url else "–", url)]
    return top, [(n, txt(n)) for n in NOTES]


def heading(t):
    d = t["Entry time"]; res = res_of(t)[1]
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
        for t, _ in newest_first(made):
            if y < 0.05: pdf.savefig(fig); plt.close(fig); fig = plt.figure(figsize=(8.27, 11.69)); y = 0.95
            fig.text(0.07, y, heading(t).replace("✅ ", "").replace("❌ ", "").replace("⚪ ", ""), fontsize=8.5, color=res_of(t)[3])
            y -= 0.017
        pdf.savefig(fig); plt.close(fig)
        for t, (p1, p2) in newest_first(made):
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.05, 0.965, heading(t).replace("✅ ", "").replace("❌ ", "").replace("⚪ ", ""), fontsize=13, weight="bold",
                     color=res_of(t)[3])
            fig.text(0.05, 0.945, trade_line(t), fontsize=9.5, color="#555555")
            img = [plt.imread(p) for p in (p1, p2)]
            h = 0.96 * 8.27 * img[0].shape[0] / img[0].shape[1] / 11.69  # page fraction one full-width chart needs
            for k, im in enumerate(img):
                ax = fig.add_axes([0.02, 0.925 - (k + 1) * h - k * 0.02, 0.96, h]); ax.imshow(im, interpolation="lanczos"); ax.axis("off")
            pdf.savefig(fig, dpi=200); plt.close(fig)
    return path


def newest_first(made):
    """The trades in the order the pages list them: the latest first."""
    return sorted(made, key=lambda m: m[0]["Entry time"], reverse=True)


def anchor(t):
    """A stable id for a trade's section: its symbol and TradingView drawing id (the workbook's key for the trade)."""
    import re
    key = t.get("Drawing id") or t["Entry time"].strftime("%Y%m%d%H%M")
    return "t-" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{t['Symbol']}-{key}")


def write_html(path, label, wbp, made, groups=()):
    """One self-contained page for any browser; images are linked relative to the page, clicking one opens it full size.
    groups adds a strategy's own filter rows: (title, key, value_of(trade), order of the values), key in lowercase letters.
    Each trade's section has an id (anchor()), and a one-line page per trade jumps to it (enrich.jump_dir: Office's
    container on a Mac, <page>_files/trades/ elsewhere), because Excel strips the #anchor from links to local files."""
    import html as h, os
    first, last = made[0][0]["Entry time"], made[-1][0]["Entry time"]
    rel = lambda p: os.path.relpath(p, path.parent).replace(os.sep, "/")
    syms = len({t["Symbol"] for t, _ in made}) > 1
    dec = lambda t: str(t.get("Decision") or "Taken")
    grade = lambda t: str(t.get("Grade") or "Ungraded")
    num = lambda v: "" if v is None else f"{v}"
    clear = lambda t: "" if t.get("Bars clear of EMA 9") in (None, "") else int(t["Bars clear of EMA 9"])
    attrs = lambda t: (f'data-res="{res_of(t)[0]}" data-dec="{h.escape(dec(t))}" data-grade="{h.escape(grade(t))}" data-nclear="{clear(t)}" '
                       f'data-r="{num(t.get("Result R"))}" data-mae="{num(t.get("MAE pts"))}" data-mfe="{num(t.get("MFE pts"))}" '
                       f'data-dir="{h.escape(t["Direction"])}"' + "".join(f' data-{k}="{h.escape(str(f(t)))}"' for _, k, f, _ in groups))
    side = "".join(
        f'<a href="#{anchor(t)}" class="{res_of(t)[0]}" {attrs(t)}>'
        f'<b>{t["Entry time"]:%a} {t["Entry time"].day} {t["Entry time"]:%b %H:%M}</b>'
        f'<span>{res_of(t)[2]} · {h.escape(t["Direction"])}'
        + (f' · {h.escape(t["Symbol"].split(":")[-1])}' if syms else "") + '</span></a>' for t, _ in newest_first(made))
    def values(f):
        order = {"Taken": 0, "Filtered": 1, "Missed": 2, "A+": 0, "A": 1, "B": 2, "C": 3, "D": 4, "F": 5, "Ungraded": 9}
        vals = sorted({f(t) for t, _ in made}, key=lambda v: (order.get(v, 8), v))
        return [(v, v, sum(f(t) == v for t, _ in made)) for v in vals]

    def group(title, key, items):
        """A row of toggle buttons: several in one group show trades matching any of them (OR); the groups combine (AND)."""
        btns = "".join(f'<button data-g="{key}" data-v="{h.escape(v)}">{h.escape(lbl)} <i>{n}</i></button>' for v, lbl, n in items)
        return f'<div class="grp"><div class="gt">{h.escape(title)}</div><div class="btns">{btns}</div></div>'

    def clear_range(made, clear):
        """From / To boxes for the "Bars clear of EMA 9" column; nothing when no trade has it."""
        vals = [clear(t) for t, _ in made if clear(t) != ""]
        if not vals: return ""
        return ('<div class="grp"><div class="gt">Bars clear of EMA 9</div><div class="btns rng">'
                f'from <input id="cmin" type="number" min="0" max="48" placeholder="any"> to '
                f'<input id="cmax" type="number" min="0" max="48" placeholder="any"> <i>{min(vals)}–{max(vals)} in this log</i></div></div>')

    def dims(p):
        import struct
        with open(p, "rb") as fh: head = fh.read(24)
        w, ht = struct.unpack(">II", head[16:24]); return f'width="{w}" height="{ht}"'
    links = tv_links(wbp)

    def fact_table(t):
        top, notes = facts(t, links); cells = []
        for _, v, u in top:
            if u: cells.append('<td><a href="%s" target="_blank">%s</a></td>' % (h.escape(u), h.escape(v)))
            else: cells.append('<td class="%s">%s</td>' % ({"Win": "rw", "Loss": "rl", "BE": "rb"}.get(v, ""), h.escape(v)))
        heads = "".join("<th>%s</th>" % h.escape(n) for n in FACTS)
        note = "".join('<div><b>%s</b> %s</div>' % (h.escape(n), h.escape(v)) for n, v in notes)
        return ('<div class="scroll"><table class="facts"><tr>%s</tr><tr>%s</tr></table></div><div class="notes">%s</div>'
                % (heads, "".join(cells), note))

    body = "".join(
        f'<section id="{anchor(t)}" {attrs(t)}><h2 class="{res_of(t)[0]}">{h.escape(heading(t))}</h2><p>{h.escape(trade_line(t))}</p>'
        f'{fact_table(t)}'
        f'<a class="ent" href="{rel(p1)}"><img src="{rel(p1)}" {dims(p1)} loading="lazy" alt="at entry"></a>'
        f'<a class="fol" href="{rel(p2)}"><img src="{rel(p2)}" {dims(p2)} loading="lazy" alt="follow-through"></a></section>' for t, (p1, p2) in newest_first(made))
    css = """
*{box-sizing:border-box} html{scroll-behavior:smooth} body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:#fff}
nav{position:fixed;top:0;left:0;bottom:0;width:230px;overflow-y:auto;border-right:1px solid #e5e5e5;background:#fafafa;padding:12px 8px}
nav h3{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#777;margin:4px 8px 8px}
#clear{float:right;float:right;font:11px inherit;text-transform:none;letter-spacing:0;padding:1px 8px;border:1px solid #ddd;background:#fff;border-radius:4px;cursor:pointer}
.grp{} .gt{font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.03em;margin:0 2px 3px}
.btns{display:flex;flex-wrap:wrap;gap:4px} .btns button{font:12px inherit;padding:3px 8px;border:1px solid #ddd;background:#fff;border-radius:4px;cursor:pointer}
.rng{align-items:center;font-size:12px;color:#555} .rng input{width:52px;font:12px inherit;padding:2px 4px;border:1px solid #ddd;border-radius:4px}
.rng i{font-style:normal;color:#999;font-size:11px}
.btns button i{font-style:normal;color:#999;font-size:11px} .btns button.on{background:#222;color:#fff;border-color:#222} .btns button.on i{color:#ccc}
nav a{display:block;padding:5px 8px;margin:1px 0;border-radius:5px;text-decoration:none;border-left:3px solid transparent;font-size:13px}
nav a b{display:block;font-weight:600;color:#222} nav a span{font-size:12px}
nav a.tp{border-left-color:#43a047} nav a.tp span{color:#2e7d32} nav a.sl{border-left-color:#e53935} nav a.sl span{color:#c62828} nav a.be{border-left-color:#9e9e9e} nav a.be span{color:#616161}
nav a:hover{background:#eee} nav a.active{background:#e3f2fd}
main{margin-left:230px;padding:0 28px 24px;max-width:1300px}
header.top{position:sticky;top:0;z-index:10;background:#fff;padding:14px 0 10px;border-bottom:1px solid #e5e5e5}
header.top h1{font-size:24px} header.top .sub{margin:0 0 8px;font-size:13px}
.bar{display:flex;gap:10px;align-items:stretch} .blk{border:1px solid #e5e5e5;border-radius:6px;padding:6px 10px;background:#fafafa}
.blk.filters{flex:1 1 auto;min-width:0} .blk:not(.filters){flex:0 0 auto}
.bt{font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.03em;margin-bottom:4px}
.grps{display:flex;flex-wrap:wrap;gap:4px 14px}
.stats table{border-collapse:collapse;margin:0;white-space:nowrap;font-size:12.5px} .stats th,.stats td{border:0;padding:1px 6px;text-align:right}
.stats tr:first-child th{font-size:10.5px;color:#888;font-weight:400} .stats th:first-child{text-align:left;color:#555;font-weight:600}
.stats tr:nth-child(2){font-weight:700}
h1{margin:0 0 4px} .sub{color:#666} table{border-collapse:collapse;margin:16px 0} td,th{border:1px solid #ddd;padding:4px 12px;text-align:center}
section{border-top:1px solid #eee;padding:16px 0;scroll-margin-top:calc(var(--hh, 150px) + 8px)} h2{font-size:17px;margin:0} .tp{color:#2e7d32} .sl{color:#c62828} .be{color:#616161}
img{width:100%;height:auto;margin:6px 0;border:1px solid #eee}
body.img-ent a.fol, body.img-fol a.ent{display:none}
main section a.ent, main section a.fol{cursor:zoom-in}
#lb{display:none;position:fixed;inset:0;z-index:100;background:rgba(30,30,30,.85);align-items:center;justify-content:center;cursor:zoom-out}
#lb.open{display:flex} #lb img{max-width:95vw;max-height:95vh;width:auto;height:auto;margin:0;border:0;object-fit:contain;background:#fff;
  box-sizing:border-box;border-radius:10px;border-left:6px solid transparent;box-shadow:0 6px 30px rgba(0,0,0,.45);cursor:default}
#lb img.tp{border-left-color:#43a047} #lb img.sl{border-left-color:#e53935} #lb img.be{border-left-color:#9e9e9e}
.lbnav{position:fixed;top:50%;transform:translateY(-50%);width:44px;height:64px;border:0;border-radius:6px;background:rgba(0,0,0,.45);
  color:#fff;font-size:38px;line-height:60px;cursor:pointer;z-index:101} .lbnav:hover{background:rgba(0,0,0,.7)} .lbnav:disabled{opacity:.2;cursor:default}
#lbprev{left:6px} #lbnext{right:6px}
#lbcap{position:fixed;bottom:4px;left:50%;transform:translateX(-50%);color:#fff;font-size:12.5px;background:rgba(0,0,0,.5);padding:2px 10px;border-radius:10px;white-space:nowrap}
#lbx{position:fixed;top:12px;right:16px;width:42px;height:42px;border:0;border-radius:50%;background:#e53935;color:#fff;
  font-size:22px;line-height:42px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);z-index:101} #lbx:hover{background:#c62828}
table.facts{margin:6px 0 8px;font-size:12.5px;width:100%} table.facts th{background:#f5f5f5;font-weight:600;white-space:nowrap;padding:3px 6px}
table.facts td{padding:3px 6px} td.rw{background:#e8f5e9;color:#2e7d32;font-weight:600} td.rl{background:#ffebee;color:#c62828;font-weight:600}
td.rb{background:#fff8e1;color:#a66b00;font-weight:600}
.scroll{overflow-x:auto} .notes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;font-size:12.5px;margin:0 0 8px;color:#333}
.notes b{display:block;font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.03em}
@media (max-width:800px){.notes{grid-template-columns:1fr}}
@media (max-width:800px){.bar{flex-direction:column} header.top{position:static} nav{position:static;width:auto;max-height:40vh;border-right:0;border-bottom:1px solid #e5e5e5} main{margin-left:0;padding:16px}}
"""
    js = """
const links=[...document.querySelectorAll('nav a')], byId=Object.fromEntries(links.map(a=>[a.hash.slice(1),a]));
function mark(id){links.forEach(a=>a.classList.toggle('active',a.hash==='#'+id));const a=byId[id];
  if(a){const n=a.parentElement,r=a.getBoundingClientRect(),q=n.getBoundingClientRect();if(r.top<q.top||r.bottom>q.bottom)a.scrollIntoView({block:'nearest'})}}
const obs=new IntersectionObserver(es=>{const v=es.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];
  if(v)mark(v.target.id)},{rootMargin:'0px 0px -70% 0px'});
document.querySelectorAll('main section').forEach(s=>obs.observe(s));
const sel={res:new Set(),dec:new Set(),grade:new Set()""" + "".join(f",{k}:new Set()" for _, k, _, _ in groups) + """}, secs=[...document.querySelectorAll('main section')];
const hasBE=secs.some(s=>s.dataset.res==='be');
function row(name,list){const n=list.length,w=list.filter(s=>s.dataset.res==='tp').length,l=list.filter(s=>s.dataset.res==='sl').length,num=k=>list.map(s=>parseFloat(s.dataset[k])).filter(x=>!isNaN(x)),
  avg=a=>a.length?(a.reduce((x,y)=>x+y,0)/a.length).toFixed(1):'–',r=num('r').reduce((x,y)=>x+y,0);
  return `<tr><th>${name}</th><td>${n}</td><td class="tp">${w}</td><td class="sl">${l}</td>${hasBE?`<td class="be">${n-w-l}</td>`:''}<td>${n?Math.round(100*w/n)+'%':'–'}</td>`
    +`<td class="${r>=0?'tp':'sl'}">${n?(r>=0?'+':'')+r.toFixed(1)+'R':'–'}</td><td>${avg(num('mae'))}</td><td>${avg(num('mfe'))}</td></tr>`}
function stats(list){return '<table><tr><th></th><th>Trades</th><th>Won</th><th>Lost</th>'+(hasBE?'<th>BE</th>':'')+'<th>Win %</th><th>Net R</th><th>MAE</th><th>MFE</th></tr>'
  +row('All',list)+row('Long',list.filter(s=>s.dataset.dir==='Long'))+row('Short',list.filter(s=>s.dataset.dir==='Short'))+'</table>'}
// "Bars clear of EMA 9" range: From / To, either may be blank (no limit); trades without the value drop out once one is set
const cmin=document.getElementById('cmin'), cmax=document.getElementById('cmax');
function inRange(e){if(!cmin)return true; const lo=cmin.value===''?null:+cmin.value, hi=cmax.value===''?null:+cmax.value;
  if(lo===null&&hi===null)return true; const v=e.dataset.nclear===''?NaN:+e.dataset.nclear;
  return !isNaN(v)&&(lo===null||v>=lo)&&(hi===null||v<=hi)}
function apply(){const ok=e=>Object.entries(sel).every(([g,set])=>set.size===0||set.has(e.dataset[g]))&&inRange(e);
  links.forEach(a=>a.style.display=ok(a)?'':'none');
  const shown=secs.filter(s=>{const v=ok(s);s.style.display=v?'':'none';return v});
  document.getElementById('shown').textContent=shown.length;document.getElementById('fstats').innerHTML=stats(shown)}
document.getElementById('ostats').innerHTML=stats(secs);
document.querySelectorAll('header .grp button').forEach(b=>b.onclick=()=>{const s=sel[b.dataset.g],v=b.dataset.v;
  if(s.has(v))s.delete(v);else s.add(v);b.classList.toggle('on',s.has(v));apply()});
if(cmin){cmin.oninput=apply; cmax.oninput=apply}
document.getElementById('clear').onclick=()=>{Object.values(sel).forEach(s=>s.clear()); if(cmin){cmin.value='';cmax.value=''}
  document.querySelectorAll('header .grp button').forEach(b=>b.classList.remove('on'));apply()};
apply();
document.querySelectorAll('header button[data-img]').forEach(b=>b.onclick=()=>{   // one choice at a time
  document.querySelectorAll('header button[data-img]').forEach(x=>x.classList.toggle('on',x===b));
  document.body.classList.remove('img-ent','img-fol'); if(b.dataset.img!=='both')document.body.classList.add('img-'+b.dataset.img);hh()});
// clicking a chart shows it at ~95% of the window over a greyed backdrop. The red cross, a click on the backdrop, a
// double-click or Escape closes it; the arrow keys and the side arrows step through the charts the page is showing,
// so the filters and the Images choice carry over.
const lb=document.getElementById('lb'), lbimg=document.getElementById('lbimg'), lbcap=document.getElementById('lbcap');
let lbList=[], lbAt=-1;
const shownCharts=()=>[...document.querySelectorAll('main section a.ent, main section a.fol')].filter(a=>a.offsetParent!==null);
function showAt(i){if(i<0||i>=lbList.length)return; lbAt=i; const a=lbList[i], sec=a.closest('section');
  lbimg.src=a.getAttribute('href'); lbimg.alt=a.querySelector('img').alt; lbimg.className=sec.dataset.res||'';
  lbcap.textContent=`${i+1} / ${lbList.length} · ${sec.querySelector('h2').textContent} · ${a.classList.contains('ent')?'at entry':'follow-through'}`;
  document.getElementById('lbprev').disabled=i===0; document.getElementById('lbnext').disabled=i===lbList.length-1;
  sec.scrollIntoView({behavior:'instant',block:'start'}); if(sec.id)mark(sec.id)}
function openLb(a){lbList=shownCharts(); showAt(lbList.indexOf(a)); lb.classList.add('open'); document.body.style.overflow='hidden'}
function closeLb(){lb.classList.remove('open'); lbimg.removeAttribute('src'); document.body.style.overflow=''; lbAt=-1}
document.querySelectorAll('main section a.ent, main section a.fol').forEach(a=>a.onclick=e=>{e.preventDefault(); openLb(a)});
document.getElementById('lbx').onclick=closeLb; lb.ondblclick=closeLb;
lb.onclick=e=>{if(e.target===lb)closeLb()};                 // a click on the greyed border
document.getElementById('lbprev').onclick=e=>{e.stopPropagation(); showAt(lbAt-1)};
document.getElementById('lbnext').onclick=e=>{e.stopPropagation(); showAt(lbAt+1)};
document.addEventListener('keydown',e=>{if(!lb.classList.contains('open'))return;
  if(e.key==='Escape')closeLb(); else if(e.key==='ArrowLeft'){e.preventDefault(); showAt(lbAt-1)} else if(e.key==='ArrowRight'){e.preventDefault(); showAt(lbAt+1)}});
function hh(){document.documentElement.style.setProperty('--hh',document.querySelector('header.top').offsetHeight+'px')}
hh(); window.addEventListener('resize',hh);
function go(){const id=location.hash.slice(1),e=id&&document.getElementById(id);if(e){e.scrollIntoView({behavior:'instant',block:'start'});mark(id)}}
window.addEventListener('load',go); window.addEventListener('hashchange',()=>mark(location.hash.slice(1)));
"""
    path.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h.escape(label)} — trade gallery</title><style>{css}</style></head><body>
<nav><h3><span id="shown">{len(made)}</span> of {len(made)} trades</h3>{side}</nav>
<main><header class="top"><h1>{h.escape(label)} — trade gallery</h1><p class="sub">{len(made)} trades · {first.day} {first:%b %Y} → {last.day} {last:%b %Y} · times {h.escape(config.tz_name())} · from {h.escape(wbp.name)}</p>
<div class="bar"><div class="blk"><div class="bt">All trades</div><div class="stats" id="ostats"></div></div>
<div class="blk filters"><div class="bt">Filters <button id="clear">Clear</button></div><div class="grps">
{group("Outcome", "res", [(c, w, n) for c, w, n in ((c, w, sum(res_of(t)[0] == c for t, _ in made)) for c, _, w, _ in OUTCOMES.values()) if n or c != "be"])}
{group("Decision", "dec", values(dec))}{group("Grade", "grade", values(grade))}
{"".join(group(title, k, [(v, v, n) for v in order if (n := sum(str(f(t)) == v for t, _ in made))]) for title, k, f, order in groups)}
{clear_range(made, clear)}
<div class="grp"><div class="gt">Images</div><div class="btns"><button data-img="ent">Entry only</button><button data-img="fol">Exit only</button><button data-img="both" class="on">Both</button></div></div></div></div>
<div class="blk"><div class="bt">Filtered</div><div class="stats" id="fstats"></div></div></div></header>
<p>Each trade has two charts: at entry (only what was visible at the fill) and the follow-through. Pick a trade on the left; click a chart to enlarge it, use ← → to step through the charts shown, and close it with the red cross, a click outside it, a double-click or Escape.</p>
{body}</main><div id="lb" role="dialog" aria-modal="true" aria-label="Chart"><button id="lbx" aria-label="Close">&#x2715;</button>
<button class="lbnav" id="lbprev" aria-label="Previous chart">&#x2039;</button><img id="lbimg" alt=""><button class="lbnav" id="lbnext" aria-label="Next chart">&#x203A;</button>
<div id="lbcap"></div></div>
<script>{js}</script></body></html>""")
    from enrich import OFFICE_CONTAINER, jump_dir
    d = jump_dir(path); d.mkdir(parents=True, exist_ok=True); absolute = OFFICE_CONTAINER in d.parents
    for old in d.glob("*.html"): old.unlink()
    for t, _ in made:
        to = (path.resolve().as_uri() if absolute else f"../../{path.name}".replace(" ", "%20")) + f"#{anchor(t)}"
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
    links = tv_links(wbp)
    cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    for t, (p1, p2) in newest_first(made):
        d = t["Entry time"]; res = res_of(t)[1]
        L += [f"### {d:%a} {d.day} {d:%b} {d:%H:%M} · {t['Symbol']} · {t['Direction']} · {res}", "",
              f"Entry {t['Entry']:,} · stop {t['Stop']:,} · TP {t['TP planned']:,} · {t['Result R']:+.1f}R"
              + (f" · MAE {t['MAE pts']:.1f}" if t.get("MAE pts") is not None else "") + (f" · MFE {t['MFE pts']:.1f}" if t.get("MFE pts") is not None else ""), "",
              "| " + " | ".join(FACTS) + " |", "|" + "---|" * len(FACTS),
              "| " + " | ".join(f"[{v}]({u})" if u else cell(RESULT_MARK.get(v, v)) for _, v, u in facts(t, links)[0]) + " |", "",
              *[f"**{n}:** {cell(v)}  " for n, v in facts(t, links)[1]], "",
              link(p1, note.parent, style), "", link(p2, note.parent, style), ""]
    note.parent.mkdir(parents=True, exist_ok=True); note.write_text("\n".join(L))


if __name__ == "__main__":
    main()
