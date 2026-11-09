"""Data folder layout, user-editable config CSVs, and settings."""
from __future__ import annotations

import csv
import json
import os
import platform
import re
from pathlib import Path

APP_DIR_NAME = "Spyhop"


def _base_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def clean_timezone(v) -> str:
    """Settings → General → Clock: 'local' (the computer's), 'UTC', 'auto' (from the platform's position)
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
    """Spyhop's own folder (SPYHOP_DATA_DIR, else the system's place for application data)."""
    env = os.environ.get("SPYHOP_DATA_DIR")
    return Path(env).expanduser() if env else _base_dir() / APP_DIR_NAME


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
    "behaviors": (["name", "behavior_code", "definition"], [
        ["Travel", "TR", "Moving steadily in one direction, with regular surfacings and dives."],
        ["Mill", "MI", "Moving slowly in changing directions, with no clear heading; not obviously feeding or resting."],
        ["Feed", "FE", "Feeding seen or strongly suggested (prey at the surface, birds working, defecation), depth unknown."],
        ["Surface feed", "SF", "Feeding at the surface: mouth open, lunging or gulping prey at or near the surface."],
        ["Subsurface feed", "SS", "Feeding below the surface: repeated long, regular dives in one area, often with fluke-up dives."],
        ["Bubble net", "BN", "Bubbles blown in a ring, cloud or line to trap prey, usually followed by a vertical lunge."],
        ["Skim feed", "SK", "Swimming slowly at the surface with the mouth open, filtering prey (e.g. right whales skimming copepods)."],
        ["Rest / log", "RE", "Lying still or nearly still at the surface (logging), with little or no forward movement."],
        ["Social / SAG", "SO", "Interacting with other animals: physical contact, rolling, chasing; a surface active group (SAG)."],
        ["Breach", "BR", "Leaping clear of the water, or nearly so, and landing with a splash."],
        ["Flipper slap", "FS", "Raising a pectoral flipper and slapping it on the water."],
        ["Tail slap / lobtail", "TS", "Raising the flukes and slapping them on the water."],
        ["Fluke-up dive", "FU", "Diving with the flukes raised clear of the water, usually a deep or long dive."],
        ["Fluke-down dive", "FD", "Diving without showing the flukes, usually a shallow or short dive."],
        ["Nursing", "NU", "A calf positioned under or beside its mother's belly, apparently nursing."],
        ["Bow riding", "BO", "Riding the pressure wave at a vessel's bow or in its wake."],
        ["Avoidance", "AV", "Moving away from the vessel, changing heading or diving as the vessel approaches."],
        ["Approach vessel", "AP", "Moving toward the vessel or staying close beside it."],
        ["Entangled", "EN", "Fishing gear, line or debris seen on the animal."],
        ["Other", "OT", "A behavior not in this list: describe it in Comments."],
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
    ["Mod+Shift+L", "add-resight", ""],
    ["Mod+Shift+U", "undo", ""],
    ["Mod+Shift+Y", "redo", ""],
    ["Mod+PageUp", "prev-tab", ""],
    ["Mod+PageDown", "next-tab", ""],
    ["Alt+ArrowLeft", "prev-tab", ""],
    ["Alt+ArrowRight", "next-tab", ""],
    ["Mod+1", "tab:sightings", ""],
    ["Mod+2", "tab:effort", ""],
    ["Mod+3", "tab:events", ""],
    ["Mod+4", "tab:summary", ""],
    ["Mod+5", "tab:settings", ""],
    ["Mod+Shift+C", "center-vessel", ""],
    ["Mod+Shift+M", "toggle-log", ""],
]

# what each list's columns are called in Settings → Dropdowns, and which must be unique
LIST_COLUMNS = {
    "species": {"name": "Name", "species_code": "Code", "color": "Color"},
    "event_types": {"name": "Name", "event_code": "Code", "color": "Color"},
    "behaviors": {"name": "Name", "behavior_code": "Code", "definition": "Definition"},
    "observers": {"name": "Initials", "full_name": "Full name"},
}
UNIQUE_COLUMNS = {"name", "species_code", "event_code", "behavior_code"}
SHORTCUT_VERBS = {"add", "tab"}            # verbs that take ":<argument>"
SHORTCUT_ACTIONS = {"add-current", "add-resight", "toggle-effort", "undo", "redo", "next-tab", "prev-tab",
                    "center-vessel", "toggle-log", "max-log", "measure"}
_COLOR = re.compile(r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[a-zA-Z]{3,30})$")
_MODS = {"mod": "Mod", "cmd": "Mod", "ctrl": "Mod", "shift": "Shift", "alt": "Alt", "option": "Alt"}


def clean_combo(combo: str) -> str:
    """'shift+mod+r' → 'Mod+Shift+R'. Raises ValueError for a combination that can't work."""
    parts = [x.strip() for x in str(combo or "").split("+")]
    if len(parts) > 1 and parts[-1] == "" and parts[-2] == "":      # "Mod++" means the + key
        parts = parts[:-2] + ["+"]
    if not parts or not parts[-1]:
        raise ValueError("no key")
    key, mods = parts[-1], set()
    for m in parts[:-1]:
        if m.lower() not in _MODS:
            raise ValueError(f"“{m}” isn't Mod, Shift or Alt")
        mods.add(_MODS[m.lower()])
    if len(key) == 1:
        key = key.upper()
    elif re.fullmatch(r"[fF]([1-9]|1[0-9]|2[0-4])", key):
        key = key.upper()
    if not ({"Mod", "Alt"} & mods) and not re.fullmatch(r"F\d+", key):
        raise ValueError("needs Mod or Alt (or use F1–F12), so it doesn't get in the way of typing")
    return "+".join([m for m in ("Mod", "Shift", "Alt") if m in mods] + [key])


