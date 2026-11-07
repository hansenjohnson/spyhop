"""Reports (Tools → Reports): pick rows of the Sightings, Events or Effort table and some of its
columns, see the result, and save it as CSV, HTML or PDF. (Until 0.18 this was Tools → Filter;
the older JSON report templates were removed in 0.19.)

A report is a small JSON object:

    {"name": "Right whales", "table": "sightings", "codes": ["RIWH"],
     "columns": ["time", "position", "Count", "Calves", "Notes"],
     "on_effort": false, "time_from": "", "time_to": "",
     "rules": [{"column": "Notes", "op": "contains", "value": "calf"}]}

- codes: species codes (Sightings) or event codes (Events) to keep; none = all rows. A row
  matches when its Species / EventType has that code in the lists, or was typed as the code
  itself. A row whose name has no code is matched by its name.
- columns: table columns (their keys, e.g. "Count") or computed values (COMPUTED), in order.
- on_effort: only rows made while effort was ON (Sightings and Events).
- time_from / time_to: "YYYY-MM-DDTHH:MM" in the survey clock; blank = open.
- rules: more conditions, all of which must hold (OPS).

Saved reports are files in the `reports` folder in Spyhop's own folder, one per report. Spyhop
puts the starting ones from `spyhop/report_defs/` (Gear, Dead birds, Right whales, Blue whales)
there once. Templates carry the saved reports in their spyhop-config.json (older ones as `reports/*.json`).

Older versions left other things in that folder, moved aside by `ensure_dir`: report templates
of the old format (0.9–0.18) go to `old_report_templates/`, and saved filters from 0.18's
`filters` folder are moved in.
"""
from __future__ import annotations

import csv
import html as _html
import io
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import __version__, geo, schema

BUILTIN_DIR = Path(__file__).parent / "report_defs"
TABLES = ("sightings", "events", "effort")
CODE_COLUMN = {"sightings": ("Species", "species", "species_code"), "events": ("EventType", "event_types", "event_code")}
# computed columns: key -> label (the code's label depends on the table)
COMPUTED = {"time": "Time", "time_fmt": "Time (formatted)", "date": "Date", "clock": "Clock time", "position": "Position",
            "lat": "Latitude", "lon": "Longitude", "code": "Code"}
OPS = {"is": "is", "is_not": "is not", "contains": "contains", "not_contains": "doesn't contain",
       "blank": "is blank", "not_blank": "isn't blank", "gt": "is more than", "lt": "is less than"}
NUMERIC = ("int", "float")
MAX_NAME = 60


class ReportError(ValueError):
    pass


# ------------------------------------------------------------------ the columns a table offers
def code_label(table: str) -> str:
    return {"sightings": "Species code", "events": "Event code"}.get(table, "Code")


def columns(table: str) -> list[dict]:
    """[{key, label, numeric, computed}] offered for a table, in the order they are listed."""
    out = []
    for k in ("time", "time_fmt", "date", "clock", "position", "lat", "lon"):
        out.append({"key": k, "label": COMPUTED[k], "numeric": False, "computed": True})
    if table in CODE_COLUMN:
        out.append({"key": "code", "label": code_label(table), "numeric": False, "computed": True})
    for c in schema.TABS[table]["columns"]:
        if c["key"] in ("RowID", "Map", "DateTime") or (c["hidden"] and c["key"] != "VesHdg"):
            continue
        out.append({"key": c["key"], "label": c["label"], "numeric": c["type"] == "int", "computed": False})
    return out


def _column_keys(table: str) -> set[str]:
    return {c["key"] for c in schema.TABS[table]["columns"]}


