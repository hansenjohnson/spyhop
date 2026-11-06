# Spyhop user guide

The full reference for Spyhop. For a quick tour, see the [tutorial](TUTORIAL.md). For installing and starting Spyhop, see the [README](../README.md).

## Running Spyhop

To practise without a GPS, add the simulator. It steams on a fixed heading and speed (default 000°T at 10 kn) from Cape Cod Bay:

```
python -m spyhop --sim
python -m spyhop --sim --sim-heading 135
```

It also sends made-up depth, wind, weather and engine readings, so the NMEA tab has something to show. The simulator is listed with your other inputs in the **NMEA** tab (under *GPS / NMEA inputs*) (a `--sim` one is marked *this session only*). Change its heading or speed there and press **Apply**; the boat takes the new heading at once, from where it is. Untick it and press **Apply** to stop it. Whenever you've edited the inputs but not applied them, the button reads **Apply — unsaved changes**.

Other options: `--install-shortcut` (make the Spyhop icon again), `--nmea serial:COM4:4800`, `--nmea udp:10110`, `--nmea tcp:192.168.1.5:10110`, `--nmea gpsd:127.0.0.1`, `--nmea file:mylog.nmea`, `--data-dir PATH`, `--window` (a native window, needs `pip install pywebview`), `--host 0.0.0.0` (lets a tablet on the boat network connect to the same recorder), `--no-browser`.

**Quitting:** close the Terminal/console window, or press Ctrl+C in it. Your data is saved as you go, so quitting never loses anything. Closing only Spyhop's own window leaves it running, still recording the track; open the icon again to get the window back. If you quit with a survey still active, Spyhop asks whether to continue it the next time it starts.

**Diagnostic logs:** Spyhop keeps a log in `logs/` in Spyhop's own folder (Survey → About → Open folder). `spyhop.log` is rotated at 5 MB, keeping 5 old ones. It records:
- the version and system at start-up
- each action and whether it worked or was refused (never the data itself)
- errors with their details, from Spyhop and from its window
- slow moments
- a performance snapshot every 5 minutes (CPU, memory, server delays, NMEA rate, window memory)

`crash.log` catches hard crashes. **Save diagnostics…** zips the logs, settings and system details into one file to send with a bug report. The zip has no survey data and no team names.

**If Spyhop feels slow:** the Terminal window prints a line starting `spyhop.slow` whenever something takes too long: the server busy for more than 0.25 s, a request over 1.5 s (with map tiles labelled as downloads from the internet), or the Spyhop window busy for more than 0.2 s (saying whether you were moving the map and which tab was open). Nothing is printed while everything is quick. Copy those lines when reporting slowness.

## Planning a route (Survey → Route)

The route is drawn on the map with numbered waypoints and kept between sessions. While it's a **draft** it shows only while the Route tab is open; once **activated** it stays on the map from every tab.

- **Start a route from the map:** right-click and choose **Start route here**. The Route tab opens with that point as the start (the first waypoint in manual mode, carrying on with Add points; the start point in systematic mode).
- **Survey speed** (kn) sets the times.
- **Start position:** the vessel's current position (the route follows the vessel until it's activated), or the first point (manual) or a chosen point (systematic).
- **Manual:** press **Add points on the map** and click where each waypoint should go. Drag a waypoint to move it. Use **Undo last point** or the ✕ in the waypoint list to take points off.
- **Systematic:** parallel legs ("lawnmower"). Choose:
  - the **start point** (pick it on the map, type it, or use the vessel position); drag waypoint 1 to move the whole pattern
  - the **survey direction**: the bearing of leg 1
  - the **number of legs**, the **leg length** and the **leg spacing** (nm)
  - which side the next leg goes to (starboard or port of leg 1)

  Legs alternate direction, joined by crossings of the leg spacing.
