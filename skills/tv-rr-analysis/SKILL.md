---
name: tv-rr-analysis
description: What-if analysis and chart galleries for the TradingView trade log kept by the tv-rr-trades skill, for any instrument — alternative stops and targets in R, break-even rules, MAE and MFE, ATR at entry, VWAP position, a Breakdown sheet of win/loss and R per variant, direction and symbol, and a gallery of every trade charted at entry and after. Use when the user asks to analyse or break down their logged trades, which stop, target or management rule would have worked better, or to chart their trades.
---

# Trade log: what-if analysis and galleries

Scripts are in this skill's `scripts/` folder. Check for uv or Python first, exactly as the `tv-rr-trades` skill
describes ("Before anything else"), and offer to install uv if neither is there. They use the `tv-rr-trades` skill's settings (`~/.tv-rr/config.json`) and price
store, so set that skill up first.

## What-if columns and the Breakdown sheet

```
uv run -q --with openpyxl python scripts/enrich.py [--file WORKBOOK]
```

`tv-rr-trades` runs this after every save. Run it by hand after the user edits the workbook, for example after setting a
**Confirmed outcome**. **The user must save and close the workbook first.**

| Column | What it tests |
|---|---|
| **1/2 stop** | Same entry and TP, stop at half the distance → Win / Loss |
| **TP 0.5R … TP 2.5R** | Same entry and stop, TP at that multiple of the stop distance |
| **MAE pts / MFE pts** | Worst move against and best move for the entry, from the fill to the exit |
| **BE at 55%** | Planned trade, stop moved to the entry once price is 55% of the way to the TP. **BE** = came back to the entry first |
| **1.5R BE at 55% / 1.5R BE at 1R** | The same with a 1.5R target, the stop moving at 55% or at +1R |
| **ATR 5m / 15m / 4h / D** | ATR(14) of the last closed bar of each timeframe at entry |
| **ATR 1:1 … 1.5:1.5** | Stop and TP sized from the 5m ATR (stop multiple : TP multiple) |
| **VWAP, VWAP dist, VWAP side, VWAP in the way, VWAP behind** | Session VWAP at entry: its value, the entry's distance (+ = beyond it your way), the side price closed on, and whether it sits between entry and TP or between stop and entry |
| **VWAP 30m change** | With / Against: VWAP higher or lower than 30 minutes earlier. Not a slope: on an open-type setup it often reaches back before the open's spike. (Called "VWAP slope" before.) |
| **VWAP direction** | The line at entry over the last 10 minutes: **Flat** (moved < 2 pts), **Upwards / Downwards**, or **Upwards turning / Downwards turning** when it still moves that way at under half the pace of the 10 minutes before (flattening out) |
| **TV <name>** | **Only with `indicator_columns` on** (off by default; the values are always in the price store, and Claude can read them with `prices.indicators_at`). Every other indicator column on the exported chart (e.g. TV RSI). A plain "EMA" / "MA" plot is named by the length that matches the prices exactly ("EMA (2)" → TV EMA 20); config `indicator_names` renames any plot. Values are read from the last bar closed before the entry, on the trade's bar size when it was exported. Grouped at the end of the sheet; blank where the export had no value (signals that didn't fire) |
| **VWAP immediate slope** | That 10-minute slope against the trade: **With / Against / Flat** |

- **Blank** means not filled, no price data, or a value that can't be known. For example, VWAP needs a Volume or VWAP column in the exports.
- **Open** means neither level has been reached yet.
- **MAE and MFE are blank** when one candle reached both levels.

**Breakdown sheet:** each variant for all trades, longs, shorts and (when the log mixes instruments) each symbol. With journal columns (tv-rr-trades `journal.py`), the table appears twice: **All trades**, then **Unfiltered trades** (Decision is not Filtered). For each:
- trades, wins, losses, open, break-even, win %;
- net points and net R;
- average MAE and MFE for winners and losers.

**Compare in R when instruments are mixed**, because points don't add across symbols.