# ------------------------------------------------------------------ checking a report
def clean(d) -> dict:
    """A tidy copy of a report, or ReportError saying what's wrong with it."""
    if not isinstance(d, dict):
        raise ReportError("A report must be a JSON object.")
    table = d.get("table")
    if table not in TABLES:
        raise ReportError(f'"table" must be one of {", ".join(TABLES)}.')
    offered = {c["key"] for c in columns(table)}
    cols = d.get("columns") or []
    if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
        raise ReportError('"columns" must be a list of column names.')
    bad = [c for c in cols if c not in offered]
    if bad:
        raise ReportError(f"The {table} table has no column {', '.join(map(repr, bad))}.")
    codes = d.get("codes") or []
    if not isinstance(codes, list):
        raise ReportError('"codes" must be a list.')
    keys = _column_keys(table)
    rules = []
    for r in d.get("rules") or []:
        if not isinstance(r, dict) or r.get("column") not in keys or r.get("op") not in OPS:
            raise ReportError(f"A rule must have a column of the {table} table and an op ({', '.join(OPS)}).")
        if r["op"] in ("gt", "lt"):
            try:
                float(r.get("value", ""))
            except (TypeError, ValueError):
                raise ReportError(f"“{r['column']} {OPS[r['op']]}” needs a number.")
        rules.append({"column": r["column"], "op": r["op"], "value": str(r.get("value", "")).strip()})
    tf, tt = str(d.get("time_from") or "").strip(), str(d.get("time_to") or "").strip()
    for t in (tf, tt):
        if t and _local(t) is None:
            raise ReportError(f"{t!r} isn't a date and time (YYYY-MM-DD HH:MM).")
    return {"name": str(d.get("name") or "").strip()[:MAX_NAME], "table": table,
            "codes": [str(c).strip() for c in codes if str(c).strip()],
            "columns": list(dict.fromkeys(cols)), "on_effort": bool(d.get("on_effort")) and table != "effort",
            "time_from": tf, "time_to": tt, "rules": rules}


def _local(s: str):
    try:
        return datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return None


# ------------------------------------------------------------------ running a report
def _codes(cfg, table: str) -> dict[str, str]:
    """{name in lower case: code} from the Species or Event types list."""
    if table not in CODE_COLUMN:
        return {}
    _, lst, field = CODE_COLUMN[table]
    return {str(x.get("name", "")).strip().lower(): str(x.get(field, "") or "").strip()
            for x in cfg.lists.get(lst, [])}


def row_key(table: str, row: dict, codes: dict) -> str:
    """The code a row is picked by: its name's code, else what was typed."""
    name = str(row.get(CODE_COLUMN[table][0], "") or "").strip()
    return codes.get(name.lower()) or name


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rule_ok(row: dict, r: dict) -> bool:
    val = str(row.get(r["column"], "") or "").strip()
    want, op = r["value"], r["op"]
    if op == "is":
        return val.lower() == want.lower()
    if op == "is_not":
        return val.lower() != want.lower()
    if op == "contains":
        return want.lower() in val.lower()
    if op == "not_contains":
        return want.lower() not in val.lower()
    if op == "blank":
        return not val
    if op == "not_blank":
        return bool(val)
    a, b = _num(val), _num(want)
    if a is None or b is None:
        return False
    return a > b if op == "gt" else a < b


def counts(rec, table: str) -> list[dict]:
    """[{code, name, n}] for the codes in this survey's table, most rows first."""
    if table not in CODE_COLUMN or rec.survey is None:
        return []
    codes = _codes(rec.cfg, table)
    seen: dict[str, dict] = {}
    for r in rec.tables[table].rows:
        k = row_key(table, r, codes)
        if not k:
            continue
        e = seen.setdefault(k.upper(), {"code": k, "name": str(r.get(CODE_COLUMN[table][0], "")).strip(), "n": 0})
        e["n"] += 1
    return sorted(seen.values(), key=lambda e: (-e["n"], e["code"]))


