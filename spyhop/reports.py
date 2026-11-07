"""Reports (Tools → Reports): simple tables of selected records, defined in JSON files.

Spyhop ships the definitions in `spyhop/report_defs/`. A group adds its own, or changes
one of these, by putting a .json file in the `reports` folder inside Spyhop's own folder:
a file there with the same "id" replaces the built-in one, and `"enabled": false` hides it.
The format is described in `spyhop/report_defs/README.md`. The Summary report is
separate (it is built by the window, in app.js and summary_html.js).
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import __version__, geo, schema

log = logging.getLogger("spyhop.reports")

BUILTIN_DIR = Path(__file__).parent / "report_defs"
TABLES = {"sightings", "events", "effort"}
# computed values a column can show instead of a table column
VALUES = {"time", "date", "clock", "position", "lat", "lon", "species_code", "event_code"}
TOTALS = {"sum", "count"}
_ID = re.compile(r"^[a-z0-9_]{1,40}$")


def user_dir(cfg) -> Path:
    return cfg.root / "reports"


def _validate(d: dict, src: str) -> str | None:
    """None if the definition is usable, else what's wrong with it."""
    if not isinstance(d, dict):
        return "not a JSON object"
    if not _ID.match(str(d.get("id", ""))):
        return 'needs an "id" of lower-case letters, digits and _'
    if d["id"] == "summary":
        return '"summary" is the built-in Summary report; choose another id'
    if not str(d.get("title", "")).strip():
        return 'needs a "title"'
    if d.get("table") not in TABLES:
        return f'"table" must be one of {", ".join(sorted(TABLES))}'
    keys = {c["key"] for c in schema.TABS[d["table"]]["columns"]}
    cols = d.get("columns")
    if not isinstance(cols, list) or not cols:
        return 'needs a list of "columns"'
    for c in cols:
        if not isinstance(c, dict) or not c.get("label"):
            return 'every column needs a "label"'
        if c.get("column") is None and c.get("value") is None:
            return f'column “{c.get("label")}” needs a "column" (from the {d["table"]} table) or a "value"'
        if c.get("column") is not None and c["column"] not in keys:
            return f'column “{c["label"]}”: the {d["table"]} table has no column {c["column"]!r}'
        if c.get("value") is not None and c["value"] not in VALUES:
            return f'column “{c["label"]}”: "value" must be one of {", ".join(sorted(VALUES))}'
    where = d.get("where", [])
    if not isinstance(where, list) or not all(isinstance(w, dict) for w in where):
        return '"where" must be a list of conditions'
    for w in where:
        if "column" in w and w["column"] not in keys:
            return f'a condition uses {w["column"]!r}, which the {d["table"]} table does not have'
        if "regex" in w:
            try:
                re.compile(str(w["regex"]))
            except re.error as e:
                return f'bad regex {w["regex"]!r}: {e}'
    for label, how in (d.get("totals") or {}).items():
        if how not in TOTALS or label not in [c["label"] for c in cols]:
            return f'totals: {label!r} must be a column label and "sum" or "count"'
    return None


def load_definitions(cfg) -> tuple[list[dict], list[str]]:
    """The report definitions, built-in then the user's, sorted by "order"; and any problems."""
    defs: dict[str, dict] = {}
    errors: list[str] = []
    for folder, source in ((BUILTIN_DIR, "built-in"), (user_dir(cfg), "custom")):
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:
                errors.append(f"{p.name}: can't be read ({e})")
                continue
            if isinstance(d, dict) and d.get("enabled") is False and _ID.match(str(d.get("id", ""))):
                defs.pop(d["id"], None)
                continue
            why = _validate(d, source)
            if why:
                errors.append(f"{p.name}: {why}")
                continue
            defs[d["id"]] = {**d, "source": source, "file": str(p)}
    out = sorted(defs.values(), key=lambda d: (d.get("order", 100), d["title"].lower()))
    for e in errors:
        log.warning("report definition skipped: %s", e)
    return out, errors


def get_definition(cfg, rid: str) -> dict | None:
    return next((d for d in load_definitions(cfg)[0] if d["id"] == rid), None)


