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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__, geo, resights, reticle, schema, tzguess
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
        self._platform_cache, self._platform_cache_t = "", 0.0     # platform type, for the tracker
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
        if tab == "effort":
            self._number_segments()
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

    def _file(self, prefix: str, kind: str, ext: str = "csv") -> Path:
        """A survey's file: <data folder>/<survey>/<survey>_<kind>.<ext> (one folder per survey, 0.36)."""
        return self.cfg.survey_dir(prefix) / f"{prefix}_{kind}.{ext}"

    def _path(self, tab: str) -> Path | None:
        if tab == "marks":
            return self.cfg.data_dir / "waypoints.csv"
        if self.survey is None:
            return None
        return self._file(self.survey["prefix"], tab)


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
        folder = self.cfg.nmea_log_dir
        ts = bool(self.cfg.settings.get("nmea_log_timestamps", True))
        cur = self.rawlog
        if cur and on and not force and cur.path.parent == folder and cur.path.name.startswith(stem + "_nmea_"):
            return
        if cur:
            cur.close()
        self.rawlog = RawLog(folder, stem, ts) if on else None
        self.decoder.raw_logger = self.rawlog.write if self.rawlog else None

    def raw_log_status(self) -> dict:
        st = {"on": False, "folder": str(self.cfg.nmea_log_dir),
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
        if self.survey:
            self.cfg.survey_dir(self.survey["prefix"]).mkdir(parents=True, exist_ok=True)
        self.track = Track(self._file(self.survey["prefix"], "track") if self.survey else None)
        if self.survey:
            self._number_segments()
        self._raw_log_follow()
        self._load_instruments()

    def _survey_exists(self, prefix: str) -> bool:
        # explicit paths, not glob(): survey names may contain [ ] * etc.
        return any(self._file(prefix, t).exists() for t in self.SURVEY_FILES)

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
        return self._file(prefix, "metadata") if prefix else None

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

    # recorded with the survey details but not shown or edited: (field, label)
    SYSTEM_META = [("spyhop_version_created", "Started with Spyhop version"),
                   ("template_created", "Template in use when the survey started"),
                   ("template_created_matches", "Current template matched that saved template when the survey started"),
                   ("spyhop_version_saved", "Details last saved with Spyhop version")]

    def _template_meta(self) -> dict:
        """Which saved template the current template matches (templates.current_status), for a new survey's details."""
        from . import templates
        try:
            st = templates.current_status(self.cfg)
        except Exception as e:  # noqa: BLE001 — never stops a survey starting
            log.warning("couldn't tell which template is in use: %s", e)
            return {"template_created": "", "template_created_matches": "unknown"}
        if st["saved"]:
            match = "yes"
        elif st["name"]:
            match = "no — changed since: " + ("; ".join(st["changed"]) or "unknown")
        else:
            match = "no — not saved as a template"
        return {"template_created": st["name"], "template_created_matches": match}

    def _write_meta(self, meta: dict, system: dict | None = None):
        """Write <survey>_metadata.csv: the survey details, then SYSTEM_META. The values recorded when the
        survey started are kept; `system` gives them for a new survey."""
        import csv as _csv
        sysv = {"spyhop_version_created": __version__, "template_created": "", "template_created_matches": ""}
        p = self._meta_path()
        if system is None and p and p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                for r in _csv.DictReader(fh):
                    if r.get("field") in sysv:
                        sysv[r["field"]] = r.get("value") or ""
        sysv.update(system or {})
        sysv["spyhop_version_saved"] = __version__
        self._platform_cache_t = 0.0                    # the tracker reads the platform type again
        rows = [{"field": k, "label": label, "value": meta.get(k, "")} for k, label, _ in schema.SURVEY_META]
        rows += [{"field": k, "label": label, "value": sysv.get(k, "")} for k, label in self.SYSTEM_META]
        atomic_write_csv(p, ["field", "label", "value"], rows)

    def _clean_meta(self, updates: dict, base: dict) -> dict:
        """Validate survey-detail updates on top of base; raise ValueErrorMsg if any are bad."""
        meta = dict(base)
        for k, v in (updates or {}).items():
            if k not in meta:
                continue
            v = ("" if v is None else str(v)).strip()
            if k not in schema.META_MULTILINE:
                v = v.replace("\n", " ")
            else:
                v = v.replace("\r\n", "\n")
            if k == "platform_type" and v:
                match = next((o for o in schema.FIXED_LISTS["platform_type"] if o.lower() == v.lower()), None)
                if match is None:
                    raise ValueErrorMsg("Platform type must be Shipboard, Aerial, Stationary or Other.")
                v = match
            if k == "platform_altitude_ft" and v:
                try:
                    f = float(v)
                except ValueError:
                    raise ValueErrorMsg("Platform altitude must be a number of feet.")
                if not 0 < f <= 60000:
                    raise ValueErrorMsg("Platform altitude must be more than 0 and at most 60000 ft.")
                v = f"{f:g}"
            if k == "chief_scientist_email" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise ValueErrorMsg(f"“{v}” doesn't look like an email address.")
            meta[k] = v
        return meta

    def set_meta(self, updates: dict) -> dict:
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        meta = self._clean_meta(updates, self.read_meta())
        self._write_meta(meta)
        self.cfg.save_settings({"last_meta": {k: v for k, v in meta.items() if k != "survey_notes"}})
        self.emit({"type": "reload"})
        return meta

    def platform(self) -> tuple[str, str]:
        """(platform type, platform altitude in ft) of the open survey, else of the last survey details."""
        meta = self.read_meta() if self.survey else (self.cfg.settings.get("last_meta") or {})
        return meta.get("platform_type") or "", meta.get("platform_altitude_ft") or ""

    def survey_info(self) -> dict | None:
        if self.survey is None:
            return None
        rows = self.tables["effort"].rows
        start = rows[0]["DateTime"] if rows and rows[0].get("Effort") == "Start" else ""
        end = rows[-1]["DateTime"] if self.survey_ended() else ""
        return {**self.survey, "active": self.survey_active(), "ended": self.survey_ended(),
                "start_time": start, "end_time": end, "tracking": self.tracking_on(),
                "meta": self.read_meta(), "template": self.template_status()}

    def _activate(self, prefix: str, meta: dict | None = None):
        """Make an existing survey on disk the open survey (tracking is left off)."""
        self.survey = {"name": prefix, "prefix": prefix, "started": "", "auto_tracking_done": True}
        for k in ("name", "started"):
            if meta and meta.get(k):
                self.survey[k] = meta[k]
        self.cfg.set_current_survey(self.survey)
        self._open_tables()

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
        if survey["prefix"].lower() in self.cfg.RESERVED_NAMES:
            raise ValueErrorMsg(f"“{survey['prefix']}” is the name of one of Spyhop's own folders: choose another name.")
        if self._survey_exists(survey["prefix"]) or self.cfg.survey_dir(survey["prefix"]).exists():
            raise ValueErrorMsg(f"A survey called “{survey['prefix']}” already exists. "
                                "Choose another name, or open it from the list in the Survey tab.")
        self.close_survey()                           # an ended survey may still be open
        self.survey = survey
        self.pending_resume = None
        self.cfg.set_current_survey(survey)
        self._open_tables()
        self.new_row("effort", {"Effort": "Start"}, _allow_start=True)
        self.tables["effort"].undo_stack.clear()        # the Start row can't be undone
        self._write_meta(meta, system={"spyhop_version_created": __version__, **self._template_meta()})
        self._save_template_copy()
        self.cfg.save_settings({"last_meta": {k: v for k, v in meta.items() if k != "survey_notes"}})
        self._set_tracking(True)
        self._record_point("Start")                   # the track's first point is marked Start
        self.emit({"type": "reload"})

    # -- the template a survey was recorded with (0.36) ---------------------------------
    def template_copy_path(self, prefix: str | None = None) -> Path | None:
        prefix = prefix or (self.survey["prefix"] if self.survey else None)
        return self._file(prefix, "template", "zip") if prefix else None

    def _save_template_copy(self):
        """Keep a copy of the current template (lists, shortcuts, map display, reports, shared settings)
        in the new survey's folder, so the survey always travels with the template it was recorded with.
        Lists can't change during an active survey, so the copy stays exact."""
        from . import templates
        p = self.template_copy_path()
        try:
            data = templates.make_zip(self.cfg, note=f"The template in use when the survey {self.survey['prefix']} started.")
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        except Exception as e:  # noqa: BLE001 — never stops a survey starting
            log.warning("couldn't save the template with the survey: %s", e)
            self.notices.append(f"Couldn't save a copy of the template with this survey ({e}).")

    def template_status(self, prefix: str | None = None) -> dict:
        """The survey's template copy against the current template: {saved, name, differs: [data parts]}.
        Preferences (shortcuts, map display…) and colors may change during a survey, so they don't count."""
        from . import templates
        prefix = prefix or (self.survey["prefix"] if self.survey else None)
        p = self.template_copy_path(prefix)
        meta = self.read_meta_system(prefix)
        out = {"saved": bool(p and p.is_file()), "name": meta.get("template_created", ""), "differs": []}
        if out["saved"]:
            try:
                t = templates.read_template(templates.unzip(p.read_bytes(), ""))
                out["differs"] = templates.data_differs(self.cfg, t)      # the data part only (0.40)
            except Exception as e:  # noqa: BLE001
                out["error"] = str(e)
        return out

    def read_meta_system(self, prefix: str | None = None) -> dict:
        """The SYSTEM_META values recorded in a survey's details file."""
        import csv as _csv
        out = {}
        p = self._meta_path(prefix)
        if p and p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                for r in _csv.DictReader(fh):
                    if r.get("field") in {k for k, _ in self.SYSTEM_META}:
                        out[r["field"]] = r.get("value", "") or ""
        return out

    # -- survey packages (0.36): <survey>.spyhop-survey.zip ----------------------------------
    PACKAGE_EXT = ".spyhop-survey.zip"
    PACKAGE_MANIFEST = "spyhop-survey.json"
    PACKAGE_FORMAT = 1
    PACKAGE_MIN = "0.36.0"            # the oldest Spyhop that can open a package of this format

    def _package_files(self, prefix: str, logs: bool) -> list[Path]:
        """The files of a survey's folder that go in its package: its data, details, instruments and
        template copy (and its raw NMEA logs if asked); not its exports, backups or temporary files."""
        folder = self.cfg.survey_dir(prefix)
        out = []
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder)
            if not p.is_file() or any(x.startswith(".") for x in rel.parts) or rel.parts[0] == "exports":
                continue
            if rel.parts[0] == "nmea_logs" and not logs:
                continue
            if ".bak-" in p.name or p.name.endswith(".tmp") or p.name == self.PACKAGE_MANIFEST:
                continue
            out.append(p)
        return out

    def save_package(self, logs: bool = False) -> Path:
        """Save the open survey as <survey>.spyhop-survey.zip in its exports folder: a top folder named after
        the survey holding its files as Spyhop keeps them (RowID included, so it opens for editing), the
        copy of its template, and spyhop-survey.json (what it is, and a checksum of every file)."""
        import hashlib
        if self.survey is None:
            raise ValueErrorMsg(self.NO_SURVEY)
        for t in self.tables.values():
            if t.dirty:
                t.save()
        prefix = self.survey["prefix"]
        folder = self.cfg.survey_dir(prefix)
        files = self._package_files(prefix, logs)
        start = self.tables["effort"].rows[0]["DateTime"] if self.tables["effort"].rows else ""
        manifest = {
            "spyhop_survey": self.PACKAGE_FORMAT, "min_spyhop": self.PACKAGE_MIN, "made_with": __version__,
            "made": datetime.now().astimezone().isoformat(timespec="seconds"),
            "survey": prefix, "name": self.survey.get("name") or prefix,
            "status": "active" if self.survey_active() else "ended",
            "start_time": start, "end_time": self.tables["effort"].rows[-1]["DateTime"] if self.survey_ended() else "",
            "template": self.read_meta_system(prefix).get("template_created", ""),
            "has_template": self.template_copy_path(prefix).is_file(),
            "nmea_logs": bool(logs),
            "files": {p.relative_to(folder).as_posix(): {"bytes": p.stat().st_size,
                                                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files},
        }
        dest = self.cfg.export_dir / f"{prefix}{self.PACKAGE_EXT}"
        tmp = dest.with_name(dest.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{prefix}/{self.PACKAGE_MANIFEST}", json.dumps(manifest, indent=2, ensure_ascii=False))
            for p in files:
                z.write(p, f"{prefix}/{p.relative_to(folder).as_posix()}")
        os.replace(tmp, dest)
        return dest

    def read_package(self, data: bytes) -> tuple[dict, dict[str, bytes]]:
        """Check a survey package: (manifest, {path inside the survey folder: bytes}). Raises ValueErrorMsg."""
        import hashlib
        from . import templates
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueErrorMsg("That isn't a zip file, so it can't be a Spyhop survey package.")
        names = [n for n in z.namelist() if not n.endswith("/")]
        mans = sorted((n for n in names if n.rsplit("/", 1)[-1] == self.PACKAGE_MANIFEST), key=lambda n: n.count("/"))
        if not mans:
            raise ValueErrorMsg(f"That isn't a Spyhop survey package: it has no {self.PACKAGE_MANIFEST}. "
                                "(A template, or an Export Data zip, can't be opened as a survey.)")
        root = mans[0][: -len(self.PACKAGE_MANIFEST)]
        try:
            man = json.loads(z.read(mans[0]).decode("utf-8-sig"))
        except ValueError:
            raise ValueErrorMsg(f"The package's {self.PACKAGE_MANIFEST} can't be read.")
        if man.get("spyhop_survey") != self.PACKAGE_FORMAT or not isinstance(man.get("files"), dict) or not man.get("survey"):
            raise ValueErrorMsg("That survey package is in a format this Spyhop doesn't know.")
        need = templates.version_tuple(man.get("min_spyhop")) or (0,)
        if need > (templates.version_tuple(__version__) or (0,)):
            raise ValueErrorMsg(f"That survey package needs Spyhop {man['min_spyhop']} or newer (this is {__version__}). Update Spyhop first.")
        files = {}
        for rel, info in man["files"].items():
            parts = rel.split("/")
            if not rel or rel.startswith("/") or "\\" in rel or any(x in ("", ".", "..") for x in parts):
                raise ValueErrorMsg(f"The package names a file in an unsafe place ({rel}); nothing was opened.")
            try:
                b = z.read(root + rel)
            except KeyError:
                raise ValueErrorMsg(f"The package is incomplete: {rel} is missing.")
            if hashlib.sha256(b).hexdigest() != (info or {}).get("sha256"):
                raise ValueErrorMsg(f"The package is damaged: {rel} doesn't match its checksum.")
            files[rel] = b
        if not any(rel == f"{man['survey']}_{k}.csv" for rel in files for k in self.SURVEY_FILES):
            raise ValueErrorMsg("The package has no survey tables in it.")
        return man, files

    def open_package(self, data: bytes, name: str = "") -> dict:
        """Open a survey package: unpack it into <data folder>/<survey>/ (or a new name when that's taken:
        the files are renamed to match) and open the survey (tracking stays off). Nothing is overwritten:
        if the name is taken, returns {exists, suggest} instead."""
        import shutil
        man, files = self.read_package(data)
        old = man["survey"]
        new = safe_name((name or "").strip()) if name else old
        if not new:
            raise ValueErrorMsg("Please give the survey a name.")
        if new.lower() in self.cfg.RESERVED_NAMES:
            raise ValueErrorMsg(f"“{new}” is the name of one of Spyhop's own folders: choose another name.")
        if self.cfg.survey_dir(new).exists():
            n = 2
            while self.cfg.survey_dir(f"{new} ({n})").exists():
                n += 1
            return {"exists": True, "survey": new, "suggest": f"{new} ({n})", "manifest": man}
        tmp = self.cfg.data_dir / f".{new}.opening-{uuid.uuid4().hex[:6]}"
        try:
            for rel, b in files.items():
                parts = rel.split("/")
                if new != old and parts[-1].startswith(old + "_"):
                    parts[-1] = new + parts[-1][len(old):]        # Old_sightings.csv → New_sightings.csv
                dest = tmp.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b)
            os.replace(tmp, self.cfg.survey_dir(new))
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        self.open_survey(new)
        return {"opened": new, "renamed_from": old if new != old else "", "manifest": man,
                "template": self.template_status(new)}

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
        """Surveys in the data folder (a folder each), most recently changed first."""
        found: dict[str, dict] = {}
        try:
            folders = [d for d in self.cfg.data_dir.iterdir() if d.is_dir() and d.name not in self.cfg.RESERVED_NAMES]
        except OSError:
            folders = []
        for d in folders:
            prefix = d.name
            for kind in self.SURVEY_FILES:
                p = self._file(prefix, kind)
                if not p.is_file():
                    continue
                s = found.setdefault(prefix, {"prefix": prefix, "modified": 0.0, "sightings": 0,
                                              "start_time": "", "end_time": ""})
                s["modified"] = max(s["modified"], p.stat().st_mtime)
                if kind == "sightings":
                    with open(p, encoding="utf-8-sig") as fh:
                        s["sightings"] = max(0, sum(1 for line in fh if line.strip()) - 1)
                elif kind == "effort":
                    s["start_time"], s["end_time"] = self._read_effort_bounds(p)
            if prefix in found:
                found[prefix]["has_template"] = self._file(prefix, "template", "zip").is_file()
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
        folder = self.cfg.survey_dir(self.survey["prefix"])
        self.close_survey()
        # the rest of its folder too: the template copy, its raw NMEA logs and exports (asked twice in the UI)
        import shutil
        if folder.is_dir() and folder.parent == self.cfg.data_dir:
            shutil.rmtree(folder, ignore_errors=True)

    # -- instrument history (Tools → Instruments plots) ---------------------------------
    INST_SAMPLE_S = 5            # one value per reading every this many seconds
    INST_COLUMNS = ["DateTime", "Key", "Label", "Unit", "Value"]

    def _inst_path(self, prefix: str | None = None) -> Path | None:
        prefix = prefix or (self.survey["prefix"] if self.survey else None)
        return self._file(prefix, "instruments") if prefix else None

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
    def reticle_entry(self, unit: str) -> dict | None:
        """The reticles list entry for a Unit reticles-<name> (case-insensitive), or None."""
        name = (schema.reticle_name(unit) or "").lower()
        return next((r for r in self.cfg.lists.get("reticles", []) if r["name"].lower() == name), None) if name else None

    def list_values(self, name: str) -> list[str] | None:
        if name == "distunit":            # the units, then one per entry of the reticles list
            return schema.FIXED_LISTS["distunit"] + [schema.RETICLE_UNIT + r["name"] for r in self.cfg.lists.get("reticles", [])]
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
        if tab == "sightings" and key == "ResightOf":
            return self._parse_resight_of(s, row)
        if c.get("na") and s.upper() in ("NA", "N/A"):
            return "NA", None
        if t in ("int", "seq"):
            try:
                v = float(s)
            except ValueError:
                raise ValueErrorMsg(f"{c['label']} must be a whole number" + (" (or NA)" if c.get("na") else ""))
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
            if schema.strict_list(c["list"]):
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
        keys = ("Lat", "SigLat") if is_lat else ("Lon", "SigLon")
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

    def _parse_resight_of(self, s: str, row: dict) -> tuple[str, str | None]:
        """ResightOf: the SightNo of an earlier sighting of the same animals. One typed against a
        resight is linked to that resight's original, so every resight points at the first sighting."""
        k = resights._key(s)
        if not k.isdigit():
            raise ValueErrorMsg("ResNo must be the SigNo of the first sighting of these animals")
        if k == resights._key(row.get("SightNo")):
            raise ValueErrorMsg("A sighting can't be a resight of itself")
        rows = [r for r in self.table("sightings").rows if r.get("RowID") != row.get("RowID")]
        index = resights.by_sightno(rows)
        target = index.get(k)
        if target is None:
            raise ValueErrorMsg(f"There is no sighting {k} to be a resight of")
        me, cur, seen = resights._key(row.get("SightNo")), target, set()
        while True:                                 # follow the target's own links to its first sighting
            ref = resights._key(cur.get("ResightOf"))
            if ref and ref == me:
                raise ValueErrorMsg(f"Sighting {k} is itself a resight of this sighting")
            nxt = index.get(ref) if ref else None
            if nxt is None or id(nxt) in seen:
                break
            seen.add(id(nxt))
            cur = nxt
        ok = resights._key(cur.get("SightNo"))
        if ok != k:
            return ok, f"Sighting {k} is a resight of {ok}, so this row is linked to {ok}, the first sighting."
        return k, None

    def add_resight(self, row_id: str) -> dict:
        """A new sighting row for another look at the animals of row_id: linked to their first
        sighting, with the species, number, calves, number and ID confidence and FieldID copied
        from the row chosen (the latest resight, if it's a resight itself)."""
        t = self.table("sightings")
        try:
            row = t.get(row_id)
        except KeyError:
            raise ValueErrorMsg("That sighting no longer exists.")
        orig = resights.original_of(row, t.rows)
        if not resights._key(orig.get("SightNo")):
            raise ValueErrorMsg("That sighting has no SigNo to link a resight to.")
        prefill = {k: row.get(k, "") for k in resights.COPIED if row.get(k, "") != ""}
        prefill["ResightOf"] = orig.get("SightNo")
        return self.new_row("sightings", prefill)

    # -- computed fields -----------------------------------------------------------
    def compute(self, tab: str, row: dict, changed: set[str], old: dict | None = None) -> list[str]:
        warnings = []
        if tab == "sightings":
            keys = {"Bearing", "BrgRef", "Distance", "DistUnit", "Lat", "Lon", "VesHdg", "Altitude"}
            b, d = row.get("Bearing", ""), row.get("Distance", "")
            if b == "" or d == "":
                # No bearing/distance: the animal is taken to be at the vessel, unless
                # someone typed (or picked on the map) the animal's position themselves.
                if changed & {"SigLat", "SigLon"}:
                    return warnings
                follows = (old is None or not old.get("SigLat")
                           or (old.get("SigLat") == old.get("Lat") and old.get("SigLon") == old.get("Lon"))
                           or bool(changed & {"Bearing", "Distance"}))
                if follows:
                    row["SigLat"], row["SigLon"] = row.get("Lat", ""), row.get("Lon", "")
                return warnings
            if changed & keys:
                try:
                    lat, lon = float(row["Lat"]), float(row["Lon"])
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
                if ref == "C" and not 0 <= float(b) <= 12:
                    warnings.append("With Ref C the bearing is a clock bearing, 1 to 12 (3 = 90° to starboard, 12 = dead ahead). "
                                    "The animal's position wasn't calculated.")
                    return warnings
                true_b = geo.to_true_bearing(float(b), ref, hdg, var)
                if true_b is None:
                    warnings.append("Can't convert the bearing to true: " + (
                        "no magnetic variation available (set it in Settings)" if ref == "M"
                        else "no vessel heading on this row"))
                    return warnings
                unit = row.get("DistUnit") or self.cfg.settings.get("distance_unit", "nm")
                if schema.reticle_name(unit) is not None:
                    entry = self.reticle_entry(unit)
                    if entry is None:
                        warnings.append(f"There's no reticle “{schema.reticle_name(unit)}” in Settings → Dropdowns → Reticles, so the animal's position wasn't calculated.")
                        return warnings
                    alt = row.get("Altitude") or self.platform()[1]
                    if not alt:
                        warnings.append("Set the platform altitude (Survey tab, or this row's Alt) to turn the reticle reading into a distance.")
                        return warnings
                    try:
                        dist_m = reticle.distance_m(float(d), float(alt), reticle.settings_for(entry))
                    except reticle.ReticleError as e:
                        warnings.append(f"{e} The animal's position wasn't calculated.")
                        return warnings
                else:
                    dist_m = geo.to_meters(float(d), unit)
                slat, slon = geo.destination(lat, lon, true_b, dist_m)
                row["SigLat"], row["SigLon"] = f"{slat:.6f}", f"{slon:.6f}"
        return warnings

    def _fill_bearing_distance(self, row: dict):
        """Animal position given directly (e.g. picked on the map): fill in the
        bearing (in the row's reference) and distance from the vessel to it."""
        try:
            vlat, vlon = float(row["Lat"]), float(row["Lon"])
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
        elif ref in ("R", "C"):
            try:
                b = true_b - float(row.get("VesHdg") or "x")
            except ValueError:
                ref, b = "T", true_b
            if ref == "C":                          # to the nearest hour, 1–12
                b = (round((b % 360) / 30) % 12) or 12
        else:
            b = true_b
        unit = row.get("DistUnit") or "nm"
        dm = geo.haversine_m(vlat, vlon, slat, slon)
        d = None
        if schema.reticle_name(unit) is not None:
            alt = row.get("Altitude") or self.platform()[1]
            entry = self.reticle_entry(unit)
            try:
                d = reticle.reading_for(dm, float(alt), reticle.settings_for(entry)) if alt and entry else None
            except (ValueError, ZeroDivisionError):
                d = None
            if d is None or d < 0:                 # no reading for it (marks, no altitude): give it in meters
                unit, d = "m", dm
                row["DistUnit"] = "m"
        else:
            d = dm / geo.UNIT_TO_M.get(unit, 1852.0)
        row["BrgRef"] = ref
        row["Bearing"] = f"{b:.0f}" if ref == "C" else f"{b % 360:.0f}"
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

    def new_row(self, tab: str, prefill: dict | None = None, lat=None, lon=None, _allow_start=False,
                _index: int | None = None) -> dict:
        """A new row with the time and position now (prefill may give others). _index: insert it there,
        copying forward from the row before it and not using the live GPS (insert_row)."""
        self._require_survey(tab)
        if tab != "marks" and self.survey_ended() and _index is None:     # inserting to fix a gap is allowed
            raise ValueErrorMsg("This survey has ended, so no rows can be added. To continue it, "
                                "delete its End row in the Effort tab (or Undo).")
        t = self.table(tab)
        spec = schema.TABS[tab]
        row = {c["key"]: c["default"] for c in spec["columns"]}
        v = self.vessel()
        has_fix = v["has_fix"]
        warnings = []
        at = len(t.rows) if _index is None else _index
        if tab == "effort" and t.rows and at > 0:
            prev = t.rows[at - 1]
            for c in spec["columns"]:
                if c["copy"] and c["type"] != "id":
                    row[c["key"]] = prev.get(c["key"], "")
            if not schema.is_effort_choice(row.get("Effort")):
                row["Effort"] = ""          # after Start, choose ON (or a kind of on effort) or OFF
        if tab == "effort" and not t.rows:
            row["Effort"] = "Start"
        row["DateTime"] = self.now().isoformat(timespec="seconds")
        pos_keys = {"sightings": ("Lat", "Lon"),
                    "effort": ("Lat", "Lon"), "events": ("Lat", "Lon"),
                    "marks": ("Lat", "Lon")}[tab]
        if lat is not None and lon is not None:
            row[pos_keys[0]], row[pos_keys[1]] = f"{float(lat):.6f}", f"{float(lon):.6f}"
        elif _index is not None:
            pass                            # an inserted row: its position comes from prefill
        elif has_fix:
            row[pos_keys[0]], row[pos_keys[1]] = f"{v['lat']:.6f}", f"{v['lon']:.6f}"
        else:
            warnings.append("No GPS fix — position left blank.")
        if "VesHdg" in row and has_fix and v.get("best_heading") is not None and _index is None:
            row["VesHdg"] = f"{v['best_heading']:.0f}"
        if "BrgRef" in row:
            row["BrgRef"] = self.cfg.settings.get("bearing_reference", "M")
        if "DistUnit" in row:
            row["DistUnit"] = self.cfg.settings.get("distance_unit", "nm")
        if "Altitude" in row:
            row["Altitude"] = self.platform()[1]
        if spec.get("seq"):
            row[spec["seq"]] = str(t.next_seq(spec["seq"]))
        if tab == "marks":
            row["Name"] = f"WP{len(t.rows) + 1}"
        changed = set()
        for k, raw in (prefill or {}).items():
            if schema.column(tab, k) is None or schema.column(tab, k).get("readonly"):
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
            self._check_effort_value(t, at, row.get("Effort", ""), adding=True)
        added = self._write(lambda: t.add(row, at))
        if tab == "effort" and row.get("Effort") == "End":
            self._set_tracking(False)
        if tab == "effort" and schema.is_on(row.get("Effort")):
            self._auto_tracking()
        self.emit_tab(tab)
        return {"row": added or row, "warnings": warnings}

    def _number_segments(self):
        """Effort segments: a new number on each Effort row whose status differs from the row before;
        rows with the same status as the row before share its number. Kept up to date after every
        change to the Effort table (not an undo step of its own)."""
        t = self.tables.get("effort")
        if t is None or t.path is None:
            return
        seg, prev, changed = 0, None, False
        for i, r in enumerate(t.rows):
            st = r.get("Effort", "")
            if i == 0 or st != prev:
                seg += 1
            prev = st
            if r.get("Segment") != str(seg):
                r["Segment"] = str(seg)
                changed = True
        if changed:
            self._write(t.save)

    INSERT_METHODS = {"average": "averaged from the rows before and after",
                      "previous": "copied from the row before", "next": "copied from the row after",
                      "time": "at a time typed in"}

    def track_position_at(self, when: datetime) -> tuple[float, float] | None:
        """The platform's position at a time, from the trackline: between the two track points either side
        of it (in proportion), or the nearest point when it's before the first or after the last."""
        pts = []
        for p in self.track.points if self.track else []:
            pt = parse_time(p.get("DateTime", ""))
            try:
                pts.append((pt, float(p["Lat"]), float(p["Lon"])))
            except (TypeError, ValueError, KeyError):
                continue
        pts = sorted((x for x in pts if x[0] is not None), key=lambda x: x[0])
        if not pts:
            return None
        if when <= pts[0][0]:
            return pts[0][1], pts[0][2]
        for (t0, a0, b0), (t1, a1, b1) in zip(pts, pts[1:]):
            if t0 <= when <= t1:
                f = 0.0 if t1 == t0 else (when - t0) / (t1 - t0)
                return a0 + (a1 - a0) * f, b0 + (b1 - b0) * f
        return pts[-1][1], pts[-1][2]

    def _insert_at_time(self, tab: str, t, row_id: str, text: str) -> dict:
        """Insert a row at a time typed in, in time order, at the platform's position then (trackline)."""
        ref = t.get(row_id)
        if not str(text or "").strip():
            raise ValueErrorMsg("Type the time for the new row (e.g. 14:05 or 14:05:30).")
        when = parse_time(self.parse_datetime(str(text), ref.get("DateTime", "")))
        if when is None:
            raise ValueErrorMsg("That time couldn't be read: type it as 14:05 or 14:05:30.")
        at = len(t.rows)
        for k, r in enumerate(t.rows):
            rt = parse_time(r.get("DateTime", ""))
            if rt is not None and rt > when:
                at = k
                break
        if tab == "effort":
            if at == 0:
                raise ValueErrorMsg("That time is before the Start row: nothing can go before it.")
            if t.rows and t.rows[-1].get("Effort") == "End" and at >= len(t.rows):
                raise ValueErrorMsg("That time is after the End row: nothing can go after it.")
        tz = self.tz()
        hms = when.astimezone(tz).strftime("%H:%M:%S")
        prefill = {"DateTime": when.replace(microsecond=0).isoformat()}
        pos = self.track_position_at(when)
        warn = None
        if pos:
            prefill["Lat"], prefill["Lon"] = f"{pos[0]:.6f}", f"{pos[1]:.6f}"
            prefill["Notes"] = f"Inserted: time typed in ({hms}), position from the trackline at that time."
        else:
            prefill["Notes"] = f"Inserted: time typed in ({hms}); no trackline, so no position."
            warn = "There's no trackline to take the position from, so the position is blank."
        res = self.new_row(tab, prefill, _index=at)
        if warn:
            res["warnings"] = [warn, *res.get("warnings", [])]
        return res

    def insert_row(self, tab: str, row_id: str, method: str, where: str = "after", time_text: str = "") -> dict:
        """Insert a row before or after row_id, its time and position averaged from the rows either side
        of the gap, or copied from the row before or after it; or at a time typed in, in time order, at the
        platform's position then. A note says how."""
        self._require_survey(tab)
        t = self.table(tab)
        if method not in self.INSERT_METHODS:
            raise ValueErrorMsg("Choose how to fill in the time and position: average, previous, next or a time.")
        try:
            i = t.index_of(row_id)
        except KeyError:
            raise ValueErrorMsg("That row no longer exists.")
        if method == "time":
            return self._insert_at_time(tab, t, row_id, time_text)
        at = i + 1 if where == "after" else i
        before = t.rows[at - 1] if at > 0 else None
        after = t.rows[at] if at < len(t.rows) else None
        if tab == "effort" and at == 0:
            raise ValueErrorMsg("Nothing can go before the Start row: it marks when the survey began.")
        if tab == "effort" and before is not None and before.get("Effort") == "End":
            raise ValueErrorMsg("Nothing can go after the End row: it must be the last.")
        src = {"previous": [before], "next": [after], "average": [before, after]}[method]
        if any(r is None for r in src):
            raise ValueErrorMsg({"previous": "There is no row before it to copy from.", "next": "There is no row after it to copy from.",
                                 "average": "Averaging needs a row before and a row after."}[method])
        times = [parse_time(r.get("DateTime", "")) for r in src]
        if any(x is None for x in times):
            raise ValueErrorMsg("A row to take the time from has no time.")
        when = times[0] if len(times) == 1 else times[0] + (times[1] - times[0]) / 2
        prefill = {"DateTime": when.replace(microsecond=0).isoformat()}
        pts = [(r.get("Lat"), r.get("Lon")) for r in src if r.get("Lat") not in (None, "") and r.get("Lon") not in (None, "")]
        warn = None
        if len(pts) == len(src):
            prefill["Lat"] = f"{sum(float(a) for a, _ in pts) / len(pts):.6f}"
            prefill["Lon"] = f"{sum(float(b) for _, b in pts) / len(pts):.6f}"
        else:
            warn = "A row to take the position from has none, so the position is blank."
        tz = self.tz()
        hms = lambda x: x.astimezone(tz).strftime("%H:%M:%S")
        note = f"Inserted: time and position {self.INSERT_METHODS[method]} ({' and '.join(hms(x) for x in times)})."
        prefill["Notes"] = note
        res = self.new_row(tab, prefill, _index=at)
        if warn:
            res["warnings"] = [warn, *res.get("warnings", [])]
        return res

    def toggle_effort(self) -> dict:
        self._require_survey("effort")
        t = self.table("effort")
        last = t.rows[-1].get("Effort") if t.rows else ""
        if schema.is_on(last):
            return self.new_row("effort", {"Effort": schema.default_off()})
        # back on effort the way it was last on (ON, TRANSECT, … : the on-effort entries of the effort list)
        first = "ON" if "ON" in schema.ON_EFFORT else (schema.ON_EFFORT[0] if schema.ON_EFFORT else "ON")
        kind = next((r.get("Effort") for r in reversed(t.rows) if schema.is_on(r.get("Effort"))), first)
        return self.new_row("effort", {"Effort": kind})

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
            c = schema.column(tab, k)
            if c and c.get("readonly"):
                raise ValueErrorMsg(f"{c['label']} is filled in by Spyhop and can't be typed.")
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
        if tab == "effort" and "Effort" in changed and schema.is_on(row.get("Effort")):
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
        if self._platform_cache_t < time.time() - 30:          # read the survey details at most every 30 s
            self._platform_cache = self.platform()[0]
            self._platform_cache_t = time.time()
        if self._platform_cache == "Stationary":                # it doesn't move: only Start and End points
            return
        interval = max(1, min(300, int(s.get("tracking_interval", 10) or 10)))
        now = time.time()
        if now - self._last_track_t < interval:
            return
        self._record_point()

    def _track_state(self, when: datetime) -> str:
        """Effort state in force at a time: Start, an on- or off-effort value, End or ERROR (OFF if unknown)."""
        st = self.effort_at(when)
        return st if st in schema.EFFORT_NAMES else schema.default_off()

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
                row["Lat"], row["Lon"] = p.get("Lat", ""), p.get("Lon", "")
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
        # the ERROR row goes one second after the last track point before the break, so that in the
        # merged export (sorted by time) it comes after that point rather than tying with it
        last = None
        for p in self.track.points if self.track else []:
            pt = parse_time(p.get("DateTime", ""))
            if pt is not None and pt <= t0 and (last is None or pt > last):
                last = pt
        t_err = (last or t0) + timedelta(seconds=1)
        if t_err >= t1:
            t_err = t0
        err = make(t_err, "ERROR", f"Trackline break (GPS jump or loss) until {hhmm(t1)}, added by Error check → Fix.")
        r = self._write(lambda: t.add(err, index_for(t_err)))
        if r:
            added.append(r)
        follows = any(x[0] is not None and t0 < x[0] <= t1 for x in timed)
        if not follows:
            back = make(t1, st if schema.is_effort_choice(st) else "", f"Back after the trackline break from {hhmm(t0)}.")
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
                if not (when in row_times and q.get("Effort") in ("Start", "End", *schema.ON_EFFORT, *schema.OFF_EFFORT)):
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
        if any(f.startswith("report:") for f in formats) and self.survey_active():
            raise ValueErrorMsg("Saved reports can't be run during a survey: export them once it ends (or untick them).")
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
    MERGED_EFFORT = ["Effort", "Segment", "Visibility", "SeaState", "Weather", "Glare", "GlareStart", "GlareEnd", "GlareRef", "Port", "Recorder", "Starboard"]
    MERGED_SIGHTING = ["SightNo", "ResightOf", "Species", "Count", "Calves", "NumConf", "IDrel", "Behaviors", "Observer",
                       "Bearing", "BrgRef", "Distance", "DistUnit", "Altitude", "SigLat", "SigLon", "VesHdg", "Images", "FieldID"]
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
                row.update(Lat=r.get("Lat", ""), Lon=r.get("Lon", ""), **{k: r.get(k, "") for k in self.MERGED_EFFORT})
            else:
                row.update(state)
                if kind == "Sighting":
                    row.update(Lat=r.get("Lat", ""), Lon=r.get("Lon", ""),
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
            p = self._file(prefix, kind)
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
                    on = schema.is_on(state)
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
                calves = f" + {r['Calves']} calves" if r.get("Calves") not in (None, "", "0", "NA") else ""
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
        from . import templates          # the template's parts, for Settings → Templates
        return {
            "config": self.cfg.public(),
            "schema": {"tabs": schema.TABS, "fixed_lists": schema.FIXED_LISTS, "survey_meta": schema.SURVEY_META,
                       "reticle": {"methods": reticle.METHODS, "presets": {k: list(v) for k, v in reticle.PRESETS.items()}},
                       "template_parts": templates.PARTS},
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
