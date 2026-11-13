"""Data folder layout, user-editable config CSVs, and settings."""
from __future__ import annotations

import csv
import json
import os
import platform
import re
from pathlib import Path

from . import schema

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
        ["Vessel sighted", "gray", "VESL"],
        ["Marine debris", "sienna", "DEBR"],
        ["Fishing gear - reported", "darkorange", "GRPT"],
        ["Fishing gear - recovered", "chocolate", "GRCV"],
        ["Other", "black", "OTHR"],
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
        ["Mooring deployed", "teal", "MOOD"],
        ["Mooring recovered", "teal", "MOOR"],
        ["Plankton tow", "seagreen", "PLNK"],
        ["Other", "black", "OTH"],
    ]),
    "observers": (["name", "full_name"], [
        ["OBS1", "Observer 1"],
        ["OBS2", "Observer 2"],
        ["OBS3", "Observer 3"],
        ["OBS4", "Observer 4"],
        ["NA", "None"],             # an empty watch position: may fill several positions at once
        ["Other", "Someone not in this list (fill in after the survey)"],
    ]),
    # Effort values (0.39): status on/off decides plotting, reporting and the Error check; color = the track.
    # Start, End and ERROR are required (Start/End begin and end a survey; ERROR is added by Error check → Fix).
    "effort": (["name", "status", "definition", "color"], [
        ["Start", "off", "Survey began (the first row only).", "#7a7a7a"],
        ["ON", "on", "Observers are on watch.", "#00a000"],
        ["TRANSECT", "on", "Conducting a systematic line-transect survey.", "#1f6fd1"],
        ["DIRECTED", "on", "Conducting a directed survey or activity.", "#d97a00"],
        ["PHOTO-ID", "on", "Conducting a photo-ID survey.", "#9b30d9"],
        ["FOLLOW", "on", "Conducting a focal follow.", "#c0306a"],
        ["OFF", "off", "Observers are off watch.", "#7a7a7a"],
        ["Other", "off", "An effort value not in this list: fill in the right one after the survey.", "#a0a0a0"],
        ["End", "off", "Survey ended (the last row only; use End survey in the Survey tab).", "#7a7a7a"],
        ["ERROR", "off", "A trackline break (GPS jump or loss), added by Error check → Fix; not drawn or counted.", "#d00000"],
    ]),
    "visibility": (["name"], [["<0.5 nm"], ["0.5-1 nm"], ["1-2 nm"], ["2-5 nm"], ["5-10 nm"], [">10 nm"], ["Other"]]),
    "weather": (["name"], [["Clear"], ["Partly cloudy"], ["Overcast"], ["Haze"], ["Fog"], ["Mist"],
                           ["Drizzle"], ["Rain"], ["Showers"], ["Snow"], ["Other"]]),
    # how reticle distances are worked out (reticle.py): Unit = reticles-<name> on a sighting.
    # binoculars: magnification (a key of reticle.PRESETS, a suggestion) and degrees per division;
    # marks: evenly spaced calibrated marks, degrees between marks; inclinometer: the reading is the angle itself.
    "reticles": (["name", "method", "magnification", "deg_per_division"], [
        ["binos", "binoculars", "7", "0.573"],
        ["big-eyes", "binoculars", "25", "0.0771"],
        ["incl", "inclinometer", "", ""],
        ["Other", "other", "", ""],
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
        ["First surfacing", "SU", "The first time the animals are seen at the surface after a dive (the start of a surfacing). With a dive, it gives the dive time in Tools → Resights."],
        ["Nursing", "NU", "A calf positioned under or beside its mother's belly, apparently nursing."],
        ["Bow riding", "BO", "Riding the pressure wave at a vessel's bow or in its wake."],
        ["Avoidance", "AV", "Moving away from the vessel, changing heading or diving as the vessel approaches."],
        ["Approach vessel", "AP", "Moving toward the vessel or staying close beside it."],
        ["Entangled", "EN", "Fishing gear, line or debris seen on the animal."],
        ["Other", "OT", "A behavior not in this list: describe it in Notes, and fill in the right one after the survey."],
    ]),
}

