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
    "indicator_names": {},   # exported plot name → column name, e.g. {"Buy": "Long signal"}
    "indicator_columns": False,  # also add a "TV <name>" column per stored indicator to the trade log
    "gallery": {"elements": DEFAULT_ELEMENTS, "images_dir": None, "notes_dir": None, "link_style": "obsidian",
                "timeframe": None, "format": ["html"],
                "workbooks": {}},  # workbook name fragment → gallery settings for those workbooks, e.g. their own elements
    # workbook name fragment → a strategy's own columns: {"columns": [your columns, kept like the journal's],
    # "dropdowns": {column: [choices]}, "plugins": [python files with COLUMNS and compute(row, t0) → {column: value}],
    # "after": the column they follow (default: the end). A plugin column listed in "columns" is placed there too.
    # "differs": {your column: another column} shades yours yellow when it is filled in and differs from the other.
    "workbooks": {},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load():
    raw = json.loads(FILE.read_text()) if FILE.exists() else {}
    return _merge(DEFAULTS, raw)


_read = {}


def cached():
    """load(), read once per change of the settings file. Read-only: callers must not modify it (use load() to edit)."""
    sig = (FILE.stat().st_mtime, FILE.stat().st_size) if FILE.exists() else None
    if _read.get("sig") != sig or "cfg" not in _read: _read.update(sig=sig, cfg=load())
    return _read["cfg"]


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


def gallery_for(wb):
    """The gallery settings for a workbook: the general ones, overridden by every gallery.workbooks entry whose key appears
    in the workbook's file name (case-insensitive), so "9 Ema Retest" covers its back, forward and replay logs."""
    g = load()["gallery"]
    out = {k: v for k, v in g.items() if k != "workbooks"}
    for frag, over in (g.get("workbooks") or {}).items():
        if frag.lower() in Path(wb).stem.lower(): out.update(over)
    return out


def extras_for(wb):
    """A strategy's own columns for a workbook, from every workbooks entry whose key appears in its file name
    (case-insensitive): {"columns": [...], "dropdowns": {...}, "plugins": [...], "after": column or None}."""
    out = {"columns": [], "dropdowns": {}, "plugins": [], "after": None, "differs": {}}
    for frag, x in (cached().get("workbooks") or {}).items():
        if frag.lower() not in Path(wb).stem.lower(): continue
        out["columns"] += [c for c in x.get("columns", []) if c not in out["columns"]]
        out["dropdowns"].update(x.get("dropdowns", {})); out["differs"].update(x.get("differs", {})); out["plugins"] += x.get("plugins", [])
        out["after"] = x.get("after") or out["after"]
    return out


def symbol(sym):
    cfg = cached()
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
