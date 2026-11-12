"""Column definitions for each data tab, and the fixed (hardcoded) choice lists.

Column keys are the CSV headers. Display labels are kept short for the grid.
Types:
  id        hidden stable row id
  seq       auto-incrementing number (SightNo, EventNo)
  datetime  ISO 8601 with UTC offset in the CSV; shown in the survey time zone
  lat/lon   decimal degrees in the CSV; shown in the chosen DDM/DD/DMS format
  int, float, text
  choice    one value from a list (list = name of a config or fixed list)
  multi     several values from a list, stored separated by "; "
  bool      Map checkbox, stored as 1/0
"""
from __future__ import annotations


def col(key, type="text", label=None, list=None, auto=False, width=None, hidden=False,
        default="", copy=True, skip=False, help="", optional=None, readonly=False, na=False):
    """skip=True: a new row's cursor jumps over this column (filled in later, e.g. IDs).
    help: one-line description shown under the table when the column is selected.
    optional: the name of a Settings → General choice that shows or hides the column (it's always in the CSV).
    readonly: worked out by Spyhop, not typed (e.g. the effort segment).
    na: a number column that also takes NA (not applicable, e.g. calves of fishing gear)."""
    return {"key": key, "type": type, "label": label or key, "list": list, "auto": auto,
            "width": width, "hidden": hidden, "default": default, "copy": copy, "skip": skip,
            "help": help, "optional": optional, "readonly": readonly, "na": na}


FIXED_LISTS = {
    "numconf": ["Definite", "Probable", "Possible", "At Least"],
    "idrel": ["Definite", "Probable", "Possible"],
    "seastate": [str(i) for i in range(0, 10)],
    "glare": ["None", "Slight", "Moderate", "Severe"],
    "images": ["None", "Photo", "Video", "Photo + Video", "Drone"],
    "brgref": ["M", "T", "R", "C"],              # C: clock bearing (1–12) relative to the heading
    # plus one "reticles-<name>" for each entry of the reticles list (Settings → Dropdowns → Reticles)
    "distunit": ["m", "km", "nm", "mi", "yd"],
    "shapes": ["Circle", "Diamond", "Square", "Triangle", "Star"],
    "colors": ["red", "orange", "gold", "yellow", "green", "darkgreen", "teal", "cyan", "blue", "navy",
               "purple", "magenta", "pink", "brown", "black", "gray", "white"],
    "platform_type": ["Shipboard", "Aerial", "Stationary", "Other"],
}

# Survey details kept with each survey in <survey>_metadata.csv
SURVEY_META = [
    ("platform_name", "Platform name", "Vessel, aircraft or station name"),
    ("platform_type", "Platform type", "Shipboard, Aerial, Stationary or Other"),
    ("platform_altitude_ft", "Platform altitude (ft)",
     "Observers’ average eye height above the water (ship or station), or the usual survey altitude (aircraft)"),
    ("organization", "Organization", "Organization running the survey"),
    ("chief_scientist", "Chief scientist", "Chief scientist for this survey"),
    ("chief_scientist_email", "Chief scientist email", "name@example.org"),
    ("survey_notes", "Survey notes", "General notes or a summary of the survey: conditions, what went well, problems, follow-up"),
]
META_MULTILINE = {"survey_notes"}       # a text box of several lines in the Survey tab

COMMON_HEAD = [
    col("RowID", "id", hidden=True),
]

T_HELP = "Time the row was added (survey clock). Type HH:MM or HH:MM:SS to change the time of day."
MAP_HELP = "Show this row on the map — click or press Space to switch on/off."