# focus (0.51): the column selected in the new row of an add shortcut (blank: the first empty one)
DEFAULT_SHORTCUTS = ["combo", "action", "prefill", "focus"], [
    ["Mod+Enter", "add-current", "", ""],
    ["Mod+Shift+S", "add:sightings", "", ""],
    ["Mod+Shift+E", "add:effort", "", ""],
    ["Mod+Shift+F", "toggle-effort", "", ""],
    ["Mod+Shift+V", "add:events", "", ""],
    ["Mod+Shift+K", "add:marks", "", ""],
    ["Mod+Shift+R", "add:sightings", "Species=North Atlantic right whale", ""],
    ["Mod+Shift+H", "add:sightings", "Species=Humpback whale", ""],
    ["Mod+Shift+L", "add-resight", "", ""],
    ["Mod+Z", "undo", "", ""],
    ["Mod+Shift+Z", "redo", "", ""],
    ["Mod+PageUp", "prev-tab", "", ""],
    ["Mod+PageDown", "next-tab", "", ""],
    ["Alt+ArrowLeft", "prev-tab", "", ""],
    ["Alt+ArrowRight", "next-tab", "", ""],
    ["Mod+1", "tab:sightings", "", ""],
    ["Mod+2", "tab:effort", "", ""],
    ["Mod+3", "tab:events", "", ""],
    ["Mod+4", "tab:summary", "", ""],
    ["Mod+5", "tab:settings", "", ""],
    ["Mod+Shift+C", "center-vessel", "", ""],
    ["Mod+Shift+M", "toggle-log", "", ""],
]

# what each list's columns are called in Settings → Dropdowns, and which must be unique
LIST_COLUMNS = {
    "species": {"name": "Name", "species_code": "Code", "color": "Color"},
    "event_types": {"name": "Name", "event_code": "Code", "color": "Color"},
    "behaviors": {"name": "Name", "behavior_code": "Code", "definition": "Definition"},
    "observers": {"name": "Initials", "full_name": "Full name"},
    "effort": {"name": "Name", "status": "Status", "definition": "Definition", "color": "Color"},
    "visibility": {"name": "Visibility"},
    "weather": {"name": "Weather"},
    "reticles": {"name": "Name", "method": "How readings are taken", "magnification": "Magnification",
                 "deg_per_division": "Degrees per division"},
}
# lists that define what recorded values mean: none can change during an active survey
LOCKED_LISTS = ("species", "event_types", "observers", "behaviors", "effort", "visibility", "weather", "reticles")
# settings that change recorded or calculated data: locked during an active survey too
# (0.45: the trackline-break settings are gone: the trackline breaks only at ERROR rows in the Effort table)
LOCKED_SETTINGS = {"mag_variation": "Magnetic variation", "tracking_interval": "Track point every (s)"}
UNIQUE_COLUMNS = {"name", "species_code", "event_code", "behavior_code"}
# every drop-down list has "Other" (0.40): a placeholder for an entry that's missing from the list, which
# can't be added during a survey; the Error check lists the rows that use it, to fill in afterwards
OTHER = "Other"
COLOR_COLUMNS = {"color"}           # the only columns of a locked list that may change during a survey


def other_row(name: str) -> dict:
    """The default "Other" entry of a list."""
    hdr, rows = DEFAULT_LISTS[name]
    row = next(r for r in rows if r[0] == OTHER)
    return dict(zip(hdr, row))


def without_colors(rows) -> list[dict]:
    """A list's rows without their colors, to tell whether anything but colors changed."""
    return [{k: str(v or "").strip() for k, v in r.items() if k not in COLOR_COLUMNS} for r in rows or []]
SHORTCUT_VERBS = {"add", "tab"}            # verbs that take ":<argument>"
SHORTCUT_ACTIONS = {"add-current", "add-resight", "toggle-effort", "undo", "redo", "next-tab", "prev-tab",
                    "center-vessel", "toggle-log", "max-log", "measure"}
_COLOR = re.compile(r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[a-zA-Z]{3,30})$")
_MODS = {"mod": "Mod", "cmd": "Mod", "ctrl": "Mod", "shift": "Shift", "alt": "Alt", "option": "Alt"}


