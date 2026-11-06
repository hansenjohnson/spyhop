# Changelog

Spyhop's version is set in `spyhop/__init__.py` and shown in the status bar, the window title, Survey → About, the Terminal window, the diagnostic logs and exports.

The numbers are MAJOR.MINOR.PATCH. MINOR goes up for new features and PATCH for fixes only. Version 1.0.0 will be the first release used on real surveys. After that, MAJOR goes up only when the data files change in a way older versions can't read.

Earlier builds had no version numbers; the entries for 0.1–0.4 were reconstructed afterwards.

## 0.10.0 — 2026-11-06

- **Survey → Settings → Sleep:** Spyhop can stop the computer going to sleep, which would stop the trackline and NMEA recording.
  - **Keep the computer awake:** *During a survey* (the default: from Start until End, or until the survey is closed), *Always* (whenever Spyhop is open) or *Never*.
  - **Keep the screen on too** also stops the screen turning off.
  - The setting shows whether it's holding the computer awake now. Closing a laptop's lid still puts most laptops to sleep. When Spyhop quits or crashes, the computer's own sleep settings apply again.
  - Uses `caffeinate` on macOS, a power request on Windows and `systemd-inhibit` on Linux.

## 0.9.2 — 2026-11-06

- **Survey → About → Updates:** **Check for updates** looks for a newer Spyhop at github.com/hansenjohnson/spyhop (the latest release, or the main branch until there is one) and shows what's new.
  - **Install** downloads it, keeps a backup of the current version (in Spyhop's `updates` folder), installs it without touching your surveys, lists or settings, and installs any new Python packages.
  - **Restart Spyhop now** (Mac and Linux) restarts it in the same window, and the page reloads by itself. On Windows, start Spyhop again from its icon.
  - A copy that is a git checkout is updated with `git pull`.
  - Optional: *Check when Spyhop starts*.

## 0.9.1 — 2026-11-06

- **Route waypoint popups show an ETA:** the time at which the vessel reaches that waypoint following the route from where it is now, at the survey speed, with the time and distance to go. A waypoint already behind the vessel says *passed*.
- **Off-effort tracklines** are now solid by default, and thinner than on effort (1.5 px against 3 px).
- **Line styles:** each of the on- and off-effort tracks can be solid, dashed, dotted or dash-dot, set in Settings → Map display → Trackline, next to its colour, width and on/off. The HTML summary uses the same styles.
- **Settings → Map display** now holds everything about the map's look (markers, trackline, lines and vectors, fading). Font sizes moved to their own *Text size* section.
- **Waypoints no longer fade.** Fading applies only to the trackline, sightings and events.
- **The merged CSV includes the track:** one `Track` row per track point, with position, new `SOG` and `COG` columns, its Effort label and the conditions in force at the time, in time order with the other records.

## 0.9.0 — 2026-11-06

- **Reports has its own row of tabs:**
  - **Summary**, then **Gear** (gear reported or recovered), **Dead Birds**, **Right whales** and **Blue whales**
  - Each tab has **Save as HTML…** and **Save as PDF…** (PDFs are printed by Chrome or Edge), and each is offered in **Export Data…**, as HTML, PDF or both.
  - The reports are JSON definitions (`spyhop/report_defs/`), run by `spyhop/reports.py`, which is separate from the rest of Spyhop. A group adds, changes or hides reports in the **reports folder** inside Spyhop's own folder, without touching the code. The Summary can be saved as a PDF too.
- **Species:** **Dead bird** (DEBI) was added, and is added to existing species lists.
- **Observers:** **NA** (None) is a placeholder for an empty watch position. It can fill several positions at once without a QC error, and isn't counted as an observer on watch. It was added to the default observers list.
- **Survey → About** has a **tutorial**: finding your way around, the simulator, config files, routes, starting a survey, recording, ending, error checking, reports and export. It's also in `docs/TUTORIAL.md`.
- **Documentation for sharing on GitHub:**
  - a new README (description, development status, features, system requirements, installation for Mac and Windows, starting a survey)
  - a full user guide (`docs/USER_GUIDE.md`), developer notes (`docs/DEVELOPERS.md`), a `.gitignore` and a new screenshot
- **Code clean-up:**
  - removed unused functions, imports, styles, a duplicate map method and the old `/api/survey/new` alias
  - the browser finding code moved to `spyhop/browser.py`

## 0.8.0 — 2026-11-06

- **Clock:** Settings → Clock can follow the **platform's position**. Spyhop finds the time zone there from an offline map, including daylight saving; at sea it uses the nearest coast's zone, up to 150 nm out, and the nautical zone beyond that. You can also pick **any fixed UTC offset**, from UTC−12:00 to UTC+14:00, including half and quarter hours.
- **Trackline breaks:**
  - New settings: break the trackline above **30 kn** (a GPS jump) or after **120 s** without a position. These breaks are left out of the map and of the summary distances.
  - Quality Control lists each jump or gap, and a GPS that jumps away and comes back counts as one. Its **Fix** button adds an **ERROR** row to the Effort table for that stretch, plus a row that puts the effort back. ERROR stretches count as off effort and aren't drawn.
- **Quality control:**
  - The duplicate check now only flags a sighting entered twice (same time, species, number and position). Two sightings of the same species close together are fine.
  - Removed the "FieldID used for two species" check.
  - New check: a sighting further away than the visibility recorded at the time.
- **Route:**
  - Click a waypoint of an active route for a popup: its name and position, its distance and bearing from the vessel (kept up to date), and **View the route**.
  - The default look is grey and dotted.
  - **Import GPX…** loads a route. One exported by Spyhop comes back exactly as it was designed; any other GPX loads as a manual route.
- The Vis column no longer wraps.
- On start, the launchers install any Python packages a new version needs (this version adds `tzfpy`, the offline time-zone map).

## 0.7.0 — 2026-11-06

- **Planning is now Survey → Route**, with:
  - **Activate route:** locks the waypoints (no dragging or editing) and keeps the route on the map from every tab. Deactivate to edit it again.
  - a **Route** entry in the map's layers menu to show or hide it
  - **Appearance:** colour, line style (solid, dashed, dotted, dash-dot), line width and waypoint size, also used in saved overlays
  - **Clear route**
  - right-click the map → **Start route here**, which opens the Route tab with that point as the start
- **Summary moved into Reports.** Ctrl/Cmd+4 now opens Reports, and existing shortcuts are updated.
- The summary has a **North Atlantic right whale sightings** table: time, position, number, calves, field ID and notes for each sighting (also in the HTML summary).
- **Past surveys as overlays:** Survey → Waypoints lists the other surveys in the data folder, each with **Add as overlay** (its trackline, sightings and events).
- **Opening an old survey zooms the map to it.**

## 0.6.0 — 2026-11-06

- **Survey → Planning:** design tracklines.
  - **Manual:** click waypoints on the map; drag them to move them.
  - **Systematic:** parallel legs from a start point, with direction, number of legs, leg length, spacing, and which side the next leg goes to.
  - **Both:** choose the survey speed and whether to start from the vessel or from the first point. A table shows each leg's course, distance and time, with running totals and ETAs.
  - Save a plan as a **map overlay** and/or **export it as GPX** (waypoints plus a route).
- **Survey → About** is a tab of its own (it was in File). The version badge in the status bar opens it.
- The Survey tabs are now in this order: File, Settings, Shortcuts, Waypoints, Planning, NMEA, Summary, Quality Control, Reports, About.
- Removed the 📂 overlay button from the map; overlays are imported in Survey → Waypoints.
- Overlays honour simple style properties (`stroke`, `stroke-width`, `marker-color`, `dash`), so saved plans keep their orange dashed look.

## 0.5.0 — 2026-11-05

- **Version number**, shown in the status bar, the window title and Survey → About. Spyhop says when it has been updated.
- **Diagnostic logs:** `logs/spyhop.log` in Spyhop's folder, rotated at 5 MB. It records:
  - start-up details and errors
  - slow moments
  - errors from the Spyhop window
  - a performance snapshot every 5 minutes
  - hard crashes (to `logs/crash.log`)

  **Save diagnostics…** (now in Survey → About) bundles the logs and settings (no survey data) to send with a bug report.
- **NMEA plots:** click an instrument reading in Survey → NMEA to plot it since the start of the survey. Readings are saved every 5 s to `<survey>_instruments.csv`.
- **Marks are now Waypoints**, in Survey → Waypoints, together with the map overlays. `marks.csv` is renamed `waypoints.csv`.
- **Negative bearings** are accepted: −10 is stored as 350, which is handy for relative bearings to port.
- **Map popups** show only the essentials: time, position, species and number (or event and ID), the current distance and bearing from the vessel, and a link to the row.
- **Merged CSV:** times are read more leniently, and sightings before any effort row are labelled "no effort row yet". The file also gains a SpyhopVersion column.
- Removed **Quit Spyhop**; close the Terminal window instead.
- The survey details file records which Spyhop version started the survey and which last saved it.

## 0.4.0 — 2026-11-05

- A **Spyhop icon** (Applications/Desktop on a Mac; Desktop/Start menu on Windows) that opens Spyhop in Terminal.
- **Export dialog:** separate CSVs, merged CSV, GPX, GeoJSON and the HTML summary, as one file or a zip.
- **Survey → NMEA:** instrument readings, a raw NMEA log and the GPS inputs.
- **Quality control check.**
- Gear Reported and Gear Recovered event types.
- **Survey sub-tabs:** File, Settings, Shortcuts, NMEA, Summary, Quality Control, Reports.
- Much faster map: the coastline is drawn only in view.

## 0.3.0 — 2026-11-05

- **Survey lifecycle:** Start and End effort rows, Start/End/Close/Open, crash recovery.
- Survey details (platform, organization, chief scientist and email).
- A choosable data folder.
- The HTML summary with an offline map.
- The track CSV records Start/ON/OFF/End; exports leave out RowID.
- Tidier Settings layout.

## 0.2.0 — 2026-11-04

- FieldID and event IDs, a local/UTC clock, and live Summary counters with observers and conditions.
- Graticule, heading vector, sighting lines, FieldID lines and fading.
- The GPS simulator with a fixed heading.
- Minimize/maximize instead of map-only and log-only views.
- Renamed to **Spyhop**.

## 0.1.0 — 2026-11-04

First build: a Python rebuild of the OpenCPN spotter plugin. It has the Leaflet map, the data tables, NMEA input, CSV storage with undo/redo, and offline charts.