**Rules:**
- Everything uses only what was known at the entry. ATR and VWAP come from the last closed bar, and fills and exits follow the same candle-path rules as `tv-rr-trades`.
- Higher timeframes start at the symbol's session start (config). VWAP and the kernel line come from the export's own columns when present, otherwise they are calculated. The calculation matches TradingView's.
- **Samples are small.** When reporting, say how many trades each figure rests on.

## Trade gallery

```
uv run -q --with openpyxl --with matplotlib python scripts/gallery.py [--file WORKBOOK] [--only YYYY-MM-DD …] [--symbol SYMBOL] [--format html,pdf,markdown]
```

Two charts per closed trade, both with the risk/reward tool drawn on:
- **at entry:** only what was visible at the fill. With 1m data, the entry candle is rebuilt up to the fill minute;
- **follow-through:** to the exit, plus a little after.

It also writes the gallery in the formats set by `gallery.format` (or `--format`):
- **`html`:** one page that opens in any browser. A sidebar lists every trade (date, time, win or loss, direction, plus the symbol in a mixed log), with All / Wins / Losses filters. Clicking a trade scrolls to it, the sidebar highlights the trade in view as you scroll, and charts open full size when clicked. Recommend it to anyone who doesn't use Obsidian.
- **`pdf`:** a summary page, then one A4 page per trade. Use it for sharing and printing.
- **`markdown`:** a page for Obsidian, VS Code or GitHub.

**Chart links in the workbook.** With `html`, every trade gets a **Chart** column in the workbook: "Open chart" jumps straight to that trade in the gallery.
- **Each trade's section is anchored** on its symbol and TradingView drawing id. A one-line jump page per trade redirects to the anchor, because Excel strips `#anchors` (and `?queries`) from links to local files.
- **On a Mac the jump pages live in Office's own folder** (`~/Library/Group Containers/UBF8T346G9.Office/tv-rr/<id>/`). Mac Excel is sandboxed: it asks permission for every other file a link opens and can't be given a folder, but it opens files there without asking. Those links are absolute, so if the gallery folder moves, run the gallery again.
- **Elsewhere the jump pages sit in `<gallery>_files/trades/`** and are linked relative to the workbook. On Windows, Excel may warn that hyperlinks can be harmful; clicking **Yes** opens the trade.
- **The workbook must be closed** for the links to be written. `enrich.py` refreshes them after every update.
- **If a user says the links ask for permission,** check that the gallery was generated on this Mac with the current version, then rerun `gallery.py`.

**Before the first gallery, ask the user which elements to draw** and save the answer with
`config.py set gallery.elements '["sessions","vwap","kernel","sma50","sma100","sma200","sma500","sma1000"]'` (that list is the default).
`config.py elements` lists every choice:

| Element | What it draws |
|---|---|
| `vwap` | Session VWAP |
| `kernel` | The Lorentzian Classification kernel regression line (red falling, teal rising) |
| `sma50` … `sma1000` | Simple moving averages 50, 100, 200, 500, 1000 |
| `ema9` | EMA 9 |
| `prior_day` / `prior_week` | Prior session / prior week high and low |
| `prior_value` | Prior session value area and POC (needs volume) |
| `sessions` | The session bar along the top: Asia, EU pre-market / open / afternoon, US pre-market / open / afternoon, each in its market's local time |
| `round_numbers` | Round-number price lines |

Also ask where images and the page should go:
- `gallery.images_dir`, by default a `Charts` folder beside the workbook;
- `gallery.notes_dir`, by default beside the workbook;
- `gallery.link_style`, for the Markdown page only: `obsidian` (`![[…]]`, the default) or `markdown` (`![](…)`);
- `gallery.format`: any of `html`, `pdf`, `markdown`. The default is `["html"]`; Obsidian users usually want `["markdown","html"]`;
- `gallery.timeframe`: chart every trade at one bar size, e.g. `5`. By default each trade is charted at the timeframe it was drawn on.