def _clean_reticle(row: dict) -> dict:
    """Check a reticles list entry; returns its cleaned columns. Raises ValueError saying what's wrong."""
    from . import reticle
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", row["name"]):
        raise ValueError("the name may use letters, digits, - _ and . only (no spaces): it becomes the Unit reticles-<name>.")
    method = row.get("method", "").strip().lower()
    if method not in reticle.METHODS:
        raise ValueError("choose how readings are taken: " + ", ".join(reticle.METHODS) + ".")
    out = {"method": method, "magnification": "", "deg_per_division": ""}
    if method == "other":                   # the placeholder: no distance is worked out
        return out
    if method in ("binoculars", "marks"):
        mag = row.get("magnification", "").strip() if method == "binoculars" else ""
        if mag and mag not in reticle.PRESETS:
            raise ValueError("the magnification is one of " + ", ".join(reticle.PRESETS) + " (or blank).")
        what = "degrees per reticle division (e.g. 0.573)" if method == "binoculars" else "degrees between marks (e.g. 5)"
        try:
            per = float(row.get("deg_per_division", "") or "x")
        except ValueError:
            raise ValueError(f"give the {what}.")
        if not 0 < per <= (10 if method == "binoculars" else 45):
            raise ValueError(f"the {what.split(' (')[0]} must be more than 0° and at most {10 if method == 'binoculars' else 45}°.")
        out.update(magnification=mag, deg_per_division=f"{per:g}")
    return out


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
    "vessel_color": "#d00000",
    "use_species_colors": "1",
    "heading_vector": "1",          # draw the vessel heading vector
    "heading_vector_min": "6",      # its length: minutes ahead at the current speed
    "sighting_lines": "1",          # vectors from the vessel to each sighting
    "sighting_lines_style": "dashed",   # solid | dashed | dotted | dashdot (util.LINE_STYLES)
    "sighting_lines_width": "1.5",
    "fieldid_lines_style": "dotted",
    "fieldid_lines_width": "2.5",
    "resight_lines_style": "dotted",
    "resight_lines_width": "2.5",
    "focus_selected": "1",          # pan the map to a sighting, event or waypoint selected in its table
    "fieldid_lines": "0",           # dotted line joining sightings with the same FieldID
    "sightings_row_colors": "resights",  # Sightings rows: none | alternate | resights (tint resights) | groups (a tint per sighting and its resights)
    "resight_dive_behaviors": "Fluke-up dive|Fluke-down dive",   # Tools → Resights: behaviors that mean a dive (| between)
    "resight_surface_behavior": "First surfacing",              # … and the one that ends it
    "resight_order": "time",        # Sightings table: time (as recorded) | nested (resights under their first sighting)
    "resight_lines": "1",           # dotted line from a sighting through its resights, in time order
    "resight_marker_shape": "same", # resights' marker: same (as the sighting) | a shape | hidden
    "resight_marker_fill": "hollow",  # hollow (outline in the sighting's color) | filled | faded
    "resight_marker_size": "70",    # % of the sightings' marker size
    "resight_labels": "0",          # label resight markers too
    "show_track_on": "1",
    "show_track_off": "1",
    "show_track_errors": "0",       # 0.47: draw the ERROR stretches (GPS jumps / gaps marked by Error check) in ERROR's color
    "label_survey_start": "1",      # 0.47: a "Start" label where the survey started
    "label_survey_end": "1",        # … and an "End" label where it ended
    "fade_enabled": "0",            # fade the track, sightings and events older than fade_min (not waypoints)
    "fade_min": "30",
    "overlay_colors": "{}",         # colors chosen in Tools → Overlays: JSON {file: "#rrggbb"}
}