def _position(table: str, r: dict):
    keys = {"sightings": [("SigLat", "SigLon"), ("VesLat", "VesLon")], "events": [("Lat", "Lon")],
            "effort": [("VesLat", "VesLon")]}[table]
    for la, lo in keys:
        try:
            return float(r[la]), float(r[lo])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def run(rec, spec: dict) -> dict:
    """The rows a report picks from the open survey, formatted for display and export."""
    from .recorder import parse_time
    spec = clean(spec)
    cfg, table = rec.cfg, spec["table"]
    fmt = cfg.settings.get("latlon_format", "DDM")
    tz = rec.tz()
    codes = _codes(cfg, table)
    rows = list(rec.tables[table].rows) if rec.survey is not None else []
    total = len(rows)
    want = {c.upper() for c in spec["codes"]}
    t_from, t_to = _local(spec["time_from"]) if spec["time_from"] else None, _local(spec["time_to"]) if spec["time_to"] else None
    intervals = rec.effort_intervals() if spec["on_effort"] else None

    def when(r):
        return parse_time(r.get("DateTime", ""))

    def effort_at(t):
        st = ""
        for t0, _t1, s in intervals:
            if t0 <= t:
                st = s
            else:
                break
        return st

    picked = []
    for r in rows:
        if want and table in CODE_COLUMN:
            name = str(r.get(CODE_COLUMN[table][0], "") or "").strip()
            if row_key(table, r, codes).upper() not in want and name.upper() not in want:
                continue
        t = when(r)
        if t_from or t_to:
            if t is None:
                continue
            lt = t.astimezone(tz).replace(tzinfo=None)
            if (t_from and lt < t_from) or (t_to and lt > t_to):
                continue
        if intervals is not None and (t is None or effort_at(t) != "ON"):
            continue
        if not all(_rule_ok(r, x) for x in spec["rules"]):
            continue
        picked.append(r)
    order = {id(r): i for i, r in enumerate(picked)}
    far = datetime.max.replace(tzinfo=tz)
    picked.sort(key=lambda r: (when(r) or far, order[id(r)]))

    offered = {c["key"]: c for c in columns(table)}
    cols = [offered[k] for k in spec["columns"]]

    def cell(r, c):
        k = c["key"]
        if not c["computed"]:
            return str(r.get(k, "") or "")
        if k in ("time", "time_fmt", "date", "clock"):
            t = when(r)
            if t is None:
                return str(r.get("DateTime", "") or "")
            t = t.astimezone(tz)
            return {"time": t.strftime("%Y-%m-%d %H:%M:%S"), "date": t.strftime("%Y-%m-%d"),
                    "time_fmt": f"{t.strftime('%Y-%m-%d %H:%M')} {t.tzname() or ''}".strip(),
                    "clock": t.strftime("%H:%M:%S")}[k]
        if k == "code":
            return row_key(table, r, codes)
        p = _position(table, r)
        if not p:
            return ""
        if k == "lat":
            return geo.format_coord(p[0], True, fmt)
        if k == "lon":
            return geo.format_coord(p[1], False, fmt)
        return f"{geo.format_coord(p[0], True, fmt)} {geo.format_coord(p[1], False, fmt)}"

    body = [[cell(r, c) for c in cols] for r in picked]
    totals = None
    if body and any(c["numeric"] for c in cols):
        totals = []
        for i, c in enumerate(cols):
            if c["numeric"]:
                s = sum(v for v in (_num(row[i]) for row in body) if v is not None)
                totals.append(f"{s:g}")
            else:
                totals.append("")
    return {"name": spec["name"], "table": table, "spec": spec,
            "columns": [{"key": c["key"], "label": c["label"], "align": "right" if c["numeric"] else "left"} for c in cols],
            "rows": body, "row_ids": [r.get("RowID", "") for r in picked], "totals": totals,
            "count": len(body), "total": total, "survey": (rec.survey or {}).get("prefix"),
            "zone": datetime.now(tz).tzname() or ""}