DEFAULT_DISPLAY = {
    "marker_radius": "8",
    "label_size": "12",
    "track_width": "3",             # on-effort track width (px)
    "track_off_width": "1.5",       # off-effort track width (px): thinner, so on effort stands out
    "track_on_style": "solid",      # solid | dashed | dotted | dashdot
    "track_off_style": "solid",
    "grid_font_size": "13",
    "ui_font_size": "13",
    "status_font_size": "13",       # the status bar along the top
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
    "sightings_row_colors": "resights",  # Sightings rows: none | alternate | resights (tint resights) | groups (a tint per sighting and its resights)
    "resight_order": "time",        # Sightings table: time (as recorded) | nested (resights under their first sighting)
    "resight_lines": "1",           # dotted line from a sighting through its resights, in time order
    "resight_marker_shape": "same", # resights' marker: same (as the sighting) | a shape | hidden
    "resight_marker_fill": "hollow",  # hollow (outline in the sighting's color) | filled | faded
    "resight_marker_size": "70",    # % of the sightings' marker size
    "resight_labels": "0",          # label resight markers too
    "show_track_on": "1",
    "show_track_off": "1",
    "fade_enabled": "0",            # fade the track, sightings and events older than fade_hours (not waypoints)
    "fade_hours": "2",
    "overlay_colors": "{}",         # colors chosen in Tools → Overlays: JSON {file: "#rrggbb"}
}

