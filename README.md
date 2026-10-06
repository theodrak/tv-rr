# tv-rr — TradingView trade log and analysis for Claude Code

Two skills for traders who mark trades on TradingView with the **Long Position / Short Position** tools:

- **tv-rr-trades** copies the tools from the clipboard into an Excel trade log: entry, stop, TP, times, outcome.
  - It re-checks every outcome against real price data, 1-minute bars where you have them.
  - It flags the uncertain ones for you to confirm.
- **tv-rr-analysis** adds what-if columns and a Breakdown sheet:
  - what-if columns: other stops and targets in R, break-even rules, MAE / MFE, ATR at entry, VWAP position;
  - Breakdown sheet: win rate, points and R per variant, direction and symbol.

  It also draws a chart gallery of every trade, at entry and after.

Works for any instrument TradingView can export, on macOS, Windows and Linux.

## Install

In Claude Code:

```
/plugin marketplace add theodrak/tv-rr
/plugin install tv-rr@tv-rr
```

**Requirements:** [uv](https://docs.astral.sh/uv/), a small tool that downloads Python and the libraries the skills
need the first time they run. No separate Python install is needed. If you don't have it, Claude offers to install it,
or you can install it yourself:

```
curl -LsSf https://astral.sh/uv/install.sh | sh                                   # macOS / Linux
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

If you already have Python 3.9+, that works too: `pip install openpyxl matplotlib`.

## Set up

Ask Claude to "set up my TradingView trade log". It will ask you three things:
- where the workbook should live;
- which timezone to show times in;
- where you save TradingView price exports.

Settings are kept in `~/.tv-rr/config.json`, outside the plugin.

## Settings

Claude asks for these on first use. Change them any time by asking Claude ("show times in London time", "my exports are now in ~/Trading/Exports"), or by running the settings script yourself:

```
python3 skills/tv-rr-trades/scripts/config.py show
python3 skills/tv-rr-trades/scripts/config.py set timezone Europe/London
python3 skills/tv-rr-trades/scripts/config.py set exports_dirs '["~/Downloads/TradingView exports", "~/Trading/Exports"]'
python3 skills/tv-rr-trades/scripts/config.py set gallery.format '["html","pdf"]'
```

| Setting | What it does | Default |
|---|---|---|
| `workbook` | The Excel trade log | none; asked on first use |
| `timezone` | Timezone for Entry, Fill, Exit and Checked times in the sheet, and for chart axes. Any IANA name: `Europe/London`, `America/New_York`, `Australia/Sydney` | the computer's timezone |
| `exports_dirs` | Folders searched (with subfolders) for TradingView CSV exports | none |
| `gallery.elements` | What the charts draw; `config.py elements` lists the choices | session bar, VWAP, kernel line, SMA 50–1000 |
| `gallery.images_dir` | Where chart images (PNG) are saved | a `Charts` folder beside the workbook |
| `gallery.notes_dir` | Where the gallery page (Markdown) is saved | beside the workbook |
| `gallery.format` | Gallery outputs: `html` (any browser, and adds an "Open chart" link per trade to the workbook), `pdf`, `markdown` | `["html"]` |
| `gallery.timeframe` | Bar size, in minutes, every chart uses (e.g. `5`) | the timeframe each trade was drawn on |
| `gallery.link_style` | For the Markdown page: `obsidian` embeds images as `![[file.png]]`; `markdown` as `![](Charts/file.png)` for GitHub, VS Code or any Markdown viewer | `obsidian` |
| `default_session_start` | When a trading day starts, for daily bars, ATR and VWAP | `17:00 America/New_York` |
| `symbols.<SYMBOL>.tick` / `.session_start` | Per-instrument tick size and session start | learned / the default |

**Chart links and Excel for Mac.** Mac Excel is sandboxed: it asks permission for every file a link opens, can't be
given a folder, and strips `#anchors` from links. So on a Mac the gallery writes a tiny jump page per trade into Office's
own folder (`~/Library/Group Containers/UBF8T346G9.Office/tv-rr/`), which Excel opens without asking, and each one sends
the browser to that trade's anchor in the gallery. These links use absolute paths: if you move the gallery folder, run
the gallery again to refresh them. Windows Excel may show a "hyperlinks can be harmful" warning; click Yes.

**Changing the timezone** moves every time in the sheet to the new zone on the next run, including times copied from TradingView; the UTC entry time is kept as the reference.
The settings file is `~/.tv-rr/config.json` (set `TV_RR_HOME` to keep it elsewhere).

## Price data: exporting from TradingView

Outcomes, MAE/MFE, ATR, VWAP and charts need price bars for each instrument you trade. They come from TradingView's
**Export chart data**, which is available on TradingView's paid plans.

### 1. Set up the chart

> [!IMPORTANT]
> **Set the chart up before you export.** The export contains only what is on the chart when you export it: the
> prices, plus a column for each indicator on the chart. An indicator you add later is not in the files you already
> saved.

Open the instrument at the bar size you want to export, then add these from **Indicators**:

| Add | Why | Needed? |
|---|---|---|
| **Volume** | VWAP is calculated from it | **Yes**, for VWAP |
| **VWAP** (built in, anchor: Session) | Used exactly as the chart shows it | Recommended |
| **SMA 50, 100, 200, 500, 1000** | Match what you see on your own chart | Optional: the skill calculates them from prices |
| **EMA** (e.g. 9, 21, 50) | Match what you see on your own chart | Optional: the skill calculates any EMA length from prices |
| **ATR** (length 14) | Match what you see on your own chart | Optional: the skill calculates ATR on 5m, 15m, 4h and daily itself |

Without VWAP on the chart, the skill calculates it from Volume, matching TradingView.

**Indicators your strategy uses.** If your entries depend on an indicator, add it to the chart before exporting so its
values are in the file. Some examples:
- **RSI** (e.g. length 14), for overbought / oversold or divergence entries;
- **MACD**, for momentum or crossover entries;
- **Stochastic**, for pullback timing;
- **Bollinger Bands** or **Keltner Channels**, for range or squeeze setups;
- **Supertrend** or **Ichimoku**, for trend filters;
- **Anchored VWAP** or **Volume Profile** levels, for confluence.

**Every other indicator column is kept in the price store.** Each indicator on the chart is stored under its plot's
name, candle by candle, so Claude can answer questions about it later, e.g. "how did my trades do when RSI was above
70?". There's no limit on the number of indicators, and any indicator that plots a number works, including your own
Pine scripts.

The trade log stays as it is by default. If you'd like each indicator as a **TV <name>** column there too (its value on
the last candle that closed before the entry), turn it on with `config.py set indicator_columns true`.

