# Changelog

Spyhop's version is set in `spyhop/__init__.py` and shown in the status bar, the window title, Survey → About, the Terminal window, the diagnostic logs and exports.

The numbers are MAJOR.MINOR.PATCH. MINOR goes up for new features and PATCH for fixes only. Version 1.0.0 will be the first release used on real surveys. After that, MAJOR goes up only when the data files change in a way older versions can't read.

Earlier builds had no version numbers; the entries for 0.1–0.4 were reconstructed afterwards.

## 0.55.0 — 2026-11-13

- **Satellite trackers as inputs:** two new kinds in Settings → Inputs, **SPOT feed** (Globalstar SPOT Gen4, SPOT Trace…: the XML Feed ID, an optional feed password, how often to check, at least every 150 s) and **inReach MapShare** (Garmin: the MapShare name, an optional password, how often to check). They're always "other" inputs and need an internet connection. Each device in a feed is its own "other" source, named after the device: its map layer, trail and popup, and its track in `<survey>_<device>_gps.gpx` while a survey is active.
- Positions keep the device's own fix time; ones already recorded are skipped, and a check after a gap catches up on what was missed.
- Each feed's status line shows its last check, its newest fix and devices, or what's wrong (no internet connection, no such feed, password protected). Checks run in the background with a time limit, so no internet never slows Spyhop down.
- A tracker's marker turns grey when its last fix is older than a set time (30 min by default, in Mapping 'Other' inputs); the popup shows the fix's age, and SPOT's battery state.
- Templates carry tracker feeds but never their passwords, which stay on each computer (diagnostics leave them out too).
- The map's "other" layers now come from `/api/externals`, so view-only windows see them too.

## 0.54.0 — 2026-11-13

- **Map credits** fold into a small ⓘ at the bottom right, so they no longer cover the cursor position, distance and depth readout; click or tap it to read them. The Seascape credit no longer names OpenStreetMap (Spyhop leaves out Seascape's OpenStreetMap background).
- **Default observer altitude (ft)** is now in Settings → General → Altitude and reticles (it was **Platform altitude** in the survey details). It fills in new sightings' Alt as before, and travels with the template. Surveys started earlier keep the altitude already in their rows; set the default once in Settings.
- **"Other" GPS inputs' tracks** are saved as GPX files, `<survey>_<name>_gps.gpx`, so they can be shared or opened as overlays (they were CSV files). Each point has its time and, as GPX extensions, speed, course and heading. Tracks recorded as CSV by earlier versions aren't read any more.
- **The Error check counts** moved from the status bar to the right of the data tables' header (next to Sightings, Effort and Events).
- **Error check → What is checked** has a link to Settings → Rules.
- **The status bar** no longer shows "Sharing: N viewers"; Settings → Sharing and the Survey tab do.

## 0.53.0 — 2026-11-13

- **Settings → Sharing:** phones, tablets or a screen on the bridge on the vessel's network can open Spyhop in a browser and follow the survey live, view only. Only the laptop running Spyhop enters or changes data. Sharing is off until it's switched on. Settings → Sharing shows the address to type, with a QR code for each, the devices watching and **Disconnect all viewers**; the status bar shows **Sharing: N viewers**.
- **Optional PIN** for viewers; a wrong PIN is refused, and each wrong try makes the next one wait longer.
- **Viewers** see every tab but can't change anything: no editing, no row buttons, no survey actions, and only the shortcuts that move around. Settings that only change how Spyhop looks (text size, map display, columns, formats) change that browser only. Viewers don't get the laptop's folders, GPS / NMEA inputs or the details remembered from earlier surveys, and never make the laptop use the internet (map tiles come from those already on the laptop; no online overlays).
- **Lost connection banner:** when Spyhop (or, for a viewer, the laptop) can't be reached, a red banner says so, and the window reconnects and reloads by itself.
- Fixed: quitting Spyhop with a window open took up to 30 seconds; it now takes a second or two.

## 0.52.0 — 2026-11-13

- **Settings → Rules:** your team's own checks of one row of Sightings, Effort or Events, written as a sentence: *if* these conditions are true, *then* these must be true too. For example: if Event is CTD cast, then ID isn't blank; if Weather is Fog, then Glare is not Severe; if Behaviors includes Mom/calf, then Calves > 0. A value in [brackets] is another column of the same row (Num ≥ [Calves]). Each rule has a level (error, warning or note), a message, an On switch and, for Sightings, whether resights are checked. **Test on this survey** lists the rows that break a rule before you save it.
- The rules are part of the template's data part (`rules.csv`), so every computer using a template checks the same way, and they can't change during a survey. The Error check lists each row that breaks one (check **Rules**).
- **The Calves ≤ Num check is now a rule** (the one Spyhop starts with), so it can be changed or switched off. Its message has moved from the Plausible numbers check to Rules.
- **Error check → Check automatically:** runs the check quietly every 1–30 minutes while a survey is active (off by default; a shared setting). A message pops up when it finds more errors or warnings than before.
- **Status bar:** a **Check** field shows the counts from the last Error check; click it to open the Error check.
- **Open** on a list's file in Settings → Dropdowns now works for every list (it only worked for species, events, observers and behaviors).

## 0.51.0 — 2026-11-12

- **Columns… can hide columns:** select columns and press **Hide** to save screen space. Hidden columns stay in the data, the files and the exports, and are shown greyed in Columns…. While any are hidden, **Show hidden columns** appears next to Columns… and brings them all back. This applies to this computer only.
- **Resights layer:** the map's layers menu has **Resights**, which switches resights on and off. That covers their markers, the lines to them from the vessel, and the lines through them. The first sightings stay on the map.
- **Shortcuts: a Focus column.** It sets the column selected in the new row of a shortcut that adds a row (or a resight), ready to type in; for example, Num for a species shortcut. Leave it blank for the first empty column, as before.
- **Error check → Highlight in the tables:** colors each cell with a problem in its table, in the color of its level (error, warning or note), following the Show filter. A problem with a whole row colors the row number. Hover over a cell to see the problems.
- **Instruments:** the latitude and longitude tiles are wider, so the position fits in any lat/lon format.
- **Shortcuts on a Mac:** pressing Control now explains that Mac shortcuts use ⌘ (Command), not Control. The help says that Mod is ⌘ on a Mac and Ctrl on Windows and Linux.
- Using a template sets this computer's default distance unit (and its other shared settings) for new sightings, before or during a survey. A test now checks this.

## 0.50.0 — 2026-11-12

- **Settings → Guide:** the contents stay in view while you scroll. In a wide pane they sit beside the guide. In a narrow pane they become a bar across the top that names the section you're in; click it to open the list.
- **The Quick start's parts are lettered** a to i (*a. Find your way around*, *b. Try it with the simulator*, …).
- The user guide no longer has the comparison with the OpenCPN plugin, or the section on starting Spyhop from a terminal (not supported). Quitting, updates and diagnostics now have a section of their own.
- Fixed: in 0.49 the contents never stayed beside the guide in a wide pane.

## 0.49.0 — 2026-11-12

- **One user guide:** the tutorial and the user guide are now one document, `docs/USER_GUIDE.md`, which starts with a **Quick start** (the old tutorial). It's shown in **Settings → Guide**. `docs/TUTORIAL.md` is gone.
- The guide was reviewed against the current Spyhop. It now has a **Templates** section covering what's in a template (the data part and preferences), the drop-down lists, shortcuts, sharing and what's locked during a survey. It says "template" throughout, not "config files".
- **Settings → Guide:** the contents list has two levels. It lists each section, and opens the subsections of the one you're reading. The guide shows tables, code blocks, italics and links: links within the guide jump to their section, and links to other documents open on GitHub.
- README: installation grouped by operating system (Python, then Spyhop), with more help on installing Python.

## 0.48.0 — 2026-11-12

- **Clock check:** Spyhop compares the computer's clock with the GPS time. A difference over 2 s shows in the status bar (click it), and **Start New Survey** asks you to sync first. **Sync** sets the computer's clock to the GPS time (it asks for administrator rights) and works only between surveys. Also in Settings → General → Data collection. Each survey's details record `clock_offset_at_start`.
- **Stationary surveys:** a **station latitude / longitude** in the survey details (shown for Stationary only). When given, it is the platform position for the whole survey, and Start New Survey needs no GPS fix or clock check.
- Start New Survey now asks for the details first, then checks the GPS and clock.
- Clicking a stretch flagged with a GPS error shows a popup titled **Effort: ERROR** (with its segment and notes).
- The Summary no longer shows resight counts.
- **Save as a new template:** the new template's record of changes starts fresh (it used to copy the old template's record).

