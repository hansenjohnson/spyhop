# Changelog

Spyhop's version is set in `spyhop/__init__.py` and shown in the status bar, the window title, Survey → About, the Terminal window, the diagnostic logs and exports.

The numbers are MAJOR.MINOR.PATCH. MINOR goes up for new features and PATCH for fixes only. Version 1.0.0 will be the first release used on real surveys. After that, MAJOR goes up only when the data files change in a way older versions can't read.

Earlier builds had no version numbers; the entries for 0.1–0.4 were reconstructed afterwards.

## 0.23.0 — 2026-11-07

- **Tools → Routes:**
  - **Close route** (and **Close** on the route being edited in Saved routes) puts the route away: the editor is emptied and it's no longer drawn. It asks first if there are unsaved changes or the route is active. *Clear route* is now **Clear waypoints**.
  - New mode **Systematic — sawtooth (zig-zag)**: leg direction, leg length, turning angle at each waypoint, first turn to starboard or port, number of legs, and **one way** or **return** (a reciprocal sawtooth back from the far end, mirrored so the legs make a chain of diamonds). Saved and reopened like the other modes.
- **Map layers menu:**
  - One **Routes** entry switches the current route and the saved routes on or off together (replacing *Current route* and *Saved routes*); which routes are drawn is chosen in the Routes tab.
  - Overlays are in two sections, **Offline overlays** and **Online overlays**, like the map tiles.
- The **survey data folder** and **Spyhop folder** moved from the Survey tab to **Settings → General → Folders**; the Survey tab shows where surveys are saved, with a link there.

## 0.22.0 — 2026-11-07

- **Config packs hold a team's whole setup** (Settings → Templates), so every computer can be set up the same way from one small file:
  - **Shared settings:** lat/lon format, clock, bearing reference, distance unit, magnetic variation, tracking interval and breaks, effort reminder, keep awake / screen on, raw NMEA log. The pack's **network GPS / NMEA inputs** (UDP, TCP, gpsd) replace this computer's; serial ports, file replays and the simulator are never in a pack, and nor is the data folder.
  - **Map feeds** (with their saved copies) and **which online overlays are switched on** (set once when the pack is used).
  - **Waypoints, routes and overlays**, if you tick them when saving the pack. These are **only added**: any the computer already has (same name, or for feeds the same address) are kept, and nothing is removed.
  - A **minimum Spyhop version** (0.22.0 or newer): a computer with an older Spyhop won't use the pack until it's updated.
  - The check before using a pack lists what's added, replaced and kept, and the settings that change. Restoring the backup made before using a pack also removes what that pack added.
  - Offline charts stay out of packs. Packs and Spyhop are still only updated by hand.

## 0.21.0 — 2026-11-07

- **Online overlays**, in a new section of **Settings → Inputs** and in the map's layers menu:
  - **AIS vessels** from Open Waters AIS (free, no account): the vessels in view, every 30 s, coloured by type and pointing the way they're heading; click one for its details and its distance and bearing from you. Option to hide vessels that aren't moving.
  - **Weather radar**: US (NOAA NEXRAD, via the Iowa Environmental Mesonet, every 5 minutes) and worldwide (RainViewer, every 10 minutes), with an opacity setting.
  - **Map feeds**: add any ArcGIS FeatureServer / MapServer layer or service, or a GeoJSON file, with its own colour and refresh. Ready-made: NOAA's **right whale Seasonal Management Areas** (shown solid while in effect, dashed otherwise) and **right whale Slow Zones / DMAs** (NEFSC). The last copy of each feed is kept, so it still shows offline.

## 0.20.0 — 2026-11-07

- **Tools → Routes** (was Route) keeps any number of routes, in a new `routes` folder in Spyhop's folder (one GPX file each, so a route can also go straight to a chart plotter).
  - **Saved routes** at the top of the tab lists them, with mode, waypoints, length and date. **Show** puts any of them on the map on every tab (in their own colours; *Saved routes* in the layers menu); **Open** loads one to edit or activate; **Zoom to**; **Delete**.
  - **Save route** / **Save as new…** / **New route** in the editor; the route being edited is marked, with *changed* until it's saved, and Spyhop asks before discarding changes.
  - GPX files copied into the folder are listed after **Look for new files**.
  - **Save as map overlay** is gone: show a saved route instead. (Overlays saved from routes before stay in Tools → Overlays.)
  - In the layers menu, *Route* is now *Current route*.
- **Status bar font size** in Settings → General → Text size.
- The Summary's title no longer says "(ended)".

## 0.19.0 — 2026-11-07

- **Tools → Filter is now Tools → Reports**, and the old Reports tab, its JSON report templates and the code behind them are gone. Tools: Waypoints, Overlays, Route, Instruments, Quality Control, Summary, Reports.
  - Saved filters are now **saved reports**, kept in the `reports` folder in Spyhop's folder (0.18's `filters` folder is moved in). Old report templates there are moved to `reports/old_report_templates` and no longer used.
  - Config packs carry saved reports as `reports/*.json`; 0.18 packs (`filters/`) still work, and old templates in older packs are ignored.
