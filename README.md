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
