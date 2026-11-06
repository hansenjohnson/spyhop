"""Data folder layout, user-editable config CSVs, and settings."""
from __future__ import annotations

import csv
import json
import os
import platform
from pathlib import Path

APP_DIR_NAME = "Spyhop"
LEGACY_DIR_NAMES = ["WhaleSurveyRecorder"]     # the app's earlier name


def _base_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def clean_timezone(v) -> str:
    """Settings → Clock: 'local' (the computer's), 'UTC', 'auto' (from the platform's position)
    or a fixed offset such as 'UTC-04:00'. Anything else (older IANA names) becomes 'local'."""
    from .tzguess import parse_offset, offset_name
    v = str(v or "").strip()
    if v in ("local", "auto"):
        return v
    if v.upper() in ("UTC", "Z", "GMT", "UTC+00:00", "UTC-00:00"):
        return "UTC"
    z = parse_offset(v)
    if z is not None:
        return offset_name(z.utcoffset(None).total_seconds() / 3600)
    return "local"


def default_data_dir() -> Path:
    env = os.environ.get("SPYHOP_DATA_DIR") or os.environ.get("WSR_DATA_DIR")
    if env:
        return Path(env).expanduser()
    base = _base_dir()
    new = base / APP_DIR_NAME
    if not new.exists():
        # first start after the rename: move the old data folder across
        for old_name in LEGACY_DIR_NAMES:
            old = base / old_name
            if old.is_dir():
                try:
                    old.rename(new)
                    print(f"Moved your data folder from {old} to {new}")
                except OSError as e:
                    print(f"Couldn't rename {old} to {new} ({e}); using the old folder.")
                    return old
                break
    return new


DEFAULT_LISTS: dict[str, tuple[list[str], list[list[str]]]] = {
    "species": (["name", "color", "species_code"], [
        ["North Atlantic right whale", "red", "RIWH"],
        ["Humpback whale", "darkorange", "HUWH"],
        ["Fin whale", "royalblue", "FIWH"],
        ["Sei whale", "teal", "SEWH"],
        ["Minke whale", "mediumseagreen", "MIWH"],
        ["Blue whale", "navy", "BLWH"],
        ["Sperm whale", "saddlebrown", "SPWH"],
        ["Unid. large whale", "dimgray", "UNLW"],
        ["Unid. baleen whale", "gray", "UNBW"],
        ["Fin/sei whale", "steelblue", "FISE"],
        ["Long-finned pilot whale", "black", "PIWH"],
        ["Risso's dolphin", "slategray", "GRAM"],
        ["Common dolphin", "gold", "SADO"],
        ["Atlantic white-sided dolphin", "khaki", "WSDO"],
        ["Bottlenose dolphin", "lightslategray", "BODO"],
        ["Unid. dolphin", "silver", "UNDO"],
        ["Harbor porpoise", "plum", "HAPO"],
        ["Gray seal", "rosybrown", "GRSE"],
        ["Harbor seal", "tan", "HASE"],
        ["Unid. seal", "wheat", "UNSE"],
        ["Basking shark", "darkolivegreen", "BASH"],
        ["White shark", "darkslategray", "WHSH"],
        ["Ocean sunfish", "lightsteelblue", "OCSU"],
        ["Leatherback sea turtle", "darkgreen", "LETU"],
        ["Loggerhead sea turtle", "olive", "LOTU"],
        ["Unid. sea turtle", "yellowgreen", "UNTU"],
        ["Dead bird", "sienna", "DEBI"],
    ]),
    "event_types": (["name", "color", "event_code"], [
        ["CTD cast", "blue", "CTD"],
        ["Drifter deployed", "deepskyblue", "DRFD"],
        ["Drifter recovered", "deepskyblue", "DRFR"],
        ["Drone launched", "darkviolet", "UASL"],
        ["Drone recovered", "darkviolet", "UASR"],
        ["Tag deployed", "crimson", "TAG"],
        ["Tagging attempt", "lightcoral", "TAGA"],
        ["Biopsy sample", "darkgoldenrod", "BIOP"],
        ["Biopsy attempt", "goldenrod", "BIOA"],
        ["Acoustic recorder deployed", "teal", "ACOD"],
        ["Acoustic recorder recovered", "teal", "ACOR"],
        ["Plankton tow", "seagreen", "PLNK"],
        ["Photo-ID session start", "slateblue", "PIDS"],
        ["Photo-ID session end", "slateblue", "PIDE"],
        ["Fishing gear sighted", "orangered", "GEAR"],
        ["Vessel sighted", "gray", "VESL"],
        ["Marine debris", "sienna", "DEBR"],
        ["Gear Reported", "darkorange", "GRPT"],
        ["Gear Recovered", "chocolate", "GRCV"],
        ["Other", "black", "OTH"],
    ]),
    "observers": (["name", "full_name"], [
        ["OBS1", "Observer 1"],
        ["OBS2", "Observer 2"],
        ["OBS3", "Observer 3"],
        ["OBS4", "Observer 4"],
        ["UNK", "Unknown"],
        ["NA", "None"],             # an empty watch position: may fill several positions at once
    ]),
    "behaviors": (["name", "behavior_code"], [
        ["Travel", "TR"], ["Mill", "MI"], ["Feed", "FE"], ["Surface feed", "SF"],
        ["Subsurface feed", "SS"], ["Bubble net", "BN"], ["Skim feed", "SK"],
        ["Rest / log", "RE"], ["Social / SAG", "SO"], ["Breach", "BR"],
        ["Flipper slap", "FS"], ["Tail slap / lobtail", "TS"], ["Fluke-up dive", "FU"],
        ["Fluke-down dive", "FD"], ["Nursing", "NU"], ["Bow riding", "BO"],
        ["Avoidance", "AV"], ["Approach vessel", "AP"], ["Entangled", "EN"],
        ["Other", "OT"],
    ]),
}

