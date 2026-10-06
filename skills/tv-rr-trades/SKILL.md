---
name: tv-rr-trades
description: Logs TradingView Long/Short Position (risk/reward) tools copied to the clipboard into an Excel trade log — entry, stop, TP, entry and exit times, outcome — for any instrument, re-checking each outcome on stored price data and flagging uncertain ones for the user to confirm. Use when the user has copied long/short position tools from TradingView and wants them logged, updated or checked, or wants to set up or update the price data the checks use.
---

# TradingView risk/reward tools → Excel trade log

Scripts are in this skill's `scripts/` folder. Run them with `uv run -q --with openpyxl python scripts/<name>.py`
(or plain `python3` once `openpyxl` is installed).

## Before anything else: check uv or Python

Run `uv --version`. If it works, use `uv run …` for every script: uv fetches its own Python and the libraries (openpyxl,
matplotlib) the first time, so nothing else is needed.

If it fails, try `python3 --version` (on Windows, `py --version`). With Python 3.9+ present, run the scripts with it
after `python3 -m pip install --user openpyxl matplotlib`.

If neither works, **tell the user nothing can run yet and offer to install uv**, the one small tool the skills need. It
installs Python for them. Ask first and install only on a yes, because it adds software to their computer:
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

After installing, open a new terminal (or use the full path the installer prints, e.g. `~/.local/bin/uv`) and run
`uv --version` to confirm. Don't send macOS users to `python3` first: on a Mac without it, that only offers Apple's
large Command Line Tools download. On Windows, typing `python` may open the Microsoft Store instead of running anything.

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
- `--decision Filtered` / `--decision Missed` covers "add these filtered trades", "add these missed trades" and "update these trades to filtered". It sets **Decision** on every drawing on the clipboard: drawings not in the sheet are added, ones already there are updated. Without `--decision`, new trades are **Taken**; `--decision Taken` sets it back ("mark these as taken"). The workbook needs journal columns.
- `--remove` covers "remove these trades". It deletes the clipboard's drawings from the sheet. **Run it with `--dry-run` first, show the user the list, and remove only after they confirm.** Drawings not in the sheet are listed as such.
- `--recheck` re-assesses every trade already in the workbook (no clipboard), for example after new price data arrives;
- `--dry-run` shows what would be logged and writes nothing;
- `--file clip.html` reads a saved clip instead of the clipboard;
- `--tick 0.1` sets the tick size for this run;
- `--out PATH` writes to a different workbook.

The clipboard is read on macOS (`osascript`), Windows (PowerShell) and Linux (`wl-paste` or `xclip`). TradingView puts drawings in the clipboard's HTML. If nothing is found, ask the user to select the Long/Short Position tools in TradingView, press Cmd-C or Ctrl-C, and try again.

When the `tv-rr-analysis` skill is installed, its what-if columns and Breakdown sheet are refreshed automatically after every save.

## TV chart column