## 0.47.0 — 2026-11-12

- **ERROR stretches on the map:** no more red points. A stretch marked ERROR is hidden (the trackline is broken there) unless **Settings → General → Map display → Trackline → Show segments flagged with GPS errors** is ticked; then the whole stretch is drawn in the ERROR color. The HTML summary's map follows the same choice.
- **Start and End labels** on the map where the survey started and ended (same section; both on by default).
- **Error check:** the speed limit for shipboard surveys (and when no platform type is set) is 50 kn (was 30).
- **Track points every second** by default (was 10 s). Settings already saved keep their own interval.
- **Data collection** in Settings → General is greyed out during a survey, with the same yellow note as the Dropdowns.
- **Drone** icon for “other” inputs (turns with its heading).
- **Columns…** is now chips: click to select one or more (Shift+click for a range), drag them together to a new place, or move them with ← / →.
- Fixed: an “other” input added or changed in another window (or over the API) appeared on the map only after a reload.

## 0.46.0 — 2026-11-12

- **One Spyhop per computer:** a lock in Spyhop's folder (released by the operating system when Spyhop ends, even after a crash). A second start, from any program folder or on any port, opens a window onto the running one.
- **Fixed: ERROR rows didn't break the trackline** for a GPS gap or a one-way jump (no track point fell inside the ERROR stretch, since Fix puts the ERROR row just after the last good point and the restoring row at the next one). The map, the Summary distances and the HTML summary now break at the ERROR row's time.
- **ERROR on the map:** each ERROR Effort row is a red point (with a popup); track points inside an ERROR stretch are small red points, never joined.
- **Track point popup** shows the effort segment (Seg), and the effort from the Effort table as it is now.
- **Error check:** the GPS gap and speed boxes are gone; the limits are fixed (120 s; 30 kn shipboard/stationary, 200 kn aerial/other) and stated above the check.
- **Columns…** is back on each table's toolbar: ↑ / ↓ per column, Save, or Reset to the standard order (dragging headers still works).

## 0.45.0 — 2026-11-11