DEFAULT_SETTINGS = {
    # --- shared: kept in templates/current/spyhop-config.json and carried by templates (SHARED_SETTINGS)
    "latlon_format": "DDM",
    "timezone": "local",            # local | UTC | auto (from the position) | UTC±hh:mm
    "bearing_reference": "M",
    "distance_unit": "nm",
    "mag_variation": "auto",
    "tracking_interval": 10,
    "track_break_kn": 30,           # break the trackline where it moves faster than this (0 = never)
    "track_break_gap_s": 120,       # … or where there are no points for this long (0 = never)
    "effort_reminder_min": 30,
    "keep_awake": "survey",         # stop the computer sleeping: off | survey (while one is active) | always
    "keep_screen_on": False,        # … and keep the screen on too
    "nmea_log_enabled": False,      # write every received NMEA sentence to <data folder>/nmea_logs
    "nmea_log_timestamps": True,
    "altitude_column": "auto",      # Sightings' Alt column: auto (shown for aerial surveys) | show | hide
    "segment_column": "show",       # Effort's Seg (effort segment) column: show | hide
    "column_layout": {},            # this computer's column order and widths: {tab: {order: [keys], widths: {key: px}}}
    "reticle_method": "binoculars", # how Unit = reticle readings are taken: binoculars | marks | inclinometer (reticle.py)
    "reticle_magnification": "7",   # binoculars: a key of reticle.PRESETS, which suggests the angle below
    "reticle_deg_per_division": 0.573,   # binoculars: degrees per reticle division
    "reticle_marks": [],            # calibrated marks: [{mark, angle (degrees below the horizontal)}]
    # --- also in spyhop-config.json, under their own keys (see CONFIG_KEYS)
    "online_feeds": [],             # map feeds (Settings → Inputs → Online overlays; feeds.py) → map_feeds
    "online_display": {},           # online overlays to show, set by a template: {ais, radar_us, radar_world,
                                    # feeds: [urls], radar_opacity, hide_stopped, stamp}; applied once per stamp
    "nmea_sources": [{"type": "udp", "port": 10110, "enabled": True}],
                                    # all inputs in order (spyhop-local.json); the network ones (UDP, TCP, gpsd)
                                    # are also nmea_inputs in spyhop-config.json, which wins when they differ
    # --- this computer only: spyhop-local.json
    "data_dir": "",                 # survey data folder; "" = the "data" folder inside Spyhop's folder
    "last_meta": {},                # survey details used last time, offered for the next survey
    "tracking_enabled": False,
    "clock_zone_last": "",          # the zone last found from the position (used until there's a fix)
    "check_updates_on_start": False,  # look on GitHub for a newer Spyhop when it starts (needs internet)
    "view": "split-v",
    "split_ratio": 0.6,
    "follow_vessel": True,
    "tile_cache_enabled": True,
    "last_version": "",             # the Spyhop version that last ran (to say when it was updated)
    "template_url": "",             # web address of the team's template (templates.py)
    "template_backup": True,        # save a backup (templates/backups) of the current template before using another
    "template_last": {},            # the last one from the web: {url, pulled, latest: {date, by, changed, notes}, changed}
    "template_author": "",          # the name last given when saving a template
    "template_current": {},         # the saved template the current template came from or was saved to: {name, how: loaded|saved|backup, when}
    "template_fingerprints": {},    # {from: use|save, when, files: {part: sha1}}: to list what changed since
    "template_added": {},           # what each template used added, by the backup made before it: {backup: {waypoints:
                                    # [RowIDs], routes, overlays, feeds}}, so restoring that backup removes them
}

# settings a team shares, with their names in the check before using a template
SHARED_SETTINGS = {
    "latlon_format": "Lat/lon format",
    "timezone": "Clock",
    "bearing_reference": "Bearing reference",
    "distance_unit": "Distance unit",
    "mag_variation": "Magnetic variation",
    "tracking_interval": "Track point every (s)",
    "track_break_kn": "Break the track above (kn)",
    "track_break_gap_s": "Break the track after a gap of (s)",
    "effort_reminder_min": "Effort reminder (min)",
    "keep_awake": "Keep the computer awake",
    "keep_screen_on": "Keep the screen on",
    "nmea_log_enabled": "Raw NMEA log",
    "nmea_log_timestamps": "Raw NMEA log time stamps",
    "altitude_column": "Altitude column",
    "segment_column": "Effort segment column",
    "reticle_method": "Reticle readings",
    "reticle_magnification": "Binocular magnification",
    "reticle_deg_per_division": "Degrees per reticle division",
    "reticle_marks": "Calibrated marks",
}
NETWORK_INPUTS = ("udp", "tcp", "gpsd")       # the GPS / NMEA inputs a template carries