- **Run Reports…** at the top of the tab saves several saved reports at once: choose the reports, the formats (CSV, HTML, PDF) and the folder (the exports folder or one you pick). It remembers your choices.
- New column **Time (formatted)**: `2026-11-07 10:54 EST` (to the minute, with the time zone).
- The tab no longer shows "n of N sightings" or the "Sightings: …" line, and saved HTML/PDF pages no longer have that line.
- Saved pages show one **Date** for a one-day survey (a range only when it runs over several days) and include the **chief scientist's email**.
- Export Data… lists saved reports (as CSV); its PDF/HTML choice is now for the summary only.

## 0.18.0 — 2026-11-07

- **Tools → Summary** is its own tab again (after Quality Control); Ctrl/Cmd+4 opens it. Reports no longer has a Summary tab.
- **Tools → Filter** (new) shows part of a table and exports it:
  - pick **Sightings**, **Events** or **Effort**, then species or event types (chips show the codes in this survey and how many of each), the columns and their order;
  - **more conditions:** on effort only, a time range, and rules on any column (*is*, *contains*, *is blank*, *is more than* and so on);
  - the result updates as you go and as records come in, with totals under number columns; click a row to show it in its table;
  - **Export CSV…**, **HTML…** or **PDF…** (in the exports folder);
  - **saved filters**, by name, in a `filters` folder in Spyhop's folder: Right whales, Blue whales, Dead birds and Gear to start (the same as the reports). They travel in config packs and can be included in Export Data… as CSV.
- Tools → Reports is unchanged for now, so the two can be compared; Filter may replace it.
- Saved report pages of a survey still under way said "still acti" for its end date; they say "still active".

## 0.17.0 — 2026-11-07

