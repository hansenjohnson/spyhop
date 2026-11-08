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
        default="", copy=True, skip=False, help=""):
    """skip=True: a new row's cursor jumps over this column (filled in later, e.g. IDs).
    help: one-line description shown under the table when the column is selected."""
    return {"key": key, "type": type, "label": label or key, "list": list, "auto": auto,
            "width": width, "hidden": hidden, "default": default, "copy": copy, "skip": skip,
            "help": help}


FIXED_LISTS = {
    "numconf": ["Definite", "Probable", "Possible", "At Least"],
    "idrel": ["Definite", "Probable", "Possible"],
    "seastate": [str(i) for i in range(0, 10)],
    "weather": ["Clear", "Partly cloudy", "Overcast", "Haze", "Fog", "Mist",
                "Drizzle", "Rain", "Showers", "Snow"],
    "visibility": ["<0.5 nm", "0.5-1 nm", "1-2 nm", "2-5 nm", "5-10 nm", ">10 nm"],
    "glare": ["None", "Slight", "Moderate", "Severe"],
    "effort": ["Start", "ON", "OFF", "End", "ERROR"],   # ERROR: a trackline break (GPS jump or loss)
    "images": ["None", "Photo", "Video", "Photo + Video", "Drone"],
    "brgref": ["M", "T", "R"],
    "distunit": ["m", "km", "nm", "mi", "yd"],
    "shapes": ["Circle", "Diamond", "Square", "Triangle", "Star"],
    "colors": ["red", "orange", "gold", "yellow", "green", "darkgreen", "teal", "cyan", "blue", "navy",
               "purple", "magenta", "pink", "brown", "black", "gray", "white"],
    "platform_type": ["Vessel", "Plane", "Land", "Other"],
}

# Survey details kept with each survey in <survey>_metadata.csv
SURVEY_META = [
    ("platform_name", "Platform name", "Vessel (or aircraft, station…) name"),
    ("platform_type", "Platform type", "Vessel, Plane, Land or Other"),
    ("organization", "Organization", "Organization running the survey"),
    ("chief_scientist", "Chief scientist", "Chief scientist for this survey"),
    ("chief_scientist_email", "Chief scientist email", "name@example.org"),
]

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
            col("SightNo", "seq", "SightNo", width=60,
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
            col("NumConf", "choice", "NumConf", list="numconf",
                help="Confidence in the number: Definite, Probable, Possible, or At Least (the number is a minimum)."),
            col("IDrel", "choice", "IDrel", list="idrel", width=80, help="Confidence in the species identification."),
            col("Behaviors", "multi", "Behaviors", list="behaviors", width=160,
                help="Behaviours seen. Press Enter or double-click to tick several. List: behaviors.csv."),
            col("Observer", "choice", "Obs", list="observers", width=60, help="Who made the sighting. List: observers.csv."),
            col("Bearing", "float", "Bearing", width=65,
                help="Bearing from the vessel to the animals, 0–360°; negative counts back from 360 (−10 = 350, e.g. 10° to port for a relative bearing). Its reference is in Ref."),
            col("BrgRef", "choice", "Ref", list="brgref", width=45,
                help="Bearing reference: M = magnetic (compass), T = true, R = relative to the bow (000 = dead ahead)."),
            col("Distance", "float", "Dist", width=55, help="Distance from the vessel to the animals. Its unit is in Unit."),
            col("DistUnit", "choice", "Unit", list="distunit", width=45, help="Unit of Dist: m, km, nm, mi or yd."),
            col("SigLat", "lat", "SigLat",
                help="Animal latitude, calculated from Bearing and Dist (the vessel position if those are blank). You can also type it."),
            col("SigLon", "lon", "SigLon",
                help="Animal longitude, calculated from Bearing and Dist (the vessel position if those are blank). You can also type it."),
            col("Images", "choice", "Images", list="images", help="Photos or video collected of this sighting."),
            col("FieldID", "text", "FieldID", width=80, skip=True,
                help="Your own ID for this sighting or animal (photo-ID, catalogue number…). Added to the map label after the species code."),
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
                help="Start = survey began (first row only) · ON = actively searching · OFF = not searching · End = survey ended (last row only; use End survey in the Survey tab)."),
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
                help="Marker colour for this mark: pick one, or type a #hex code such as #ff8800."),
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

# columns renamed in later versions, by table: old name -> new name (files and saved reports are
# read with the new names; 0.26: VesLat/VesLon became Lat/Lon, so they suit any platform)
RENAMED_COLUMNS = {
    "sightings": {"VesLat": "Lat", "VesLon": "Lon"},
    "effort": {"VesLat": "Lat", "VesLon": "Lon"},
}


def renamed(tab: str, names):
    """Column names with old ones replaced by their new names (an old name is kept if the new one is already there)."""
    ren = RENAMED_COLUMNS.get(tab, {})
    names = list(names)
    return [ren[n] if n in ren and ren[n] not in names else n for n in names]


TRACK_COLUMNS = ["DateTime", "Lat", "Lon", "SOG", "COG", "Effort"]


def headers(tab: str) -> list[str]:
    return [c["key"] for c in TABS[tab]["columns"]]


def column(tab: str, key: str) -> dict | None:
    for c in TABS[tab]["columns"]:
        if c["key"] == key:
            return c
    return None