# Spyhop's folder:
#   templates/current/   the current template: LIST_FILES, shortcuts.csv and spyhop-config.json (a template, unzipped)
#   templates/saved/     templates (<name>.spyhop-template.zip)
#   templates/backups/   the current template as it was before another was used
#   spyhop-local.json    this computer's own settings and the open survey
#   charts/ overlays/ routes/ feeds/ tile_cache/ logs/ data/ (the default survey data folder)
CONFIG_FILE = "spyhop-config.json"
LOCAL_FILE = "spyhop-local.json"
TEMPLATE_FORMAT = 3

DEFAULT_TILE_SOURCES = ["name", "url", "attribution", "overlay", "max_zoom", "kind"], [
    # kind "style": a MapLibre style (vector tiles), drawn with MapLibre GL and cached like the rest
    ["Seascape depths (feet)", "https://tiles.openwaters.io/seascape/style.json?unit=ft",
     "Seascape by Open Waters (CC BY 4.0), © OpenStreetMap contributors — not for navigation", "0", "22", "style"],
    ["Esri Ocean", "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
     "Esri, GEBCO, NOAA, Garmin, HERE", "0", "13", "raster"],
    ["Esri Imagery", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
     "Esri, Maxar, Earthstar Geographics", "0", "18", "raster"],
    ["NOAA charts", "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/MapServer/export?bbox={bbox}&bboxSR=3857&imageSR=3857&size=256,256&format=png&transparent=true&f=image",
     "NOAA Office of Coast Survey", "0", "18", "raster"],
    ["OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "© OpenStreetMap contributors", "0", "19", "raster"],
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
    """Spyhop's folder: the current template (templates/current), this computer's settings
    (spyhop-local.json) and the other folders. Settings are one dict in memory (self.settings);
    save_settings() writes the shared ones to spyhop-config.json and the rest to spyhop-local.json."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.templates_root = self.root / "templates"
        self.current_dir = self.templates_root / "current"
        self.saved_dir = self.templates_root / "saved"
        self.backups_dir = self.templates_root / "backups"
        self.charts_dir = self.root / "charts"
        self.overlays_dir = self.root / "overlays"
        self.routes_dir = self.root / "routes"          # saved routes (Tools → Routes), one GPX file each
        self.tile_cache_dir = self.root / "tile_cache"
        self.notices: list[str] = []
        self.root.mkdir(parents=True, exist_ok=True)
        from .layout import move_old_layout             # the 0.27 layout, moved once (removed before 1.0)
        move_old_layout(self)
        for d in (self.current_dir, self.saved_dir, self.backups_dir, self.charts_dir, self.overlays_dir, self.routes_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.ensure_defaults()
        self.load()
        self._resolve_data_dir()
        from .layout import tidy_data_folder
        tidy_data_folder(self)
        self.reload()

    # -- paths -----------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.current_dir / CONFIG_FILE

    @property
    def local_path(self) -> Path:
        return self.root / LOCAL_FILE

    def list_path(self, name: str) -> Path:
        return self.current_dir / f"{name}.csv"

    @property
    def shortcuts_path(self) -> Path:
        return self.current_dir / "shortcuts.csv"

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
                                f"Using {self.default_data_dir} for now — change it in Settings → General.")
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
        from .layout import tidy_data_folder
        tidy_data_folder(self)
        return p

    # -- the current template: templates/current -----------------------------------
    def ensure_defaults(self):
        for name, (hdr, rows) in DEFAULT_LISTS.items():
            if not self.list_path(name).exists():
                _write_csv(self.list_path(name), hdr, rows)
        if not self.shortcuts_path.exists():
            _write_csv(self.shortcuts_path, *DEFAULT_SHORTCUTS)
        if not self.config_path.exists():
            reps = {}
            for p in sorted((Path(__file__).parent / "report_defs").glob("*.json")):     # the starting reports
                try:
                    reps[p.name] = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            _write_json(self.config_path, {"spyhop_template": TEMPLATE_FORMAT, "history": [], "reports": reps})
        readme = self.charts_dir / "README.txt"
        if not readme.exists():
            self.charts_dir.mkdir(parents=True, exist_ok=True)
            readme.write_text(
                "Offline charts and maps, as .mbtiles files. Areas downloaded in Spyhop (Settings -> Basemap)\n"
                "are saved here, one file per area; you can also add MBTiles files of\n"
                "raster PNG/JPEG tiles. Each file appears under Offline map tiles in the map's layers menu (after\n"
                "\"Refresh\" in that section, or a restart). Copy a file to another computer's charts\n"
                "folder to use it there.\n\n"
                "Free NOAA nautical charts for US waters (updated weekly):\n"
                "  https://distribution.charts.noaa.gov/ncds/  -> click a region -> download the MBTiles file.\n")

    def list_header(self, name: str) -> list[str]:
        """The columns of a list file as they are now (known ones first)."""
        known = DEFAULT_LISTS[name][0]
        try:
            with open(self.list_path(name), newline="", encoding="utf-8-sig") as fh:
                have = [h.strip() for h in next(csv.reader(fh), []) if h.strip()]
        except OSError:
            have = []
        return known + [h for h in have if h not in known]

    def save_list(self, name: str, rows: list[dict]) -> list[dict]:
        """Replace a drop-down list (Settings → Dropdowns). Raises ValueError listing the problems."""
        if name not in DEFAULT_LISTS:
            raise ValueError("Unknown list")
        hdr = self.list_header(name)
        cols = LIST_COLUMNS[name]
        out, problems, seen = [], [], {c: {} for c in hdr if c in UNIQUE_COLUMNS}
        for i, r in enumerate(rows or [], 1):
            row = {c: str((r or {}).get(c, "") or "").strip() for c in hdr}
            if not any(row.values()):
                continue                                    # a blank row is simply dropped
            if not row["name"]:
                problems.append(f"Row {i}: {cols['name']} is empty.")
            if row.get("color") and not _COLOR.match(row["color"]):
                problems.append(f"Row {i}: “{row['color']}” isn't a color (use a name like red, or #rrggbb).")
            for c, prev in seen.items():
                v = row.get(c, "").lower()
                if v and v in prev:
                    problems.append(f"Row {i}: {cols.get(c, c)} “{row[c]}” is already used in row {prev[v]}.")
                elif v:
                    prev[v] = i
            out.append(row)
        if not out:
            problems.append("The list can't be empty.")
        if problems:
            raise ValueError("\n".join(problems[:12]) + (f"\n… and {len(problems) - 12} more." if len(problems) > 12 else ""))
        _write_csv(self.list_path(name), hdr, [[r[c] for c in hdr] for r in out])
        self.reload()
        return out

    def save_shortcuts(self, rows: list[dict], tabs: dict | None = None) -> list[dict]:
        """Replace the keyboard shortcuts (Settings → Shortcuts). `tabs` maps data tabs to their column keys,
        to check pre-fills. Raises ValueError listing the problems."""
        out, problems, seen = [], [], {}
        for i, r in enumerate(rows or [], 1):
            combo, action, prefill = (str((r or {}).get(k, "") or "").strip() for k in ("combo", "action", "prefill"))
            if not combo and not action and not prefill:
                continue
            try:
                combo = clean_combo(combo)
            except ValueError as e:
                problems.append(f"Row {i}: the keys {combo or '(none)'} — {e}.")
            verb, _, arg = action.partition(":")
            if not (action in SHORTCUT_ACTIONS or (verb in SHORTCUT_VERBS and re.fullmatch(r"[a-z_]+", arg or ""))):
                problems.append(f"Row {i}: “{action or '(none)'}” isn't an action Spyhop knows.")
            if verb == "add" and tabs is not None and arg not in tabs:
                problems.append(f"Row {i}: there's no {arg} table to add a row to.")
            if prefill:
                for part in prefill.split(";"):
                    k, eq, v = part.partition("=")
                    if not part.strip():
                        continue
                    if not eq or not k.strip():
                        problems.append(f"Row {i}: pre-fill “{part.strip()}” should look like Column=value.")
                    elif verb == "add" and tabs and arg in tabs and k.strip() not in tabs[arg]:
                        problems.append(f"Row {i}: the {arg} table has no column “{k.strip()}”.")
                    elif not (verb == "add" or action == "add-current"):
                        problems.append(f"Row {i}: only shortcuts that add a row can pre-fill columns.")
                        break
            key = combo.lower()
            if key in seen:
                problems.append(f"Row {i}: {combo} is already used in row {seen[key]}.")
            else:
                seen[key] = i
            out.append({"combo": combo, "action": action, "prefill": prefill})
        if problems:
            raise ValueError("\n".join(problems[:12]) + (f"\n… and {len(problems) - 12} more." if len(problems) > 12 else ""))
        _write_csv(self.shortcuts_path, DEFAULT_SHORTCUTS[0], [[r["combo"], r["action"], r["prefill"]] for r in out])
        self.reload()
        return out

    def reload(self):
        """Read the lists and shortcuts again (they're CSV files in templates/current)."""
        self.lists: dict[str, list[dict]] = {}
        for name in DEFAULT_LISTS:
            try:
                self.lists[name] = [r for r in _read_csv(self.list_path(name)) if r.get("name")]
            except FileNotFoundError:
                self.lists[name] = []
        try:
            self.shortcuts = [r for r in _read_csv(self.shortcuts_path) if r.get("combo")]
        except FileNotFoundError:
            self.shortcuts = []
        # the online map layers are defined in code, so fixes arrive with updates
        hdr = DEFAULT_TILE_SOURCES[0]
        self.tile_sources = [dict(zip(hdr, r)) for r in DEFAULT_TILE_SOURCES[1]]
        extra = os.environ.get("SPYHOP_EXTRA_TILE_SOURCES")      # tests only: a CSV of more layers (same columns)
        if extra:
            try:
                self.tile_sources += [r for r in _read_csv(Path(extra)) if r.get("name") and r.get("url")]
            except OSError:
                pass
        self.mbtiles = sorted(p.name for p in self.charts_dir.glob("*.mbtiles"))

    # -- settings, map display, saved reports and the record of changes --------
    def load(self):
        """Read spyhop-local.json and templates/current/spyhop-config.json into settings, display,
        reports and history."""
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        local = _read_json(self.local_path)
        loc = local.get("settings") if isinstance(local.get("settings"), dict) else {}
        s.update({k: v for k, v in loc.items() if k in DEFAULT_SETTINGS and k not in SHARED_SETTINGS})
        self.survey_record = local.get("current_survey") if isinstance(local.get("current_survey"), dict) else None
        doc = _read_json(self.config_path)
        self.doc = doc
        shared = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
        s.update({k: v for k, v in shared.items() if k in SHARED_SETTINGS})
        if isinstance(doc.get("map_feeds"), list):
            s["online_feeds"] = [f for f in doc["map_feeds"] if isinstance(f, dict)]
        if isinstance(doc.get("online_overlays"), dict):
            s["online_display"] = doc["online_overlays"]
        if isinstance(doc.get("nmea_inputs"), list):
            s["nmea_sources"] = merge_network_inputs(s.get("nmea_sources") or [], doc["nmea_inputs"])
        s["timezone"] = clean_timezone(s.get("timezone"))
        self.settings = s
        display = dict(DEFAULT_DISPLAY)
        if isinstance(doc.get("map_display"), dict):
            display.update({str(k): str(v) for k, v in doc["map_display"].items()})
        self.display = display
        self.reports = {str(k): v for k, v in doc["reports"].items()} if isinstance(doc.get("reports"), dict) else {}
        self.history = [e for e in doc.get("history") or [] if isinstance(e, dict)]

    def _config_doc(self) -> dict:
        """templates/current/spyhop-config.json as it should be now."""
        s = self.settings
        doc = {k: v for k, v in self.doc.items()
               if k not in ("settings", "nmea_inputs", "map_feeds", "online_overlays", "map_display", "reports", "history")}
        doc.update({
            "spyhop_template": TEMPLATE_FORMAT,
            "history": self.history,
            "settings": {k: s.get(k) for k in SHARED_SETTINGS},
            "nmea_inputs": [dict(x) for x in s.get("nmea_sources") or [] if isinstance(x, dict) and x.get("type") in NETWORK_INPUTS],
            "map_feeds": s.get("online_feeds") or [],
            "map_display": dict(self.display),
            "reports": self.reports,
        })
        if s.get("online_display"):
            doc["online_overlays"] = s["online_display"]
        return doc

    def save(self):
        """Write both files from what's in memory."""
        self.doc = self._config_doc()
        _write_json(self.config_path, self.doc)
        local = {k: v for k, v in self.settings.items() if k not in SHARED_SETTINGS
                 and k not in ("online_feeds", "online_display")}
        _write_json(self.local_path, {"settings": local, "current_survey": self.survey_record})

    def save_settings(self, updates: dict | None = None):
        if updates and "timezone" in updates:
            updates = {**updates, "timezone": clean_timezone(updates["timezone"])}
        if updates and "keep_awake" in updates and updates["keep_awake"] not in ("off", "survey", "always"):
            updates = {**updates, "keep_awake": "survey"}
        for k, v in (updates or {}).items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = v
        self.save()

    def save_display(self, updates: dict, replace: bool = False):
        self.display = dict(DEFAULT_DISPLAY) if replace else self.display
        self.display.update({k: str(v) for k, v in updates.items()})
        self.save()

    def save_reports(self, reports: dict):
        self.reports = dict(reports)
        self.save()

    def save_history(self, history: list[dict]):
        self.history = list(history)
        self.save()

    def shared_settings(self) -> dict:
        return {k: self.settings.get(k) for k in SHARED_SETTINGS}

    # -- the open survey ---------------------------------------------------------
    def current_survey(self) -> dict | None:
        data = self.survey_record
        if not data or not data.get("prefix"):
            return None
        if data.get("data_dir") and Path(data["data_dir"]) != self.data_dir:
            return None          # it belongs to a different data folder
        return data

    def set_current_survey(self, survey: dict | None):
        self.survey_record = None if survey is None else {**survey, "data_dir": str(self.data_dir)}
        self.save()

    def public(self) -> dict:
        return {
            "lists": dict(self.lists),
            "shortcuts": self.shortcuts,
            "list_columns": {k: self.list_header(k) for k in DEFAULT_LISTS},
            "list_labels": LIST_COLUMNS,
            "default_shortcuts": [dict(zip(DEFAULT_SHORTCUTS[0], r)) for r in DEFAULT_SHORTCUTS[1]],
            "display": self.display,
            "settings": self.settings,
            "tile_sources": self.tile_sources,
            "mbtiles": self.mbtiles,
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "default_data_dir": str(self.default_data_dir),
            "current_dir": str(self.current_dir),
        }


def merge_network_inputs(mine: list[dict], network: list[dict]) -> list[dict]:
    """This computer's inputs with its network ones (UDP, TCP, gpsd) replaced by `network`, which go
    where the first network input was (serial ports, file replays and the simulator keep their places)."""
    mine = [dict(x) for x in mine if isinstance(x, dict)]
    first = next((i for i, x in enumerate(mine) if x.get("type") in NETWORK_INPUTS), None)
    rest = [x for x in mine if x.get("type") not in NETWORK_INPUTS]
    at = len(rest) if first is None else sum(1 for x in mine[:first] if x.get("type") not in NETWORK_INPUTS)
    return rest[:at] + [dict(x) for x in network if isinstance(x, dict) and x.get("type") in NETWORK_INPUTS] + rest[at:]


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_json(p: Path, d: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