DEFAULT_SHORTCUTS = ["combo", "action", "prefill"], [
    ["Mod+Enter", "add-current", ""],
    ["Mod+Shift+S", "add:sightings", ""],
    ["Mod+Shift+E", "add:effort", ""],
    ["Mod+Shift+F", "toggle-effort", ""],
    ["Mod+Shift+V", "add:events", ""],
    ["Mod+Shift+K", "add:marks", ""],
    ["Mod+Shift+R", "add:sightings", "Species=North Atlantic right whale"],
    ["Mod+Shift+H", "add:sightings", "Species=Humpback whale"],
    ["Mod+Shift+U", "undo", ""],
    ["Mod+Shift+Y", "redo", ""],
    ["Mod+PageUp", "prev-tab", ""],
    ["Mod+PageDown", "next-tab", ""],
    ["Alt+ArrowLeft", "prev-tab", ""],
    ["Alt+ArrowRight", "next-tab", ""],
    ["Mod+1", "tab:sightings", ""],
    ["Mod+2", "tab:effort", ""],
    ["Mod+3", "tab:events", ""],
    ["Mod+4", "tab:reports", ""],
    ["Mod+5", "tab:settings", ""],
    ["Mod+Shift+C", "center-vessel", ""],
    ["Mod+Shift+M", "toggle-log", ""],
]

# List entries added in later versions: put into existing list files once (if the
# user later deletes one, it stays deleted). Recorded in settings/list_rows_added.txt.
NEW_LIST_ROWS = {"event_types": ["Gear Reported", "Gear Recovered", "Other"], "species": ["Dead bird"]}
NEW_ACTIONS = {"toggle-log", "add-current"}
REMOVED_ACTIONS = {"cycle-latlon", "add:surfacings"}
# tabs renamed or merged in 0.7.0: existing shortcuts are pointed at the new tab
RENAMED_ACTIONS = {"tab:summary": "tab:reports", "tab:planning": "tab:route"}