DEFAULT_SETTINGS = {
    # --- shared: kept in templates/current/spyhop-config.json and carried by templates (SHARED_SETTINGS)
    "latlon_format": "DDM",
    "timezone": "local",            # local | UTC | auto (from the position) | UTC±hh:mm
    "bearing_reference": "M",
    "distance_unit": "nm",
    "map_distance_unit": "nm",      # distances on the map, in popups, routes and the Summary (no reticles)
    "mag_variation": "auto",
    "tracking_interval": 1,         # 0.47: a track point every second (was 10)
    "effort_reminder_min": 30,
    "keep_awake": "survey",         # stop the computer sleeping: off | survey (while one is active) | always
    "keep_screen_on": False,        # … and keep the screen on too
    "nmea_log_enabled": False,      # write every received NMEA sentence to <data folder>/nmea_logs
    "nmea_log_timestamps": True,
    "altitude_column": "auto",      # Sightings' Alt column: auto (shown for aerial surveys) | show | hide
    "segment_column": "show",       # Effort's Seg (effort segment) column: show | hide
    "qc_auto_minutes": 0,           # 0.52: run the Error check every N minutes (1–30) during a survey; 0: off
    "column_layout": {},            # this computer's column order and widths: {tab: {order: [keys], widths: {key: px}}}
    # --- also in spyhop-config.json, under their own keys (see CONFIG_KEYS)
    "online_feeds": [],             # map feeds (Tools → Overlays → Online overlays; feeds.py) → map_feeds
    "online_display": {},           # online overlays to show, set by a template: {ais, radar_us, radar_world,
                                    # feeds: [urls], radar_opacity, hide_stopped, stamp}; applied once per stamp
    "nmea_sources": [{"name": "UDP port 10110", "type": "udp", "port": 10110, "enabled": True, "role": "primary"}],
    "nmea_failover": False,         # use a secondary input's position while the primary has been quiet for 5 s (never an "other")
                                    # all inputs in order (spyhop-local.json); the network ones (UDP, TCP, gpsd)
                                    # are also nmea_inputs in spyhop-config.json, which wins when they differ
    # --- this computer only: spyhop-local.json
    "last_meta": {},                # survey details used last time, offered for the next survey
    "tracking_enabled": False,
    "clock_zone_last": "",          # the zone last found from the position (used until there's a fix)
    "check_updates_on_start": True,   # look on GitHub for a newer Spyhop when it starts (0.45: on; quick, silent offline; always asks before installing)
    "pane_layout": {},              # this computer's panes: {fx, fy, min: {map, util, data}, max} (app.js)
    "follow_vessel": True,
    "smooth_vessel": True,          # glide the vessel icon between fixes on the map (drawing only; map.js)
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
    "map_distance_unit": "Map distance unit",
    "mag_variation": "Magnetic variation",
    "tracking_interval": "Track point every (s)",
    "effort_reminder_min": "Effort reminder (min)",
    "keep_awake": "Keep the computer awake",
    "keep_screen_on": "Keep the screen on",
    "nmea_log_enabled": "Raw NMEA log",
    "nmea_log_timestamps": "Raw NMEA log time stamps",
    "altitude_column": "Altitude column",
    "segment_column": "Effort segment column",
    "qc_auto_minutes": "Error check automatically (min)",
}
# The GPS / NMEA inputs a template carries (0.41: serial too, named for the device, e.g. "External GPS").
# Each has a role (0.42): the platform's primary (its position, course, speed and heading), a secondary
# (another of the platform's own inputs: logged, fills in readings, can stand in for the primary), or
# other (0.44; "external" before: not the platform at all: a drone, a drifting buoy, a second vessel;
# logged and drawn on the map, never the platform; "other" so it isn't confused with an external GPS device). Which inputs are in use, primary or secondary, and which show on the map is this
# computer's choice (INPUT_FLAGS), kept by name when a template is used; "other" travels with the input.
TEMPLATE_INPUTS = ("serial", "udp", "tcp", "gpsd")
INPUT_ROLES = ("primary", "secondary", "other")
INPUT_FLAGS = ("enabled", "role", "show_on_map", "primary")