- **Moving averages are named for you.** TradingView exports a built-in moving average under a plain name ("EMA",
  "MA") and doesn't let you rename it, so two EMAs export as "EMA" and "EMA (2)". The skill works out each one's length
  from the prices, so they're known as **EMA 9** and **EMA 20**.
- **Other repeated or unclear names** get numbered ("Plot", "Plot (2)"). Give them your own names with
  `config.py set indicator_names '{"Plot": "RSI 14", "Plot (2)": "RSI signal"}'`.
- **Signals that only fire on some candles** (buy/sell arrows) are blank on the candles where they didn't fire.
- **Bar sizes:** values come from your 5-minute and larger exports, taken on the trade's own bar size when you exported
  it. 1-minute exports are big, so their indicator columns are skipped unless you set
  `config.py set indicators_1m true`.
- **Where exports overlap,** the newest file's values win, indicator by indicator. An indicator you've since taken
  off the chart keeps its older values.

### 2. Load the history you want

The export contains only the bars loaded on the chart. Scroll left (or zoom out) until the chart reaches as far back as you
need. The bars are already loaded from TradingView's servers, so this takes only a moment.

### 3. Export

1. Click the arrow next to the chart's layout name at the top right, then **Export chart data…**.
2. Choose **ISO time** (UNIX time works too), then **Export**.
3. Save the file into your exports folder, **keeping the name TradingView gives it**, e.g. `OANDA_EURUSD, 1.csv` or
   `OANDA_EURUSD, 1 (1).csv`. The name tells the skill the symbol; the bar size is read from the data.

### Which bar sizes