DEFAULT_DISPLAY = {
    "marker_radius": "8",
    "label_size": "12",
    "track_width": "3",             # on-effort track width (px)
    "track_off_width": "1.5",       # off-effort track width (px): thinner, so on effort stands out
    "track_on_style": "solid",      # solid | dashed | dotted | dashdot
    "track_off_style": "solid",
    "grid_font_size": "13",
    "ui_font_size": "13",
    "sightings_marker_shape": "Diamond",
    "sightings_marker_color": "darkorange",
    "events_marker_shape": "Square",
    "events_marker_color": "royalblue",
    "marks_marker_shape": "Circle",
    "marks_marker_color": "purple",
    "track_on_effort_color": "#00a000",
    "track_off_effort_color": "#7a7a7a",
    "vessel_color": "#d00000",
    "use_species_colors": "1",
    "heading_vector": "1",          # draw the vessel heading vector
    "heading_vector_min": "6",      # its length: minutes ahead at the current speed
    "sighting_lines": "1",          # vectors from the vessel to each sighting
    "fieldid_lines": "0",           # dotted line joining sightings with the same FieldID
    "show_track_on": "1",
    "show_track_off": "1",
    "fade_enabled": "0",            # fade the track, sightings and events older than fade_hours (not waypoints)
    "fade_hours": "2",
}

DEFAULT_SETTINGS = {
    "tracking_enabled": False,
    "tracking_interval": 10,
    "track_break_kn": 30,           # break the trackline where it moves faster than this (0 = never)
    "track_break_gap_s": 120,       # … or where there are no points for this long (0 = never)
    "effort_reminder_min": 30,
    "latlon_format": "DDM",
    "timezone": "local",            # local | UTC | auto (from the position) | UTC±hh:mm
    "clock_zone_last": "",
    "check_updates_on_start": False,  # look on GitHub for a newer Spyhop when it starts (needs internet)          # the zone last found from the position (used until there's a fix)
    "bearing_reference": "M",
    "distance_unit": "nm",
    "mag_variation": "auto",
    "view": "split-v",
    "split_ratio": 0.6,
    "follow_vessel": True,
    "nmea_sources": [{"type": "udp", "port": 10110, "enabled": True}],
    "tile_cache_enabled": True,
    "last_version": "",          # the Spyhop version that last ran (to say when it was updated)
    "nmea_log_enabled": False,   # write every received NMEA sentence to <data folder>/nmea_logs
    "nmea_log_timestamps": True,
    "data_dir": "",          # survey data folder; "" = the "data" folder inside Spyhop's folder
    "last_meta": {},         # survey details used last time, offered for the next survey
}

DEFAULT_TILE_SOURCES = ["name", "url", "attribution", "overlay", "max_zoom"], [
    ["OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "© OpenStreetMap contributors", "0", "19"],
    ["Esri Ocean", "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
     "Esri, GEBCO, NOAA, Garmin, HERE", "0", "13"],
    ["Esri Imagery", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
     "Esri, Maxar, Earthstar Geographics", "0", "18"],
    ["NOAA charts (tiled)", "https://gis.charttools.noaa.gov/arcgis/rest/services/MarineChart_Services/NOAACharts/MapServer/tile/{z}/{y}/{x}",
     "NOAA Office of Coast Survey", "0", "18"],
    ["NOAA charts (dynamic)", "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/MapServer/export?bbox={bbox}&bboxSR=3857&imageSR=3857&size=256,256&format=png&transparent=true&f=image",
     "NOAA Office of Coast Survey", "0", "18"],
    ["OpenSeaMap seamarks", "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
     "© OpenSeaMap contributors", "1", "18"],
]


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(fh)]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


