"""Resights: later sightings of animals already recorded (an approach for photos, a focal follow).

A sighting whose ResightOf holds another sighting's SightNo is a resight of it. Resights point at
the first sighting of the animals (the original): one typed against another resight is linked to
that resight's original. A ResightOf that names no sighting (the original deleted or renumbered)
leaves the row counted as a sighting of its own, so no animals are lost from the summary.
The same rules are in web/js/resights.js.
"""
from __future__ import annotations

COPIED = ("Species", "Count", "Calves", "NumConf", "IDrel", "FieldID")   # filled in on a new resight


def _key(v) -> str:
    s = str(v or "").strip().lstrip("#")
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except ValueError:
        return s


def by_sightno(rows: list[dict]) -> dict[str, dict]:
    """SightNo → row (the first row with that number)."""
    out: dict[str, dict] = {}
    for r in rows:
        k = _key(r.get("SightNo"))
        if k and k not in out:
            out[k] = r
    return out


def original_of(row: dict, rows: list[dict], index: dict[str, dict] | None = None) -> dict:
    """The original sighting this row is a resight of (following chains), or the row itself."""
    index = index if index is not None else by_sightno(rows)
    seen = {id(row)}
    cur = row
    while True:
        ref = _key(cur.get("ResightOf"))
        nxt = index.get(ref) if ref else None
        if nxt is None or id(nxt) in seen:
            return cur
        seen.add(id(nxt))
        cur = nxt


def originals(rows: list[dict]) -> dict[str, dict]:
    """RowID → its original sighting's row."""
    index = by_sightno(rows)
    return {r.get("RowID", ""): original_of(r, rows, index) for r in rows}


def is_resight(row: dict, rows: list[dict], index: dict[str, dict] | None = None) -> bool:
    return original_of(row, rows, index) is not row


def groups(rows: list[dict]) -> list[list[dict]]:
    """Each original with its resights after it, in the order the originals come in the table."""
    orig = originals(rows)
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(id(orig[r.get("RowID", "")]), []).append(r)
    return [sorted(g, key=lambda r: 0 if orig[r.get("RowID", "")] is r else 1) for g in out.values()]