**TV chart** (column 5, next to the gallery's **Chart** link) holds the user's own TradingView chart link for each trade.
They can paste a URL, or a link shown as text. It is kept through every rebuild, even when the drawing is re-copied with
new levels, and shown as a clickable "TV chart" link. The first six columns, Symbol to Outcome, stay frozen.

## Journal columns (optional, per workbook)

```
uv run -q --with openpyxl python scripts/journal.py init WORKBOOK [--from OTHER_WORKBOOK] [--distance 10 --unit pts|pips]
uv run -q --with openpyxl python scripts/extract.py --recheck --out WORKBOOK
```

This adds two sheets and a group of columns after **Last copied**. Only workbooks with a Lists sheet get them.

**Before running `init`, ask the user** what they filter on and which levels they count as confluence, since every setup
differs. Use `--from` to copy the lists from a workbook they already use for the same setup (for example a Replay file
next to a Backtest file). Without `--from`, the lists start with a few generic examples to replace.

- **Lists sheet:** the dropdown choices. Column A is filter reasons, B is grade reasons (each starts with `+` or `-`), C is confluences. The user edits them in Excel. Column E is a guide the script rewrites.
- **Auto confluence sheet:** controls which levels are filled in automatically.
  - **Distance** and **Unit**: `pts` means price units; `pips` means 10 ticks, as on 5-decimal FX quotes. Ask the user for both, in their own terms. Never use ATR, because a moving yardstick can't be read back.
  - **Level rows:** VWAP, `SMA n`, `EMA n`, Previous day high, Previous day low, each with **On** (Yes/No) and the **Name** to write, which should match their Confluence list.
  - **A blank Distance** switches auto-fill off.
- **Columns:**
  - **Decision:** **Taken** by default for every trade added, or Filtered or Missed. Taken with filter reasons means the user took it because something outweighed them, noted in Filter notes.
  - **Filter 1–3**, **Confluence 1–3**, **Grade reason 1–3:** dropdowns.
  - **Filter notes**, **Grade notes**, **General notes:** free text.
  - **Grade:** the user's call. **Rule grade:** an Excel formula.
  - **Auto confluence:** what the script found, with distances. A level the user deleted is never re-added.
- **Safeguard:** Excel turns Decision orange when it doesn't add up: Filtered with no filter reason, Missed with one, or Taken with filter reasons but no Filter notes saying why. Nothing is changed automatically. Rule grade never gives F; that's the user's call. In the Breakdown, Taken and Missed count as unfiltered.
- **Breakdown:** gets two sections: **All trades**, and **Unfiltered trades** (Taken and Missed, i.e. Decision is not Filtered).

Every rebuild keeps both sheets and all journal values, including when the drawing is re-copied with new levels. A
journal made before the Auto confluence sheet existed gets one that keeps its old behaviour: VWAP and the 50/100/200 SMA
within 10 pts.

## Price data

Outcomes are checked on stored bars: 1-minute wherever they cover a trade, otherwise the finest bars held.

**Helping the user export from TradingView** (the README has the full guide):
1. **Set up the chart.** Open the instrument at the bar size to export, then add:
   - **Volume**, needed for VWAP;
   - **VWAP** with anchor Session;
   - **Machine Learning: Lorentzian Classification** (jdehorty, default settings), for the kernel line.

   SMAs and ATR are optional: the skill calculates them itself.
2. **Load the history.** Scroll left until the chart reaches back far enough; the export contains only the loaded bars.
3. **Export.** Use the arrow next to the layout name at the top right, then **Export chart data…**, **ISO time**, **Export**. Save into the exports folder, **keeping TradingView's file name** (`OANDA_EURUSD, 1.csv`): it names the symbol.
4. **Which bar sizes.** 1-minute for the trades' period gives the most accurate checks. 5-minute reaches further back. Paid TradingView plans only.

**Ingesting:**
- **`scripts/prices.py ingest`** reads every export folder and merges overlapping files: the newest wins, except its last, possibly unfinished, bar. `extract.py` runs it automatically, and unchanged files cost nothing.
  - **Where it's stored:** one SQLite database, `<TV_RR_HOME>/data/prices.db`, in WAL mode. It has tables `bars`, `indicators`, `series`, `symbols` and `exports`, plus the readable views `prices` and `indicator_values`. The `prices.py` docstring explains the source ranks.
    - Only new or changed export files are read. Their rows are upserted, and exports outrank MCP bars, which outrank bars built from 1m.
    - It must be on a local disk: it refuses synced folders. An old JSON store is moved in automatically the first time.
    - For one-off questions, query it directly with `sqlite3`.
  - **Keeps bars once read:** deleting old exports is safe, and `ingest --rebuild` starts again from the files present (MCP top-ups are kept).
  - **Keeps every other indicator column** (RSI, MAs, levels…) under its plot name, in the database's `indicators` table. This applies to exports of 5 minutes and up; set `indicators_1m true` to include 1-minute exports. `prices.py status` lists the columns held. Each file is read once more after an upgrade to pick these up. They stay in the store; the trade log only gets **TV <name>** columns with `config.py set indicator_columns true`. To answer a question about an indicator ("my win rate when RSI > 70"), read it per trade with `prices.indicators_at(symbol, entry_utc_seconds, 5)`.
- **Builds 5m, 15m, 30m, 60m and 4h bars from 1m** wherever no export of that size exists; an exported bar always wins.
  - **5m to 60m** are on the clock.
  - **4h** starts at the symbol's **session start** (the rollover), as TradingView builds it. The day's first and last 4h bar only cover the trading inside them; for example, DE30 opening at 02:15 Berlin gives a 45-minute first bar. A 4h bar never crosses into the next trading day.
- **`prices.py status`** lists what is held.
- **`prices.py export SYMBOL 5m OUT.csv [--no-built]`** writes the bars with every indicator column. **`prices.py snapshot OUT.db`** writes a clean single-file copy of the database (VACUUM INTO) for sharing; never hand over the live `prices.db`, because in WAL mode its latest writes may sit in `-wal`.
- **Other skills share this store.** de30-open-review reads its 5m bars and indicator columns from it (`prices.load(sym, 5, built=False)`, `indicator_rows`) and loads exports and MCP files into it.
- **`prices.py export SYMBOL 1m out.csv`** writes one merged CSV.
- **TradingView MCP top-up:** see the next section.

## TradingView MCP server (optional)

The claude.ai **TradingView** connector can fill recent gaps without an export. Its tools are named
`mcp-tv-get-ohlcv`, `mcp-tv-search-symbols` and so on, with a prefix that depends on how it is connected.

**Check it's there.** Look for a `mcp-tv-get-ohlcv` tool, using ToolSearch with "tradingview ohlcv" if tools are deferred.
- **Not there:** tell the user to connect or sign in to it under claude.ai **Settings → Connectors**, or with `/mcp` in a terminal session, then carry on with exports.
- **Never stop logging because the MCP is missing:** exports cover everything it does.

**When to use it:**
- a trade says **Open** or **No price data yet**, because the exports end before its exit;
- the user asks for "today's" data before exporting.

**How:**
1. **Find the symbol.** Use the trade's symbol as written (e.g. `OANDA:DE30EUR`). If the tool rejects it, look it up with `mcp-tv-search-symbols`.
2. **Fetch bars** with `mcp-tv-get-ohlcv`:
   - **Arguments:** `symbol`, `interval` (`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1D`) and `count` (up to 5000). 5000 1m bars cover about 3½ trading days.
   - **Size of the gap:** start from where `prices.py status` says the 1m data ends and ask for a few hundred bars.
   - **What comes back:** `{"bars": [{t, o, h, l, c, v}]}`, with `t` in UTC seconds. Data is delayed 15+ minutes and the last bar is still forming.
3. **Save the result** as it came back to a `.json` file in the scratchpad.
4. **Add it:** `prices.py add SYMBOL 1m FILE`. It leaves out any bar that hasn't closed yet, and reads the usual shapes (`{"bars": […]}`, `{"data": […]}`, a plain list, `[time, open, high, low, close, volume]` rows, or UDF-style columns), with times in seconds, milliseconds or ISO text. 1m bars rebuild the 5m to 4h bars automatically.
5. **Re-check:** `extract.py --recheck` (with `--out` for a workbook that isn't the default).

**Limits:**
- The connector's 4h bars match the ones built from 1m exactly; checked on 38 DE30 bars on 6 Oct 2026, including the short first and last bar of the day.
- MCP bars are prices and volume only, with no indicator columns, so the TV columns still come from exports.
- Where an export and MCP bars overlap, the export wins.
- MCP bars are stored with source "mcp", rank below exports, and survive `ingest --rebuild`.

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
