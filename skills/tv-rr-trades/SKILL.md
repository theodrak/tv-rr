---
name: tv-rr-trades
description: Logs TradingView Long/Short Position (risk/reward) tools copied to the clipboard into an Excel trade log — entry, stop, TP, entry and exit times, outcome — for any instrument, re-checking each outcome on stored price data and flagging uncertain ones for the user to confirm. Use when the user has copied long/short position tools from TradingView and wants them logged, updated or checked, or wants to set up or update the price data the checks use.
---

# TradingView risk/reward tools → Excel trade log

Scripts are in this skill's `scripts/` folder. Run them with `uv run -q --with openpyxl python scripts/<name>.py`
(or plain `python3` once `openpyxl` is installed).

## First run: set up

Settings live in `~/.tv-rr/config.json` (or `$TV_RR_HOME`), outside the plugin, so updates never lose them.
`config.py show` prints them. If no workbook is set, **ask the user** before running anything else:

1. **Where the trade log should live:** `config.py set workbook "~/Documents/Trading/TradingView trades.xlsx"`.
2. **Which timezone to show times in** (default: the computer's): `config.py set timezone Europe/London`.
3. **Where they save TradingView price exports** (needed to check outcomes, see below):
   `config.py set exports_dirs '["~/Downloads/TradingView exports"]'`.

Per-instrument settings, only when needed:
- **Tick size:** `config.py symbol OANDA:EURUSD tick 0.00001`. It is learned automatically from any drawing that has an exit point.
- **Session start:** `config.py symbol CME_MINI:ES1! session_start "18:00 America/New_York"`. It anchors daily bars and VWAP. The default is 17:00 New York, the FX and CFD rollover. Use 00:00 UTC for crypto, or the exchange's session start for futures and stocks.

## Logging trades

```
uv run -q --with openpyxl python scripts/extract.py
```

Options:
- `--recheck` re-assesses every trade already in the workbook (no clipboard), for example after new price data arrives;
- `--dry-run` shows what would be logged and writes nothing;
- `--file clip.html` reads a saved clip instead of the clipboard;
- `--tick 0.1` sets the tick size for this run;
- `--out PATH` writes to a different workbook.

The clipboard is read on macOS (`osascript`), Windows (PowerShell) and Linux (`wl-paste` or `xclip`). TradingView puts drawings in the clipboard's HTML. If nothing is found, ask the user to select the Long/Short Position tools in TradingView, press Cmd-C or Ctrl-C, and try again.

When the `tv-rr-analysis` skill is installed, its what-if columns and Breakdown sheet are refreshed automatically after every save.

## Price data

Outcomes are checked on stored bars: 1-minute wherever they cover a trade, otherwise the finest bars held.

- **From TradingView exports:** in TradingView, open the chart and choose "Export chart data…", then save the CSV into an export folder. `scripts/prices.py ingest` reads every folder, works out the symbol from the file name TradingView gives it (`OANDA_EURUSD, 5.csv`) and the bar size from the data, and merges overlapping files. `extract.py` runs it automatically, and unchanged files cost nothing. `prices.py status` lists what is held.
- **Columns worth exporting:** add **Volume** to the chart so VWAP can be computed. A **VWAP** or **Kernel Regression Estimate** column on the chart is used directly.
- **Top-up from the TradingView MCP server, if connected:** when a trade says **Open** or **No price data yet**, fetch bars with `mcp-tv-get-ohlcv`. Save the returned JSON to a file and run `prices.py add SYMBOL 5m FILE`, then `extract.py --recheck`. Keep top-ups small: a few hundred bars covering the gap. Exports are the main source, because the MCP holds only a few days of 1-minute history.

## Rules the script relies on (don't "simplify" them)

- **Exit point.** The exit is `points[3]`, where TradingView shows the TP or stop being hit. `points[1]` is only the box's right edge. A drawing with no 4th point never closed.
- **Stop and TP** come from `stopLevel` / `profitLevel`, which are tick counts. The tick is confirmed from the exit point, otherwise read from the config or `--tick`. **Never infer it from the entry's decimals**: an entry of 25172 does not mean a tick of 1.
- **Duplicates.** Rows are keyed on symbol + drawing id, so copying a drawing again, even after moving it, updates its row.
- **Every row is re-checked on every run:**
  - **1-minute bars first.** When they cover the trade, the outcome is re-derived from them whatever TradingView shows. The trade is flagged only if the call was decided inside one 1m candle, or if TradingView disagrees.
  - **Without 1m bars,** TradingView's exit is the record when it falls after the candle the order filled in. It is re-derived from the bars when it falls in the entry or fill candle (TradingView counts a level anywhere in that candle's range, even before the fill), when its close is at neither the TP nor the stop, or when it shows no exit.
  - **Candle path:** each candle is walked along its likely path, bullish O→L→H→C and bearish O→H→L→C. The fill is where the path crosses the entry; the exit is whichever of stop or TP it reaches next.
  - **An exit in the fill candle is not automatically a doubt.** If that candle reached only one level and the following candles reach the same level first, the result is the same either way.
- **Confirmation.** Uncertain results are flagged **CONFIRM** in the **Check** column, with the reason. The user picks the real result in **Confirmed outcome** (TP / Stop / Not filled / Open). Every run keeps that value and the script never overwrites it, unless the drawing is copied again with different levels.
- **Times** are shown in the configured timezone, in columns named without a zone (Entry time, Exit time…). Older workbooks with "Entry time (Sydney)" columns are migrated automatically. **Entry (UTC)** is the reference.

## After running, tell the user

- how many drawings were found, and how many were new or updated;
- the trades, one line each;
- any rows to confirm, and any WARNING lines (an unknown tick leaves stop and TP blank: ask for the tick);
- the workbook's path.
