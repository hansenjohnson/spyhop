"""Rules (0.52): a team's own checks of the values in one row of Sightings, Effort or Events.

Each rule: "if <conditions> then <conditions>". The rule applies to a row when every "if" condition holds
(no "if" conditions: every row); then every "then" condition must hold, or the row breaks the rule.
Rules are part of the template's data part (rules.csv in templates/current), so they can't change during
a survey, and the Error check runs them (check "Rules").

rules.csv columns: on (yes/no), table, level (error/warning/info), if, then, message, resights
(include/skip, Sightings only). "if" and "then" are conditions joined by " AND ", each written
"<column> <test> <value>", e.g.  Behaviors includes Mom/calf AND Species is not Unid. whale
A value in [brackets] is another column of the same row, e.g.  Count >= [Calves]
"is one of" takes values separated by " | ".

A condition on a blank cell is false, except "is blank" (so a rule doesn't apply to a row whose "if"
cell is blank, and a "then" test fails on a blank cell). Number tests are false unless both sides are
numbers (so NA doesn't count as a number).
"""

from __future__ import annotations

import re

from . import schema

TABLES = ("sightings", "effort", "events")
LEVELS = ("error", "warning", "info")
COLUMNS = ["on", "table", "level", "if", "then", "message", "resights"]

# test → (label in Spyhop, needs a value, kinds of column it's for)
TESTS = {
    "is": ("is", True, {"text", "choice", "number"}),
    "is not": ("is not", True, {"text", "choice", "number"}),
    "is one of": ("is one of", True, {"text", "choice"}),
    "is not one of": ("is not one of", True, {"text", "choice"}),
    "contains": ("contains", True, {"text", "choice"}),
    "does not contain": ("doesn’t contain", True, {"text", "choice"}),
    "includes": ("includes", True, {"multi"}),
    "does not include": ("doesn’t include", True, {"multi"}),
    "=": ("=", True, {"number"}),
    "!=": ("≠", True, {"number"}),
    ">": (">", True, {"number"}),
    ">=": ("≥", True, {"number"}),
    "<": ("<", True, {"number"}),
    "<=": ("≤", True, {"number"}),
    "is blank": ("is blank", False, {"text", "choice", "multi", "number"}),
    "is not blank": ("isn’t blank", False, {"text", "choice", "multi", "number"}),
}
# longest first, so "is not one of" isn't read as "is not"
_TEST_ORDER = sorted(TESTS, key=len, reverse=True)
_KIND = {"text": "text", "choice": "choice", "multi": "multi", "int": "number", "float": "number", "seq": "number"}

DEFAULT_RULES = (COLUMNS, [
    ["yes", "sightings", "error", "Calves >= 0", "Count >= [Calves]", "More calves than animals: Num should be at least Calves.", "include"],
])


def kind(col: dict | None) -> str | None:
    """The kind of value a column holds, for rules (None: not usable in a rule, e.g. times and positions)."""
    if not col or col.get("hidden") or col["key"] in ("RowID", "Map"):
        return None
    return _KIND.get(col["type"])


def columns(table: str) -> list[dict]:
    """The columns a rule on this table can use: [{key, label, kind, list}]."""
    out = []
    for c in schema.TABS[table]["columns"]:
        k = kind(c)
        if k:
            out.append({"key": c["key"], "label": c["label"], "kind": k, "list": c.get("list")})
    return out


def parse_conditions(text: str) -> list[dict]:
    """"Calves >= 0 AND Species is Fin whale" → [{column, test, value}]. Raises ValueError."""
    out = []
    for part in re.split(r"\s+AND\s+", (text or "").strip()):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(\S+)\s*(.*)$", part)
        col, rest = m.group(1), m.group(2).strip()
        for t in ("<=", ">=", "!=", "=", ">", "<"):          # "Count>=1" written without spaces
            if col.endswith(t) or t in col:
                i = col.find(t)
                col, rest = col[:i], (col[i:] + " " + rest).strip()
                break
        test = next((t for t in _TEST_ORDER if rest == t or rest.startswith(t + " ") or (t in "<=>=!=" and rest.startswith(t))), None)
        if test is None:
            raise ValueError(f"“{part}”: no test after {col} (e.g. is, is not, includes, >=, is blank).")
        value = rest[len(test):].strip()
        out.append({"column": col, "test": test, "value": value})
    return out