- **Settings → Basemap** (new tab after General) holds the downloads for offline use and the charts folder, moved from General.
- The map's layers menu lists base maps under **Online map tiles** and **Offline map tiles** (the files in the charts folder, and the built-in coastline). Downloaded areas no longer need "(offline)" in their names.
- Charts folder: **Select** (was Preview) puts a chart on the map, without the dashed outline; the chart on the map is marked *On the map*. **Delete** removes a file from the folder, after asking.
- **Tools → Overlays** (new tab after Waypoints) holds the map overlays and past surveys, moved from Waypoints. Each overlay can be **shown or hidden** (remembered), zoomed to or removed; Show all / Hide all.
- Route: the start position is chosen in the Manual trackline and Systematic trackline sections (the vessel's position, or the first point clicked / a fixed point), no longer in Design.

## 0.16.0 — 2026-11-07

- **Downloaded map areas are saved in the charts folder**, one `.mbtiles` file per area, named when you download (Settings → General → Map and offline charts). Downloading again with the same name adds to the file. Esri and NOAA downloads are standard MBTiles files; a Seascape download also holds its style and label fonts, so it draws from the file alone. Copy a file to another computer's charts folder to use it there.
- **A list of the charts folder**, with what each file was made from, its zooms, tiles, size and date, and the totals. **Preview** shows one file on its own, zoomed to its area. **Look for new files** picks up files copied in without a restart, and each file is its own "… (offline)" layer in the layers menu.
- Online layers use a downloaded area's tiles before going online.
- A map server that can't be reached is skipped for a few seconds without holding up the others.
- Instrument plots close when you click outside them.
- The summary and reports no longer show "null" where a section has nothing in it (e.g. no right whales sighted).

## 0.15.0 — 2026-11-07

- **New tab layout.** The top row is now Sightings, Effort, Events, **Survey**, **Tools** and **Settings**, in place of one Survey tab holding ten others.
  - **Survey:** start, end, open and export surveys, the survey details, the surveys in the data folder, and the folders (formerly Survey → File).
  - **Tools:** Waypoints, Route, **Instruments** (formerly NMEA: live readings and the raw NMEA log), Quality Control and Reports.
  - **Settings:** **General** (formerly Settings), **Inputs** (the GPS / NMEA inputs, moved from NMEA), Shortcuts, Dropdowns, **Templates** (the config packs, moved from Survey → File) and About.
  - Tools and Settings each reopen the tab you used last. Keyboard shortcuts that open a tab keep working (Ctrl/Cmd+4 Reports, Ctrl/Cmd+5 General).

## 0.14.0 — 2026-11-06

- **Config packs are kept in a folder and listed.** They live in the `config_packs` folder of the survey data folder. Survey → File → Config packs (formerly Group config) lists them, with each one's latest change, whether it matches this computer's config, and which is in use.
- From the list: **Use this pack…** (with the same check, warning and backup as before), **Overwrite…** with this computer's config, and **Download**. **Save this computer's config as a new pack…** replaces "Make a pack from this computer…".
- Packs are saved as `<name>.spyhop.zip`: still ordinary zips, but easy to tell apart. Packs named `.zip` or `.spyhop` are read too.
- A pack pulled from the web is also kept in the folder, so it can be used again offline.
- Backups now go in `config_packs/backups` (unless you chose a folder), are listed, and can be restored with one button. Older backups stay in the `config_backups` folder in Spyhop's folder.

## 0.13.2 — 2026-11-06

- The map readout shows the water depth at the cursor, next to the scale bar, when the Seascape layer is shown. It reads Seascape's depth tiles, so it works offline wherever the map has been viewed or downloaded.
- More contour lines on the Seascape layer get their depth labels.

## 0.13.1 — 2026-11-06

- The Seascape layer no longer shows spot depth soundings; depth shading and contours stay.

## 0.13.0 — 2026-11-06

- **New default map: Seascape depths (feet)**, Open Waters' Seascape bathymetry with depth shading, contours and soundings in feet. It's drawn with MapLibre GL (bundled, BSD licence). Its style, tiles and fonts go through Spyhop's tile cache, so they work offline once viewed or downloaded. Not for navigation.
- Removed **NOAA charts (tiled)**, which no longer works, and **OpenSeaMap seamarks**. "NOAA charts (dynamic)" is now called **NOAA charts**.
- **Downloading map areas for offline use was fixed and reworked** (Survey → Settings → Map and offline charts):
  - **What was wrong:** a download kept nothing when "save tiles as you view them" was off. Zoomed in past the default highest zoom, it got no tiles at all. And it gave no reason when tiles failed.
  - **What you can set:** choose the zoom range. Spyhop shows how many tiles that is before you start, and respects each layer's top zoom.
  - **While and after it runs:** a progress bar, then a summary of what was saved, what had no data, and what failed and why. Dropped connections are retried.
  - **Seascape** can be downloaded too.
- **With no internet, the map stays quick.** After repeated failed connections, Spyhop answers from the saved tiles at once for a short while, rather than waiting on each tile.

## 0.12.0 — 2026-11-06

- **Survey → Shortcuts** is now an editor.
  - Click a shortcut's keys and press new ones, choose what it does from a list, and set pre-fills.
  - Add, delete and reorder shortcuts, restore the defaults, and Save.
  - Keys used twice, keys without Mod or Alt, and unknown actions or columns are refused, and keys the browser may take are marked.
- **Survey → Dropdowns** (new, after Shortcuts) edits the Species, Events, Behaviors and Observers lists.
  - Add, remove, reorder and sort entries, and pick colours.
  - Names and codes must be unique.
  - **While a survey is under way the lists are greyed out and can't be changed.**
- The CSV files can still be edited in a spreadsheet for big changes.
- Group config: a GitHub link to a `.zip` file in a repository now downloads that file alone, not a zip of the whole repository.
- **Group config moved to Survey → File.** **Make a pack from this computer…** now asks for your name, what changed and the file name. It fills in which files changed since the last pull or pack, and adds the row to `spyhop-config.csv` itself.
- The **Config files** section is gone from Settings. Survey → Shortcuts and each Dropdowns list have an **Open** button for their file and **Reload from the file**.
- The online map layers are now built into Spyhop, and `tile_sources.csv` is no longer created or shared in group config packs. Extra layers in an existing `tile_sources.csv` are still added.

## 0.11.0 — 2026-11-06

- **Group config** (Survey → Settings): a team keeps its config files on the web, and each computer pulls them.
  - What can be shared: the species, event types, observers and behaviours lists, shortcuts, map display, map sources and report templates.
  - Where the pack can be: a public GitHub repository (or a folder in one), a Dropbox or Google Drive link, a zip on a website, or a zip or folder on this computer.
  - **Check for new config** shows each file that would be added, changed or removed (with row counts), the pack's recent changes from its `spyhop-config.csv`, and any problems. A pack with problems can't be pulled.
  - **Pull and overwrite** replaces this computer's copies of the pack's files, with no merging. A pack's report templates replace all of this computer's templates. It can save a backup zip first, in a folder you choose. A backup can be pulled again to undo.
  - Pulling during a survey is allowed after a warning. Survey data and personal settings are never changed.
  - **Make a pack from this computer** downloads the current config files with a starter `spyhop-config.csv`, a plain CSV of Date, Changed by, Files and Notes.
  - See docs/CONFIG_PACKS.md.
- The Spyhop folder and the survey data folder are now both in **Survey → File → Folders**, no longer linked from Settings → Config files. Config files gained a link to the report templates folder.

## 0.10.1 — 2026-11-06

- **Summary as PDF** (Reports → Summary → Save as PDF…, and in Export Data…): the map is made for paper.
  - It's zoomed to the extent of the survey.
  - It uses the Esri Ocean basemap when there's internet, and the offline coastline otherwise (a note under the map says which).
  - The points have no text labels, and a legend of the point symbols (by species and event type, with counts) sits under the map.
  - The HTML summary is unchanged: interactive, with labels and popups.

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
