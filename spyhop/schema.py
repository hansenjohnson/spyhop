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
        default="", copy=True, skip=False, help="", optional=None, readonly=False):
    """skip=True: a new row's cursor jumps over this column (filled in later, e.g. IDs).
    help: one-line description shown under the table when the column is selected.
    optional: the name of a Settings → General choice that shows or hides the column (it's always in the CSV).
    readonly: worked out by Spyhop, not typed (e.g. the effort segment)."""
    return {"key": key, "type": type, "label": label or key, "list": list, "auto": auto,
            "width": width, "hidden": hidden, "default": default, "copy": copy, "skip": skip,
            "help": help, "optional": optional, "readonly": readonly}


FIXED_LISTS = {
    "numconf": ["Definite", "Probable", "Possible", "At Least"],
    "idrel": ["Definite", "Probable", "Possible"],
    "seastate": [str(i) for i in range(0, 10)],
    "weather": ["Clear", "Partly cloudy", "Overcast", "Haze", "Fog", "Mist",
                "Drizzle", "Rain", "Showers", "Snow"],
    "visibility": ["<0.5 nm", "0.5-1 nm", "1-2 nm", "2-5 nm", "5-10 nm", ">10 nm"],
    "glare": ["None", "Slight", "Moderate", "Severe"],
    # on effort: ON (plain on/off effort) or a kind of on effort (LINE transect, FOLLOW a focal whale or
    # group, PHOTO a directed photo-ID approach); ERROR: a trackline break (GPS jump or loss)
    "effort": ["Start", "ON", "LINE", "FOLLOW", "PHOTO", "OFF", "End", "ERROR"],
    "images": ["None", "Photo", "Video", "Photo + Video", "Drone"],
    "brgref": ["M", "T", "R", "C"],              # C: clock bearing (1–12) relative to the heading
    "distunit": ["m", "km", "nm", "mi", "yd", "reticle"],
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
            col("Calves", "int", "Calves", width=55, help="Number of calves."),
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
                help="Distance from the platform to the animals, in Unit. With Unit = reticle: the reading (reticles below the horizon, a calibrated mark, or degrees below the horizontal; Settings → General → Reticles)."),
            col("DistUnit", "choice", "Unit", list="distunit", width=60,
                help="Unit of Dist: m, km, nm, mi, yd, or reticle (a reading turned into a distance with the platform altitude)."),
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
                help="Start = survey began (first row only) · ON = on effort, searching · LINE = on effort, line transect · FOLLOW = on effort, focal follow of one whale or group · PHOTO = on effort, directed photo-ID approach · OFF = not searching · End = survey ended (last row only; use End survey in the Survey tab)."),
            col("Segment", "int", "Seg", width=45, copy=False, skip=True, readonly=True, optional="segment",
                help="Effort segment: numbered by Spyhop, a new number each time the effort status changes from the row before (e.g. ON → OFF). Rows with the same status in a row share it."),
            col("Visibility", "choice", "Vis", list="visibility", help="Estimated visibility."),
            col("SeaState", "choice", "SeaSt", list="seastate", width=55, help="Sea state, 0–9."),
            col("Weather", "choice", "Weather", list="weather", help="Weather."),
            col("Glare", "choice", "Glare", list="glare", help="Sun glare on the search area."),
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

ON_EFFORT = ("ON", "LINE", "FOLLOW", "PHOTO")     # every Effort value that counts as on effort


def is_on(effort) -> bool:
    return effort in ON_EFFORT


TRACK_COLUMNS = ["DateTime", "Lat", "Lon", "SOG", "COG", "Effort"]


def headers(tab: str) -> list[str]:
    return [c["key"] for c in TABS[tab]["columns"]]


def column(tab: str, key: str) -> dict | None:
    for c in TABS[tab]["columns"]:
        if c["key"] == key:
            return c
    return None