def format_conditions(conds: list[dict]) -> str:
    return " AND ".join(" ".join(x for x in (c["column"], c["test"], c.get("value", "")) if x) for c in conds)


def ref(value: str) -> str | None:
    """"[Calves]" → "Calves" (a value taken from another column of the row)."""
    m = re.fullmatch(r"\[\s*([^\]]+?)\s*\]", (value or "").strip())
    return m.group(1) if m else None


def clean_rule(r: dict, i: int, problems: list[str]) -> dict | None:
    """One rule from Settings → Rules or rules.csv, checked. Problems go in `problems` ("Rule i: …")."""
    g = lambda k: str((r or {}).get(k, "") or "").strip()      # noqa: E731
    table = g("table").lower()
    if table not in TABLES:
        problems.append(f"Rule {i}: choose the table (Sightings, Effort or Events).")
        return None
    level = (g("level").lower() or "error").replace("note", "info")
    if level not in LEVELS:
        problems.append(f"Rule {i}: the level should be error, warning or note.")
        return None
    cols = {c["key"]: c for c in columns(table)}
    sides = {}
    for side in ("if", "then"):
        raw = r.get(side)
        try:
            conds = [dict(c) for c in raw] if isinstance(raw, list) else parse_conditions(str(raw or ""))
        except ValueError as e:
            problems.append(f"Rule {i}: {e}")
            return None
        ok = []
        for c in conds:
            col, test, value = str(c.get("column", "")).strip(), str(c.get("test", "")).strip(), str(c.get("value", "") or "").strip()
            if not col and not test and not value:
                continue
            what = f"Rule {i} ({'if' if side == 'if' else 'then'} {col or '?'})"
            if col not in cols:
                problems.append(f"{what}: {schema.TABS[table]['title']} has no column “{col}” that a rule can use.")
                continue
            if test not in TESTS:
                problems.append(f"{what}: unknown test “{test}”.")
                continue
            label, needs, kinds = TESTS[test]
            k = cols[col]["kind"]
            if k not in kinds:
                problems.append(f"{what}: “{label}” doesn't work with {cols[col]['label']}.")
                continue
            if not needs:
                value = ""
            elif not value:
                problems.append(f"{what}: give a value after “{label}”.")
                continue
            rc = ref(value)
            if rc is not None:
                if rc not in cols:
                    problems.append(f"{what}: [{rc}] isn't a column of {schema.TABS[table]['title']}.")
                    continue
                value = f"[{rc}]"
            elif k == "number" and test in ("=", "!=", ">", ">=", "<", "<="):
                try:
                    float(value)
                except ValueError:
                    problems.append(f"{what}: “{value}” isn't a number (or a [column]).")
                    continue
            ok.append({"column": col, "test": test, "value": value})
        sides[side] = ok
    if not sides["then"]:
        problems.append(f"Rule {i}: give at least one “then” condition (what must be true).")
        return None
    on = g("on").lower() not in ("no", "off", "false", "0")
    res = "skip" if g("resights").lower() == "skip" and table == "sightings" else "include"
    return {"on": on, "table": table, "level": level, "if": sides["if"], "then": sides["then"],
            "message": g("message"), "resights": res}


def to_csv_row(r: dict) -> list[str]:
    return ["yes" if r["on"] else "no", r["table"], r["level"], format_conditions(r["if"]),
            format_conditions(r["then"]), r["message"], r["resights"]]