- **Route** box at the top:
  - **Activate route** locks the waypoints where they are (no dragging or editing, and a vessel start is frozen at the position it had) and keeps the route on the map from every tab. **Deactivate** to edit it again.
  - **Clear route** removes all its waypoints (saved overlays and GPX files are kept).
  - **Zoom to route.**
  - The map's layers menu has a **Route** entry to hide or show it.
- **Tables:**
  - **Legs:** from/to, course, distance, time, running total distance and time, and the ETA if you start now. Crossings are greyed.
  - **Totals:** total distance (and distance on the legs), total time and finish time.
  - **Waypoints:** each position.

  Times assume the survey speed and no time for turns.
- **Appearance:** colour, line style (solid, dashed, dotted, dash-dot), line width and waypoint size (numbers show from 14 px). The default is grey and dotted. Used on the map and in saved overlays.
- **Active route waypoints:** click one to see:
  - its name and position
  - its distance and bearing from the vessel
  - its **ETA**: following the route from where the vessel is now, at the survey speed (or *passed*)
  - a **View the route** link

  Everything except the name and position is kept up to date as the vessel moves.
- **Save as map overlay** saves the route, under its name, as a GeoJSON overlay. It's drawn under *Imported overlays* in the map's layers menu and listed in Survey → Waypoints, where you can remove it.
- **Export GPX…** downloads the waypoints and a route for a chart plotter or OpenCPN, and keeps a copy in `exports/`.
- **Import GPX…** loads a route back. A GPX exported by Spyhop holds the whole design (mode, legs, speed, appearance), so it comes back exactly; from any other GPX, the route (or else the waypoints, or a track) becomes a manual route.

## Connecting GPS / instruments (Survey → NMEA)

The **NMEA** tab (inside Survey) has three parts:

- **Instruments:** the latest reading of everything coming in, grouped as Navigation (SOG, speed through water, COG, heading, rate of turn, rudder, GPS fix, satellites, HDOP), Depth, Wind (apparent and true), Weather (air and water temperature, humidity, dew point, pressure), Engine (RPM per engine or shaft) and Other transducers. Each tile shows the sentence it came from and how old it is, and turns grey after 15 seconds without an update.
- **Plots:** click any numeric reading to plot it since the start of the survey, with now/min/max/mean and a hover readout. Angles are plotted as dots, because they wrap at 360. While a survey is active, Spyhop saves every reading every 5 seconds in `<survey>_instruments.csv` (DateTime, Key, Label, Unit, Value). That file is part of the separate-CSV export, so the history survives a restart.
- **Raw NMEA log:** tick **Record raw NMEA to a file** to save every sentence from every input as it arrives. Each line starts with the UTC time and the input name (untick that option for plain NMEA that any NMEA tool reads). Logs go in `nmea_logs/` in the survey data folder, one file per survey (`<survey>_nmea_<time>.nmea`; a new file starts when you start, open or close a survey). Recording carries on after a restart until you switch it off. A log can be played back as a **File** input.
- **GPS / NMEA inputs** (moved here from Settings).

Set up inputs in **NMEA → GPS / NMEA inputs**. You can run several inputs at once. The first one in the list is preferred, and the next one takes over if it goes quiet for 5 seconds.

