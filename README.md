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
python3 skills/tv-rr-trades/scripts/config.py set gallery.link_style markdown
```

| Setting | What it does | Default |
|---|---|---|
| `workbook` | The Excel trade log | none; asked on first use |
| `timezone` | Timezone for Entry, Fill, Exit and Checked times in the sheet, and for chart axes. Any IANA name: `Europe/London`, `America/New_York`, `Australia/Sydney` | the computer's timezone |
| `exports_dirs` | Folders searched (with subfolders) for TradingView CSV exports | none |
| `gallery.elements` | What the charts draw; `config.py elements` lists the choices | VWAP, kernel line, SMA 50–1000 |
| `gallery.images_dir` | Where chart images (PNG) are saved | a `Charts` folder beside the workbook |
| `gallery.notes_dir` | Where the gallery page (Markdown) is saved | beside the workbook |
| `gallery.link_style` | `obsidian` embeds images as `![[file.png]]`; `markdown` as `![](Charts/file.png)` for GitHub, VS Code or any Markdown viewer | `obsidian` |
| `default_session_start` | When a trading day starts, for daily bars, ATR and VWAP | `17:00 America/New_York` |
| `symbols.<SYMBOL>.tick` / `.session_start` | Per-instrument tick size and session start | learned / the default |

**Changing the timezone** moves every time in the sheet to the new zone on the next run, including times copied from TradingView; the UTC entry time is kept as the reference.
The settings file is `~/.tv-rr/config.json` (set `TV_RR_HOME` to keep it elsewhere).

## Price data

Outcomes, MAE/MFE, ATR, VWAP and charts need bars for each instrument you trade.

1. In TradingView, open the chart, add **Volume** (needed for VWAP), and choose **Export chart data…**.
2. Save the CSV in your exports folder, keeping the file name TradingView gives it (e.g. `OANDA_EURUSD, 1.csv`). The name tells the skill the symbol.
3. Export **1-minute** bars for the most accurate checks, and 5-minute bars for longer history.

Overlapping exports are merged, so just keep adding new ones. If the TradingView MCP server is connected, Claude can also fill small gaps from it.

## Use

1. Select your Long/Short Position tools on a TradingView chart and copy them (Cmd-C / Ctrl-C).
2. Tell Claude "log the trades I copied".

Ask for "the breakdown", "which target would have worked better", or "a gallery of my trades".

## Licence

MIT — see [LICENSE](LICENSE).