def load(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Rules read from rules.csv: the ones that can be used, and the problems with the others."""
    out, problems = [], []
    for i, r in enumerate(rows, 1):
        c = clean_rule(r, i, problems)
        if c:
            out.append(c)
    return out, problems


# ---- evaluation -------------------------------------------------------------------------------
def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _multi(v: str) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[;,|]", v or "") if p.strip()]


def holds(c: dict, row: dict, kinds: dict[str, str]) -> bool:
    """Does condition c hold for this row? (kinds: column → kind)"""
    v = str(row.get(c["column"], "") or "").strip()
    t = c["test"]
    if t == "is blank":
        return not v
    if t == "is not blank":
        return bool(v)
    if not v:
        return False
    rc = ref(c["value"])
    other = str(row.get(rc, "") or "").strip() if rc else c["value"]
    if rc and not other:
        return False
    k = kinds.get(c["column"])
    if t in ("=", "!=", ">", ">=", "<", "<="):
        a, b = _num(v), _num(other)
        if a is None or b is None:
            return False
        return {"=": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[t]
    if t in ("includes", "does not include"):
        have = _multi(v)
        want = _multi(other) if rc else [other.lower()]
        inc = all(w in have for w in want)
        return inc if t == "includes" else not inc
    vl, ol = v.lower(), other.lower()
    if t == "is":
        return vl == ol if k != "number" or _num(v) is None or _num(other) is None else _num(v) == _num(other)
    if t == "is not":
        return not holds({**c, "test": "is"}, row, kinds)
    opts = [o.strip().lower() for o in other.split("|") if o.strip()]
    if t == "is one of":
        return vl in opts
    if t == "is not one of":
        return vl not in opts
    if t == "contains":
        return ol in vl
    if t == "does not contain":
        return ol not in vl
    return False


def describe(c: dict) -> str:
    label = TESTS.get(c["test"], (c["test"],))[0]
    return " ".join(x for x in (c["column"], label, c.get("value", "")) if x)


def auto_message(rule: dict) -> str:
    then = " and ".join(describe(c) for c in rule["then"])
    cond = " and ".join(describe(c) for c in rule["if"])
    return f"When {cond}, {then} is expected." if cond else f"{then} is expected."


def broken(rule: dict, rows: list[dict], is_resight=None) -> list[tuple[dict, str]]:
    """The rows that break a rule: [(row, the first "then" column that failed)]."""
    kinds = {c["key"]: c["kind"] for c in columns(rule["table"])}
    out = []
    for r in rows:
        if rule["table"] == "sightings" and rule.get("resights") == "skip" and is_resight and is_resight(r):
            continue
        if not all(holds(c, r, kinds) for c in rule["if"]):
            continue
        bad = next((c for c in rule["then"] if not holds(c, r, kinds)), None)
        if bad:
            out.append((r, bad["column"]))
    return out


def unknown_values(rule: dict, list_values) -> list[str]:
    """Values a rule names that aren't in their column's list (e.g. a species renamed since)."""
    cols = {c["key"]: c for c in columns(rule["table"])}
    out = []
    for c in rule["if"] + rule["then"]:
        col = cols.get(c["column"])
        if not col or not col.get("list") or ref(c["value"]) or c["test"] in ("contains", "does not contain", "is blank", "is not blank"):
            continue
        opts = {o.lower() for o in (list_values(col["list"]) or [])}
        if not opts:
            continue
        vals = c["value"].split("|") if c["test"] in ("is one of", "is not one of") else re.split(r"[;,|]", c["value"]) if col["kind"] == "multi" else [c["value"]]
        out += [f"{col['label']} “{v.strip()}”" for v in vals if v.strip() and v.strip().lower() not in opts]
    return out


def schema_info() -> dict:
    """For the Rules tab: the tests and the columns of each table."""
    return {"tests": {k: {"label": v[0], "value": v[1], "kinds": sorted(v[2])} for k, v in TESTS.items()},
            "test_order": list(TESTS), "columns": {t: columns(t) for t in TABLES}, "levels": list(LEVELS)}