def describe(spec: dict) -> str:
    """One line saying what a report picks (used in the Export Data and Run Reports lists)."""
    s = clean(spec)
    what = {"sightings": "Sightings", "events": "Events", "effort": "Effort rows"}[s["table"]]
    bits = []
    if s["codes"]:
        bits.append(", ".join(s["codes"]))
    if s["on_effort"]:
        bits.append("on effort")
    if s["time_from"] or s["time_to"]:
        bits.append(f"from {s['time_from'].replace('T', ' ') or 'the start'} to {s['time_to'].replace('T', ' ') or 'the end'}")
    bits += [f"{r['column']} {OPS[r['op']]}{(' ' + r['value']) if r['op'] not in ('blank', 'not_blank') else ''}"
             for r in s["rules"]]
    return what + (": " + "; ".join(bits) if bits else " (all)") + "."


def to_csv(res: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([c["label"] for c in res["columns"]])
    w.writerows(res["rows"])
    return "﻿" + buf.getvalue()        # the BOM makes Excel read it as UTF-8


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


def _dates(rec, prefix) -> str:
    """The survey's date, or its first and last dates if it ran over more than one."""
    try:
        sv = next((s for s in rec.list_surveys() if s["prefix"] == prefix), None)
    except Exception:                                    # pragma: no cover - only decoration
        sv = None
    if not sv or not sv.get("start_time"):
        return ""
    from .recorder import parse_time
    tz = rec.tz()
    def day(iso):
        t = parse_time(iso or "")
        return t.astimezone(tz).strftime("%Y-%m-%d") if t else (iso or "")[:10]
    start = day(sv["start_time"])
    if sv.get("end_time"):
        end = day(sv["end_time"])
        return start if end == start else f"{start} – {end}"
    today = rec.now().strftime("%Y-%m-%d")
    return start if today == start else f"{start} – still under way"


def to_html(rec, res: dict) -> str:
    """A self-contained page: the survey details, the table and its totals."""
    e = _html.escape
    meta = rec.read_meta() if rec.survey is not None else {}
    labels = {k: lab for k, lab, _ in schema.SURVEY_META}
    info = [("Survey", res.get("survey") or "—")]
    dates = _dates(rec, res.get("survey")) if rec.survey is not None else ""
    if dates:
        info.append(("Date" if "–" not in dates else "Dates", dates))
    info += [(labels[k], meta[k]) for k in ("platform_name", "platform_type", "organization", "chief_scientist",
                                            "chief_scientist_email") if meta.get(k)]
    now = rec.now()
    cols = res["columns"]
    right = lambda i: "r" if cols[i]["align"] == "right" else ""                     # noqa: E731
    nowrap = {i for i, c in enumerate(cols) if c.get("key") in ("time", "time_fmt", "date", "clock", "position", "lat", "lon")}
    head = "".join(f'<th class="{right(i)}">{e(c["label"])}</th>' for i, c in enumerate(cols))
    rows = "".join("<tr>" + "".join(f'<td class="{right(i)}{" nw" if i in nowrap else ""}">{e(v)}</td>'
                                    for i, v in enumerate(r)) + "</tr>" for r in res["rows"])
    foot = ""
    if res.get("totals"):
        cells = list(res["totals"])
        cells[0] = cells[0] or f"Total ({res['count']})"
        foot = "<tfoot><tr>" + "".join(f'<td class="{right(i)}">{e(v)}</td>' for i, v in enumerate(cells)) + "</tr></tfoot>"
    table = (f'<table class="rep"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody>{foot}</table>'
             f'<p class="sub">{res["count"]} record{"" if res["count"] == 1 else "s"}</p>') if res["rows"] \
        else '<p class="empty">No records match this report.</p>'
    title = res.get("name") or "Report"
    def cell(v):
        v = str(v)
        return f'<a href="mailto:{e(v)}">{e(v)}</a>' if "@" in v and " " not in v else e(v)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{e(title)} — {e(res.get('survey') or '')}</title>
<meta name="generator" content="Spyhop {e(__version__)}"><style>{CSS}</style></head>
<body><h1>{e(title)}</h1><p class="sub">Spyhop report · made {e(now.strftime('%Y-%m-%d %H:%M ') + (now.tzname() or ''))}</p>
<table class="meta">{''.join(f'<tr><th>{e(k)}</th><td>{cell(v)}</td></tr>' for k, v in info)}</table>
{table}
<footer>Made with Spyhop {e(__version__)}. Times are in the survey clock ({e(now.tzname() or '')}).</footer>
</body></html>"""


# ------------------------------------------------------------------ saved reports
OLD_DIR = "old_report_templates"     # report templates of the old format (0.9–0.18), moved aside


def user_dir(cfg) -> Path:
    return cfg.root / "reports"


def file_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return (s[:50] or "report") + ".json"


def is_old_report_template(d) -> bool:
    """A report template of the format used before 0.19 (it has "id"/"title" and column objects)."""
    return isinstance(d, dict) and ("where" in d or "id" in d or
                                    any(isinstance(c, dict) for c in d.get("columns") or []))


def ensure_dir(cfg) -> Path:
    """The reports folder: old templates moved aside, 0.18's saved filters moved in, and the
    starting reports put in once."""
    d = user_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    old = d / OLD_DIR
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if is_old_report_template(data):
            old.mkdir(exist_ok=True)
            p.replace(old / p.name)
    for extra in ("README.md", "examples"):
        if (d / extra).exists():
            old.mkdir(exist_ok=True)
            if not (old / extra).exists():
                (d / extra).replace(old / extra)
    seeded = cfg.settings_dir / "reports_started.txt"
    fdir = cfg.root / "filters"                        # 0.18 saved filters
    if fdir.is_dir():
        for p in sorted(fdir.glob("*.json")):
            if not (d / p.name).exists():
                p.replace(d / p.name)
        try:
            fdir.rmdir()
        except OSError:
            pass
        _mark(seeded)
    if not seeded.exists():
        for p in sorted(BUILTIN_DIR.glob("*.json")):
            if not (d / p.name).exists():
                shutil.copyfile(p, d / p.name)
        _mark(seeded)
    return d


def _mark(p: Path):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("The starting reports were put in the reports folder (they are not put back if deleted).\n")
    except OSError:
        pass


def load(cfg) -> tuple[list[dict], list[str]]:
    """The saved reports, by name, and any files that couldn't be used."""
    out, errors = [], []
    d = ensure_dir(cfg)
    for p in sorted(d.glob("*.json")):
        try:
            f = clean(json.loads(p.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as e:
            errors.append(f"{p.name}: {e}")
            continue
        f["name"] = f["name"] or p.stem
        f["file"] = p.name
        out.append(f)
    out.sort(key=lambda f: f["name"].lower())
    return out, errors


def validate(d) -> str | None:
    """None if a saved report (e.g. in a template) is usable, else what's wrong."""
    try:
        clean(d)
    except ReportError as e:
        return str(e).rstrip(".")
    return None


def save(cfg, spec: dict, replace: str | None = None) -> dict:
    """Save a report under its name. replace: the file of the report it replaces (renaming it)."""
    f = clean(spec)
    if not f["name"]:
        raise ReportError("Give the report a name.")
    d = ensure_dir(cfg)
    fn = file_name(f["name"])
    existing = {x["file"]: x for x in load(cfg)[0]}
    if fn in existing and fn != replace and existing[fn]["name"].lower() != f["name"].lower():
        fn = fn[:-5] + "_2.json"
    body = {k: f[k] for k in ("name", "table", "codes", "columns", "on_effort", "time_from", "time_to", "rules")}
    tmp = d / (fn + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(d / fn)
    if replace and replace != fn:
        delete(cfg, replace)
    return {**body, "file": fn}


def delete(cfg, fn: str):
    p = user_dir(cfg) / Path(str(fn)).name
    if p.suffix != ".json" or not p.is_file():
        raise ReportError("There's no saved report by that name.")
    p.unlink()
