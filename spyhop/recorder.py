"""Spyhop's core: ties config, tables, the track and the live vessel state together.

All edits come through here so values are parsed and validated in one place,
and computed fields (sighting position) stay in step.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import math
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import geo, schema, tzguess
from .config import Config
from .nmea import NmeaDecoder, RawLog, VesselState
import uuid

from .store import Table, Track, WriteError, atomic_write_csv, safe_name

log = logging.getLogger(__name__)


class ValueErrorMsg(ValueError):
    pass


def parse_time(s: str) -> datetime | None:
    """Read a stored time leniently: ISO 8601 with or without a zone, a trailing Z, or a space
    instead of the T (e.g. after editing a CSV in Excel). Times with no zone are taken as local."""
    s = (s or "").strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    for cand in (s, s.replace(" ", "T", 1)):
        try:
            t = datetime.fromisoformat(cand)
            return t if t.tzinfo else t.astimezone()
        except ValueError:
            continue
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).astimezone()
        except ValueError:
            continue
    return None


def _pdf_bytes(page: str, wait_ms: int = 3000) -> bytes:
    """A page printed to PDF by headless Chrome / Edge (see browser.py)."""
    import tempfile
    from .browser import html_to_pdf, PdfError
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = html_to_pdf(page, Path(tmp) / "page.pdf", wait_ms)
        except PdfError as e:
            raise ValueErrorMsg(str(e))
        return p.read_bytes()


class Recorder:
    def __init__(self, root: Path):
        self.cfg = Config(root)
        self.state = VesselState()
        self.decoder = NmeaDecoder(self.state)
        self.listeners: list = []
        self.notices: list[str] = list(self.cfg.notices)
        self.tables: dict[str, Table] = {}
        self.track: Track | None = None
        self.survey: dict | None = None
        self.pending_resume: str | None = None
        self._last_track_t = 0.0
        self.rawlog: RawLog | None = None
        # Tracking only runs for an open, active survey that someone has started or continued.
        if self.cfg.settings.get("tracking_enabled"):
            self.cfg.save_settings({"tracking_enabled": False})
        self._open_tables()
        cur = self.cfg.current_survey()
        if cur and self._survey_exists(cur["prefix"]):
            self._activate(cur["prefix"], meta=cur)
            if self.survey_active():
                # Spyhop was closed (or crashed) with this survey still running: ask before continuing
                self.pending_resume = self.survey["prefix"]
        elif cur:
            self.cfg.set_current_survey(None)

    # -- events ------------------------------------------------------------
    def emit(self, msg: dict):
        for fn in list(self.listeners):
            try:
                fn(msg)
            except Exception:
                pass

    def emit_tab(self, tab: str):
        t = self.tables[tab]
        self.emit({"type": "tab", "tab": tab, "rows": t.rows,
                   "can_undo": bool(t.undo_stack), "can_redo": bool(t.redo_stack)})

    # -- time ----------------------------------------------------------------
    def tz(self):
        """Survey clock (Settings → General → Clock): the computer's local time zone, UTC, a fixed UTC
        offset, or the zone guessed from the platform's position."""
        v = self.cfg.settings.get("timezone") or "local"
        if v == "UTC":
            return timezone.utc
        if v == "auto":
            name = self.clock_zone()
            z = tzguess.tzinfo_for(name) if name else None
            if z is not None:
                return z
        elif v.startswith("UTC"):
            z = tzguess.parse_offset(v)
            if z is not None:
                return z
        return datetime.now().astimezone().tzinfo

    def clock_zone(self) -> str | None:
        """The IANA zone for the platform's position (cached; remembered between sessions)."""
        if not hasattr(self, "_zone_guess"):
            self._zone_guess = tzguess.ZoneGuess()
            self._zone_guess.name = self.cfg.settings.get("clock_zone_last") or None
        st = self.state
        name = self._zone_guess.update(st.lat, st.lon) if getattr(st, "lat", None) is not None else self._zone_guess.name
        if name and name != self.cfg.settings.get("clock_zone_last"):
            self.cfg.settings["clock_zone_last"] = name
            try:
                self.cfg.save_settings()
            except OSError:
                pass
        return name

    def clock_info(self) -> dict:
        """What the clock is, for the window: {setting, zone (IANA name or offset), how, abbr, offset_min}."""
        v = self.cfg.settings.get("timezone") or "local"
        now = self.now()
        info = {"setting": v, "zone": None, "how": "", "offset_min": int(now.utcoffset().total_seconds() // 60),
                "abbr": now.tzname() or ""}
        if v == "auto":
            info["zone"] = self.clock_zone()
            info["how"] = self._zone_guess.how if getattr(self, "_zone_guess", None) and self._zone_guess.how else \
                ("last known position" if info["zone"] else "no position yet: the computer's clock")
            if info["zone"] and tzguess.tzinfo_for(info["zone"]) is None:
                info["zone"] = None             # not in this computer's zone database
        return info

    def now(self) -> datetime:
        return datetime.now(self.tz()).replace(microsecond=0)

    # -- surveys -------------------------------------------------------------
    SURVEY_FILES = ("sightings", "effort", "events", "track")
    NO_SURVEY = "No survey is open. Start a new survey or open one in the Survey tab."

    def _make_survey(self, name: str) -> dict:
        return {"name": name, "prefix": safe_name(name),
                "started": datetime.now().astimezone().isoformat(timespec="seconds"),
                "auto_tracking_done": True}

    def _path(self, tab: str) -> Path | None:
        if tab == "marks":
            # "Marks" were renamed Waypoints in 0.5.0: move an old marks.csv over once
            new, old = self.cfg.data_dir / "waypoints.csv", self.cfg.data_dir / "marks.csv"
            if old.exists() and not new.exists():
                try:
                    old.rename(new)
                    log.info("renamed %s to %s (Marks are now Waypoints)", old, new.name)
                except OSError as e:
                    log.warning("couldn't rename %s: %s", old, e)
                    return old
            return new
        if self.survey is None:
            return None
        return self.cfg.data_dir / f"{self.survey['prefix']}_{tab}.csv"


    # -- raw NMEA log --------------------------------------------------------
    def template_waypoints(self, rows: list[dict], remove_ids: list[str] = ()) -> list[str]:
        """Waypoints from a template: add these rows (no undo entry, as they didn't come from typing), and
        remove the ones with these RowIDs (restoring a backup). Returns the new rows' RowIDs."""
        t = self.tables["marks"]
        if not rows and not remove_ids:
            return []
        gone = set(remove_ids or ())
        if gone:
            t.rows = [r for r in t.rows if r["RowID"] not in gone]
        ids = []
        for r in rows:
            row = {k: str(r.get(k, "") or "") for k in t.header}
            row["RowID"] = uuid.uuid4().hex[:12]
            t.rows.append(row)
            ids.append(row["RowID"])
        t.undo_stack.clear()
        t.redo_stack.clear()
        t.save()
        self.emit_tab("marks")
        return ids

    def set_raw_logging(self, enabled: bool | None = None, timestamps: bool | None = None):
        upd = {}
        if enabled is not None:
            upd["nmea_log_enabled"] = bool(enabled)
        if timestamps is not None:
            upd["nmea_log_timestamps"] = bool(timestamps)
        if upd:
            self.cfg.save_settings(upd)
        self._raw_log_follow(force=True)
        return self.raw_log_status()

    def _raw_log_follow(self, force: bool = False):
        """(Re)start the raw log so it goes to the current data folder, named after the open survey."""
        on = bool(self.cfg.settings.get("nmea_log_enabled"))
        stem = self.survey["prefix"] if self.survey else "no-survey"
        folder = self.cfg.data_dir / "nmea_logs"
        ts = bool(self.cfg.settings.get("nmea_log_timestamps", True))
        cur = self.rawlog
        if cur and on and not force and cur.path.parent == folder and cur.path.name.startswith(stem + "_nmea_"):
            return
        if cur:
            cur.close()
        self.rawlog = RawLog(folder, stem, ts) if on else None
        self.decoder.raw_logger = self.rawlog.write if self.rawlog else None

    def raw_log_status(self) -> dict:
        st = {"on": False, "folder": str(self.cfg.data_dir / "nmea_logs"),
              "timestamps": bool(self.cfg.settings.get("nmea_log_timestamps", True))}
        if self.rawlog:
            st.update(self.rawlog.status())
        return st

    def _open_tables(self):
        self.tables = {}
        for tab in schema.TABS:
            t = Table(tab, self._path(tab))
            if t.notice:
                self.notices.append(t.notice)
            self.tables[tab] = t
        self.track = Track(self.cfg.data_dir / f"{self.survey['prefix']}_track.csv" if self.survey else None)
        self._raw_log_follow()
        self._load_instruments()

    def _survey_exists(self, prefix: str) -> bool:
        # explicit paths, not glob(): survey names may contain [ ] * etc.
        return any((self.cfg.data_dir / f"{prefix}_{t}.csv").exists() for t in self.SURVEY_FILES)

    # state of the open survey, from its Effort table
    def survey_ended(self) -> bool:
        rows = self.tables["effort"].rows if self.survey else []
        return bool(rows) and rows[-1].get("Effort") == "End"

    def survey_active(self) -> bool:
        return self.survey is not None and not self.survey_ended()

    def tracking_on(self) -> bool:
        return bool(self.cfg.settings.get("tracking_enabled"))

    def _set_tracking(self, on: bool):
        if self.tracking_on() != on:
            self.cfg.save_settings({"tracking_enabled": on})
            self.emit({"type": "settings", "settings": self.cfg.settings})
        if on:
            self._last_track_t = 0.0

    # -- survey details (platform, organization, …) ------------------------------------
    def _meta_path(self, prefix: str | None = None) -> Path | None:
        prefix = prefix or (self.survey["prefix"] if self.survey else None)
        return self.cfg.data_dir / f"{prefix}_metadata.csv" if prefix else None

    def read_meta(self, prefix: str | None = None) -> dict:
        import csv as _csv
        meta = {k: "" for k, _, _ in schema.SURVEY_META}
        p = self._meta_path(prefix)
        if p and p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                for r in _csv.DictReader(fh):
                    if r.get("field") in meta:
                        meta[r["field"]] = r.get("value", "") or ""
        return meta

    def _write_meta(self, meta: dict):
        from . import __version__
        import csv as _csv
        created = __version__
        p = self._meta_path()
        if p and p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                for r in _csv.DictReader(fh):
                    if r.get("field") == "spyhop_version_created" and r.get("value"):
                        created = r["value"]
        rows = [{"field": k, "label": label, "value": meta.get(k, "")} for k, label, _ in schema.SURVEY_META]
        rows += [{"field": "spyhop_version_created", "label": "Started with Spyhop version", "value": created},
                 {"field": "spyhop_version_saved", "label": "Details last saved with Spyhop version", "value": __version__}]
        atomic_write_csv(p, ["field", "label", "value"], rows)

    def _clean_meta(self, updates: dict, base: dict) -> dict:
        """Validate survey-detail updates on top of base; raise ValueErrorMsg if any are bad."""
        meta = dict(base)
        for k, v in (updates or {}).items():
            if k not in meta:
                continue
            v = ("" if v is None else str(v)).strip().replace("\n", " ")
            if k == "platform_type" and v:
                match = next((o for o in schema.FIXED_LISTS["platform_type"] if o.lower() == v.lower()), None)
                if match is None:
                    raise ValueErrorMsg("Platform type must be Vessel, Plane, Land or Other.")
                v = match
            if k == "chief_scientist_email" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise ValueErrorMsg(f"“{v}” doesn't look like an email address.")
            meta[k] = v
        return meta

    def set_meta(self, updates: dict) -> dict:
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        meta = self._clean_meta(updates, self.read_meta())
        self._write_meta(meta)
        self.cfg.save_settings({"last_meta": meta})
        self.emit({"type": "reload"})
        return meta

    def survey_info(self) -> dict | None:
        if self.survey is None:
            return None
        rows = self.tables["effort"].rows
        start = rows[0]["DateTime"] if rows and rows[0].get("Effort") == "Start" else ""
        end = rows[-1]["DateTime"] if self.survey_ended() else ""
        return {**self.survey, "active": self.survey_active(), "ended": self.survey_ended(),
                "start_time": start, "end_time": end, "tracking": self.tracking_on(),
                "meta": self.read_meta()}

    def _activate(self, prefix: str, meta: dict | None = None):
        """Make an existing survey on disk the open survey (tracking is left off)."""
        self.survey = {"name": prefix, "prefix": prefix, "started": "", "auto_tracking_done": True}
        for k in ("name", "started"):
            if meta and meta.get(k):
                self.survey[k] = meta[k]
        self.cfg.set_current_survey(self.survey)
        self._open_tables()
        self._ensure_start_row()

    def _ensure_start_row(self):
        """Every survey's Effort table begins with a Start row. Surveys made before
        Start/End existed get one, timed at their earliest record."""
        t = self.tables["effort"]
        if t.rows and t.rows[0].get("Effort") == "Start":
            return
        times = []
        for tab in ("effort", "sightings", "events"):
            times += [r["DateTime"] for r in self.tables[tab].rows if r.get("DateTime")]
        times += [p["DateTime"] for p in self.track.points if p.get("DateTime")]
        when = min(times, key=self._ts) if times else self.now().isoformat(timespec="seconds")
        first = t.rows[0] if t.rows else {}
        pt = self.track.points[0] if self.track.points else {}
        row = {k: "" for k in t.header}
        row.update(RowID=uuid.uuid4().hex[:12], DateTime=when, Effort="Start",
                   VesLat=first.get("VesLat") or pt.get("Lat", ""),
                   VesLon=first.get("VesLon") or pt.get("Lon", ""),
                   Notes="Start row added automatically (survey made before Start/End existed)")
        t.rows.insert(0, row)
        try:
            t.save()
        except WriteError as e:
            self.notices.append(str(e))
            return
        self.notices.append(f"Added a Start row at the top of the Effort table of “{self.survey['prefix']}” "
                            "(timed at its earliest record) — every survey now begins with one.")

    @staticmethod
    def _ts(iso: str) -> float:
        try:
            return datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return float("inf")

    def start_survey(self, name: str, meta: dict | None = None):
        name = (name or "").strip()
        if not name:
            raise ValueErrorMsg("Please give the survey a name.")
        if self.survey_active():
            raise ValueErrorMsg(f"“{self.survey['prefix']}” is still active. End or close it first.")
        base = {k: "" for k, _, _ in schema.SURVEY_META}
        base.update({k: v for k, v in (self.cfg.settings.get("last_meta") or {}).items() if k in base})
        meta = self._clean_meta(meta or {}, base)        # check the details before creating anything
        survey = self._make_survey(name)
        if self._survey_exists(survey["prefix"]):
            raise ValueErrorMsg(f"A survey called “{survey['prefix']}” already exists. "
                                "Choose another name, or open it from the list in the Survey tab.")
        self.close_survey()                           # an ended survey may still be open
        self.survey = survey
        self.pending_resume = None
        self.cfg.set_current_survey(survey)
        self._open_tables()
        self.new_row("effort", {"Effort": "Start"}, _allow_start=True)
        self.tables["effort"].undo_stack.clear()        # the Start row can't be undone
        self._write_meta(meta)
        self.cfg.save_settings({"last_meta": meta})
        self._set_tracking(True)
        self._record_point("Start")                   # the track's first point is marked Start
        self.emit({"type": "reload"})

    def end_survey(self):
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        if self.survey_ended():
            raise ValueErrorMsg("This survey has already ended.")
        was_tracking = self.tracking_on()
        self.new_row("effort", {"Effort": "End"})
        if was_tracking:
            self._record_point("End")                 # the track's last point is marked End
        self._set_tracking(False)
        self.emit({"type": "reload"})

    def close_survey(self):
        if self.survey is None:
            return
        for t in self.tables.values():
            if t.dirty:
                try:
                    t.save()
                except WriteError as e:
                    raise ValueErrorMsg(f"Not closed — {e}")
        self._set_tracking(False)
        self.survey = None
        self.pending_resume = None
        self.cfg.set_current_survey(None)
        self._open_tables()
        self.emit({"type": "reload"})

    def open_survey(self, prefix: str, resume: bool = False):
        if not self._survey_exists(prefix):
            raise ValueErrorMsg("No files found for that survey.")
        if self.survey is None or prefix != self.survey["prefix"]:
            self.close_survey()
            self._activate(prefix)
        self.pending_resume = None
        self._set_tracking(bool(resume and self.survey_active()))
        self.emit({"type": "reload"})

    def answer_resume(self, action: str):
        """Reply to the start-up question about a survey left active."""
        self.pending_resume = None
        if action == "continue" and self.survey_active():
            self._set_tracking(True)
        elif action == "close":
            self.close_survey()
        self.emit({"type": "reload"})

    def set_data_dir(self, path: str):
        self.close_survey()
        self.cfg.set_data_dir(path)
        self._open_tables()          # waypoints.csv lives in the data folder
        self.emit({"type": "reload"})

    @staticmethod
    def _read_effort_bounds(p: Path) -> tuple[str, str]:
        """(start time, end time) from an Effort CSV."""
        import csv as _csv
        try:
            with open(p, newline="", encoding="utf-8-sig") as fh:
                rows = [r for r in _csv.DictReader(fh) if any(r.values())]
        except OSError:
            return "", ""
        if not rows:
            return "", ""
        end = rows[-1].get("DateTime", "") if rows[-1].get("Effort") == "End" else ""
        return rows[0].get("DateTime", ""), end

    def list_surveys(self) -> list[dict]:
        """Surveys in the data folder, most recently changed first."""
        found: dict[str, dict] = {}
        try:
            files = list(self.cfg.data_dir.iterdir())
        except OSError:
            files = []
        for p in files:
            m = re.match(r"^(.*)_(sightings|effort|events|track)\.csv$", p.name)
            if not m:
                continue
            s = found.setdefault(m.group(1), {"prefix": m.group(1), "modified": 0.0, "sightings": 0,
                                              "start_time": "", "end_time": ""})
            s["modified"] = max(s["modified"], p.stat().st_mtime)
            if m.group(2) == "sightings":
                with open(p, encoding="utf-8-sig") as fh:
                    s["sightings"] = max(0, sum(1 for line in fh if line.strip()) - 1)
            elif m.group(2) == "effort":
                s["start_time"], s["end_time"] = self._read_effort_bounds(p)
        cur = self.survey["prefix"] if self.survey else None
        for s in found.values():
            s["current"] = s["prefix"] == cur
            s["active"] = not s["end_time"]
            s["modified_iso"] = datetime.fromtimestamp(s["modified"]).astimezone().isoformat(timespec="seconds")
        return sorted(found.values(), key=lambda s: s["modified"], reverse=True)

    def clear_survey(self):
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        for tab, t in self.tables.items():
            if tab != "marks":
                t.clear()
        self.track.clear()
        ip = self._inst_path()
        if ip and ip.exists():
            ip.unlink()
        self.inst_hist = {}
        mp = self._meta_path()
        if mp and mp.exists():
            mp.unlink()
        self.close_survey()

    # -- instrument history (Tools → Instruments plots) ---------------------------------
    INST_SAMPLE_S = 5            # one value per reading every this many seconds
    INST_COLUMNS = ["DateTime", "Key", "Label", "Unit", "Value"]

    def _inst_path(self, prefix: str | None = None) -> Path | None:
        prefix = prefix or (self.survey["prefix"] if self.survey else None)
        return self.cfg.data_dir / f"{prefix}_instruments.csv" if prefix else None

    def _load_instruments(self):
        """history: key -> {"label", "unit", "points": [(epoch seconds, value)]}, from the survey's file."""
        self.inst_hist: dict[str, dict] = {}
        p = self._inst_path()
        if not p or not p.exists():
            return
        try:
            with open(p, newline="", encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    t = parse_time(r.get("DateTime", ""))
                    try:
                        v = float(r.get("Value", ""))
                    except ValueError:
                        continue
                    if t is None:
                        continue
                    h = self.inst_hist.setdefault(r["Key"], {"label": r.get("Label", r["Key"]), "unit": r.get("Unit", ""), "points": []})
                    h["points"].append((t.timestamp(), v))
        except OSError as e:
            log.warning("couldn't read %s: %s", p, e)

    def sample_instruments(self):
        """Save the current numeric readings (called every INST_SAMPLE_S seconds while a survey is active)."""
        if not self.survey_active():
            return
        p = self._inst_path()
        now = time.time()
        stamp = self.now().isoformat(timespec="seconds")
        rows = []
        for k, r in self.decoder.inst.items():
            v = r.get("value")
            if not isinstance(v, (int, float)) or isinstance(v, bool) or now - r.get("t", 0) > 2 * self.INST_SAMPLE_S:
                continue
            h = self.inst_hist.setdefault(k, {"label": r["label"], "unit": r["unit"], "points": []})
            h["points"].append((now, float(v)))
            rows.append([stamp, k, r["label"], r["unit"], v])
        if not rows:
            return
        try:
            new = not p.exists()
            with open(p, "a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(self.INST_COLUMNS)
                w.writerows(rows)
        except OSError as e:
            log.warning("couldn't save instrument readings: %s", e)

    def instrument_history(self, key: str, max_points: int = 2000) -> dict:
        h = self.inst_hist.get(key)
        if not h:
            r = self.decoder.inst.get(key, {})
            return {"key": key, "label": r.get("label", key), "unit": r.get("unit", ""), "points": [], "start": self._survey_start_epoch()}
        pts = h["points"]
        angle = h["unit"].startswith("°") and h["unit"] != "°C"
        if len(pts) > max_points:
            # thin to max_points buckets: the mean (angles: the first value, as means of angles mislead)
            n = len(pts) / max_points
            out = []
            for b in range(max_points):
                chunk = pts[int(b * n):int((b + 1) * n)]
                if chunk:
                    out.append(chunk[0] if angle else (chunk[len(chunk) // 2][0], sum(v for _, v in chunk) / len(chunk)))
            pts = out
        return {"key": key, "label": h["label"], "unit": h["unit"], "angle": angle, "start": self._survey_start_epoch(),
                "points": [[round(t * 1000), v] for t, v in pts], "samples": len(h["points"])}

    def _survey_start_epoch(self) -> float | None:
        rows = self.tables["effort"].rows if self.survey else []
        t = parse_time(rows[0].get("DateTime", "")) if rows else None
        return t.timestamp() * 1000 if t else None

    # -- live position ---------------------------------------------------------
    def vessel(self) -> dict:
        d = self.state.snapshot()
        d["mag_var"] = self.variation_at(d["lat"], d["lon"]) if d["lat"] is not None else None
        if self.cfg.settings.get("timezone") == "auto":
            d["clock"] = self.clock_info()
        return d

    def variation_at(self, lat, lon) -> float | None:
        setting = self.cfg.settings.get("mag_variation", "auto")
        if setting not in ("auto", "", None):
            try:
                return float(setting)
            except (TypeError, ValueError):
                pass
        v = geo.magnetic_variation(lat, lon) if lat is not None else None
        if v is None:
            v = self.state.variation
        return v

    # -- parsing ----------------------------------------------------------------
    def list_values(self, name: str) -> list[str] | None:
        if name in schema.FIXED_LISTS:
            return schema.FIXED_LISTS[name]
        if name in self.cfg.lists:
            return [r["name"] for r in self.cfg.lists[name]]
        return None

    def parse_value(self, tab: str, key: str, raw, row: dict) -> tuple[str, str | None]:
        """Return (stored_value, warning)."""
        c = schema.column(tab, key)
        if c is None:
            raise ValueErrorMsg(f"Unknown column {key}")
        s = "" if raw is None else str(raw).strip()
        t = c["type"]
        if s == "":
            return "", None
        if t in ("lat", "lon"):
            try:
                ref = self._reference_coord(tab, row, t == "lat")
                v = geo.parse_coord(s, t == "lat", default_negative=ref is not None and ref < 0)
                return f"{v:.6f}", None
            except ValueError as e:
                raise ValueErrorMsg(f"{c['label']}: {e}")
        if t in ("int", "seq"):
            try:
                v = float(s)
            except ValueError:
                raise ValueErrorMsg(f"{c['label']} must be a whole number")
            if v != int(v) or v < 0:
                raise ValueErrorMsg(f"{c['label']} must be a whole number ≥ 0")
            return str(int(v)), None
        if t == "float":
            try:
                v = float(s.replace(",", "."))
            except ValueError:
                raise ValueErrorMsg(f"{c['label']} must be a number")
            if key in ("Bearing", "VesHdg"):
                # negative bearings count back from 360 (−10 = 350), handy for relative bearings to port
                if not -360 <= v <= 360:
                    raise ValueErrorMsg(f"{c['label']} must be between −360 and 360 (−10 is the same as 350)")
                v = round(v % 360, 6) % 360
            if key == "Distance" and v < 0:
                raise ValueErrorMsg("Distance can't be negative")
            return (f"{v:g}"), None
        if t == "bool":
            return ("1" if s.lower() in ("1", "true", "yes", "y", "on", "x") else "0"), None
        if t == "datetime":
            return self.parse_datetime(s, row.get(key, "")), None
        if t == "choice" and c["list"] == "colors" and re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", s):
            return s.lower(), None
        if t == "choice":
            opts = self.list_values(c["list"]) or []
            for o in opts:
                if o.lower() == s.lower():
                    return o, None
            if c["list"] in schema.FIXED_LISTS:
                raise ValueErrorMsg(f"{c['label']}: choose one of {', '.join(opts)}")
            return s, f"'{s}' isn't in {c['list']}.csv — saved anyway."
        if t == "multi":
            opts = self.list_values(c["list"]) or []
            out, unknown = [], []
            for part in re.split(r"[;,|]", s):
                p = part.strip()
                if not p:
                    continue
                match = next((o for o in opts if o.lower() == p.lower()), None)
                if match is None:
                    unknown.append(p)
                    match = p
                if match not in out:
                    out.append(match)
            warn = f"Not in {c['list']}.csv: {', '.join(unknown)} — saved anyway." if unknown else None
            return "; ".join(out), warn
        return s.replace("\r", " ").replace("\n", " "), None

    def _reference_coord(self, tab: str, row: dict, is_lat: bool):
        """A nearby coordinate (row's vessel position, else live GPS) used to pick
        the hemisphere when someone types a position without N/S/E/W."""
        keys = ("VesLat", "Lat", "SigLat") if is_lat else ("VesLon", "Lon", "SigLon")
        for k in keys:
            try:
                return float(row.get(k) or "x")
            except ValueError:
                continue
        v = self.state.lat if is_lat else self.state.lon
        return v

    def parse_datetime(self, s: str, existing: str) -> str:
        tz = self.tz()
        s = s.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass
        m = re.fullmatch(r"(\d{1,2})[:.]?(\d{2})(?:[:.]?(\d{2}))?", s)
        if m:
            h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
            if h > 23 or mi > 59 or se > 59:
                raise ValueErrorMsg("Time must be HH:MM or HH:MM:SS")
            base = None
            if existing:
                try:
                    base = datetime.fromisoformat(existing).astimezone(tz)
                except ValueError:
                    base = None
            base = base or self.now()
            return base.replace(hour=h, minute=mi, second=se).isoformat(timespec="seconds")
        raise ValueErrorMsg("Time must be HH:MM[:SS] or YYYY-MM-DD HH:MM[:SS]")

    # -- computed fields -----------------------------------------------------------
    def compute(self, tab: str, row: dict, changed: set[str], old: dict | None = None) -> list[str]:
        warnings = []
        if tab == "sightings":
            keys = {"Bearing", "BrgRef", "Distance", "DistUnit", "VesLat", "VesLon", "VesHdg"}
            b, d = row.get("Bearing", ""), row.get("Distance", "")
            if b == "" or d == "":
                # No bearing/distance: the animal is taken to be at the vessel, unless
                # someone typed (or picked on the map) the animal's position themselves.
                if changed & {"SigLat", "SigLon"}:
                    return warnings
                follows = (old is None or not old.get("SigLat")
                           or (old.get("SigLat") == old.get("VesLat") and old.get("SigLon") == old.get("VesLon"))
                           or bool(changed & {"Bearing", "Distance"}))
                if follows:
                    row["SigLat"], row["SigLon"] = row.get("VesLat", ""), row.get("VesLon", "")
                return warnings
            if changed & keys:
                try:
                    lat, lon = float(row["VesLat"]), float(row["VesLon"])
                except (TypeError, ValueError):
                    warnings.append("No vessel position on this row, so the animal's position "
                                    "can't be calculated.")
                    return warnings
                hdg = None
                try:
                    hdg = float(row.get("VesHdg") or "nan")
                    hdg = None if math.isnan(hdg) else hdg
                except ValueError:
                    pass
                ref = row.get("BrgRef") or self.cfg.settings.get("bearing_reference", "M")
                var = self.variation_at(lat, lon) if ref == "M" else None
                true_b = geo.to_true_bearing(float(b), ref, hdg, var)
                if true_b is None:
                    warnings.append("Can't convert the bearing to true: " + (
                        "no magnetic variation available (set it in Settings)" if ref == "M"
                        else "no vessel heading on this row"))
                    return warnings
                unit = row.get("DistUnit") or self.cfg.settings.get("distance_unit", "nm")
                slat, slon = geo.destination(lat, lon, true_b, geo.to_metres(float(d), unit))
                row["SigLat"], row["SigLon"] = f"{slat:.6f}", f"{slon:.6f}"
        return warnings

    def _fill_bearing_distance(self, row: dict):
        """Animal position given directly (e.g. picked on the map): fill in the
        bearing (in the row's reference) and distance from the vessel to it."""
        try:
            vlat, vlon = float(row["VesLat"]), float(row["VesLon"])
            slat, slon = float(row["SigLat"]), float(row["SigLon"])
        except (KeyError, TypeError, ValueError):
            return
        true_b = geo.initial_bearing(vlat, vlon, slat, slon)
        ref = row.get("BrgRef") or "T"
        if ref == "M":
            var = self.variation_at(vlat, vlon)
            if var is None:
                ref, b = "T", true_b
            else:
                b = true_b - var
        elif ref == "R":
            try:
                b = true_b - float(row.get("VesHdg") or "x")
            except ValueError:
                ref, b = "T", true_b
        else:
            b = true_b
        unit = row.get("DistUnit") or "nm"
        d = geo.haversine_m(vlat, vlon, slat, slon) / geo.UNIT_TO_M.get(unit, 1852.0)
        row["BrgRef"] = ref
        row["Bearing"] = f"{b % 360:.0f}"
        row["Distance"] = f"{d:.3g}" if d < 100 else f"{d:.0f}"

    # -- row operations --------------------------------------------------------------
    def table(self, tab: str) -> Table:
        if tab not in self.tables:
            raise ValueErrorMsg(f"Unknown tab {tab}")
        return self.tables[tab]

    def _write(self, fn):
        try:
            return fn()
        except WriteError as e:
            self.emit({"type": "notice", "level": "error", "text": str(e)})
            return None

    def _require_survey(self, tab: str):
        if tab != "marks" and self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)

    def _check_effort_value(self, t: Table, index: int, value: str, adding: bool):
        n = len(t.rows) + (1 if adding else 0)
        if index == 0 and value != "Start":
            raise ValueErrorMsg("The first Effort row must be Start — it marks when the survey began.")
        if value == "Start" and index != 0:
            raise ValueErrorMsg("Only the first Effort row can be Start.")
        if value == "End" and index != n - 1:
            raise ValueErrorMsg("Only the last Effort row can be End. "
                                "To end the survey, use End survey in the Survey tab.")

    def new_row(self, tab: str, prefill: dict | None = None, lat=None, lon=None, _allow_start=False) -> dict:
        self._require_survey(tab)
        if tab != "marks" and self.survey_ended():
            raise ValueErrorMsg("This survey has ended, so no rows can be added. To continue it, "
                                "delete its End row in the Effort tab (or Undo).")
        t = self.table(tab)
        spec = schema.TABS[tab]
        row = {c["key"]: c["default"] for c in spec["columns"]}
        v = self.vessel()
        has_fix = v["has_fix"]
        warnings = []
        if tab == "effort" and t.rows:
            prev = t.rows[-1]
            for c in spec["columns"]:
                if c["copy"] and c["type"] != "id":
                    row[c["key"]] = prev.get(c["key"], "")
            if row.get("Effort") not in ("ON", "OFF"):
                row["Effort"] = ""          # after Start, choose ON or OFF
        if tab == "effort" and not t.rows:
            row["Effort"] = "Start"
        row["DateTime"] = self.now().isoformat(timespec="seconds")
        pos_keys = {"sightings": ("VesLat", "VesLon"),
                    "effort": ("VesLat", "VesLon"), "events": ("Lat", "Lon"),
                    "marks": ("Lat", "Lon")}[tab]
        if lat is not None and lon is not None:
            row[pos_keys[0]], row[pos_keys[1]] = f"{float(lat):.6f}", f"{float(lon):.6f}"
        elif has_fix:
            row[pos_keys[0]], row[pos_keys[1]] = f"{v['lat']:.6f}", f"{v['lon']:.6f}"
        else:
            warnings.append("No GPS fix — position left blank.")
        if "VesHdg" in row and has_fix and v.get("best_heading") is not None:
            row["VesHdg"] = f"{v['best_heading']:.0f}"
        if "BrgRef" in row:
            row["BrgRef"] = self.cfg.settings.get("bearing_reference", "M")
        if "DistUnit" in row:
            row["DistUnit"] = self.cfg.settings.get("distance_unit", "nm")
        if spec.get("seq"):
            row[spec["seq"]] = str(t.next_seq(spec["seq"]))
        if tab == "marks":
            row["Name"] = f"WP{len(t.rows) + 1}"
        changed = set()
        for k, raw in (prefill or {}).items():
            if schema.column(tab, k) is None:
                continue
            val, w = self.parse_value(tab, k, raw, row)
            row[k] = val
            changed.add(k)
            if w:
                warnings.append(w)
        if tab == "sightings" and {"SigLat", "SigLon"} <= changed and not row.get("Bearing"):
            self._fill_bearing_distance(row)
        warnings += self.compute(tab, row, changed)
        if tab == "effort":
            if row.get("Effort") == "Start" and t.rows and not _allow_start:
                raise ValueErrorMsg("Only the first Effort row can be Start.")
            self._check_effort_value(t, len(t.rows), row.get("Effort", ""), adding=True)
        added = self._write(lambda: t.add(row))
        if tab == "effort" and row.get("Effort") == "End":
            self._set_tracking(False)
        if tab == "effort" and row.get("Effort") == "ON":
            self._auto_tracking()
        self.emit_tab(tab)
        return {"row": added or row, "warnings": warnings}

    def toggle_effort(self) -> dict:
        self._require_survey("effort")
        t = self.table("effort")
        last = t.rows[-1].get("Effort") if t.rows else ""
        return self.new_row("effort", {"Effort": "OFF" if last == "ON" else "ON"})

    def edit(self, tab: str, row_id: str, updates: dict) -> dict:
        self._require_survey(tab)
        t = self.table(tab)
        try:
            row = dict(t.get(row_id))
        except KeyError:
            raise ValueErrorMsg("That row no longer exists.")
        warnings = []
        changed = set()
        for k, raw in updates.items():
            if k == "RowID":
                continue
            val, w = self.parse_value(tab, k, raw, row)
            if w:
                warnings.append(w)
            if row.get(k, "") != val:
                row[k] = val
                changed.add(k)
        warnings += self.compute(tab, row, changed, old=t.get(row_id))
        was_ended = tab == "effort" and self.survey_ended()
        if tab == "effort" and "Effort" in changed:
            self._check_effort_value(t, t.index_of(row_id), row.get("Effort", ""), adding=False)
        new = self._write(lambda: t.replace(row_id, row))
        if tab == "effort" and "Effort" in changed and row.get("Effort") == "End":
            self._set_tracking(False)
        if tab == "effort" and was_ended != self.survey_ended():
            self.emit({"type": "reload"})
        if tab == "effort" and "Effort" in changed and row.get("Effort") == "ON":
            self._auto_tracking()
        self.emit_tab(tab)
        return {"row": new or row, "warnings": warnings}

    def delete(self, tab: str, row_id: str):
        self._require_survey(tab)
        t = self.table(tab)
        if tab == "effort" and t.rows and t.rows[0]["RowID"] == row_id:
            raise ValueErrorMsg("The Start row can't be deleted — it marks when the survey began.")
        was_ended = tab == "effort" and self.survey_ended()
        self._write(lambda: t.delete(row_id))
        self.emit_tab(tab)
        if was_ended and not self.survey_ended():
            self.emit({"type": "reload"})

    def _undo_redo(self, tab: str, fn: str) -> bool:
        self._require_survey(tab)
        t = self.table(tab)
        before = self.survey_ended()
        rows_before = [dict(r) for r in t.rows]
        undo_before, redo_before = list(t.undo_stack), list(t.redo_stack)
        ok = self._write(lambda: getattr(t, fn)())
        if tab == "effort" and ok and (not t.rows or t.rows[0].get("Effort") != "Start"):
            # never let undo/redo remove or change the Start row
            t.rows, t.undo_stack, t.redo_stack = rows_before, undo_before, redo_before
            self._write(t.save)
            self.emit_tab(tab)
            raise ValueErrorMsg("That would remove the Start row, which every survey needs.")
        if tab == "effort" and self.survey_ended() and not before:
            self._set_tracking(False)
        self.emit_tab(tab)
        if tab == "effort" and before != self.survey_ended():
            self.emit({"type": "reload"})
        return bool(ok)

    def undo(self, tab: str) -> bool:
        return self._undo_redo(tab, "undo")

    def redo(self, tab: str) -> bool:
        return self._undo_redo(tab, "redo")

    def _auto_tracking(self):
        if self.survey and not self.survey.get("auto_tracking_done"):
            self.survey["auto_tracking_done"] = True
            self.cfg.set_current_survey(self.survey)
            if not self.cfg.settings.get("tracking_enabled"):
                self.cfg.save_settings({"tracking_enabled": True})
                self.emit({"type": "settings", "settings": self.cfg.settings})
                self.emit({"type": "notice", "level": "info",
                           "text": "Effort is ON — internal tracking switched on."})

    # -- effort / track ---------------------------------------------------------------
    def effort_intervals(self) -> list[tuple[datetime, datetime | None, str]]:
        rows = []
        for r in self.tables["effort"].rows:
            t = parse_time(r.get("DateTime", ""))
            if t is not None:
                rows.append((t, r.get("Effort", "")))
        rows.sort(key=lambda x: x[0])
        out = []
        for i, (t0, st) in enumerate(rows):
            t1 = rows[i + 1][0] if i + 1 < len(rows) else None
            out.append((t0, t1, st))
        return out

    def effort_at(self, when: datetime) -> str:
        state = ""
        for t0, t1, st in self.effort_intervals():
            if t0 <= when:
                state = st
            else:
                break
        return state

    def tick_tracker(self):
        s = self.cfg.settings
        if not s.get("tracking_enabled") or not self.survey_active():
            return
        interval = max(1, min(300, int(s.get("tracking_interval", 10) or 10)))
        now = time.time()
        if now - self._last_track_t < interval:
            return
        self._record_point()

    def _track_state(self, when: datetime) -> str:
        """Effort state in force at a time: Start, ON, OFF, End or ERROR (OFF if unknown)."""
        st = self.effort_at(when)
        return st if st in ("Start", "ON", "OFF", "End", "ERROR") else "OFF"

    # -- trackline breaks (QC → Fix) ----------------------------------------------------
    def insert_track_break(self, t0_iso: str, t1_iso: str) -> dict:
        """Mark a GPS jump or loss between two track points: an ERROR row in the Effort table at
        the last good point (t0), and, unless an Effort row already follows within the break, a row
        at t1 that puts back the effort and conditions in force before it. Both are placed in
        time order. Off-effort time and distance then leave the break out."""
        self._require_survey("effort")
        t0, t1 = parse_time(t0_iso), parse_time(t1_iso)
        if t0 is None or t1 is None or t1 <= t0:
            raise ValueErrorMsg("That trackline break has no valid start and end time.")
        t = self.tables["effort"]
        timed = [(parse_time(r.get("DateTime", "")), i, r) for i, r in enumerate(t.rows)]
        before = [x for x in timed if x[0] is not None and x[0] <= t0]
        if not before:
            raise ValueErrorMsg("The break is before the survey's Start row.")
        state_row = max(before, key=lambda x: (x[0], x[1]))[2]
        st = state_row.get("Effort", "")
        if st == "End":
            raise ValueErrorMsg("The break is after the survey's End row.")
        if st == "ERROR" or any(x[0] is not None and t0 <= x[0] < t1 and x[2].get("Effort") == "ERROR" for x in timed):
            raise ValueErrorMsg("That break is already marked with an ERROR row.")

        def nearest_point(when):
            best, bd = None, None
            for p in self.track.points if self.track else []:
                pt = parse_time(p.get("DateTime", ""))
                if pt is None:
                    continue
                d = abs((pt - when).total_seconds())
                if bd is None or d < bd:
                    best, bd = p, d
            return best if bd is not None and bd <= 60 else None

        spec = schema.TABS["effort"]
        tz = self.tz()

        def make(when, effort, note):
            row = {c["key"]: c["default"] for c in spec["columns"]}
            for c in spec["columns"]:
                if c["copy"] and c["type"] != "id":
                    row[c["key"]] = state_row.get(c["key"], "")
            row["Effort"] = effort
            row["DateTime"] = when.astimezone(tz).isoformat(timespec="seconds")
            p = nearest_point(when)
            if p:
                row["VesLat"], row["VesLon"] = p.get("Lat", ""), p.get("Lon", "")
            row["Notes"] = note
            return row

        def index_for(when):
            for i, r in enumerate(t.rows):
                rt = parse_time(r.get("DateTime", ""))
                if rt is not None and rt > when and i > 0:
                    return i
            n = len(t.rows)
            return n - 1 if n and t.rows[-1].get("Effort") == "End" else n

        hhmm = lambda x: x.astimezone(tz).strftime("%H:%M:%S")
        added = []
        err = make(t0, "ERROR", f"Trackline break (GPS jump or loss) until {hhmm(t1)}, added by Quality Control → Fix.")
        r = self._write(lambda: t.add(err, index_for(t0)))
        if r:
            added.append(r)
        follows = any(x[0] is not None and t0 < x[0] <= t1 for x in timed)
        if not follows:
            back = make(t1, st if st in ("ON", "OFF") else "", f"Back after the trackline break from {hhmm(t0)}.")
            r = self._write(lambda: t.add(back, index_for(t1)))
            if r:
                added.append(r)
        self.emit_tab("effort")
        return {"added": len(added), "rows": added}

    def _record_point(self, effort: str | None = None):
        """Append one track point at the current GPS position."""
        v = self.vessel()
        if not v["has_fix"] or self.track is None or self.track.path is None:
            return
        self._last_track_t = time.time()
        when = self.now()
        p = {"DateTime": when.isoformat(timespec="seconds"), "Lat": f"{v['lat']:.6f}",
             "Lon": f"{v['lon']:.6f}",
             "SOG": "" if v["sog"] is None else f"{v['sog']:.1f}",
             "COG": "" if v["cog"] is None else f"{v['cog']:.0f}",
             "Effort": effort or self._track_state(when)}
        try:
            self.track.append(p)
        except OSError as e:
            self.emit({"type": "notice", "level": "error", "text": f"Track not saved: {e}"})
            return
        self.emit({"type": "track", "point": p})

    # -- export -------------------------------------------------------------------
    EXPORT_FORMATS = {
        "csv": "Separate CSV files",
        "merged": "Merged CSV file",
        "gpx": "GPX file",
        "geojson": "GeoJSON file",
        "html": "Summary report",
    }
    REPORT_AS = ("html", "pdf")

    def _export_track(self) -> list[dict]:
        """Track points with Effort (Start / ON / OFF / End) recomputed from the final Effort table."""
        pts = []
        row_times = {t0 for t0, _, _ in self.effort_intervals()}
        for p in self.track.points:
            q = dict(p)
            try:
                when = datetime.fromisoformat(p["DateTime"])
                # a point in the same second as an effort row keeps the state recorded at the time
                if not (when in row_times and q.get("Effort") in ("Start", "ON", "OFF", "End")):
                    q["Effort"] = self._track_state(when)
            except ValueError:
                pass
            pts.append(q)
        return pts

    def export(self, formats: list[str] | None = None, html: str | None = None,
               report_as: list[str] | None = None, html_pdf: str | None = None) -> Path:
        """Write the chosen formats to the exports folder.

        One file comes back as itself; several files come back as one zip.
        formats: any of EXPORT_FORMATS (default: all but the summary, which the browser builds),
        plus "report:<file>" for each saved report in Tools → Reports (saved as CSV).
        report_as: how the summary is saved: "html", "pdf" or both.
        html_pdf: the summary page made for printing (map fitted to the survey, a legend);
        the PDF of the summary uses it when given.
        """
        from . import reports as _reports
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        formats = list(formats) if formats is not None else ["csv", "merged", "gpx", "geojson"]
        report_defs = {f["file"]: f for f in _reports.load(self.cfg)[0]} if any(
            f.startswith("report:") for f in formats) else {}
        bad = [f for f in formats if f not in self.EXPORT_FORMATS
               and not (f.startswith("report:") and f.split(":", 1)[1] in report_defs)]
        report_as = [x for x in (report_as or ["html"]) if x in self.REPORT_AS] or ["html"]
        if bad:
            raise ValueErrorMsg(f"Unknown export format: {', '.join(bad)}")
        if not formats:
            raise ValueErrorMsg("Choose at least one format to export.")
        if "html" in formats and not (html or "").startswith("<!DOCTYPE html>"):
            raise ValueErrorMsg("The HTML summary is missing.")
        prefix = self.survey["prefix"]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.cfg.export_dir
        out.mkdir(parents=True, exist_ok=True)
        files: dict[str, bytes] = {}

        def csv_bytes(header, rows) -> bytes:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in header})
            return buf.getvalue().encode("utf-8")

        pts = self._export_track()
        if "csv" in formats:
            # data tables without the internal RowID column (only Spyhop's own files need it)
            for tab, t in self.tables.items():
                if t.path is not None and t.path.exists():
                    files[t.path.name] = csv_bytes([h for h in t.header if h != "RowID"], t.rows)
            mp = self._meta_path()
            if mp and mp.exists():
                files[mp.name] = mp.read_bytes()
            files[self.track.path.name] = csv_bytes(schema.TRACK_COLUMNS, pts)
            ip = self._inst_path()
            if ip and ip.exists():
                files[ip.name] = ip.read_bytes()
        if "merged" in formats:
            header, rows = self.merged_rows(pts)
            files[f"{prefix}_merged.csv"] = csv_bytes(header, rows)
        if "gpx" in formats:
            files[f"{prefix}.gpx"] = self.gpx(pts).encode("utf-8")
        if "geojson" in formats:
            files[f"{prefix}.geojson"] = json.dumps(self.geojson(pts)).encode("utf-8")
        for f in formats:
            if f.startswith("report:"):
                fd = report_defs[f.split(":", 1)[1]]
                files[f"{prefix}_report_{fd['file'][:-5]}.csv"] = _reports.to_csv(_reports.run(self, fd)).encode("utf-8")
        pages: dict[str, str] = {}
        if "html" in formats:
            pages[f"{prefix}_summary"] = html
        for stem, page in pages.items():
            if "html" in report_as:
                files[f"{stem}.html"] = page.encode("utf-8")
            if "pdf" in report_as:
                printed = html_pdf if (stem == f"{prefix}_summary" and (html_pdf or "").startswith("<!DOCTYPE html>")) else page
                files[f"{stem}.pdf"] = _pdf_bytes(printed, 6000 if stem == f"{prefix}_summary" else 3000)

        if len(files) == 1:
            name, data = next(iter(files.items()))
            stem, _, ext = name.rpartition(".")
            dest = out / f"{stem}_{stamp}.{ext}"
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            return dest
        folder = f"{prefix}_export_{stamp}"
        dest = out / f"{folder}.zip"
        tmp = dest.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(files):
                z.writestr(f"{folder}/{name}", files[name])
        os.replace(tmp, dest)
        return dest

    # columns of the merged CSV, in order
    MERGED_EFFORT = ["Effort", "Visibility", "SeaState", "Weather", "Glare", "Port", "Recorder", "Starboard"]
    MERGED_SIGHTING = ["SightNo", "Species", "Count", "Calves", "NumConf", "IDrel", "Behaviors", "Observer",
                       "Bearing", "BrgRef", "Distance", "DistUnit", "SigLat", "SigLon", "VesHdg", "Images", "FieldID"]
    MERGED_EVENT = ["EventNo", "EventType", "EventID"]

    def merged_rows(self, pts: list[dict] | None = None) -> tuple[list[str], list[dict]]:
        """Sightings, effort, events and track points in one time-ordered table.

        One row per record. Record says which it is (Effort, Sighting, Event or Track);
        Lat/Lon is the vessel position (the event position for events), and track rows
        add SOG and COG. Every row carries the survey details and the effort and
        conditions in force at its time (the latest Effort row at or before it), so each
        sighting, event and track point can be read with its conditions. A track row's
        Effort is its label in the track file (Start/ON/OFF/End/ERROR, recalculated from
        the final Effort table).
        """
        if pts is None:
            pts = self._export_track()
        meta = self.read_meta()
        from . import __version__
        meta_cols = [("Survey", self.survey["prefix"]), ("SpyhopVersion", __version__)] + [
            ("".join(w.capitalize() for w in k.split("_")), meta.get(k, "")) for k, _, _ in schema.SURVEY_META]
        header = ([k for k, _ in meta_cols] + ["Record", "DateTime", "Lat", "Lon", "SOG", "COG"] + self.MERGED_EFFORT
                  + self.MERGED_SIGHTING + self.MERGED_EVENT + ["Notes"])

        when = lambda r: parse_time(r.get("DateTime", ""))  # noqa: E731

        recs = []   # (time, kind order, original order, record type, row)
        for i, r in enumerate(self.tables["effort"].rows):
            recs.append((when(r), 0, i, "Effort", r))
        for i, r in enumerate(self.tables["sightings"].rows):
            recs.append((when(r), 1, i, "Sighting", r))
        for i, r in enumerate(self.tables["events"].rows):
            recs.append((when(r), 2, i, "Event", r))
        for i, p in enumerate(pts):
            recs.append((when(p), 3, i, "Track", p))
        far = datetime.max.replace(tzinfo=timezone.utc)
        recs.sort(key=lambda x: (x[0] or far, x[1], x[2]))
        state = {k: "" for k in self.MERGED_EFFORT}
        state["Effort"] = "no effort row yet"
        out = []
        for t, _, _, kind, r in recs:
            row = dict(meta_cols)
            row.update(Record=kind, DateTime=r.get("DateTime", ""), Notes=r.get("Notes", ""))
            if kind == "Track":
                row.update(state)
                row.update(Lat=r.get("Lat", ""), Lon=r.get("Lon", ""), SOG=r.get("SOG", ""), COG=r.get("COG", ""),
                           Effort=r.get("Effort", ""), Notes="")
            elif kind == "Effort":
                if t is not None:
                    state = {k: r.get(k, "") for k in self.MERGED_EFFORT}
                row.update(Lat=r.get("VesLat", ""), Lon=r.get("VesLon", ""), **{k: r.get(k, "") for k in self.MERGED_EFFORT})
            else:
                row.update(state)
                if kind == "Sighting":
                    row.update(Lat=r.get("VesLat", ""), Lon=r.get("VesLon", ""),
                               **{k: r.get(k, "") for k in self.MERGED_SIGHTING})
                else:
                    row.update(Lat=r.get("Lat", ""), Lon=r.get("Lon", ""), EventNo=r.get("EventNo", ""),
                               EventType=r.get("EventType", ""), EventID=r.get("ID", ""))
            out.append(row)
        return header, out

    def _marker_pos(self, tab, r):
        for la, lo in schema.MARKER_POS.get(tab, []):
            try:
                return float(r[la]), float(r[lo])
            except (KeyError, ValueError, TypeError):
                continue
        return None

    def geojson(self, pts) -> dict:
        feats = []
        for tab in ("sightings", "events", "marks"):
            for r in self.tables[tab].rows:
                pos = self._marker_pos(tab, r)
                if pos:
                    props = {k: v for k, v in r.items() if k != "RowID"}
                    props["layer"] = tab
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": {"type": "Point", "coordinates": [pos[1], pos[0]]}})
        # track as line segments split by effort state
        seg, state = [], None
        for p in pts + [None]:
            st = p["Effort"] if p else None
            if seg and (p is None or st != state):
                if len(seg) > 1:
                    feats.append({"type": "Feature",
                                  "properties": {"layer": "track", "Effort": state},
                                  "geometry": {"type": "LineString", "coordinates": seg}})
                seg = seg[-1:] if p else []
            if p:
                seg.append([float(p["Lon"]), float(p["Lat"])])
                state = st
        return {"type": "FeatureCollection", "features": feats}

    # -- a past survey as a map overlay -------------------------------------------------
    @staticmethod
    def survey_overlay_name(prefix: str) -> str:
        return f"Survey - {prefix}.geojson"

    def survey_overlay(self, prefix: str) -> tuple[str, dict]:
        """GeoJSON of another survey in the data folder: its trackline (on effort solid,
        off effort dashed), sightings and events, read straight from its CSV files."""
        if not self._survey_exists(prefix):
            raise ValueError(f"There's no survey called “{prefix}” in the data folder.")

        def rows(kind):
            p = self.cfg.data_dir / f"{prefix}_{kind}.csv"
            if not p.exists():
                return []
            try:
                with open(p, newline="", encoding="utf-8-sig") as fh:
                    return list(csv.DictReader(fh))
            except (OSError, csv.Error) as e:
                log.warning("couldn't read %s: %s", p, e)
                return []

        feats = []
        track = []
        for p in rows("track"):
            try:
                track.append((float(p["Lat"]), float(p["Lon"]), p.get("Effort", "")))
            except (KeyError, ValueError, TypeError):
                continue
        # keep the file small: thin long tracks, but never drop a change of effort state
        step = max(1, len(track) // 5000)
        thin = [q for i, q in enumerate(track)
                if i % step == 0 or i == len(track) - 1 or q[2] != track[i - 1][2] or (i + 1 < len(track) and q[2] != track[i + 1][2])]
        seg, state = [], None
        for q in thin + [None]:
            st = q[2] if q else None
            if seg and (q is None or st != state):
                if len(seg) > 1:
                    on = state == "ON"
                    feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": seg},
                                  "properties": {"name": f"{prefix} track ({'on' if on else 'off'} effort)",
                                                 "survey": prefix, "Effort": state,
                                                 "stroke-width": 3 if on else 2, "dash": None if on else "4 6"}})
                seg = seg[-1:] if q else []
            if q:
                seg.append([round(q[1], 6), round(q[0], 6)])
                state = st
        for r in rows("sightings"):
            pos = self._marker_pos("sightings", r)
            if pos:
                n = r.get("Count", "")
                calves = f" + {r['Calves']} calves" if r.get("Calves") not in (None, "", "0") else ""
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(pos[1], 6), round(pos[0], 6)]},
                              "properties": {"name": f"S{r.get('SightNo', '')} {r.get('Species', '')}".strip(),
                                             "survey": prefix, "time": r.get("DateTime", ""), "number": f"{n}{calves}",
                                             "FieldID": r.get("FieldID", ""), "notes": r.get("Notes", "")}})
        for r in rows("events"):
            pos = self._marker_pos("events", r)
            if pos:
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(pos[1], 6), round(pos[0], 6)]},
                              "properties": {"name": f"E{r.get('EventNo', '')} {r.get('EventType', '')}".strip(),
                                             "survey": prefix, "time": r.get("DateTime", ""), "ID": r.get("ID", ""),
                                             "notes": r.get("Notes", "")}})
        if not feats:
            raise ValueError(f"“{prefix}” has no trackline, sightings or events with positions to draw.")
        return self.survey_overlay_name(prefix), {"type": "FeatureCollection", "features": feats}

    def gpx(self, pts) -> str:
        from xml.sax.saxutils import escape
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<gpx version="1.1" creator="Spyhop" xmlns="http://www.topografix.com/GPX/1/1">']
        for tab, name_fn in (("sightings", lambda r: f"S{r['SightNo']} {r['Species']}"),
                             ("events", lambda r: f"E{r['EventNo']} {r['EventType']}"),
                             ("marks", lambda r: r["Name"])):
            for r in self.tables[tab].rows:
                pos = self._marker_pos(tab, r)
                if pos:
                    t = ""
                    try:
                        t = datetime.fromisoformat(r["DateTime"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except (ValueError, KeyError):
                        pass
                    out.append(f'<wpt lat="{pos[0]:.6f}" lon="{pos[1]:.6f}"><name>{escape(name_fn(r).strip())}</name>'
                               + (f"<time>{t}</time>" if t else "")
                               + f"<desc>{escape(r.get('Notes', ''))}</desc></wpt>")
        out.append(f"<trk><name>{escape(self.survey['name'])}</name><trkseg>")
        for p in pts:
            try:
                t = datetime.fromisoformat(p["DateTime"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                t = ""
            out.append(f'<trkpt lat="{p["Lat"]}" lon="{p["Lon"]}"><time>{t}</time></trkpt>')
        out.append("</trkseg></trk></gpx>")
        return "\n".join(out)

    # -- bootstrap ---------------------------------------------------------------------
    def bootstrap(self) -> dict:
        return {
            "config": self.cfg.public(),
            "schema": {"tabs": schema.TABS, "fixed_lists": schema.FIXED_LISTS, "survey_meta": schema.SURVEY_META},
            "survey": self.survey_info(),
            "resume_prompt": self.pending_resume,
            "surveys": self.list_surveys(),
            "tables": {tab: {"rows": t.rows, "can_undo": bool(t.undo_stack),
                             "can_redo": bool(t.redo_stack)} for tab, t in self.tables.items()},
            "track": self.track.points,
            "vessel": self.vessel(),
            "notices": self.notices,
            "overlays": sorted(p.name for p in self.cfg.overlays_dir.iterdir()
                               if p.suffix.lower() in (".geojson", ".json", ".gpx", ".kml")),
            "tz_name": str(self.tz()),
            "clock": self.clock_info(),
            "tz_offset_min": int(self.now().utcoffset().total_seconds() // 60),
        }