TABS = {
    "sightings": {
        "title": "Sightings",
        "marker": True,
        "seq": "SightNo",
        "columns": COMMON_HEAD + [
            col("SightNo", "seq", "SigNo", width=60,
                help="Sighting number, assigned automatically. Photos and other records refer to it, so change it with care."),
            col("DateTime", "datetime", "Time", auto=True, help=T_HELP),
            col("Lat", "lat", "Lat", auto=True, help="Platform latitude from GPS when the row was added."),
            col("Lon", "lon", "Lon", auto=True, help="Platform longitude from GPS when the row was added."),
            # kept in the CSV (needed for bearings relative to the bow) but not shown in the table
            col("VesHdg", "float", "VesHdg", auto=True, hidden=True),
            col("Species", "choice", "Species", list="species", width=170,
                help="Species seen. Type part of the name or its code (e.g. HUWH) to filter. List: species.csv."),
            col("Count", "int", "Num", width=50, help="Best estimate of the number of animals."),
            col("Calves", "int", "Calves", width=55, na=True,
                help="Number of calves, or NA where calves don't apply (dead birds, fishing gear, vessels…)."),
            col("ResightOf", "int", "ResNo", width=60, skip=True,
                help="Resight number: for a resight of animals already recorded (an approach, a focal follow), the SigNo of their first sighting. Blank for a new sighting. Resights aren’t counted again in the summary. “Add resight” fills it in."),
            col("NumConf", "choice", "NumConf", list="numconf",
                help="Confidence in the number: Definite, Probable, Possible, or At Least (the number is a minimum)."),
            col("IDrel", "choice", "IDrel", list="idrel", width=80, help="Confidence in the species identification."),
            col("Behaviors", "multi", "Behaviors", list="behaviors", width=160,
                help="Behaviors seen. Press Enter or double-click, then ↑/↓ and Space to tick several (each one’s definition is shown). List: behaviors.csv."),
            col("Observer", "choice", "Obs", list="observers", width=60, help="Who made the sighting. List: observers.csv."),
            col("Bearing", "float", "Bearing", width=65,
                help="Bearing from the vessel to the animals, 0–360°; negative counts back from 360 (−10 = 350, e.g. 10° to port for a relative bearing). With Ref C, a clock bearing 1–12 (picked from a list; 3 = 90° to starboard, 12 = dead ahead). Its reference is in Ref."),
            col("BrgRef", "choice", "Ref", list="brgref", width=45,
                help="Bearing reference: M = magnetic (compass), T = true, R = relative to the bow (000 = dead ahead), C = clock bearing relative to the bow (each hour 30°: 12 = dead ahead, 3 = starboard beam, 6 = astern, 9 = port beam)."),
            col("Distance", "float", "Dist", width=55,
                help="Distance from the platform to the animals, in Unit. With a reticles-… Unit: the reading (reticles below the horizon, a calibrated mark, or degrees below the horizontal, as that entry of Settings → Dropdowns → Reticles says)."),
            col("DistUnit", "choice", "Unit", list="distunit", width=60,
                help="Unit of Dist: m, km, nm, mi, yd, or reticles-<name> (a reading taken the way that entry of Settings → Dropdowns → Reticles says, turned into a distance with the platform altitude)."),
            col("Altitude", "float", "Alt (ft)", width=60, optional="altitude",
                help="Platform altitude (ft) for this sighting: eye height, or the aircraft’s altitude. Filled in from the survey details; used to turn reticle readings into distances. Show or hide it in Settings → General."),
            col("SigLat", "lat", "SigLat",
                help="Animal latitude, calculated from Bearing and Dist (the vessel position if those are blank). You can also type it."),
            col("SigLon", "lon", "SigLon",
                help="Animal longitude, calculated from Bearing and Dist (the vessel position if those are blank). You can also type it."),
            col("Images", "choice", "Images", list="images", help="Photos or video collected of this sighting."),
            col("FieldID", "text", "FieldID", width=80, skip=True,
                help="Your own ID for this sighting or animal (photo-ID, catalog number…). Added to the map label after the species code."),
            col("Notes", "text", "Notes", width=220, help="Free-text notes."),
            col("Map", "bool", "Map", default="1", width=40, help=MAP_HELP),
        ],
    },
    "effort": {
        "title": "Effort",
        "marker": False,
        "seq": None,
        "columns": COMMON_HEAD + [
            col("DateTime", "datetime", "Time", auto=True, copy=False, help=T_HELP),
            col("Lat", "lat", "Lat", auto=True, copy=False, help="Platform latitude from GPS when the row was added."),
            col("Lon", "lon", "Lon", auto=True, copy=False, help="Platform longitude from GPS when the row was added."),
            col("Effort", "choice", "Effort", list="effort", width=60,
                help="The effort status. Start = survey began (first row only) · End = survey ended (last row only; use End survey in the Survey tab) · the others, and whether each counts as on or off effort: Settings → Dropdowns → Effort."),
            col("Segment", "int", "Seg", width=45, copy=False, skip=True, readonly=True, optional="segment",
                help="Effort segment: numbered by Spyhop, a new number each time the effort status changes from the row before (e.g. ON → OFF). Rows with the same status in a row share it."),
            col("Visibility", "choice", "Vis", list="visibility", help="Estimated visibility. List: Settings → Dropdowns → Visibility."),
            col("SeaState", "choice", "SeaSt", list="seastate", width=55, help="Sea state, 0–9."),
            col("Weather", "choice", "Weather", list="weather", help="Weather. List: Settings → Dropdowns → Weather."),
            col("Glare", "choice", "Glare", list="glare", help="Sun glare on the search area."),
            col("GlareStart", "float", "Gstart", width=55, na=True,
                help="Glare start: where the glare starts, a bearing in Gref (0–360°, or 1–12 o'clock with C), going clockwise to Gend. NA when Glare is None (filled in by Spyhop); needed for any other glare."),
            col("GlareEnd", "float", "Gend", width=55, na=True,
                help="Glare end: where the glare ends, a bearing in Gref (0–360°, or 1–12 o'clock with C), clockwise from Gstart. NA when Glare is None; needed for any other glare."),
            col("GlareRef", "choice", "Gref", list="brgref", width=50, default="M",
                help="Glare reference, for Gstart and Gend: M = magnetic, T = true, R = relative to the bow, C = clock bearing (12 = dead ahead)."),
            col("Port", "choice", "Port", list="observers", help="Observer on the port side. List: observers.csv."),
            col("Recorder", "choice", "Recorder", list="observers", help="Data recorder. List: observers.csv."),
            col("Starboard", "choice", "Stbd", list="observers", help="Observer on the starboard side. List: observers.csv."),
            col("Notes", "text", "Notes", width=240, copy=False, help="Free-text notes (not copied to the next row)."),
        ],
    },
    "events": {
        "title": "Events",
        "marker": True,
        "seq": "EventNo",
        "columns": COMMON_HEAD + [
            col("EventNo", "seq", "EventNo", width=60, help="Event number, assigned automatically."),
            col("DateTime", "datetime", "Time", auto=True, help=T_HELP),
            col("Lat", "lat", "Lat", auto=True, help="Event latitude: the vessel position when added, or the point picked on the map."),
            col("Lon", "lon", "Lon", auto=True, help="Event longitude: the vessel position when added, or the point picked on the map."),
            col("EventType", "choice", "Event", list="event_types", width=190,
                help="Type of event. Type part of the name or its code to filter. List: event_types.csv."),
            col("ID", "text", "ID", width=90, skip=True,
                help="ID for this event, e.g. CTD cast number, tag ID, drifter ID or sample number. Shown on the map label."),
            col("Notes", "text", "Notes", width=280, help="Free-text notes."),
            col("Map", "bool", "Map", default="1", width=40, help=MAP_HELP),
        ],
    },
    "marks": {
        "title": "Waypoints",
        "marker": True,
        "seq": None,
        "columns": COMMON_HEAD + [
            col("Name", "text", "Name", width=140, help="Name of the waypoint, shown on the map."),
            col("DateTime", "datetime", "Time", auto=True, help=T_HELP),
            col("Lat", "lat", "Lat", help="Waypoint latitude."),
            col("Lon", "lon", "Lon", help="Waypoint longitude."),
            col("Shape", "choice", "Shape", list="shapes", default="Circle", width=90,
                help="Marker shape on the map for this mark."),
            col("Color", "choice", "Color", list="colors", default="purple", width=95,
                help="Marker color for this mark: pick one, or type a #hex code such as #ff8800."),
            col("Notes", "text", "Notes", width=280, help="Free-text notes."),
            col("Map", "bool", "Map", default="1", width=40, help=MAP_HELP),
        ],
    },
}