# --------------------------------------------------------------------- running a report
def _matches(row: dict, cond: dict, codes: dict) -> bool:
    for k, v in cond.items():
        if k == "column":
            continue
        if k in ("species_code", "event_code"):
            name = row.get("Species" if k == "species_code" else "EventType", "")
            want = {str(x).upper() for x in (v if isinstance(v, list) else [v])}
            if str(codes[k].get(name, "")).upper() not in want:
                return False
            continue
        val = str(row.get(cond.get("column", ""), "")).strip()
        if k == "equals" and val.lower() != str(v).strip().lower():
            return False
        if k == "in" and val.lower() not in {str(x).strip().lower() for x in v}:
            return False
        if k == "regex" and not re.search(str(v), val, re.I):
            return False
        if k == "not_blank" and bool(val) != bool(v):
            return False
    return True


def _position(table: str, r: dict):
    keys = {"sightings": [("SigLat", "SigLon"), ("VesLat", "VesLon")], "events": [("Lat", "Lon")],
            "effort": [("VesLat", "VesLon")]}[table]
    for la, lo in keys:
        try:
            return float(r[la]), float(r[lo])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def run(rec, d: dict) -> dict:
    """Rows of a report for the open survey, formatted for display."""
    from .recorder import parse_time
    cfg = rec.cfg
    fmt = cfg.settings.get("latlon_format", "DDM")
    tz = rec.tz()
    codes = {"species_code": {x.get("name"): x.get("species_code", "") for x in cfg.lists.get("species", [])},
             "event_code": {x.get("name"): x.get("event_code", "") for x in cfg.lists.get("event_types", [])}}
    rows = list(rec.tables[d["table"]].rows) if rec.survey is not None else []
    where = d.get("where") or []
    picked = [r for r in rows if not where or any(_matches(r, w, codes) for w in where)]
    order = {id(r): i for i, r in enumerate(picked)}
    picked.sort(key=lambda r: ((parse_time(r.get("DateTime", "")) or datetime.max.replace(tzinfo=tz)), order[id(r)]))

    def cell(r, c):
        if c.get("column"):
            return str(r.get(c["column"], "") or "")
        v = c["value"]
        if v in ("time", "date", "clock"):
            t = parse_time(r.get("DateTime", ""))
            if t is None:
                return r.get("DateTime", "")
            t = t.astimezone(tz)
            return {"time": t.strftime("%Y-%m-%d %H:%M:%S ") + (t.tzname() or ""),
                    "date": t.strftime("%Y-%m-%d"), "clock": t.strftime("%H:%M:%S ") + (t.tzname() or "")}[v].strip()
        if v in ("position", "lat", "lon"):
            p = _position(d["table"], r)
            if not p:
                return ""
            if v == "lat":
                return geo.format_coord(p[0], True, fmt)
            if v == "lon":
                return geo.format_coord(p[1], False, fmt)
            return f"{geo.format_coord(p[0], True, fmt)} {geo.format_coord(p[1], False, fmt)}"
        if v == "species_code":
            return str(codes["species_code"].get(r.get("Species", ""), ""))
        if v == "event_code":
            return str(codes["event_code"].get(r.get("EventType", ""), ""))
        return ""

    cols = d["columns"]
    body = [[cell(r, c) for c in cols] for r in picked]
    totals = None
    if d.get("totals") and body:
        totals = []
        for i, c in enumerate(cols):
            how = d["totals"].get(c["label"])
            if how == "sum":
                s = 0.0
                for row in body:
                    try:
                        s += float(row[i])
                    except ValueError:
                        pass
                totals.append(f"{s:g}")
            elif how == "count":
                totals.append(str(sum(1 for row in body if row[i])))
            else:
                totals.append("")
    return {"id": d["id"], "title": d["title"], "description": d.get("description", ""),
            "columns": [{"label": c["label"], "align": c.get("align", "left")} for c in cols],
            "rows": body, "totals": totals, "count": len(body), "empty": d.get("empty", "Nothing to report."),
            "survey": (rec.survey or {}).get("prefix"), "source": d.get("source"), "file": d.get("file")}