# 0.43: how an "other" source is drawn and kept: its color, line (solid/dashed/dotted/dashdot) and width, how
# much trail (all of it, the last N minutes, or none: a point only), whether its name shows on the map and
# whether its fixes are recorded to <survey>_<name>_gps.csv (0.44). They belong to the device, so they travel in
# templates with the input (preferences, never data).
EXTERNAL_COLORS = ["#e07000", "#0097a7", "#c2185b", "#7cb342", "#5e35b1", "#6d4c41"]
LINE_STYLES = ("solid", "dashed", "dotted", "dashdot")
EXTERNAL_STYLE = ("color", "line", "width", "trail", "label", "record", "icon")
# 0.45: its icon on the map (vessel and aircraft turn with its heading)
EXTERNAL_ICONS = ("circle", "square", "triangle", "diamond", "star", "vessel", "aircraft", "drone", "tower")


def _clean_external(x: dict, i: int):
    c = str(x.get("color") or "").strip()
    x["color"] = c.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else EXTERNAL_COLORS[i % len(EXTERNAL_COLORS)]
    x["line"] = x.get("line") if x.get("line") in LINE_STYLES else "solid"
    try:
        w = float(x.get("width") or 2)
    except (TypeError, ValueError):
        w = 2
    x["width"] = min(10.0, max(0.5, w))
    t = x.get("trail", "all")
    if t not in ("all", "none"):
        try:
            t = max(1, min(24 * 60, int(t)))
        except (TypeError, ValueError):
            t = "all"
    x["trail"] = t
    x["label"] = x.get("label", True) is not False
    x["record"] = x.get("record", True) is not False
    x["icon"] = x.get("icon") if x.get("icon") in EXTERNAL_ICONS else "circle"


def input_definition(src: dict) -> dict:
    """An input without this computer's choices: what a template holds (role only if other)."""
    d = {k: v for k, v in src.items() if k not in INPUT_FLAGS and k != "session"}
    if src.get("role") == "other":
        d["role"] = "other"
    return d


def clean_inputs(sources) -> list[dict]:
    """Inputs with a name each (unique; default from the type and port), a role, the flags as booleans,
    and one primary among the enabled platform inputs (the first marked primary, else the first enabled
    one that isn't other). Others show on the map unless told not to."""
    from .sources import describe
    out, seen = [], set()
    for x in sources or []:
        if not isinstance(x, dict) or not x.get("type"):
            continue
        x = dict(x)
        base = str(x.get("name") or "").strip()[:60] or describe(x)
        name, n = base, 2
        while name.lower() in seen:
            name, n = f"{base} ({n})", n + 1
        seen.add(name.lower())
        x["name"] = name
        x["enabled"] = x.get("enabled", True) is not False
        role = x.get("role")
        if role == "external":            # 0.42–0.43's name for "other"; delete before 1.0
            role = "other"
        if role not in INPUT_ROLES:
            role = "primary" if x.get("primary") else "secondary"     # 0.41's primary flag
        x["role"] = role
        x.pop("primary", None)
        x["show_on_map"] = bool(x.get("show_on_map", role == "other"))
        if role == "other":
            _clean_external(x, sum(1 for y in out if y["role"] == "other"))
        else:
            for k in EXTERNAL_STYLE:
                x.pop(k, None)
        out.append(x)
    platform = [x for x in out if x["enabled"] and x["role"] != "other"]
    prim = next((x for x in platform if x["role"] == "primary"), platform[0] if platform else None)
    for x in out:
        if x["role"] != "other":
            x["role"] = "primary" if x is prim else "secondary"
    return out


def primary_of(sources) -> dict | None:
    return next((x for x in sources or [] if x.get("enabled", True) is not False and x.get("role") == "primary"), None)


