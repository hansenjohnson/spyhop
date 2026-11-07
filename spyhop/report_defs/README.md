# Spyhop report definitions

Each report in **Tools → Reports** (other than Summary) is one JSON file. Spyhop's
own are in this folder (`spyhop/report_defs/`). The report engine is `spyhop/reports.py`,
which is separate from the rest of Spyhop.

## Adding or changing a report

Don't edit the files here: an update to Spyhop replaces them. Instead:

1. Open **Tools → Reports → Open the reports folder**. This is the `reports` folder
   inside Spyhop's own folder, and it is kept across updates.
2. Put a `.json` file there:
   - **New report:** give it a new `id`.
   - **Change a built-in report:** use the same `id` as the built-in one. Copies of the
     built-in files are in the `examples` subfolder to start from.
   - **Hide a built-in report:** `{"id": "blue_whales", "enabled": false}`.
3. Press **Reload reports**, or restart Spyhop.

A file with a mistake is skipped, and the Reports tab says what's wrong with it.

## The format

```json
{
  "id": "right_whales",
  "title": "Right whales",
  "order": 40,
  "description": "Every North Atlantic right whale sighting.",
  "table": "sightings",
  "where": [
    {"species_code": ["RIWH"]},
    {"column": "Species", "regex": "^north atlantic right whale$"}
  ],
  "columns": [
    {"label": "Time", "value": "time"},
    {"label": "Position", "value": "position"},
    {"label": "Number", "column": "Count", "align": "right"},
    {"label": "Calves", "column": "Calves", "align": "right"},
    {"label": "Notes", "column": "Notes"}
  ],
  "totals": {"Number": "sum", "Calves": "sum"},
  "empty": "No right whales sighted."
}
```

| Key | Meaning |
| --- | --- |
| `id` | Lower-case letters, digits and `_`. It names the report in exported files. |
| `title` | The tab name and the report's heading. |
| `order` | Where its tab goes; lower numbers come first. Summary is always first. |
| `description` | Optional. Shown above the table. |
| `table` | `sightings`, `events` or `effort`. |
| `where` | A list of conditions. A record is included if it meets **any** of them. In one condition, **every** key must hold. An empty or missing list includes every record. |
| `columns` | What to show. Each column has a `label` and either a `column` (a column of the table, by its CSV name) or a `value` (see below). Add `"align": "right"` for numbers. |
| `totals` | Optional. A totals row, keyed by column label: `"sum"` adds the numbers, `"count"` counts the cells that aren't blank. |
| `empty` | Optional. Shown when no records match. |
| `enabled` | `false` hides the report. |

**Conditions:**

- `{"species_code": ["RIWH", "BLWH"]}`: species whose code in species.csv is one of these.
- `{"event_code": ["GRPT"]}`: event types whose code in event_types.csv is one of these.
- `{"column": "Species", "equals": "Fin whale"}`: the value, ignoring case.
- `{"column": "EventType", "in": ["Gear Reported", "Gear Recovered"]}`: one of these values.
- `{"column": "Notes", "regex": "entangl"}`: a regular expression, ignoring case.
- `{"column": "FieldID", "not_blank": true}`: the column is filled in.

**Values:**

- `time`: date and time in the survey clock
- `date`
- `clock`: the time of day only
- `position`, `lat`, `lon`: in the lat/lon format from Settings. Sightings use SigLat/SigLon (the animal), else the vessel. Events use Lat/Lon, and Effort rows use the vessel.
- `species_code`, `event_code`

**Table columns** (the CSV names):

- **Sightings:** SightNo, DateTime, VesLat, VesLon, Species, Count, Calves, NumConf, IDrel, Behaviors, Observer, Bearing, BrgRef, Distance, DistUnit, SigLat, SigLon, Images, FieldID, Notes.
- **Events:** EventNo, DateTime, Lat, Lon, EventType, ID, Notes.
- **Effort:** DateTime, VesLat, VesLon, Effort, Visibility, SeaState, Weather, Glare, Port, Recorder, Starboard, Notes.

Records are listed in time order. Every report can be saved as HTML or PDF from its
tab, and chosen in **Export Data…**. PDFs are printed by Google Chrome or Microsoft Edge,
which must be installed.
