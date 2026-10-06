"""Settings shared by the tv-rr skills, kept outside the plugin so updates never overwrite them.

usage: config.py show
       config.py set KEY VALUE      (dotted keys; VALUE is parsed as JSON when it can be, e.g. '["~/Exports"]')
       config.py symbol SYMBOL KEY VALUE

The file is ~/.tv-rr/config.json, or $TV_RR_HOME/config.json. Price data lives beside it in data/.
"""
import copy, datetime as dt, json, os, sys
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path(os.environ.get("TV_RR_HOME", Path.home() / ".tv-rr")).expanduser()
FILE = HOME / "config.json"
DATA = HOME / "data"

DEFAULT_ELEMENTS = ["sessions", "vwap", "kernel", "sma50", "sma100", "sma200", "sma500", "sma1000"]
ALL_ELEMENTS = {
    "vwap": "Session VWAP",
    "kernel": "Kernel regression line from the Lorentzian Classification indicator (red falling, teal rising)",
    "sma50": "SMA 50", "sma100": "SMA 100", "sma200": "SMA 200", "sma500": "SMA 500", "sma1000": "SMA 1000",
    "ema9": "EMA 9",
    "prior_day": "Prior session high and low",
    "prior_week": "Prior week high and low",
    "prior_value": "Prior session value area and POC (needs volume)",
    "sessions": "Session bar along the top: Asia, EU pre-market / open / afternoon, US pre-market / open / afternoon",
    "round_numbers": "Round-number price lines in the right margin",
}
DEFAULTS = {
    "workbook": None,
    "timezone": None,
    "exports_dirs": [],
    "default_session_start": "17:00 America/New_York",
    "symbols": {},
    "indicators_1m": False,  # keep other indicator columns from 1-minute exports too (large files)
    "gallery": {"elements": DEFAULT_ELEMENTS, "images_dir": None, "notes_dir": None, "link_style": "obsidian",
                "timeframe": None, "format": ["html"]},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load():
    raw = json.loads(FILE.read_text()) if FILE.exists() else {}
    return _merge(DEFAULTS, raw)


def save(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def path(p):
    return Path(p).expanduser() if p else None


def tz():
    name = load().get("timezone")
    return ZoneInfo(name) if name else dt.datetime.now().astimezone().tzinfo


def tz_name():
    z = tz()
    return getattr(z, "key", None) or dt.datetime.now(z).tzname()


def workbook(override=None):
    p = path(override) or path(load().get("workbook"))
    if not p:
        sys.exit("No workbook set. Choose where the trade log should live, then run:\n"
                 "  config.py set workbook \"~/path/to/TradingView trades.xlsx\"")
    return p


def symbol(sym):
    cfg = load()
    return {"tick": None, "session_start": cfg["default_session_start"], **cfg["symbols"].get(sym, {})}


def session_start(sym):
    """(hour, minute, ZoneInfo) at which the symbol's trading day starts; daily/4h bars and VWAP anchor here."""
    hhmm, zone = symbol(sym)["session_start"].split()
    h, m = (int(x) for x in hhmm.split(":"))
    return h, m, ZoneInfo(zone)


def decimals(sym, price=None):
    """Decimals to show and round prices to: from the symbol's tick when known, else from the price's size."""
    import math
    tick = symbol(sym).get("tick")
    if tick: return max(0, -int(math.floor(math.log10(tick) + 1e-9)))
    p = abs(price or 0)
    return 1 if p >= 1000 else 2 if p >= 10 else 4 if p >= 0.1 else 6


def set_symbol(sym, key, value):
    cfg = load(); cfg["symbols"].setdefault(sym, {})[key] = value; save(cfg)


def _parse(v):
    try: return json.loads(v)
    except json.JSONDecodeError: return v


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "show":
        cfg = load()
        print(f"config: {FILE}{'' if FILE.exists() else ' (not created yet — defaults shown)'}")
        print(json.dumps(cfg, indent=2))
        print(f"times shown in: {tz_name()}")
    elif a[0] == "set" and len(a) == 3:
        cfg = load(); node = cfg; *parents, last = a[1].split(".")
        for k in parents: node = node.setdefault(k, {})
        node[last] = _parse(a[2]); save(cfg); print(f"{a[1]} = {json.dumps(node[last])}")
    elif a[0] == "symbol" and len(a) == 4:
        set_symbol(a[1], a[2], _parse(a[3])); print(f"{a[1]}.{a[2]} = {a[3]}")
    elif a[0] == "elements":
        for k, v in ALL_ELEMENTS.items(): print(f"{k:14} {v}")
    else:
        sys.exit(__doc__)