def merge_inputs(mine: list[dict], template: list[dict]) -> list[dict]:
    """This computer's inputs with its template kinds (serial, UDP, TCP, gpsd) replaced by the template's,
    which go where the first of them was (file replays and the simulator keep their places). This
    computer's choices (in use, role, on the map) are kept by name; inputs new to it come in not in
    use (as secondaries, or other), unless none would be in use."""
    mine = clean_inputs(mine)
    template = clean_inputs(template)      # names from the type and port where none is given, as here
    flags = {str(x.get("name", "")).lower(): {k: x.get(k) for k in INPUT_FLAGS if k in x} for x in mine if x.get("name")}
    first = next((i for i, x in enumerate(mine) if x.get("type") in TEMPLATE_INPUTS), None)
    rest = [x for x in mine if x.get("type") not in TEMPLATE_INPUTS]
    at = len(rest) if first is None else sum(1 for x in mine[:first] if x.get("type") not in TEMPLATE_INPUTS)
    new = []
    for x in template or []:
        if not isinstance(x, dict) or x.get("type") not in TEMPLATE_INPUTS:
            continue
        ext = x.get("role") == "other"
        d = input_definition(x)
        d.update(flags.get(str(d.get("name", "")).lower(),
                           {"enabled": False, "role": "other" if ext else "secondary", "show_on_map": ext}))
        if ext:
            d["role"] = "other"           # what the device is travels with it
        new.append(d)
    out = rest[:at] + new + rest[at:]
    if out and not any(x.get("enabled", True) is not False for x in out):
        first_platform = next((x for x in out if x.get("role") != "other"), out[0])
        first_platform.update(enabled=True, role="primary" if first_platform.get("role") != "other" else "other")
    return clean_inputs(out)

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
        from .layout import tidy_data_folder, move_surveys_into_folders, rename_instrument_files
        tidy_data_folder(self)
        move_surveys_into_folders(self)        # the pre-0.36 layout, moved once (removed before 1.0)
        rename_instrument_files(self.data_dir)  # _instruments.csv → _nmea.csv (0.41; removed before 1.0)
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

    @property
    def rules_path(self) -> Path:
        return self.current_dir / "rules.csv"

    # -- survey data folder (survey CSVs, waypoints, exports) ------------------------
    @property
    def default_data_dir(self) -> Path:
        return self.root / "data"

    def _resolve_data_dir(self):
        # 0.45: always the "data" folder inside Spyhop's folder (it can't be changed any more)
        p = self.default_data_dir
        p.mkdir(parents=True, exist_ok=True)
        self.data_dir = p

    # One folder per survey (0.36): <data folder>/<survey>/ holds <survey>_sightings.csv … _track.csv,
    # _metadata.csv, _instruments.csv, the copy of the template it was started with (<survey>_template.zip),
    # its raw NMEA logs (nmea_logs/) and its exports (exports/). Waypoints, and NMEA logs and exports made
    # with no survey open, stay at the top of the data folder.
    RESERVED_NAMES = {"exports", "nmea_logs", "templates", "config_packs"}

    def survey_dir(self, prefix: str) -> Path:
        return self.data_dir / prefix

    def _open_prefix(self) -> str | None:
        cur = self.current_survey()
        return cur["prefix"] if cur else None

    @property
    def export_dir(self) -> Path:
        """Where exports, reports and summaries go: the open survey's exports folder, else the data folder's."""
        pre = self._open_prefix()
        d = (self.survey_dir(pre) if pre else self.data_dir) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def nmea_log_dir(self) -> Path:
        pre = self._open_prefix()
        return (self.survey_dir(pre) if pre else self.data_dir) / "nmea_logs"

    def ensure_defaults(self):
        for name, (hdr, rows) in DEFAULT_LISTS.items():
            if not self.list_path(name).exists():
                _write_csv(self.list_path(name), hdr, rows)
        if not self.shortcuts_path.exists():
            _write_csv(self.shortcuts_path, *DEFAULT_SHORTCUTS)
        if not self.rules_path.exists():
            from .rules import DEFAULT_RULES
            _write_csv(self.rules_path, *DEFAULT_RULES)
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

    # -- what can't change during an active survey (0.37) ------------------------------
    def locked_snapshot(self) -> dict:
        return {"lists": {n: [dict(r) for r in self.lists.get(n, [])] for n in LOCKED_LISTS},
                "settings": {k: self.settings.get(k) for k in LOCKED_SETTINGS},
                "reports": json.loads(json.dumps(self.reports)),           # saved reports: data part too (0.40)
                "rules": self.rules_loaded}                                # and the rules (0.52)

    def restore_locked(self, snap: dict) -> list[str]:
        """Put back the locked lists and settings from a snapshot (files too) if they changed; returns what was put back."""
        back = []
        for n, rows in snap["lists"].items():
            if self.lists.get(n) != rows and without_colors(self.lists.get(n)) == without_colors(rows):
                continue                     # only colors changed: allowed during a survey (0.40)
            if self.lists.get(n) != rows:
                hdr = list(dict.fromkeys([*DEFAULT_LISTS[n][0], *(k for r in rows for k in r)]))
                _write_csv(self.list_path(n), hdr, [[r.get(c, "") for c in hdr] for r in rows])
                self.lists[n] = rows
                back.append(f"{n}.csv")
        if snap.get("rules") is not None and self.rules_text() != snap["rules"]:
            self.rules_path.write_text(snap["rules"], encoding="utf-8")
            self.reload()
            back.append("rules.csv")
        if "reports" in snap and self.reports != snap["reports"]:
            self.save_reports(snap["reports"])
            back.append("saved reports")
        changed = {k: v for k, v in snap["settings"].items() if self.settings.get(k) != v}
        if changed:
            self.settings.update(changed)
            self.save()
            back += [LOCKED_SETTINGS[k] for k in changed]
        return back

    def list_header(self, name: str) -> list[str]:
        """The columns of a list file as they are now (known ones first)."""
        known = DEFAULT_LISTS[name][0]
        try:
            with open(self.list_path(name), newline="", encoding="utf-8-sig") as fh:
                have = [h.strip() for h in next(csv.reader(fh), []) if h.strip()]
        except OSError:
            have = []
        if name == "reticles":         # 0.37's calibrated-marks table column: marks are evenly spaced since 0.38
            have = [h for h in have if h != "marks"]
        return known + [h for h in have if h not in known]

    def colors_only_change(self, name: str, rows: list[dict]) -> bool:
        """True if `rows` differ from the list in use only in their colors (allowed during a survey)."""
        hdr = self.list_header(name)
        new = [{c: str((r or {}).get(c, "") or "").strip() for c in hdr} for r in rows or []]
        new = [r for r in new if any(r.values())]
        old = [{c: str(r.get(c, "") or "").strip() for c in hdr} for r in self.lists.get(name, [])]
        return without_colors(new) == without_colors(old)

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
            if name == "reticles" and row["name"]:
                try:
                    row.update(_clean_reticle(row))
                except ValueError as e:
                    problems.append(f"Row {i} ({row['name']}): {e}")
            if row["name"].lower() == OTHER.lower():
                row["name"] = OTHER
            if name == "effort" and row["name"]:
                req = next((x for x in schema.EFFORT_REQUIRED if x.lower() == row["name"].lower()), None)
                if req:
                    row["name"], row["status"] = req, "off"          # always these names, never on effort
                st = row.get("status", "").strip().lower()
                if st not in ("on", "off"):
                    problems.append(f"Row {i} ({row['name']}): Status must be on or off.")
                row["status"] = st
                if re.search(r"[,;|]", row["name"]):
                    problems.append(f"Row {i}: the name can't contain , ; or |.")
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
        if out and not any(r["name"] == OTHER for r in out):     # always there (0.40): put back at the end
            out.append({c: other_row(name).get(c, "") for c in hdr})
        if name == "effort":
            have = {r["name"] for r in out}
            miss = [x for x in schema.EFFORT_REQUIRED if x not in have]
            if miss:
                problems.append(f"The effort list must include {', '.join(miss)} ({'they are' if len(miss) > 1 else 'it is'} needed to start and end a survey and to mark trackline breaks).")
            if not any(r["status"] == "on" for r in out):
                problems.append("At least one entry must be on effort (Status on).")
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
            combo, action, prefill, focus = (str((r or {}).get(k, "") or "").strip() for k in ("combo", "action", "prefill", "focus"))
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
            if focus:                       # 0.51: the column to select in the new row
                if not (verb == "add" or action in ("add-current", "add-resight")):
                    problems.append(f"Row {i}: only shortcuts that add a row can choose the column to select.")
                elif tabs is not None:
                    where = [arg] if verb == "add" else ["sightings"] if action == "add-resight" else [t for t in ("sightings", "effort", "events") if t in tabs]
                    if not any(focus in tabs.get(t, ()) for t in where):
                        problems.append(f"Row {i}: the {arg if verb == 'add' else 'data'} table has no column “{focus}” to select.")
            key = combo.lower()
            if key in seen:
                problems.append(f"Row {i}: {combo} is already used in row {seen[key]}.")
            else:
                seen[key] = i
            out.append({"combo": combo, "action": action, "prefill": prefill, "focus": focus})
        if problems:
            raise ValueError("\n".join(problems[:12]) + (f"\n… and {len(problems) - 12} more." if len(problems) > 12 else ""))
        _write_csv(self.shortcuts_path, DEFAULT_SHORTCUTS[0], [[r["combo"], r["action"], r["prefill"], r["focus"]] for r in out])
        self.reload()
        return out

    def rules_text(self) -> str | None:
        try:
            return self.rules_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def save_rules(self, rows: list[dict]) -> list[dict]:
        """Replace the rules (Settings → Rules). Raises ValueError listing the problems."""
        from . import rules as R
        problems, out = [], []
        for i, r in enumerate(rows or [], 1):
            c = R.clean_rule(r, i, problems)
            if c:
                out.append(c)
        if problems:
            raise ValueError("\n".join(problems))
        _write_csv(self.rules_path, R.COLUMNS, [R.to_csv_row(r) for r in out])
        self.reload()
        return self.rules

    def reload(self):
        """Read the lists, shortcuts and rules again (they're CSV files in templates/current)."""
        self.lists: dict[str, list[dict]] = {}
        for name in DEFAULT_LISTS:
            try:
                self.lists[name] = [r for r in _read_csv(self.list_path(name)) if r.get("name")]
            except FileNotFoundError:
                self.lists[name] = []
        for name in DEFAULT_LISTS:          # every list has Other (0.40); one without it gets it at the end
            rows = self.lists[name]
            if rows and not any(r.get("name") == OTHER for r in rows) and self.list_path(name).exists():
                hdr = self.list_header(name)
                rows.append({c: other_row(name).get(c, "") for c in hdr})
                try:
                    _write_csv(self.list_path(name), hdr, [[r.get(c, "") for c in hdr] for r in rows])
                except OSError:
                    pass
        schema.set_effort_list(self.lists.get("effort"))
        try:
            self.shortcuts = [r for r in _read_csv(self.shortcuts_path) if r.get("combo")]
        except FileNotFoundError:
            self.shortcuts = []
        from . import rules as R
        try:
            self.rules, self.rule_problems = R.load(_read_csv(self.rules_path))
        except FileNotFoundError:
            self.rules, self.rule_problems = [], []
        self.rules_loaded = self.rules_text()          # as read, for locked_snapshot (the file may be edited by hand)
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
            s["nmea_sources"] = merge_inputs(s.get("nmea_sources") or [], doc["nmea_inputs"])
        s["nmea_sources"] = clean_inputs(s.get("nmea_sources"))
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
            "nmea_inputs": [input_definition(x) for x in s.get("nmea_sources") or [] if isinstance(x, dict) and x.get("type") in TEMPLATE_INPUTS],
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
        if updates and "nmea_sources" in updates:
            updates = {**updates, "nmea_sources": clean_inputs(updates["nmea_sources"])}
        if updates and "keep_awake" in updates and updates["keep_awake"] not in ("off", "survey", "always"):
            updates = {**updates, "keep_awake": "survey"}
        if updates and "qc_auto_minutes" in updates:
            try:
                n = int(float(updates["qc_auto_minutes"] or 0))
            except (TypeError, ValueError):
                n = 0
            updates = {**updates, "qc_auto_minutes": max(0, min(30, n))}
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
            "rules": self.rules,
            "rule_problems": self.rule_problems,
            "rules_info": rules_info(),
            "display": self.display,
            "settings": self.settings,
            "tile_sources": self.tile_sources,
            "mbtiles": self.mbtiles,
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "default_data_dir": str(self.default_data_dir),
            "current_dir": str(self.current_dir),
        }


def rules_info() -> dict:
    from .rules import schema_info
    return schema_info()


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