- **1-minute** gives the most accurate outcome checks. Export it for the period your trades cover. The skill builds
  5m, 15m, 30m, 60m and 4-hour bars from it wherever you have no export of those. The 4-hour bars start at the
  instrument's session start (its rollover), as TradingView draws them. The first and last bar of a trading day can
  be shorter than 4 hours: a market that opens at 02:15 or closes at 22:00 gives a short bar there.
- **5-minute** reaches further back, for longer history, ATR and the charts.
- **Repeat now and then.** Overlapping exports are merged and the newest file wins, so just add new ones.
- **Deleting old exports is safe:** bars are kept once read. Run `prices.py ingest --rebuild` to start again from the files present.

### Your data

Everything is kept in one SQLite database, `~/.tv-rr/data/prices.db`:
- the candles for every instrument and bar size;
- every indicator column from your exports;
- the list of export files already read.

You can open it with any SQLite tool, such as [DB Browser for SQLite](https://sqlitebrowser.org). The `prices` and
`indicator_values` views show symbol names and readable times. Loading an export reads only that file, and a top-up
takes milliseconds.

The database runs in WAL mode, so it can be read while it's being updated. It must be on a local disk, not in iCloud,
Google Drive, Dropbox or OneDrive (the skill refuses a synced folder). An older JSON store is moved in automatically the
first time.

- `prices.py status` lists what is held for each symbol and bar size.
- `prices.py export OANDA:EURUSD 1m merged.csv` writes one merged CSV of the stored bars, for opening in Excel.
- If the TradingView MCP server is connected, Claude can also fill recent gaps from it (see below).

### Optional: the TradingView MCP server

TradingView's MCP server lets Claude fetch recent price bars directly, so a trade taken today can be checked without
exporting first.

1. **Connect it:** in claude.ai go to **Settings → Connectors**, add **TradingView** and sign in. In Claude Code, `/mcp`
   shows whether it's connected.
2. **Use it:** when a trade shows **Open** or **No price data yet**, ask Claude to "top up the prices from TradingView".
   Claude fetches the missing bars, adds them to the store and re-checks the trades.

What to expect:
- **Recent data only:** about a few days of 1-minute bars, so it's for filling gaps, not building history. Exports are
  still the main source.
- **Prices and volume only:** indicator values still come from your exports.
- **Exports win:** where an export and the MCP overlap, the export's bars are kept.
- **Without it, nothing breaks:** everything works from exports alone.

## Use

1. Select your Long/Short Position tools on a TradingView chart and copy them (Cmd-C / Ctrl-C).
2. Tell Claude "log the trades I copied".

Ask for "the breakdown", "which target would have worked better", or "a gallery of my trades".

More things you can ask, with drawings copied from TradingView:
- **"Add these filtered trades"** or **"Add these missed trades"**: logs them with **Decision** set, adding new ones and
  updating ones already in the sheet. "Update these trades to filtered" works the same way. Needs the journal
  columns (below).
- **"Mark these as taken"**: sets them back to Taken. A trade can be Taken even with filter reasons, when something
  else outweighed them; say why in Filter notes.
- **"Remove these trades"**: Claude lists what would be removed and asks before deleting.

Each trade also has a **TV chart** column for your own TradingView chart link. Paste a URL, or a link with your own
text. It's kept whenever the sheet is rebuilt.

### Optional: a trading journal in the log

Ask Claude to "add journal columns" to a workbook. Each trade then gets these columns:
- **Decision:** **Taken** (the default for every trade added), **Filtered** if a rule said no, or **Missed**.
- **Filter 1–3:** up to three filter reasons.
- **Confluence 1–3:** up to three confluences.
- **Grade:** a grade with up to three + / − reasons.
- **Notes:** free text for the filters, the grade and the trade in general.

You choose your own filter reasons, grade reasons and confluences on the workbook's **Lists** sheet. Another workbook
can copy them from one you already use.

The **Auto confluence** sheet sets which levels are filled in for you and how close to the entry counts, in points or
pips:
- VWAP
- any SMA or EMA
- the previous day's high and low

The **Breakdown** then compares all trades with the unfiltered ones (taken and missed), so you can see what your filters
keep you out of.

## Licence

MIT — see [LICENSE](LICENSE).