- **Trackline breaks only at ERROR rows:** the trackline on the map, in the HTML summary and in the Summary's distances is broken only where the Effort table has an ERROR row; the trackline-break settings are gone. The Error check flags GPS jumps faster than 30 kn (shipboard, stationary) or 200 kn (aerial, other) and gaps over 120 s (or 3 track intervals), on or off effort, each with **Fix**; the limits can be changed in the Error check.
- **Tracking follows the survey:** the trackline is always recorded while a survey is active and never otherwise (no setting, no Resume tracking). Opening an active survey continues it; after a crash it carries on recording and asks whether to continue or close.
- **Mapping ‘Other’ inputs:** its own section in Settings → Inputs, below GPS / NMEA inputs, saved at once (outside Apply / Revert). New **Icon** choice (shapes, vessel or aircraft turning with heading, tower). A **red ✕** over an other source's icon when its GPS is lost; its popup shows **Last updated**.
- **Glare:** with Glare None, Gstart and Gend are NA; otherwise they must be bearings. Gref defaults to M.
- **Settings → General:** a **Data collection** section (track point interval, magnetic variation; locked during a survey); the Folders section and the pointers to Basemap and Inputs are gone.
- **Data folder:** always `data/` in Spyhop's folder (it can't be changed). The Survey tab's **Saved Surveys** has **Open Data Folder**; Settings → About lists every folder as a link.
- **Updates:** checked when Spyhop starts (on by default; quick, silent when offline); a newer version is always offered with Install / Not now, never installed by itself.

## 0.44.0 — 2026-11-11

- **"Other" instead of "external":** the role for a drone, buoy or second vessel is now **Other**, so it isn't confused with an external GPS device; its map layer is **<name> (other)**. Inputs saved as external become other.
- **Settings → Inputs** is two tables: the inputs (in use, name, role, kind, connection), then **On the map** (show on the map for secondaries and others; color, line, width, trail, show name and record track for others).
- **Recorded tracks** of other sources are now `<survey>_<name>_gps.csv` (0.43's `<survey>_ext_<name>.csv` files aren't read).
- **Not recording yet:** a warning under On the map when an other source is set to record but no survey is active.
- **Popup on an other source's point:** name, position, speed, heading, and bearing and distance from the platform.
- Fixed: switching the **Platform icon** layer off and on drew the icon pointing north instead of its heading.

## 0.43.0 — 2026-11-11

- **External tracks:** each external input's card has **On the map** settings: color, line (solid, dashed, dotted, dash-dot), width, **Trail** (whole survey, last 10 min – 3 h, or none), **Show the name**, and **Record its track**. While a survey is active a recorded external's fixes go to `<survey>_ext_<name>.csv` in the survey folder (DateTime, Lat, Lon, SOG, COG, Heading, GPSTime); its trail is drawn live and read back from the file when the survey is opened again. The files are in the separate-CSV export and survey packages. The settings travel in templates with the input.
- **The map's layers menu:** map tiles moved to **Settings → Basemap → Map tiles** (online and offline). The menu's first section is now **Layers**, with **Platform icon**, **Effort** (the on-effort track) and **Track** (the off-effort track; the same switches as Settings → General → Map display) and a layer for each external, **<name> (external)**, drawn below everything of the survey's own.

## 0.42.0 — 2026-11-11

- **Input roles:** each GPS / NMEA input has a role drop-down: **Primary** (one: the platform's position, course, speed and heading), **Secondary** (another of the platform's inputs: logged, fills in readings, can stand in for the primary) or **External** (a drone, drifting buoy or second vessel: logged and shown on the map as an orange point, never used for the platform's position, readings or fallback). External travels with the input in templates.
- **Fallback to a secondary** is still an option (off unless ticked), now with a **red GPS FALLBACK banner** across the top of the window while a secondary stands in, naming both inputs and how long the primary has been silent, plus a message when it starts and when the primary is back. The Inputs status shows the quiet primary in red.
- `<survey>_nmea.csv`: the **Role** column (primary / secondary / external) replaces 0.41's Primary yes/no; 0.41 files are converted when the data folder is opened. Plots never use an external's readings.

## 0.41.0 — 2026-11-11

- **Named GPS / NMEA inputs:** each input in Settings → Inputs has a name (e.g. *Tablet GPS*, *External GPS*). Serial inputs now travel in templates too, with UDP, TCP and gpsd, so a template can list every device a team uses. Which inputs are **in use** is each computer's choice, kept by name when a template is used (an input new to the computer comes in unticked).
- **Primary and secondary inputs:** of the inputs in use, the **primary** gives the vessel's position, course, speed and heading. The others are **secondaries**: their readings fill in Tools → Instruments where the primary has none (each reading names its input), and **Show on the map** draws a secondary as a point with its name. An optional **failover** takes the position from a secondary while the primary has been quiet for 5 s. (Before, the first input in the list was preferred and the next took over automatically.) A `--sim` input is the primary for its session.
- **Start New Survey warns when there's no GPS position** (no input in use, or none from the primary), with a link to Settings → Inputs and a pointer to the SIMULATOR input for trying Spyhop out; *Start anyway* still starts it.
- **`<survey>_nmea.csv`** replaces `<survey>_instruments.csv`: every numeric reading of every input in use, **latitude and longitude included**, with the input's name (Source) and whether it's the primary. Existing `_instruments.csv` files are renamed and converted when the data folder (or a survey package) is opened. The raw NMEA log labels each line with the input's name.

## 0.40.0 — 2026-11-11

- **Templates have two parts.** The **data** part (the drop-down lists, the data settings: magnetic variation, track point interval, trackline breaks, and the saved reports) is fixed during a survey, copied into the survey's folder, and is the only part a survey's template copy is checked against. The **preferences** (shortcuts, map display, the other settings including the bearing reference and distance unit, network inputs, map feeds) can change at any time. Settings → Templates shows what would change under these headings.
- **Using a template during a survey** now takes its preferences (and list colors) and leaves the data part until the survey ends, instead of refusing the whole template.
- **Reports wait until the survey ends:** during a survey Tools → Reports is locked (no running, saving, changing or deleting reports, no Run Reports), and Export Data leaves saved reports out.
- **List colors can be changed during a survey** (Settings → Dropdowns); everything else in the lists stays locked. A color edited by hand in a list file is kept too.
- **Every list has Other**, a placeholder for anything missing from it: species, events, behaviors, observers, effort, visibility, weather, and the reticles (**reticles-Other** keeps the reading but works out no distance). It can't be renamed or removed, and a list without it (yours, or a template's) gets it at the end. The Error check's new **Other placeholders** check lists every row that uses it, to fill in after the survey. Other in a watch position isn't counted as one observer in two places.