# Columns used to place each tab's marker on the map (lat, lon), first non-empty wins.
MARKER_POS = {
    "sightings": [("SigLat", "SigLon"), ("Lat", "Lon")],
    "events": [("Lat", "Lon")],
    "marks": [("Lat", "Lon")],
}

# The Effort values come from the effort list (Settings → Dropdowns → Effort, 0.39): each is on or off
# effort. Config sets these from the list whenever it is read (set_effort_list).
EFFORT_REQUIRED = ("Start", "End", "ERROR")      # Start/End: first/last row; ERROR: added by Error check → Fix
DEFAULT_ON_EFFORT = ("ON", "TRANSECT", "DIRECTED", "PHOTO-ID", "FOLLOW")
ON_EFFORT: tuple = DEFAULT_ON_EFFORT              # every Effort value that counts as on effort
OFF_EFFORT: tuple = ("OFF",)                      # off-effort values a user chooses (not Start/End/ERROR)
EFFORT_NAMES: tuple = ("Start", *DEFAULT_ON_EFFORT, "OFF", "End", "ERROR")


def set_effort_list(rows) -> None:
    """Take the on-effort values and all names from the effort list's rows ({name, status, …})."""
    global ON_EFFORT, OFF_EFFORT, EFFORT_NAMES
    rows = [r for r in rows or [] if r.get("name")]
    if not rows:
        ON_EFFORT, OFF_EFFORT, EFFORT_NAMES = DEFAULT_ON_EFFORT, ("OFF",), ("Start", *DEFAULT_ON_EFFORT, "OFF", "End", "ERROR")
        return
    ON_EFFORT = tuple(r["name"] for r in rows if r.get("status", "").lower() == "on" and r["name"] not in EFFORT_REQUIRED)
    OFF_EFFORT = tuple(r["name"] for r in rows if r.get("status", "").lower() != "on" and r["name"] not in EFFORT_REQUIRED)
    EFFORT_NAMES = tuple(dict.fromkeys([*(r["name"] for r in rows), *EFFORT_REQUIRED]))