# --------------------------------------------------------------------- a standalone page
CSS = """
body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1d2733; margin: 24px; }
h1 { font-size: 20px; margin: 0 0 2px; } .sub { color: #5b6b7c; margin: 0 0 14px; }
.meta { border-collapse: collapse; margin: 0 0 16px; } .meta th { text-align: left; font-weight: 600; padding: 1px 12px 1px 0; color: #5b6b7c; }
.meta td { padding: 1px 0; }
table.rep { border-collapse: collapse; width: 100%; }
table.rep th, table.rep td { border-bottom: 1px solid #d7dde3; padding: 4px 8px; text-align: left; vertical-align: top; }
table.rep th { background: #eef1f4; font-weight: 600; }
table.rep td.r, table.rep th.r { text-align: right; }
table.rep td.nw { white-space: nowrap; }
table.rep tfoot td { font-weight: 600; border-top: 2px solid #9aa7b4; }
p.desc { color: #3b4856; } p.empty { color: #5b6b7c; font-style: italic; }
footer { margin-top: 18px; color: #7a8896; font-size: 11px; }
@page { margin: 14mm; }
@media print { body { margin: 0; } thead { display: table-header-group; } tr { break-inside: avoid; } }
"""


def to_html(rec, res: dict) -> str:
    """A self-contained page for a report: survey details, the table and its totals."""
    e = _html.escape
    meta = rec.read_meta() if rec.survey is not None else {}
    labels = {k: lab for k, lab, _ in schema.SURVEY_META}
    info = [("Survey", res.get("survey") or "—")]
    info += [(labels[k], meta[k]) for k in ("platform_name", "platform_type", "organization", "chief_scientist") if meta.get(k)]
    try:
        sv = next((s for s in rec.list_surveys() if s["prefix"] == res.get("survey")), None)
    except Exception:                                    # pragma: no cover - only decoration
        sv = None
    if sv:
        info.append(("Dates", f"{(sv.get('start_time') or '')[:10]} – {(sv.get('end_time') or '')[:10] or 'still active'}"))
    now = rec.now()
    head = "".join(f'<th class="{"r" if c["align"] == "right" else ""}">{e(c["label"])}</th>' for c in res["columns"])
    nowrap = {i for i, c in enumerate(res["columns"]) if c["label"].lower() in ("time", "date", "position")}
    rows = "".join("<tr>" + "".join(
        f'<td class="{"r" if res["columns"][i]["align"] == "right" else ""}{" nw" if i in nowrap else ""}">{e(v)}</td>'
        for i, v in enumerate(r)) + "</tr>" for r in res["rows"])
    foot = ""
    if res.get("totals"):
        cells = list(res["totals"])
        cells[0] = cells[0] or f"Total ({res['count']})"
        foot = "<tfoot><tr>" + "".join(f'<td class="{"r" if res["columns"][i]["align"] == "right" else ""}">{e(v)}</td>'
                                        for i, v in enumerate(cells)) + "</tr></tfoot>"
    table = (f'<table class="rep"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody>{foot}</table>'
             f'<p class="sub">{res["count"]} record{"" if res["count"] == 1 else "s"}</p>') if res["rows"] \
        else f'<p class="empty">{e(res["empty"])}</p>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{e(res['title'])} — {e(res.get('survey') or '')}</title>
<meta name="generator" content="Spyhop {e(__version__)}"><style>{CSS}</style></head>
<body><h1>{e(res['title'])}</h1><p class="sub">Spyhop report · made {e(now.strftime('%Y-%m-%d %H:%M ') + (now.tzname() or ''))}</p>
<table class="meta">{''.join(f'<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>' for k, v in info)}</table>
{f'<p class="desc">{e(res["description"])}</p>' if res.get('description') else ''}
{table}
<footer>Made with Spyhop {e(__version__)}. Times are in the survey clock ({e(now.tzname() or '')}).</footer>
</body></html>"""


def prepare_user_dir(cfg) -> Path:
    """Make the user's reports folder, with this README and copies of the built-in reports
    (in `examples/`, which Spyhop doesn't load) to start from."""
    import shutil
    d = user_dir(cfg)
    ex = d / "examples"
    ex.mkdir(parents=True, exist_ok=True)
    for p in BUILTIN_DIR.glob("*.json"):
        shutil.copyfile(p, ex / p.name)
    shutil.copyfile(BUILTIN_DIR / "README.md", d / "README.md")
    return d