## 0.39.0 — 2026-11-11

- **Effort is a list** (Settings → Dropdowns → Effort, `effort.csv` in the template; locked during a survey like the other lists). Each value has a **name**, a **status** (on or off effort: used for the track, the Summary, reports and the Error check), a **definition** (shown in the Effort drop-down) and a **color** (the track's color while it's in force). The defaults are **ON** (observers are on watch), **TRANSECT** (systematic line-transect survey), **DIRECTED** (directed survey/activity), **PHOTO-ID** (photo-ID survey) and **FOLLOW** (focal follow), on effort, and **OFF** (observers off watch). **Start** and **End**, and **ERROR** (added by Error check → Fix), are always there, always off effort, and can't be renamed or removed. LINE and PHOTO from earlier versions are gone: rows that still have them are flagged by the Error check.
- **The trackline colors** come from the effort list; Settings → General → Map display → Trackline keeps show, width and line style for on and off effort.
- **Help behind ? buttons:** the explanations in Survey, Tools and Settings are behind a small **?** beside each heading. Hover to read one; click to keep it open (Esc, a click elsewhere or another click closes it).
- **The Guide has a contents list** beside it (above it in a narrow pane); click a section to jump to it, and the section you're reading is highlighted.
- **Routes:** the page is in two parts, **Saved Routes** at the top and **Create New Route** below, with **Save** at the bottom. Every mode, manual too, has a **Start point** (type it, **Pick on the map**, or **Use the vessel position now**); in a manual route it's the first waypoint, and switching modes keeps it. The "vessel's current position / fixed point" choice (a route that moved with the vessel) and the map's right-click **Start route here** are gone.
- The tab bars (Survey | Tools | Settings and Sightings | Effort | Events) no longer scroll up and down a pixel under the mouse wheel.

## 0.38.0 — 2026-11-10