class Config:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.settings_dir = self.root / "settings"
        self.charts_dir = self.root / "charts"
        self.overlays_dir = self.root / "overlays"
        self.tile_cache_dir = self.root / "tile_cache"
        for d in (self.root, self.settings_dir, self.charts_dir, self.overlays_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.ensure_defaults()
        self._add_new_list_rows()
        self.settings = self.load_settings()
        self.notices: list[str] = []
        self._resolve_data_dir()
        self.reload()

    # -- survey data folder (survey CSVs, waypoints, exports) ------------------------
    @property
    def default_data_dir(self) -> Path:
        return self.root / "data"

    def _resolve_data_dir(self):
        chosen = (self.settings.get("data_dir") or "").strip()
        p = Path(chosen).expanduser() if chosen else self.default_data_dir
        if chosen and not p.is_dir():
            # e.g. a USB drive or network share that isn't connected: don't create it silently
            self.notices.append(f"The data folder {p} wasn't found (is the drive connected?). "
                                f"Using {self.default_data_dir} for now — change it in the Survey tab.")
            p = self.default_data_dir
        p.mkdir(parents=True, exist_ok=True)
        self.data_dir = p

    @property
    def export_dir(self) -> Path:
        d = self.data_dir / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def set_data_dir(self, path: str) -> Path:
        raw = (path or "").strip()
        if not raw:
            p = self.default_data_dir
        else:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                raise ValueError("Please give the full path of the folder (e.g. /Users/you/Surveys).")
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".spyhop-write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            raise ValueError(f"Can't use {p} as the data folder: {e}")
        self.data_dir = p
        self.save_settings({"data_dir": "" if p == self.default_data_dir else str(p)})
        return p

    # -- files ---------------------------------------------------------------
    def list_path(self, name: str) -> Path:
        return self.root / f"{name}.csv"

    def ensure_defaults(self):
        for name, (hdr, rows) in DEFAULT_LISTS.items():
            p = self.list_path(name)
            if not p.exists():
                _write_csv(p, hdr, rows)
            else:
                self._add_missing_list_columns(p, hdr, rows)
        p = self.root / "shortcuts.csv"
        if not p.exists():
            _write_csv(p, *DEFAULT_SHORTCUTS)
        else:
            # add shortcuts for actions introduced in later versions to an existing file
            rows = _read_csv(p)
            have = {r.get("action") for r in rows}
            new = [r for r in DEFAULT_SHORTCUTS[1] if r[1] in NEW_ACTIONS and r[1] not in have]
            keep = [r for r in rows if r.get("action") not in REMOVED_ACTIONS]
            renamed = False
            for r in keep:
                if r.get("action") in RENAMED_ACTIONS:
                    r["action"] = RENAMED_ACTIONS[r["action"]]
                    renamed = True
            if new or renamed or len(keep) != len(rows):
                _write_csv(p, DEFAULT_SHORTCUTS[0],
                           [[r.get("combo", ""), r.get("action", ""), r.get("prefill", "")] for r in keep] + new)
        p = self.root / "display.csv"
        if not p.exists():
            _write_csv(p, ["key", "value"], [[k, v] for k, v in DEFAULT_DISPLAY.items()])
        p = self.root / "tile_sources.csv"
        if not p.exists():
            _write_csv(p, *DEFAULT_TILE_SOURCES)
        readme = self.charts_dir / "README.txt"
        if not readme.exists():
            readme.write_text(
                "Put offline chart or basemap tiles here as .mbtiles files (raster PNG/JPEG tiles).\n"
                "Each file appears in the map's layer menu after restarting Spyhop.\n\n"
                "Free NOAA nautical charts for US waters (updated weekly):\n"
                "  https://distribution.charts.noaa.gov/ncds/  -> click a region -> download the MBTiles file.\n")

    def _add_new_list_rows(self):
        marker = self.settings_dir / "list_rows_added.txt"
        try:
            done = set(marker.read_text(encoding="utf-8").splitlines())
        except OSError:
            done = set()
        todo = {(lst, n) for lst, names in NEW_LIST_ROWS.items() for n in names if f"{lst}:{n}" not in done}
        if not todo:
            return
        for lst in {l for l, _ in todo}:
            hdr, defaults = DEFAULT_LISTS[lst]
            p = self.list_path(lst)
            try:
                with open(p, newline="", encoding="utf-8-sig") as fh:
                    rows = list(csv.reader(fh))
            except OSError:
                continue
            if not rows or "name" not in [h.strip() for h in rows[0]]:
                continue
            have_hdr = [h.strip() for h in rows[0]]
            ni = have_hdr.index("name")
            names = {r[ni].strip().lower() for r in rows[1:] if ni < len(r)}
            by_name = {d[0]: dict(zip(hdr, d)) for d in defaults}
            body = rows[1:]
            for n in NEW_LIST_ROWS[lst]:
                if (lst, n) not in todo or n.lower() in names:
                    continue
                new = [by_name.get(n, {}).get(h, n if h == "name" else "") for h in have_hdr]
                # new entries go before "Other", so Other stays last
                at = next((i for i, r in enumerate(body) if ni < len(r) and r[ni].strip().lower() == "other"), len(body))
                body.insert(at, new)
                names.add(n.lower())
            _write_csv(p, have_hdr, body)
        try:
            marker.write_text("\n".join(sorted(done | {f"{l}:{n}" for l, n in todo})) + "\n", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _add_missing_list_columns(p: Path, hdr: list[str], defaults: list[list[str]]):
        """Add columns introduced in later versions (e.g. event_code) to a user's list
        file, filling them from the defaults where the name matches. Keeps their edits."""
        try:
            with open(p, newline="", encoding="utf-8-sig") as fh:
                r = csv.reader(fh)
                have = next(r, [])
                body = [row for row in r]
        except OSError:
            return
        have_clean = [h.strip() for h in have]
        missing = [h for h in hdr if h not in have_clean]
        if not missing or "name" not in have_clean:
            return
        by_name = {d[0]: dict(zip(hdr, d)) for d in defaults}
        ni = have_clean.index("name")
        out = []
        for row in body:
            name = row[ni].strip() if ni < len(row) else ""
            out.append(row + [by_name.get(name, {}).get(h, "") for h in missing])
        _write_csv(p, have_clean + missing, out)

    def reload(self):
        self.lists: dict[str, list[dict]] = {}
        for name in DEFAULT_LISTS:
            try:
                self.lists[name] = [r for r in _read_csv(self.list_path(name)) if r.get("name")]
            except FileNotFoundError:
                self.lists[name] = []
        try:
            self.shortcuts = [r for r in _read_csv(self.root / "shortcuts.csv") if r.get("combo")]
        except FileNotFoundError:
            self.shortcuts = []
        display = dict(DEFAULT_DISPLAY)
        try:
            for r in _read_csv(self.root / "display.csv"):
                if r.get("key"):
                    display[r["key"]] = r.get("value", "")
        except FileNotFoundError:
            pass
        self.display = display
        try:
            self.tile_sources = [r for r in _read_csv(self.root / "tile_sources.csv")
                                 if r.get("name") and r.get("url")]
        except FileNotFoundError:
            self.tile_sources = []
        self.mbtiles = sorted(p.name for p in self.charts_dir.glob("*.mbtiles"))

    def save_display(self, updates: dict):
        self.display.update({k: str(v) for k, v in updates.items()})
        _write_csv(self.root / "display.csv", ["key", "value"],
                   [[k, v] for k, v in self.display.items()])

    # -- settings --------------------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return self.settings_dir / "settings.json"

    def load_settings(self) -> dict:
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        try:
            s.update(json.loads(self.settings_path.read_text()))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        s.pop("surfacings_enabled", None)
        s["timezone"] = clean_timezone(s.get("timezone"))
        return s

    def save_settings(self, updates: dict | None = None):
        if updates and "timezone" in updates:
            updates = {**updates, "timezone": clean_timezone(updates["timezone"])}
        if updates:
            for k, v in updates.items():
                if k in DEFAULT_SETTINGS:
                    self.settings[k] = v
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, indent=2))
        os.replace(tmp, self.settings_path)

    # -- survey name -----------------------------------------------------------
    @property
    def survey_file(self) -> Path:
        return self.settings_dir / "current_survey.txt"

    def current_survey(self) -> dict | None:
        try:
            data = json.loads(self.survey_file.read_text())
            if data.get("data_dir") and Path(data["data_dir"]) != self.data_dir:
                return None          # it belongs to a different data folder
            return data if data.get("prefix") else None
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def set_current_survey(self, survey: dict | None):
        if survey is None:
            if self.survey_file.exists():
                self.survey_file.unlink()
            return
        self.survey_file.write_text(json.dumps({**survey, "data_dir": str(self.data_dir)}))

    def public(self) -> dict:
        lists = {k: v for k, v in self.lists.items()}
        return {
            "lists": lists,
            "shortcuts": self.shortcuts,
            "display": self.display,
            "settings": self.settings,
            "tile_sources": self.tile_sources,
            "mbtiles": self.mbtiles,
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "default_data_dir": str(self.default_data_dir),
        }