| Input | Use it for |
|---|---|
| **Serial** | A USB GPS puck or an NMEA 0183 serial adapter. The port box lists the ports it finds. GPS pucks are usually 4800 or 9600 baud. |
| **UDP** (default: port 10110) | NMEA broadcast on the boat network by a multiplexer, plotter or OpenCPN. In OpenCPN, add a *Network → UDP → output* connection to 127.0.0.1:10110. |
| **TCP** | NMEA servers (multiplexers, Signal K's NMEA 0183 TCP stream on port 10110). |
| **GPSD** | Linux gpsd. |
| **File** | Replays a logged `.nmea` file in real time. |
| **Simulator** | Practice and testing. |

It reads RMC, GGA, GLL and VTG for position, speed and course, and HDT, THS, HDG and HDM for heading. For the Instruments panel it also reads VHW and VBW (speed through water), DPT, DBT, DBS and DBK (depth), MWV, VWR, VWT and MWD (wind), MTW, MTA, MHU, MMB and MDA (weather), RPM (engines), ROT, RSA, and XDR transducers (temperature, pressure, humidity, RPM, voltage, tank levels, angles). The raw NMEA monitor at the bottom of the tab shows exactly what is arriving.

## What's on screen

- **Status bar (top):**
  - the time, with its zone (e.g. `14:31:05 EST`, or `UTC` — choose the clock in Settings), and the position, with a warning if there is **NO GPS**, the **GPS is LOST** (no fix for 10 s), or the position is **NOT MOVING** (the GPS stopped updating while under way)
  - speed, course and heading
  - the **conditions-check countdown** (click it to change the interval), which flashes when overdue
  - survey name
  - whether tracking is on (switch it on or off in Settings)
  - latest effort state
- **Map:**
  - zoom and pan
  - the vessel with a heading vector (on/off and length in Settings → Map display)
  - default marker shape and colour for sightings and events are in Settings → Map display (species and event-type colours from your lists take priority); waypoints have their own shape and colour on each row
  - the track: green on effort, and a thinner grey line off effort. Set each one's colour, width and line style (solid, dashed, dotted, dash-dot), or hide it, in **Settings → Map display → Trackline**.
  - **Settings → Map display** has everything that changes the map's look: markers, the trackline, lines and vectors, and fading. Fading dims the trackline, sightings and events older than the chosen hours; waypoints never fade.
  - sighting, event and waypoint markers, each with a label and a popup. The popup shows only the essentials:
    - **sightings:** the time, the animals' position, the species and the number (with calves)
    - **events:** the time, position, event and ID
    - **all:** the current distance and bearing from the vessel, which keeps updating while the popup is open, and a link to the row in its table
  - dashed lines from the vessel to each sighting (on by default) and, optionally, a dotted line joining re-sightings of the same FieldID from oldest to newest
  - optional fading of the track and markers older than a number of hours you choose
  - **toolbar buttons:**
    - ⌖ follow the vessel
    - 📏 measure: click to add points, double-click or Esc to finish, click again to clear. Each leg shows true and magnetic bearing plus distance, and the total.
    - ◎ range rings
    - ⤢ zoom to the whole survey (overlays are imported in Survey → Waypoints)
  - **layers menu** (top right): base maps, offline charts, and overlays you can switch on and off, including a **graticule** (lat/lon grid; spacing adapts to the zoom, longitude labels run vertically so they don't collide)
  - **labels:** sightings show the species code plus the FieldID if there is one, e.g. `RIWH Eg-3720` (or SightNo if there's no species yet); events show their event code and ID, e.g. `CTD C-07` (or E1, E2… if both are blank)
  - **right-click menu:** add a sighting, event or waypoint at that point; measure from here; copy the position
  - **readout (bottom-left):** cursor position, bearing and distance from the vessel, and a nautical-mile scale
- **Tabs:** **Sightings**, **Effort**, **Events** and **Survey**. Each data tab has **Add row**, **Delete row**, **Undo** and **Redo**. With no survey open, Spyhop opens on **Survey → File** (see *Surveys* below).
  - **Survey** has a second row of tabs:
    - **File:** start, end, close, open, export and clear surveys; survey details; the data folder.
    - **Settings**
    - **Shortcuts:** every keyboard shortcut and what it does.
    - **Waypoints:** the waypoints table, and the **map overlays**: import or remove GeoJSON/GPX/KML files, and add **past surveys** in the data folder as overlays (their trackline, solid on effort and dashed off effort, sightings and events; press **Update** after changing one).
    - **Route:** plan and activate a route (see *Planning a route* below).
    - **NMEA:** instrument readings (click one to plot it), the raw NMEA log and the GPS inputs.
    - **Quality Control**
    - **Reports:** the Summary and the other reports (below).
    - **About:** the version, the tutorial, the changelog, the diagnostic logs (**Save diagnostics…**), and **Updates**: **Check for updates** looks on GitHub for a newer Spyhop and can install it (with a backup of the old version) and restart. Tick *Check when Spyhop starts* to be told automatically when there's internet.
  - Clicking **Survey** returns to the one you used last. "Settings → …", "NMEA" and so on below mean those tabs inside Survey.
- **Reports** has its own row of tabs. **Summary** comes first, then one tab per report (see *Reports* below). **Summary** shows:
  - the summary numbers, then the survey's start and end times, duration and details (platform, organization, chief scientist and their email)
  - **Save as HTML…** saves the summary as **one HTML file**, and **Save as PDF…** as a PDF of the same page, with an interactive map of the survey (track, sightings and events, with popups) at the top and the rest in the same order as the Reports tab. Waypoints aren't included, since they don't belong to a survey. It opens in any browser, even offline, with no Spyhop needed, so it's easy to email or share.
    - The offline coastline is the default base map; OpenStreetMap and Esri Ocean are offered when there's internet.
    - A copy goes in the survey's `exports` folder.
  - counts by species (sightings, number, calves) and by event type
  - **North Atlantic right whale sightings:** each one, with time, position, number, calves, field ID and notes
  - **observers on watch**: time each observer spent at Port, Recorder and Stbd while effort was ON, and their total
  - the range of environmental conditions (visibility, sea state, weather, glare) for the whole survey and on effort only
  - While effort is ON, *Time on effort*, the distances and the watch times count up live (marked ●).
- **Bottom row:** a description of the selected column (e.g. what **Ref** means) and **View**. Start, End, Close, Export and Clear are in **Survey → File** only, so they can't be clicked by accident. **View** options:
  - **Split vertical** or **Split horizontal:** drag the divider to resize
  - **Overlay:** a floating log window you can drag and resize
- **Minimize / maximize the tables:** use the ▁ and □ buttons at the right end of the tab bar, Ctrl+Shift+M (Cmd on Mac), or double-click the divider.
  - Minimized in the side-by-side view, the tables shrink to a slim **◀ Data** bar. In the other views only the tab bar is left.
  - Clicking a tab, the Data bar or ▴, or adding a row with a shortcut, brings the tables back.
  - Maximized leaves a strip of map visible. ❐ restores the normal size.

### Entering data

The tables work like a spreadsheet:

- Click a cell and start typing, or press Enter/F2 to edit. Enter saves, Tab saves and moves right, and Esc cancels. The arrow keys move between cells.
- **Dropdown cells** filter as you type and also match **species codes** (`huwh` finds Humpback whale).
- **Multi-select cells** (Behaviors) open a checklist.
- **Map** checkboxes toggle with a click or the Space bar.
- **Lat/Lon** are accepted in almost any form: `41 30.5 N`, `41°30'30"N`, `41.508`, `4130.5N`. If you leave off N/S/E/W, it uses the vessel's hemisphere, so `70 20.5` near Cape Cod means 70°20.5′W. Choose DDM, DD or DMS display under **Settings → Lat/lon format**; every table updates at once. Files always store decimal degrees.
- **Times** are shown in the survey clock (Settings → Clock), with the zone in each cell (e.g. `15:52:22 EST`). Type `14:05` to change only the time of day. The files always store each time with its UTC offset, so switching the clock never changes data. The clock can be:
  - **From the platform's position:** the time zone at the GPS position, from an offline map (`tzfpy`), daylight saving included. At sea, the nearest coast's zone within 150 nm (so a survey off Cape Cod keeps Eastern time), and the nautical zone further out. Settings shows which zone was found and how; it's checked again after every 5 nm.
  - **This computer's time zone**, **UTC**, or **any fixed UTC offset** (UTC−12:00 … UTC+14:00, including half and quarter hours).
- **Trackline breaks** (Settings → Tracking): the trackline and the summary distances are broken where the platform would have moved faster than **30 kn** between two points (a GPS jump; use about 200 for aerial surveys), or where no position came in for **120 s**. 0 turns either off. Quality Control lists each jump or gap (one that jumps away and back counts as one), and its **Fix** button adds an **ERROR** row to the Effort table at the start of the stretch, plus a row at its end that puts the effort and conditions back. ERROR counts as off effort, and the stretch isn't drawn.
- **Sightings:**
  - New rows get the time, vessel position and an auto-incrementing **SightNo**. **FieldID** (after Images) is free text for your own ID (photo-ID, catalogue number…). It becomes the sighting's map label. The cursor skips it on a new row so you go straight to Species.
  - Enter **Bearing** and **Distance**, and the animal's position (**SigLat/SigLon**) is calculated. Bearings can be negative and count back from 360 (−10 is stored as 350), which is handy for relative bearings to port. Without a bearing and distance, SigLat/SigLon are the vessel position.
  - The vessel heading is saved in the CSV (`VesHdg`, not shown in the table) so that bearings relative to the bow can be converted.
  - Each row stores its own bearing reference (**Ref**: M magnetic, T true, R relative to the bow) and distance **Unit**, so changing the defaults in Settings never changes old rows.
  - Magnetic bearings use the World Magnetic Model.
- **Waypoints** (Survey → Waypoints; called Marks before 0.5.0): each waypoint has its own **Shape** (Circle, Diamond, Square, Triangle, Star) and **Color** (pick from the list or type a `#hex` code).
- **Events:** the default list includes **Gear Reported**, **Gear Recovered** and **Other** (they're added once to existing `event_types.csv` files too; delete them there if you don't want them). **ID** is free text for an instrument or sample ID (CTD cast number, tag ID, drifter ID…). Each event type has a short code in `event_types.csv` (the `event_code` column, e.g. `CTD`, `ACOD`). Type the code to pick the event, and the map label shows code + ID.
- **Effort:** the Effort column is **Start**, **ON**, **OFF** or **End**.
  - The first row is always **Start** (added when the survey starts; it can't be changed or deleted), and **End** can only be the last row.
  - A new row copies everything from the previous row except the notes. Right after the Start row, Effort is left blank for you to choose ON or OFF.
  - Start and End count as off effort in the summary and on the track.
- Every edit is saved to disk immediately. Undo/redo is unlimited per tab.

### Keyboard shortcuts (listed in Survey → Shortcuts; edit them in `shortcuts.csv`)

| Keys (Cmd on Mac) | Action |
|---|---|
| Ctrl+Enter | Add a row to the table you're in (also works while typing in a cell; that edit is saved first) |
| Ctrl+Shift+S / E / V / K | Add sighting / conditions row / event / waypoint |
| Ctrl+Shift+F | Add an effort row that switches effort ON↔OFF |
| Ctrl+Shift+R, Ctrl+Shift+H | Add a sighting pre-filled with North Atlantic right whale / Humpback whale |
| Ctrl+Shift+U / Y | Undo / redo |
| Ctrl+1 … 5 | Sightings, Effort, Events, Survey → Reports, Survey → Settings |
| Ctrl+PageUp/PageDown, Alt+←/→ | Previous/next tab |
| Ctrl+Shift+C | Centre on the vessel |
| Ctrl+Shift+M | Minimize / restore the data tables |

A shortcut can pre-fill fields: `Mod+Shift+B,add:sightings,Species=Fin whale;Observer=OBS1`.

## Reports (Survey → Reports)

- **Summary** is described under *What's on screen*.
- The built-in reports are simple tables of selected records, in time order:
  - **Gear:** Gear Reported and Gear Recovered events (time, event, position, notes)
  - **Dead Birds:** sightings of the species *Dead bird* (code DEBI; time, position, notes)
  - **Right whales:** North Atlantic right whale sightings (time, position, number, calves, notes, with totals)
  - **Blue whales:** the same for blue whales
- They update as you add records. Each has **Save as HTML…** and **Save as PDF…**, and each is offered in **Export Data…**.
- **PDFs** are printed by Google Chrome or Microsoft Edge, which Spyhop finds by itself. Set `SPYHOP_CHROME` to the path of another Chromium-based browser if needed.
- **Your own reports:**
  - Every report except Summary is a JSON file, read by `spyhop/reports.py`, which is separate from the rest of Spyhop.
  - Groups that need different reports don't need to change Spyhop's code: press **Open the reports folder** and add a `.json` file there.
  - A file with the same `id` replaces a built-in report, and `{"id": "…", "enabled": false}` hides one.
  - Press **Reload reports** afterwards.
  - The folder's README, the same as [spyhop/report_defs/README.md](../spyhop/report_defs/README.md), describes the format. Copies of the built-in reports are in its `examples` subfolder.

## Maps offline

- **Bundled coastline:** a world coastline from Natural Earth (1:10 m scale) always draws under the map, so you have a coastline even with no internet. Only the part in view is drawn, simplified to the zoom, so it stays quick. It is coarse, so don't navigate by it.
- **Tile cache:** online layers (Esri Ocean, NOAA charts, OpenSeaMap seamarks, etc.) are saved to disk as you view them. In port, use **Settings → Map → Download visible area** to fetch a survey area ahead of time. OpenStreetMap's tile policy forbids bulk downloading, so that layer can't be pre-fetched.
- **MBTiles:** put `.mbtiles` files in the `charts` folder and restart. Free, weekly-updated **NOAA nautical charts** for US waters are available at <https://distribution.charts.noaa.gov/ncds/>: click a region and download the MBTiles file.
- Map layers are listed in `tile_sources.csv`. Add any XYZ tile server, or an ArcGIS `export` URL using `{bbox}`.

The online layers could not be tested from the machine this was built on, which had no internet. Check them once on a connected laptop before you sail.

## Surveys

Surveys are managed in **Survey → File**; the quality control check is in **Survey → Quality Control**.

- **Start New Survey…** asks for a name and the survey details, then adds the **Start** row to the Effort tab. The trackline starts recording.
  - The details are **platform name** (vessel name), **platform type** (Vessel, Plane, Land or Other), **organization**, **chief scientist** and **chief scientist email**. They're filled in from your last survey and can be changed any time in Survey → File.
  - They're saved with the survey as `<survey>_metadata.csv` and included in exports and the summary.
  - The name is used exactly as typed (only characters that file systems forbid, such as `/ : * ?`, become `_`), so use your team's own convention, e.g. `NEAQ_CCB_2026-11-04_A`. A name that's already in use is refused rather than changed.
  - If another survey is still active, you're asked whether to **End** it or just **Close** it (keeping it active) first.
- **End Survey…** adds an **End** row and stops the trackline. An ended survey can still be corrected, but no new rows can be added. To carry on, delete its End row in the Effort tab (or Undo).
- **Close Survey…** clears the tabs. Everything is already saved as you go. A closed survey that hasn't ended stays *active*, so you can continue it later.
- **Surveys in this folder** lists every survey with its status (Active/Ended), start and end times, and number of sightings.
  - Press **Open** to open one. If it's still active, you're asked whether to **Continue** it (tracking resumes) or just open it to look at or correct.
  - Surveys made before Start/End existed get a Start row added at the top, timed at their earliest record, with a notice.
- **Quality control check** (Survey → Quality Control): press **Run quality control check** before you finish a survey (or any time). It lists problems as **errors** (must fix), **warnings** (probably wrong) and **notes** (worth a look), and **Show** takes you to the row and column. It doesn't change anything, except when you press a **Fix** button. **Save report…** downloads the list as a CSV. It checks:
  - **Survey details:** every field filled in, and a valid email.
  - **Required fields:** Sightings — everything except Behaviors, Bearing, Ref, Dist, Unit, FieldID and Notes. Effort — everything except Notes (Start and End rows need only the time and position). Events — everything except ID and Notes.
  - **Valid values:** choices are in their lists; numbers, positions and times can be read; no time is in the future; nothing is before Start or after End; rows are in time order; no SightNo or EventNo is used twice; the survey starts with Start and has an End.
  - **Plausible values:** Num a whole number of at least 1 (flagged over 500); Calves not more than Num; Bearing 0–360° (negative bearings are stored as their 0–360 equivalent) and Dist not negative, given together and with their Ref and Unit; relative bearings have a heading; animals within 10 nm of the vessel and no further than the visibility on the Effort row in force; vessel positions within 0.5 nm of the trackline at that time; positions not on land (by the bundled coastline, ignoring the first 0.5 km); no track jumps or gaps beyond the trackline-break settings (each has a **Fix** button that marks it with an ERROR Effort row).
  - **Protocol:** a new Effort row at least every 1.5 × the reminder interval while on effort; nobody in two watch positions at once; the sighting's observer is on watch; a sighting entered twice (same time, species, number and position) or a duplicated event (same type and ID within 30 s). A FieldID can be reused for different species, and two sightings of one species close together are fine. Notes list sightings off effort, effort in sea state above 5 or visibility under 0.5 nm, and observers on watch over 2 hours without a break.
  - The thresholds are at the top of `spyhop/qc.py`.
- **Crash recovery:** if Spyhop is closed or crashes while a survey is active, it reopens that survey on the next start and asks whether to continue. Tracking resumes only once you say so.
- **Clear Survey Data…** is the only thing that deletes data. It needs two confirmations, the second by typing the survey name, and closes the survey.

## Your data

Spyhop's own folder holds your lists and settings:

- Windows: `%APPDATA%\Spyhop`
- Mac: `~/Library/Application Support/Spyhop`
- Linux: `~/.local/share/Spyhop`

If you used Spyhop under its earlier name (Whale Survey Recorder), the old `WhaleSurveyRecorder` folder is moved to `Spyhop` the first time Spyhop starts, so your surveys and config files carry over.

The **survey data folder** holds the survey files, waypoints and exports. It's `data/` inside Spyhop's folder unless you choose another one under **Survey → File → Data folder** (**Choose folder…** opens your computer's folder chooser, or type/paste a path). It's remembered between sessions. If it isn't found at start-up (e.g. an unplugged drive), Spyhop uses the default for that session and tells you. Switching folders closes the open survey first.

```
Spyhop/                                   (Spyhop's own folder)
  species.csv  event_types.csv  observers.csv  behaviors.csv   <- your lists (name, colour, code)
  shortcuts.csv  display.csv  tile_sources.csv
  settings/  settings.json  current_survey.txt
  charts/    *.mbtiles      overlays/  imported GeoJSON/GPX/KML
  reports/   your own report definitions (*.json), with a README and examples/
  logs/      diagnostic logs (spyhop.log, crash.log, diagnostics zips)
  data/                                   (default survey data folder — or the one you chose)
    <survey name>_sightings.csv   _effort.csv   _events.csv   _track.csv   _metadata.csv   _instruments.csv
    waypoints.csv                 <- kept across surveys (an older marks.csv is renamed to this)
    exports/   <survey>_export_<time>.zip, or a single exported file; saved summaries and reports (.html, .pdf)
    nmea_logs/ <survey>_nmea_<time>.nmea  <- raw NMEA, when recording is on
```

- The track CSV's **Effort** column is `Start` (from the Start row until the first ON or OFF), then `ON`/`OFF`, and `End` on the final point, written when you end the survey. A script can tell the start and end of the track apart from off-effort periods.
- The working CSVs have a **RowID** column. Spyhop uses it to tell rows apart, for undo/redo and for keeping open windows in step, because SightNo can be edited and Effort/Event rows have no other unique key. Leave it alone when you edit a file by hand. Exports leave it out.

- **Export Data…** asks which formats you want (it remembers your choice):
  - **Separate CSV files:** sightings, effort, events, track, instrument readings, survey details and waypoints, one file each, as Spyhop records them (without RowID). The track's Effort values are recalculated from the final Effort table.
  - **Merged CSV file** (`<survey>_merged.csv`): sightings, effort, events and the track points in one table, in time order, one row per record. `Record` says which it is (Sighting, Effort, Event or Track). Track rows have the position, `SOG` and `COG`, and their Effort label from the track file (Start, ON, OFF, End or ERROR). Every row also has the Spyhop version (SpyhopVersion) and the survey details (Survey, PlatformName, PlatformType, Organization, ChiefScientist, ChiefScientistEmail) and the effort and conditions in force at that time (Effort, Visibility, SeaState, Weather, Glare, Port, Recorder, Starboard, from the latest Effort row at or before it; "no effort row yet" before the first). So each sighting can be analysed with its conditions without a join. `Lat`/`Lon` is the vessel position (the event position for events); sightings keep SigLat/SigLon too, and the event ID is `EventID`.
  - **GPX file:** the track and waypoints, for GPS units and mapping apps.
  - **GeoJSON file:** the track split by effort, and points with all their columns, for QGIS or ArcGIS.
  - **Summary report** and each **Report:** the same pages as in Reports, as HTML, PDF or both (*Save the summary and reports as*).

  One format is saved and downloaded as that file. Several (or the separate CSVs) come as **one zip**. Everything is also kept in the data folder's `exports/`.
- When a new version adds or removes columns, existing survey files are updated automatically: data is carried over by column name and a copy of the original is kept as `*.csv.bak-<time>`. A CSV that isn't one of this app's files is renamed `*.csv.bak-<time>` and the tab starts empty. Nothing is overwritten.

If a CSV is open in Excel on Windows, saving can fail. Spyhop warns you, keeps the edit in memory and saves it with your next change. It's safer to open copies of the files from **Export** rather than the live ones.

## Compared with the OpenCPN plugin

Kept from the plugin:

- the same tabs, status bar, reminder countdown and auto-tracking on Effort ON
- copy-forward of Effort rows and blank new rows
- SightNo with a confirmation before it's changed
- the NumConf and IDrel lists
- autocomplete dropdowns and the Behaviors checklist
- per-tab undo/redo
- DDM/DD/DMS display (now set in Settings only) and lenient position parsing
- immediate saves and `.bak` files on schema changes
- New Survey, Clear Survey (double confirm) and Export
- the config CSVs and remappable shortcuts
- split and overlay views (map-only/log-only were replaced by minimize/maximize buttons)
- marker shape and colour per tab, with species and event colours
- grid and UI font sizes

New or different:

- Markers are clickable, with popups.
- New map tools: measure, range rings, right-click "add here", lines from vessel to sighting, imported overlays, and offline MBTiles and tile caching.
- A Waypoints tab, with map overlays.
- GeoJSON, GPX and merged-CSV export, chosen per export.
- An NMEA tab with live instrument readings and raw NMEA logging.
- A quality control check.
- Several NMEA inputs at once, with priority and a raw monitor.
- The keyboard opens dropdowns on Windows too. This was a known limitation in the plugin.
- Per-row bearing reference and distance unit.
- FieldID on Sightings and ID on Events.
- A clock in local time, UTC, any UTC offset, or the zone at the platform's position; a live Summary with environmental-condition ranges; reports defined in JSON files.
- The Surfacings tab was dropped.
- An extra Glare column on Effort.
- **Check these before relying on old pipelines:**
  - The CSV column names are this app's own (see `spyhop/schema.py`). They may not match the plugin's `column_definitions.csv` exactly.
  - The Visibility, Weather and Images lists are best guesses.
  - Sea state is 0–9.

  All of these are defined in one file (`schema.py`) and are easy to change.