- **Calibrated marks** (Settings → Dropdowns → Reticles) are evenly spaced: *Degrees per division* is the angle between marks, counted down from the horizontal, so mark *n* is *n* × that angle (magnification isn't used). The reticles list's marks column is gone. A position picked on the map now gives a mark reading too.
- **Gstart, Gend, Gref** are the new, shorter headers of the glare columns (the CSV columns are still GlareStart, GlareEnd, GlareRef).
- **Reports leave out resights:** a Sightings report, and its species counts, list each group of animals once, as its first sighting.
- **Calves takes NA**, for species codes where calves don't apply (dead birds, fishing gear, vessels…).
- **Insert row…:** the typed-time choice reads "Use this time and the nearest vessel position".
- **Undo / redo are Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z** by default (were Ctrl/Cmd+Shift+U / Y). While you're typing in a box they undo the typing instead. An existing shortcuts list keeps its keys: change them in Settings → Shortcuts.
- **The Unit drop-down says what each unit is** (nm nautical miles, …), and for each reticle its method and angle.

## 0.37.0 — 2026-11-10

- **Reticles are a list** (Settings → Dropdowns → Reticles), replacing General → Reticles. Each entry has a name and says how readings are taken: binocular reticles (magnification and degrees per division), calibrated marks (`mark=degrees; …`) or inclinometer degrees. Each is a Unit in Sightings, `reticles-<name>` (the default list has `reticles-binos`, `reticles-big-eyes` and `reticles-incl`), so several can be used in one survey and every sighting records which. The single `reticle` unit and the `reticle_*` settings are gone.
- **Visibility and Weather are lists** in Settings → Dropdowns.
- The reticles, visibility and weather lists are in the template (`reticles.csv`, `visibility.csv`, `weather.csv`).
- **Effort: Glare start, Glare end and Glare ref** (M, T, R or C; a clock reference offers 1–12), after Glare, in the merged CSV, and checked by the Error check (both ends, a reference, the range).
- **Nothing that affects the data can change during a survey:** besides the lists (now including reticles, visibility and weather), the track point interval, the trackline-break settings and the magnetic variation are locked from Start to End (greyed out in Settings, refused by the server); editing a locked list's file by hand is put back when the files are read again; and a template that would change any of them is refused until the survey ends (one that only changes shortcuts, display or reports can still be used). So the template copy kept with each survey is exact.
- **UNK** (Unknown) is no longer in the default observers list.
- **Tools → Resights** comes after Instruments, before Error check.
- The "Many changes at once?" box in Dropdowns and Shortcuts showed the old place of the list files; it now shows templates/current.

## 0.36.0 — 2026-11-10

- **One folder per survey:** each survey is now a folder in the data folder (`<survey>/`), holding its tables (`<survey>_sightings.csv` …), survey details, instrument readings, raw NMEA logs (`nmea_logs/`) and exports (`exports/`). Waypoints stay at the top. Surveys from older versions are moved into folders automatically the first time a data folder is opened (nothing is overwritten). Survey names that clash with Spyhop's own folders (exports, nmea_logs, templates) are refused. **Delete Survey Data** now removes the survey's whole folder.
- **The survey keeps its template:** Start New Survey saves a copy of the current template in the survey's folder (`<survey>_template.zip`), so the data always travel with the lists they were recorded with. It still offers to save the current template first if it has changed. The Survey tab shows the survey's template and says when it differs from the current one, with **Compare and use the survey's template…**.
- **Survey packages:** **Save Survey Package…** saves the open survey as `<survey>.spyhop-survey.zip` (its files with RowIDs, its template copy, optionally its raw NMEA logs, and a manifest with checksums). **Open Survey Package…** adds it to this data folder and opens it; a name already in use is never overwritten (choose another name), and damaged packages, packages from a newer Spyhop or files that aren't packages are refused.

## 0.35.0 — 2026-11-10

- **Smooth vessel movement:** the vessel icon, its heading vector and the range rings glide from one GPS fix to the next (and turn the short way round) instead of hopping once a second. Only the drawing is smoothed: recorded positions, new rows, popups, measurements and Follow vessel use the real latest fix. The icon is drawn up to about one fix interval behind (about 5 m at 10 kn). It jumps instead after a gap of more than 5 s, a jump of more than 300 m, a lost GPS or while the window is hidden. On by default; switch it off in Settings → General → Map display (kept on this computer only, `smooth_vessel` in `spyhop-local.json`).
- The vessel icon is now rotated in place instead of being rebuilt at every change of heading.

## 0.34.0 — 2026-11-10

- **Markers are colored by species (and event type) again.** Since 0.25 a second `markerColor` in map.js (for overlay colors) had replaced the one for sightings and events, so every marker was the same color.
- **Error check** is the new name of Quality Control (the tab and its text). It has a new check: a **warning** when animals would have swum faster than **30 kn** from one sighting of them to the next resight (from SigLat/SigLon, else the platform's position).
- **Error check → Show** scrolls the table itself, so the row no longer ends up hidden under the table's header (or a frozen column), brings back an optional column's row in a visible column, and flashes the row so it's easy to find.
- **Tools → Resights** says "resights", not "looks", and shows the **FieldID** (blank if none) in the table, the details and the CSV. Its Resights column now counts the resights (not counting the first sighting).
- **Online overlays** (AIS, weather radar, map feeds) moved from Settings → Inputs to **Tools → Overlays**, below the offline overlays.
- **Settings → Guide** (left of About) holds the tutorial; About keeps the version, changelog, diagnostics and updates.
- **Add a row to the table you're in** (Ctrl/Cmd+Enter) adds to the data table in view (Sightings, Effort or Events) even when Survey, Tools or Settings has the focus, and never to Waypoints (Ctrl/Cmd+Shift+K still adds a waypoint).
- Clicking the **conditions check** countdown opens the Effort table (the interval is in Settings → General).
- Column headers **SigNo** (was SightNo) and **ResNo** (was Resight of). The CSV column names are unchanged.
- **Removed:** the Columns… buttons (drag the headers instead), the status bar's **Reset panes** (now Settings → General → Tables → Reset the pane sizes, or double-click a bar) and its **Live** connection status.
- **Default lists:** *Vessel sighted*, *Marine debris*, *Fishing gear - reported* and *Fishing gear - recovered* are now species (Sightings) rather than event types; *Photo-ID session start/end*, *Fishing gear sighted* and *Acoustic recorder deployed/recovered* are gone; *Mooring deployed* and *Mooring recovered* are new event types. The starting Gear report now reads Sightings. Lists already on a computer don't change: edit them in Settings → Dropdowns.

## 0.33.0 — 2026-11-09

- **Three panes** replace the split and overlay views: the **map** and **Survey/Tools/Settings** share the top, and the **data tables** (Sightings, Effort, Events) span the full width below, so a data table and a Tools or Settings page show at the same time. Drag the bars between them (or use the arrow keys on a focused bar) to resize; ▁ minimizes a pane to a strip (the data pane to its tab bar; Ctrl/Cmd+Shift+M), □ fills the window with it and ❐ restores; **Reset panes** in the status bar goes back to the start. The map keeps its own zoom controls.
- The pane sizes and states are kept on this computer (`pane_layout` in `spyhop-local.json`), like column widths. The old `view` and `split_ratio` settings are gone.
- Each pane remembers its own tab. Shortcuts that act on "the current tab" (e.g. add a row) use the pane you last clicked in.

## 0.32.0 — 2026-11-09

- **Map distance unit** (Settings → General): a separate setting for the measuring tool, popups, routes and the Summary (nm, km, m, mi, yd; no reticles). The Sightings default unit is unchanged.
- **Calibrated marks:** choosing it in Settings → General now shows the calibration table at once (Settings didn't redraw while it had the focus).
- **Clock bearings:** Ref **C**: the Bearing cell offers 1–12 o'clock, each hour 30° from the bow, converted with the vessel heading. Also a default bearing reference; QC checks 1–12 and a heading; a map-picked position goes back to the nearest hour.
- **Add resight** keeps the selected column instead of jumping to Behaviors. Resights' SightNo is indented in time order too.
- **Lines:** show/hide, width and line style for the lines from the vessel to each sighting, the FieldID lines and the resight lines (Settings → General → Map display → Lines and vectors), in the app and the HTML/PDF summary.
- **Fade after** is in minutes (default 30); `fade_hours` is replaced by `fade_min`.
- **Insert row… at a time you type:** in time order, at the vessel's position then from the trackline.
- **Survey tab** stands out from the data tabs.
- **Move the map to a selected row** can be switched off (Settings → General → Map display).
- **First surfacing** behavior (SU) in the default behaviors list (an existing behaviors.csv doesn't get it: add it in Settings → Dropdowns).
- **Tools → Resights:** per sighting with resights, the looks, time span, distance, average and net swim speed (kn and km/h) and dive times (a dive behavior to the next First surfacing), with details per look and Save as CSV.

## 0.31.0 — 2026-11-09

- **Columns:** drag a header to move a column, drag its edge to resize it (double-click for the default width), or use the table's new **Columns…** button (↑/↓, Reset). Kept on this computer only (`spyhop-local.json`); Settings → General → Tables resets every table.
- **Sightings row colors** (Settings → General → Tables): None, Alternating, Highlight resights (default), Group resights.
- **Kinds of on effort:** **LINE** (line transect), **FOLLOW** (focal follow), **PHOTO** (photo-ID approach) besides **ON**. All count as on effort (track, Summary, Quality Control, Reports); the Summary adds the time in each; Toggle effort goes back on as the last kind used.
- **Effort segments:** a read-only **Seg** column in Effort, a new number each time the effort status changes from the row before; in the merged CSV too. Show or hide it in Settings → General → Tables.
- **Survey notes:** a multi-line notes box in Survey under the details, saved in the metadata, shown in the Summary and its HTML/PDF. Not carried over to the next survey.
- **Insert row…** on every data tab: before or after the selected row, time and position averaged from the rows either side or copied from the row before or after, with a note saying so. Works in ended surveys (not before Start or after End).

## 0.30.0 — 2026-11-09

- **Resights:** for another look at animals already recorded (closing in for photos, a focal follow). Select a sighting and press **Add resight** (Ctrl/Cmd+Shift+L; greyed out with no sighting selected): the new row's **Resight of** column, right after Calves, holds the first sighting's SightNo, and the species, Num, Calves, NumConf, IDrel and FieldID are copied. A resight of a resight links to the first sighting. Resight of can also be typed (it must name an existing sighting).
  - **Summary:** resights aren't counted as sightings again; each sighting counts once with the largest number and calves seen on any look. The species and right whale tables show how many resights each has.
  - **Settings → General → Resights:** the Sightings table in time order or with resights **nested** under their sighting; resight markers' shape (or hidden), fill (outline, filled, faded), size and labels; a dotted line from each sighting through its resights. The HTML and PDF summaries follow these settings.
  - **Quality Control:** a Resight of that names no sighting, a resight timed before its sighting, or of another species, is flagged. Resights aren't listed as off-effort sightings, nor their observer as off watch.
  - **Merged CSV:** a new **ResightOf** column.
  - New installs get the shortcut. An existing `shortcuts.csv` doesn't: add it in Settings → Shortcuts (action "Add a resight of the selected sighting").

## 0.29.0 — 2026-11-09

- **Platform types:** **Shipboard**, **Aerial**, **Stationary** and **Other** (were Vessel, Plane, Land and Other). The map marks the platform with a ship, an aircraft, a tower or a dot. A **stationary** platform records only its Start and End positions, with no trackline in between, and the status bar says so.
- **Platform altitude (ft)** in the survey details: the observers' eye height on a ship or station, or the survey altitude for an aircraft.
- **Alt (ft) column in Sightings:** filled in from the Platform altitude and editable. **Settings → General → Altitude column** shows it automatically for aerial surveys (hidden for shipboard and stationary ones), or always shows or hides it.
- **Reticle distances:** a new distance unit, **reticle**. Dist is then a reading, turned into a distance with the sighting's altitude, allowing for the curvature of the earth (Lerczak & Hobbs 1998); SigLat/SigLon follow. **Settings → General → Altitude and reticles** chooses how readings are taken:
  - **binocular reticles** counted down from the horizon (a magnification that suggests the angle of one division, which you can correct)
  - **calibrated marks** (a table of mark numbers and angles)
  - **inclinometer** degrees below the horizontal
  
  These settings travel in templates. Quality Control flags reticle sightings that have no altitude.
- **"Template" throughout:** the app no longer talks about the computer's "setup". The one in use is the **current template**, and the zips are **saved templates**.
- **A `templates` folder left in the data folder** (e.g. kept by a `.DS_Store`) is now emptied into `templates/saved` and `templates/backups` and removed. Files Spyhop doesn't know are left, with a note.
- **Uninstall and reinstall** now work on a git checkout when nothing would be lost, i.e. no uncommitted changes and nothing unpushed; otherwise the dialog says why. Reinstalling a git checkout resets it to its branch on GitHub and removes the Python set-up. Reinstall no longer keeps a copy of the old program files.
- **AIS:** the vessel popup no longer shows the source (often a very long string).

## 0.28.0 — 2026-11-09

- **New folder layout.** Everything a team shares now lives in a `templates` folder in Spyhop's folder:
  - `templates/current/` is **the setup in use**: the species, event, observer and behavior lists, `shortcuts.csv` and `spyhop-config.json`. That file holds the shared settings, network GPS inputs, map feeds, online overlays, map display, saved reports and the record of changes. It is a template, unzipped, and everything set in Settings and Tools → Reports is saved there.
  - `templates/saved/` holds your templates. They used to be in the survey data folder.
  - `templates/backups/` holds the backups made before using a template. The option to choose another backup folder is gone.
  - **`spyhop-local.json`** holds this computer's own settings: the data folder, serial ports, window layout, last survey details and the open survey.
  - The old `settings/` and `reports/` folders and the list, shortcut and `display.csv` files at the top of Spyhop's folder are gone. Spyhop moves them into the new layout the first time it starts.
- **Starting a survey:** if the setup in use isn't saved as a template, or has changed since, Start New Survey offers to **save it as a template**, update the template it came from, or start without saving.
- **Survey details** now quietly record the template the setup came from, and whether the setup still matched it when the survey started. They already recorded the Spyhop version.
- **The map zooms to the open survey** when Spyhop starts with one open, active or ended.
- **Coastline (offline)** is now only a base map. It's no longer also an overlay, so the coastline is drawn only when it is the chosen map.
- **Reports:** saved reports are part of the setup in use, so the reports folder and its Refresh link are gone.
- **Clean-up before 1.0:** Spyhop no longer converts files from older versions. This drops:
  - VesLat/VesLon columns, `marks.csv`
  - Start rows added to old surveys
  - list entries and shortcut changes added once
  - extra map layers in `tile_sources.csv`
  - old report templates
  - config packs and templates older than 0.24
  - the `WhaleSurveyRecorder` folder name
  - old route styles and 0.23 sawtooth designs
  - old tab names
  - the `--auto-quit` option
  
  Templates now need Spyhop 0.28.0 or newer. Templates saved by 0.24–0.27 still work.

## 0.27.0 — 2026-11-09

- **Behaviors:** the checklist is now a single list you can work from the keyboard: ↑/↓ move, Space ticks, a letter jumps to the first behavior starting with it (press it again for the next), Enter saves. The filter box is gone. The highlighted behavior's **definition** is shown at the bottom. Definitions come from a new **Definition** column in `behaviors.csv` (Settings → Dropdowns → Behaviors): the built-in behaviors have one, and the column is added to existing lists.
- **Drop-down lists** opened from the keyboard no longer show two highlighted entries when the mouse pointer happens to be over the list; the mouse moves the one highlight when it moves.
- **New route** scrolls to the Design section (and says so), even when the editor was already empty.
- **Settings → Shortcuts:** the pre-fill boxes are wide enough for their text.
- **FILE input:** **Choose…** opens the computer's own file chooser. A path pasted with quotes (Windows' *Copy as path*) or starting with `~` works, and a missing file is reported when you apply. Spyhop's own raw NMEA logs replay at the pace they were recorded, using their time stamps; plain NMEA files are paced by their RMC/GGA/GLL/ZDA times. The status shows the line being replayed, and says when another input higher in the list is supplying the position (inputs higher up are preferred).
- **Uninstall and reinstall** (Settings → About): **Uninstall Spyhop…** removes the program, its Python set-up and its shortcuts; ticking a box also deletes the settings, lists, maps, overlays, routes, feeds and reports. Survey data is deleted only if that is ticked too and DELETE is typed, and a data folder you chose yourself is never deleted. **Reinstall a clean copy…** downloads the latest version from GitHub and replaces the program with it (keeping a zip of the old one), sets up its Python packages again and restarts. Your surveys are always kept, and your settings unless you tick reset. Neither can be used during a survey or on a git checkout.
- **Diagnostics:** the zip now includes `folders.txt`, a listing of Spyhop's folder and the data folder (survey files are only counted). It also includes the template history and list files, though not the observers list. Web addresses in the settings have their `?…` part removed, in case it holds a key.
- **Delete Survey Data…** is the new name of *Clear Survey Data…*.
- **American spelling** throughout (color, behavior, gray, center, meter…). The AIS statuses now read *Restricted maneuverability* and *Constrained by draft*.

## 0.26.0 — 2026-11-08

- **Lat and Lon:** the Sightings and Effort columns VesLat and VesLon are now **Lat** and **Lon**, so they suit any platform (vessel, plane, land station). Survey files from earlier versions are converted when they're opened (a backup of each original is kept), past surveys shown as overlays are read either way, and saved reports that use the old names keep working. The merged export already used Lat and Lon.
- **Seascape depths** no longer draws its OpenStreetMap background, so it looks the same online as offline.
- **Survey tab:** Folders now comes between the current survey and **Surveys in this folder**.
- **Refresh** is the name of every button that reads a folder again: Settings → Basemap and Tools → Routes (were *Look for new files*), and new Refresh buttons for the survey list, Tools → Overlays and Tools → Reports.
- **Tools → Instruments** links to the GPS / NMEA inputs in Settings → Inputs.
- **AIS:** the map's credits line names each AIS network once, without station IDs (the full source is still in each vessel's popup).
- **Tutorial:** a fuller *Try it with the simulator* section (it pointed to the wrong tab): switching it on, steering it, practicing a survey, and switching it off.

## 0.25.0 — 2026-11-07

- **Overlay colors:** in Tools → Overlays, click an overlay's color to draw it in another color on the map (↺ goes back to its own colors). The colors are kept with the map display, so they are remembered and travel in templates.
- **Sawtooth routes:** the return crossover now runs straight across the pattern, at right angles to the survey direction (090° or 270° for a survey heading 000°), onto the reciprocal sawtooth.
- **Quality Control → Fix** puts the ERROR row in the Effort table one second after the last good track point before the break, so in the merged export it comes after that track point rather than tying with it.

## 0.24.0 — 2026-11-07

- **"Config packs" are now called templates everywhere**: in Settings → Templates (**Use this template…**, **Update…**, **Save as a new template…**, **Get a template from the web**), in the docs (docs/CONFIG_PACKS.md is now **docs/TEMPLATES.md**) and in the code.
  - Templates are saved as **`<name>.spyhop-template.zip`** in a **`templates`** folder in the survey data folder; the old `config_packs` folder is renamed the first time 0.24 runs. Older `.spyhop.zip` files are still read.
  - Your settings for templates (web address, backup folder, the template in use…) carry over.
- **One `spyhop-config.json` in each template** holds everything that isn't a table: the format, the minimum Spyhop version and which optional parts it has, the record of changes, the shared settings, the network inputs, the map feeds, which online overlays are on, the map display and the saved reports. The lists and shortcuts stay as CSV files, and waypoints, routes and overlays as their own files. This replaces `spyhop-pack.json`, `spyhop-settings.json`, `spyhop-config.csv`, `display.csv` and the `reports` folder in a template (all still read from older templates).
  - **Map feeds travel as their address, name, color and refresh time only.** The saved copy of each feed's data (sometimes several MB) is no longer put in templates; each computer downloads the feed itself. Templates are now usually well under 100 KB.
  - Templates now need Spyhop 0.24.0 or newer (the lowest minimum version).
  - This computer's record of changes moved from `spyhop-config.csv` in Spyhop's folder to `settings/template_history.json`.
- **Sawtooth routes, reworked:**
  - **Survey direction** is now the way the whole pattern advances (it was the bearing of leg 1), and **Angle between legs** is the angle where one leg meets the next (it was the turn at each waypoint). The first leg goes to starboard or port of the survey direction. Sawtooth routes saved in 0.23 open as the same pattern.
  - **Return:** at the far end a short **crossover** leg, at a right angle to the last leg, leads onto the reciprocal sawtooth, which comes back through the outbound one, crossing each outbound leg at its middle.

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
  - **AIS vessels** from Open Waters AIS (free, no account): the vessels in view, every 30 s, colored by type and pointing the way they're heading; click one for its details and its distance and bearing from you. Option to hide vessels that aren't moving.
  - **Weather radar**: US (NOAA NEXRAD, via the Iowa Environmental Mesonet, every 5 minutes) and worldwide (RainViewer, every 10 minutes), with an opacity setting.
  - **Map feeds**: add any ArcGIS FeatureServer / MapServer layer or service, or a GeoJSON file, with its own color and refresh. Ready-made: NOAA's **right whale Seasonal Management Areas** (shown solid while in effect, dashed otherwise) and **right whale Slow Zones / DMAs** (NEFSC). The last copy of each feed is kept, so it still shows offline.

## 0.20.0 — 2026-11-07

- **Tools → Routes** (was Route) keeps any number of routes, in a new `routes` folder in Spyhop's folder (one GPX file each, so a route can also go straight to a chart plotter).
  - **Saved routes** at the top of the tab lists them, with mode, waypoints, length and date. **Show** puts any of them on the map on every tab (in their own colors; *Saved routes* in the layers menu); **Open** loads one to edit or activate; **Zoom to**; **Delete**.
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

- **New default map: Seascape depths (feet)**, Open Waters' Seascape bathymetry with depth shading, contours and soundings in feet. It's drawn with MapLibre GL (bundled, BSD license). Its style, tiles and fonts go through Spyhop's tile cache, so they work offline once viewed or downloaded. Not for navigation.
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
  - Add, remove, reorder and sort entries, and pick colors.
  - Names and codes must be unique.
  - **While a survey is under way the lists are grayed out and can't be changed.**
- The CSV files can still be edited in a spreadsheet for big changes.
- Group config: a GitHub link to a `.zip` file in a repository now downloads that file alone, not a zip of the whole repository.
- **Group config moved to Survey → File.** **Make a pack from this computer…** now asks for your name, what changed and the file name. It fills in which files changed since the last pull or pack, and adds the row to `spyhop-config.csv` itself.
- The **Config files** section is gone from Settings. Survey → Shortcuts and each Dropdowns list have an **Open** button for their file and **Reload from the file**.
- The online map layers are now built into Spyhop, and `tile_sources.csv` is no longer created or shared in group config packs. Extra layers in an existing `tile_sources.csv` are still added.

## 0.11.0 — 2026-11-06

- **Group config** (Survey → Settings): a team keeps its config files on the web, and each computer pulls them.
  - What can be shared: the species, event types, observers and behaviors lists, shortcuts, map display, map sources and report templates.
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
- **Line styles:** each of the on- and off-effort tracks can be solid, dashed, dotted or dash-dot, set in Settings → Map display → Trackline, next to its color, width and on/off. The HTML summary uses the same styles.
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
  - The default look is gray and dotted.
  - **Import GPX…** loads a route. One exported by Spyhop comes back exactly as it was designed; any other GPX loads as a manual route.
- The Vis column no longer wraps.
- On start, the launchers install any Python packages a new version needs (this version adds `tzfpy`, the offline time-zone map).

## 0.7.0 — 2026-11-06

- **Planning is now Survey → Route**, with:
  - **Activate route:** locks the waypoints (no dragging or editing) and keeps the route on the map from every tab. Deactivate to edit it again.
  - a **Route** entry in the map's layers menu to show or hide it
  - **Appearance:** color, line style (solid, dashed, dotted, dash-dot), line width and waypoint size, also used in saved overlays
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
- Overlays honor simple style properties (`stroke`, `stroke-width`, `marker-color`, `dash`), so saved plans keep their orange dashed look.

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
- **Merged CSV:** times are read more leniently, and sightings before any effort row are labeled "no effort row yet". The file also gains a SpyhopVersion column.
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
