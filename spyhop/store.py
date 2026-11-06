"""CSV-backed tables with per-tab undo/redo, plus the internal trackline.

Every change is written to disk straight away (write to a temp file, then
replace), so a crash or power cut loses at most the edit in progress.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import schema


class WriteError(Exception):
    pass


def safe_name(s: str) -> str:
    """A survey name usable as a file-name prefix on Windows, macOS and Linux.
    Keeps the team's own naming (letters, digits, spaces, - _ . ( ) etc.); only
    characters that file systems forbid are replaced with _."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s.strip())
    s = s.strip(" .")
    return s[:80] or "survey"


def atomic_write_csv(path: Path, header: list[str], rows: list[dict]):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
        fh.flush()
        os.fsync(fh.fileno())
    last = None
    for _ in range(5):  # Windows: the file may be briefly locked (e.g. by a viewer)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.1)
    raise WriteError(f"Could not save {path.name} — is it open in another program "
                     f"(e.g. Excel)? Your edit is kept in memory and will be saved on the "
                     f"next change. ({last})")


class Table:
    """One data tab. path=None means "no survey open": the table is empty and read-only."""

    def __init__(self, tab: str, path: Path | None):
        self.tab = tab
        self.path = path
        self.header = schema.headers(tab)
        self.rows: list[dict] = []
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.dirty = False
        self.notice = ""
        self.load()

    # -- io ----------------------------------------------------------------
    def load(self):
        self.rows = []
        if self.path is None or not self.path.exists():
            return
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            try:
                hdr = next(reader)
            except StopIteration:
                return
            if hdr != self.header:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                bak = self.path.with_name(f"{self.path.name}.bak-{stamp}")
                if "RowID" in hdr:
                    # one of our own files from an earlier version: carry the data over by
                    # column name, keep a copy of the original
                    old_rows = [dict(zip(hdr, rec)) for rec in reader if any(rec)]
                    fh.close()
                    shutil.copy2(self.path, bak)
                    added = [h for h in self.header if h not in hdr]
                    dropped = [h for h in hdr if h not in self.header]
                    lost = [h for h in dropped if any(r.get(h) for r in old_rows)]
                    for r in old_rows:
                        row = {k: r.get(k, "") or "" for k in self.header}
                        row["RowID"] = row["RowID"] or uuid.uuid4().hex[:12]
                        self.rows.append(row)
                    atomic_write_csv(self.path, self.header, self.rows)
                    self.notice = (f"{self.path.name} was updated to this version's columns"
                                   + (f" (added {', '.join(added)})" if added else "")
                                   + (f"; the old {', '.join(lost)} column(s) are only in the backup" if lost else "")
                                   + f". A copy of the original is kept as {bak.name}.")
                    return
                fh.close()
                os.replace(self.path, bak)
                self.notice = (f"{self.path.name} had different columns from this version, so it was "
                               f"renamed to {bak.name} and the tab starts empty. Nothing was deleted.")
                return
            for rec in reader:
                if not any(rec):
                    continue
                row = {k: (rec[i] if i < len(rec) else "") for i, k in enumerate(self.header)}
                if not row.get("RowID"):
                    row["RowID"] = uuid.uuid4().hex[:12]
                self.rows.append(row)

    def save(self):
        if self.path is None:
            raise WriteError("No survey is open.")
        try:
            atomic_write_csv(self.path, self.header, self.rows)
            self.dirty = False
        except WriteError:
            self.dirty = True
            raise

    # -- helpers -------------------------------------------------------------
    def index_of(self, row_id: str) -> int:
        for i, r in enumerate(self.rows):
            if r["RowID"] == row_id:
                return i
        raise KeyError(row_id)

    def get(self, row_id: str) -> dict:
        return self.rows[self.index_of(row_id)]

    def _record(self, op):
        self.undo_stack.append(op)
        self.redo_stack.clear()

    # -- operations ------------------------------------------------------------
    def add(self, row: dict, index: int | None = None) -> dict:
        row = {k: str(row.get(k, "") if row.get(k) is not None else "") for k in self.header}
        row["RowID"] = row.get("RowID") or uuid.uuid4().hex[:12]
        if index is None:
            index = len(self.rows)
        self.rows.insert(index, row)
        self._record(("add", index, dict(row)))
        self.save()
        return row

    def replace(self, row_id: str, new_row: dict) -> dict:
        i = self.index_of(row_id)
        old = dict(self.rows[i])
        new = {k: str(new_row.get(k, "")) for k in self.header}
        new["RowID"] = row_id
        if new == old:
            return old
        self.rows[i] = new
        self._record(("edit", i, old, dict(new)))
        self.save()
        return new

    def delete(self, row_id: str):
        i = self.index_of(row_id)
        old = self.rows.pop(i)
        self._record(("delete", i, dict(old)))
        self.save()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        op = self.undo_stack.pop()
        self._apply_inverse(op)
        self.redo_stack.append(op)
        self.save()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        op = self.redo_stack.pop()
        self._apply(op)
        self.undo_stack.append(op)
        self.save()
        return True

    def _find(self, row_id):
        try:
            return self.index_of(row_id)
        except KeyError:
            return None

    def _apply(self, op):
        kind = op[0]
        if kind == "add":
            _, i, row = op
            self.rows.insert(min(i, len(self.rows)), dict(row))
        elif kind == "delete":
            _, i, row = op
            j = self._find(row["RowID"])
            if j is not None:
                self.rows.pop(j)
        elif kind == "edit":
            _, i, old, new = op
            j = self._find(new["RowID"])
            if j is not None:
                self.rows[j] = dict(new)

    def _apply_inverse(self, op):
        kind = op[0]
        if kind == "add":
            _, i, row = op
            j = self._find(row["RowID"])
            if j is not None:
                self.rows.pop(j)
        elif kind == "delete":
            _, i, row = op
            self.rows.insert(min(i, len(self.rows)), dict(row))
        elif kind == "edit":
            _, i, old, new = op
            j = self._find(old["RowID"])
            if j is not None:
                self.rows[j] = dict(old)

    def next_seq(self, key: str) -> int:
        n = 0
        for r in self.rows:
            try:
                n = max(n, int(float(r.get(key) or 0)))
            except ValueError:
                pass
        return n + 1

    def clear(self):
        self.rows = []
        self.undo_stack.clear()
        self.redo_stack.clear()
        if self.path is not None and self.path.exists():
            self.path.unlink()


class Track:
    """Append-only trackline CSV."""

    def __init__(self, path: Path | None):
        self.path = path
        self.points: list[dict] = []
        if path is not None and path.exists():
            with open(path, newline="", encoding="utf-8-sig") as fh:
                r = csv.DictReader(fh)
                if r.fieldnames == schema.TRACK_COLUMNS:
                    self.points = [dict(p) for p in r]
                else:
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    fh.close()
                    os.replace(path, path.with_name(f"{path.name}.bak-{stamp}"))

    def append(self, point: dict):
        if self.path is None:
            return
        new = not self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=schema.TRACK_COLUMNS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(point)
            fh.flush()
        self.points.append(point)

    def clear(self):
        self.points = []
        if self.path is not None and self.path.exists():
            self.path.unlink()