def is_on(effort) -> bool:
    return effort in ON_EFFORT


def is_effort_choice(effort) -> bool:
    """An on- or off-effort value a user picks (not Start, End or ERROR)."""
    return effort in ON_EFFORT or effort in OFF_EFFORT


def default_off() -> str:
    return "OFF" if "OFF" in OFF_EFFORT else (OFF_EFFORT[0] if OFF_EFFORT else "OFF")


def strict_list(name: str) -> bool:
    """Lists whose values must be in the list (refused otherwise): the fixed lists and the effort list."""
    return name in FIXED_LISTS or name == "effort"


TRACK_COLUMNS = ["DateTime", "Lat", "Lon", "SOG", "COG", "Effort"]


def headers(tab: str) -> list[str]:
    return [c["key"] for c in TABS[tab]["columns"]]


UNIT_NAMES = {"m": "meters", "km": "kilometers", "nm": "nautical miles", "mi": "statute miles", "yd": "yards"}
RETICLE_UNIT = "reticles-"          # Unit "reticles-<name>": an entry of the reticles list


def reticle_name(unit: str) -> str | None:
    """'reticles-binos' → 'binos'; None for any other unit."""
    u = str(unit or "")
    return u[len(RETICLE_UNIT):] if u.startswith(RETICLE_UNIT) and len(u) > len(RETICLE_UNIT) else None


def column(tab: str, key: str) -> dict | None:
    for c in TABS[tab]["columns"]:
        if c["key"] == key:
            return c
    return None
