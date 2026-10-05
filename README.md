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
/plugin marketplace add <github-user>/tv-rr
/plugin install tv-rr@tv-rr
```

Requires Python 3.9+ and either [uv](https://docs.astral.sh/uv/) or `pip install openpyxl matplotlib`.

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

Open the instrument at the bar size you want to export, then add these from **Indicators**:

| Add | Why | Needed? |
|---|---|---|
| **Volume** | VWAP is calculated from it | **Yes**, for VWAP |
| **VWAP** (built in, anchor: Session) | Used exactly as the chart shows it | Recommended |
| **Machine Learning: Lorentzian Classification** (by jdehorty), default settings | Its *Kernel Regression Estimate* line is drawn on the gallery charts | Recommended |
| **SMA 50, 100, 200, 500, 1000** | Match what you see on your own chart | Optional: the skill calculates them from prices |
| **ATR** (length 14) | Match what you see on your own chart | Optional: the skill calculates ATR on 5m, 15m, 4h and daily itself |

Without VWAP or the Lorentzian script on the chart, the skill calculates both, matching TradingView. VWAP still needs **Volume**.

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
  5m, 15m, 30m and 60m bars from it wherever you have no export of those.
- **5-minute** reaches further back, for longer history, ATR and the charts.
- **Repeat now and then.** Overlapping exports are merged and the newest file wins, so just add new ones.
- **Deleting old exports is safe:** bars are kept once read. Run `prices.py ingest --rebuild` to start again from the files present.

### Your data

- `prices.py status` lists what is held for each symbol and bar size.
- `prices.py export OANDA:EURUSD 1m merged.csv` writes one merged CSV of the stored bars, for opening in Excel.
- If the TradingView MCP server is connected, Claude can also fill small gaps from it.

## Use

1. Select your Long/Short Position tools on a TradingView chart and copy them (Cmd-C / Ctrl-C).
2. Tell Claude "log the trades I copied".

Ask for "the breakdown", "which target would have worked better", or "a gallery of my trades".

## Licence

MIT — see [LICENSE](LICENSE).
