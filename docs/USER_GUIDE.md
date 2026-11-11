# Spyhop user guide

The full reference for Spyhop. For a quick tour, see the [tutorial](TUTORIAL.md). For installing and starting Spyhop, see the [README](../README.md).

## Running Spyhop

To practice without a GPS, add the simulator. It steams on a fixed heading and speed (default 000°T at 10 kn) from Cape Cod Bay:

```
python -m spyhop --sim
python -m spyhop --sim --sim-heading 135
```

It also sends made-up depth, wind, weather and engine readings, so Tools → Instruments has something to show. The simulator is listed with your other inputs in **Settings → Inputs** (a `--sim` one is marked *this session only*). Change its heading or speed there and press **Apply**; the boat takes the new heading at once, from where it is. Untick it and press **Apply** to stop it. Whenever you've edited the inputs but not applied them, the button reads **Apply — unsaved changes**.

Other options: `--install-shortcut` (make the Spyhop icon again), `--nmea serial:COM4:4800`, `--nmea udp:10110`, `--nmea tcp:192.168.1.5:10110`, `--nmea gpsd:127.0.0.1`, `--nmea file:mylog.nmea`, `--data-dir PATH`, `--window` (a native window, needs `pip install pywebview`), `--host 0.0.0.0` (lets a tablet on the boat network connect to the same recorder), `--no-browser`.

**Quitting:** close the Terminal/console window, or press Ctrl+C in it. Your data is saved as you go, so quitting never loses anything. Closing only Spyhop's own window leaves it running, still recording the track; open the icon again to get the window back. If you quit with a survey still active, Spyhop asks whether to continue it the next time it starts.

**Diagnostic logs:** Spyhop keeps a log in `logs/` in Spyhop's own folder (Settings → About → Open folder). `spyhop.log` is rotated at 5 MB, keeping 5 old ones. It records:
- the version and system at start-up
- each action and whether it worked or was refused (never the data itself)
- errors with their details, from Spyhop and from its window
- slow moments
- a performance snapshot every 5 minutes (CPU, memory, server delays, NMEA rate, window memory)

`crash.log` catches hard crashes. **Save diagnostics…** zips the logs, settings, a listing of Spyhop's folders (`folders.txt`) and system details into one file to send with a bug report. The zip has no survey data and no team or observer names, and web addresses lose their `?…` part.

**If Spyhop feels slow:** the Terminal window prints a line starting `spyhop.slow` whenever something takes too long: the server busy for more than 0.25 s, a request over 1.5 s (with map tiles labeled as downloads from the internet), or the Spyhop window busy for more than 0.2 s (saying whether you were moving the map and which tab was open). Nothing is printed while everything is quick. Copy those lines when reporting slowness.

## Planning routes (Tools → Routes)

**Saved routes** (top of the tab) lists the routes in the `routes` folder in Spyhop's folder, one GPX file each, with its mode, waypoints, length and when it was saved:

- **Show** puts a route on the map on every tab, in its own color (remembered; **Routes** in the map's layers menu switches all routes, saved and current, on or off). Click a waypoint for its position and distance from the vessel, and **Open to edit**. **Show all** / **Hide all**.
- **Open** loads a route into the editor below (*Current route*), to change it or activate it. If the route you're editing has unsaved changes, Spyhop asks first. The route being edited is marked *editing* (*editing · changed* once you change it; **Revert** goes back to the saved copy). **Close** puts it away: the editor is emptied and the route is no longer drawn (it stays in the folder, and on the map if its **Show** box is ticked).
- **Zoom to** and **Delete** (after asking).
- **New route** starts an empty one; **Import GPX…** loads a GPX file into the editor; **Open the routes folder**; **Refresh** picks up GPX files copied into the folder (from a plotter, another computer or a colleague). A GPX file that wasn't made by Spyhop opens as a manual route.

The **current route** is drawn on the map with numbered waypoints and kept between sessions. While it's a **draft** it shows only while the Routes tab is open; once **activated** it stays on the map from every tab.

- **Save:** **Save route** keeps it in the routes folder under its name (a new name for a route opened from the folder renames its file); **Save as new…** saves a copy under another name. Saving over another route's name asks first.
- **Survey speed** (kn) sets the times.
- **Start point**, in the *Manual*, *Systematic* or *Sawtooth trackline* section: type its latitude and longitude, press **Pick on the map** and click, or press **Use the vessel position now**. In a manual route the start point is the first waypoint. Switching between modes keeps the start point.
- **Manual:** set the start point, then press **Add points on the map** and click where each further waypoint should go (with no start point, the first click is the start). Drag a waypoint to move it. Use **Undo last point** or the ✕ in the waypoint list to take points off.
- **Systematic:** parallel legs ("lawnmower"). Choose:
  - the **start point** (pick it on the map, type it, or use the vessel position); drag waypoint 1 to move the whole pattern
  - the **survey direction**: the bearing of leg 1
  - the **number of legs**, the **leg length** and the **leg spacing** (nm)
  - which side the next leg goes to (starboard or port of leg 1)

  Legs alternate direction, joined by crossings of the leg spacing.
- **Systematic — sawtooth (zig-zag):** the platform zig-zags with no crossings. Choose:
  - the **start point**, as for parallel legs
  - the **survey direction**: the way the whole pattern advances (°T)
  - the **leg length** (nm)
  - the **angle between legs**: the angle where one leg meets the next (90° gives legs at right angles; a smaller angle gives a sharper, wider zig-zag), and whether the **first leg** goes to starboard or port of the survey direction
  - the **number of legs**
  - **One way**, or **Return**: at the far end a **crossover** leg runs straight across the pattern (at right angles to the survey direction: 090° or 270° for a survey direction of 000°) onto a reciprocal sawtooth that comes back through the outbound one, crossing each outbound leg at its middle. The return ends level with the start, on the far side of the pattern. Times and distances count the crossover separately (like a crossing).

  Spyhop shows the two courses the legs alternate between, and how long and wide the pattern is. Sawtooth routes saved in 0.23 open as the same pattern.
- **Route** box at the top:
  - **Activate route** locks the waypoints where they are (no dragging or editing, and a vessel start is frozen at the position it had) and keeps the route on the map from every tab. **Deactivate** to edit it again.
  - **Close route** empties the editor and takes the route off the map (asking first if it has unsaved changes or is active). **Clear waypoints** removes its waypoints but keeps it open (saved routes and GPX files are kept).
  - **Zoom to route.**
  - **Routes** in the map's layers menu hides or shows all routes at once; which ones are drawn is chosen here.
- **Tables:**
  - **Legs:** from/to, course, distance, time, running total distance and time, and the ETA if you start now. Crossings are grayed.
  - **Totals:** total distance (and distance on the legs), total time and finish time.
  - **Waypoints:** each position.

  Times assume the survey speed and no time for turns.
- **Appearance:** color, line style (solid, dashed, dotted, dash-dot), line width and waypoint size (numbers show from 14 px). The default is gray and dotted. Used on the map and saved with the route.
- **Active route waypoints:** click one to see:
  - its name and position
  - its distance and bearing from the vessel
  - its **ETA**: following the route from where the vessel is now, at the survey speed (or *passed*)
  - a **View the route** link

  Everything except the name and position is kept up to date as the vessel moves.
- **Export GPX…** downloads the waypoints and a route for a chart plotter or OpenCPN, and keeps a copy in `exports/`.
- A GPX saved or exported by Spyhop holds the whole design (mode, legs, speed, appearance), so it opens again exactly; from any other GPX, the route (or else the waypoints, or a track) becomes a manual route.

## Connecting GPS / instruments (Settings → Inputs, Tools → Instruments)

**Tools → Instruments** shows what comes in, and links to **Settings → Inputs**, where the inputs are set up. It has:

- **Instruments:** the latest reading of everything coming in, grouped as Navigation (SOG, speed through water, COG, heading, rate of turn, rudder, GPS fix, satellites, HDOP), Depth, Wind (apparent and true), Weather (air and water temperature, humidity, dew point, pressure), Engine (RPM per engine or shaft) and Other transducers. Each tile shows the sentence it came from and how old it is, and turns gray after 15 seconds without an update.
- **Plots:** click any numeric reading to plot it since the start of the survey, with now/min/max/mean and a hover readout. Angles are plotted as dots, because they wrap at 360. While a survey is active, Spyhop saves every reading every 5 seconds in `<survey>_instruments.csv` (DateTime, Key, Label, Unit, Value). That file is part of the separate-CSV export, so the history survives a restart.
- **Raw NMEA log:** tick **Record raw NMEA to a file** to save every sentence from every input as it arrives. Each line starts with the UTC time and the input name (untick that option for plain NMEA that any NMEA tool reads). Logs go in the survey's folder, in `nmea_logs/` (`<survey>_nmea_<time>.nmea`; a new file starts when you start, open or close a survey), or in the data folder's own `nmea_logs/` while no survey is open. Recording carries on after a restart until you switch it off. A log can be played back as a **File** input.

Set up inputs in **Settings → Inputs** (GPS / NMEA inputs). You can run several inputs at once. The first one in the list is preferred, and the next one takes over if it goes quiet for 5 seconds.

| Input | Use it for |
|---|---|
| **Serial** | A USB GPS puck or an NMEA 0183 serial adapter. The port box lists the ports it finds. GPS pucks are usually 4800 or 9600 baud. |
| **UDP** (default: port 10110) | NMEA broadcast on the boat network by a multiplexer, plotter or OpenCPN. In OpenCPN, add a *Network → UDP → output* connection to 127.0.0.1:10110. |
| **TCP** | NMEA servers (multiplexers, Signal K's NMEA 0183 TCP stream on port 10110). |
| **GPSD** | Linux gpsd. |
| **File** | Replays an NMEA log in real time (or faster, with *Speed ×*). **Choose…** finds the file. Spyhop's own raw logs are replayed at the pace they were recorded; plain NMEA files at the pace of their RMC/GGA times. The status shows the line being replayed. Put the File input at the top of the list, or switch off the other GPS inputs, because inputs higher up are preferred. |
| **Simulator** | Practice and testing. |

It reads RMC, GGA, GLL and VTG for position, speed and course, and HDT, THS, HDG and HDM for heading. For the Instruments panel it also reads VHW and VBW (speed through water), DPT, DBT, DBS and DBK (depth), MWV, VWR, VWT and MWD (wind), MTW, MTA, MHU, MMB and MDA (weather), RPM (engines), ROT, RSA, and XDR transducers (temperature, pressure, humidity, RPM, voltage, tank levels, angles). The raw NMEA monitor at the bottom of the tab shows exactly what is arriving.

## What's on screen

The window has **three panes** under the status bar: the **map** (top left), **Survey, Tools and Settings** (top right), and the **data tables**, Sightings, Effort and Events, across the full width at the bottom so their columns have room. A data table and a Survey/Tools/Settings page show at the same time (e.g. Sightings below, Tools → Summary above).

- **Resize:** drag the bar between the map and Survey/Tools/Settings, or the bar above the data tables (or click a bar and use the arrow keys; double-click it for the starting size).
- **Minimize** (▁ in a pane's header): the map or Survey/Tools/Settings shrinks to a thin strip at the side and the other takes the top (click the strip to bring it back); the data tables shrink to their tab bar (click a tab, or ▴, to bring them back; Ctrl/Cmd+Shift+M toggles it). With both top panes minimized, the data tables get almost the whole window.
- **Maximize** (□): one pane fills the window; ❐ restores the three panes. Going to a tab in a hidden pane (e.g. with a shortcut) brings it back.
- **Reset the pane sizes** (Settings → General → Tables) goes back to the starting sizes; double-clicking a bar puts just that one back.
- The sizes and which panes are minimized are kept **on this computer** (like column widths), since they depend on the screen.

- **Status bar (top):**
  - the time, with its zone (e.g. `14:31:05 EST`, or `UTC` — choose the clock in Settings), and the position, with a warning if there is **NO GPS**, the **GPS is LOST** (no fix for 10 s), or the position is **NOT MOVING** (the GPS stopped updating while under way)
  - speed, course and heading
  - the **conditions-check countdown** (click it to open the Effort table; the interval is in Settings → General), which flashes when overdue
  - survey name
  - whether tracking is on (switch it on or off in Settings)
  - latest effort state
- **Map:**
  - zoom and pan
  - the vessel with a heading vector (on/off and length in Settings → General → Map display)
  - **Smooth vessel movement** (Settings → General → Map display, on by default, this computer only): the vessel glides between GPS fixes instead of hopping once a second. Only the map drawing is smoothed, so the icon can be up to about a second behind the latest fix; the data always use the real fixes. It jumps straight to the new position after a gap of more than 5 s or a jump of more than 300 m.
  - default marker shape and color for sightings and events are in Settings → General → Map display (species and event-type colors from your lists take priority); waypoints have their own shape and color on each row
  - the track, in the color of each Effort value (Settings → Dropdowns → Effort), thinner off effort. Set the on- and off-effort width and line style (solid, dashed, dotted, dash-dot), or hide either, in **Settings → General → Map display → Trackline**.
  - **Settings → General → Map display** has everything that changes the map's look: markers, the trackline, lines and vectors, and fading. Fading dims the trackline, sightings and events older than the chosen number of **minutes** (30 by default); waypoints never fade. **Move the map to a sighting, event or waypoint selected in its table** (on by default) can be switched off there too.
  - sighting, event and waypoint markers, each with a label and a popup. The popup shows only the essentials:
    - **sightings:** the time, the animals' position, the species and the number (with calves)
    - **events:** the time, position, event and ID
    - **all:** the current distance and bearing from the vessel, which keeps updating while the popup is open, and a link to the row in its table
  - dashed lines from the vessel to each sighting (on by default), optionally a dotted line joining re-sightings of the same FieldID from oldest to newest, and a dotted line from each sighting through its resights. Each of the three can be shown or hidden, with its own width and line style (solid, dashed, dotted, dash-dot), in **Settings → General → Map display → Lines and vectors**.
  - distances on the map (the measuring tool, popups, routes and the Summary) are in the **Map distance unit** (Settings → General → Bearings, distances and time: nm, km, m, mi or yd), separate from the default **Unit** of new sightings, which can be one of the reticles (`reticles-<name>`)
  - **resights** (see *Resights* below) drawn smaller and as outlines by default, with a dotted line from the first sighting through its resights; change their look in **Settings → General → Resights**
  - optional fading of the track and markers older than a number of hours you choose
  - **toolbar buttons:**
    - ⌖ follow the vessel
    - 📏 measure: click to add points, double-click or Esc to finish, click again to clear. Each leg shows true and magnetic bearing plus distance, and the total.
    - ◎ range rings
    - ⤢ zoom to the whole survey (overlays are imported in Tools → Overlays). When Spyhop starts with a survey open (active or ended), the map starts zoomed to the whole survey, with vessel-following off (⌖ turns it back on).
  - **layers menu** (top right): base maps in two sections, **Online map tiles** and **Offline map tiles** (the files in the charts folder, and the built-in **Coastline (offline)**), and overlays you can switch on and off, also in two sections, **Offline overlays** (survey data, waypoints, routes, imported files, range rings…) and **Online overlays** (AIS, weather radar, map feeds), including a **graticule** (lat/lon grid; spacing adapts to the zoom, longitude labels run vertically so they don't collide)
  - **labels:** sightings show the species code plus the FieldID if there is one, e.g. `RIWH Eg-3720` (or SigNo if there's no species yet); events show their event code and ID, e.g. `CTD C-07` (or E1, E2… if both are blank)
  - **right-click menu:** add a sighting, event or waypoint at that point; measure from here; copy the position
  - **readout (bottom-left):** cursor position, bearing and distance from the vessel, and a nautical-mile scale
- **Tabs:** **Sightings**, **Effort** and **Events** in the data pane; **Survey**, **Tools** and **Settings** in the pane beside the map. Each data tab has **Add row**, **Delete row**, **Undo** and **Redo**. With no survey open, Spyhop opens on **Survey** (see *Surveys* below).
  - **Survey:** start, end, close, open, export and clear surveys; save and open survey packages; survey details and the survey's template; the surveys in the data folder; the folders.
  - **Tools** has a second row of tabs:
    - **Waypoints:** the waypoints table.
    - **Overlays:** the **offline overlays**: import GeoJSON/GPX/KML files, **show or hide** each one (or all), zoom to one, or remove it; and add **past surveys** in the data folder as overlays (their trackline, solid on effort and dashed off effort, sightings and events; press **Update** after changing one). Hidden overlays stay hidden next time. Click an overlay's **color** to draw it in another color (↺ goes back to its own colors); the colors are kept with the map display, so they travel in templates too. *Imported overlays* in the map's layers menu switches them all on or off. Below them, the **online overlays** (AIS, weather radar, map feeds; see *Online overlays* below).
    - **Routes:** saved routes (show them on the map, open, delete) and the route being designed or activated (see *Planning routes* below).
    - **Instruments:** instrument readings (click one to plot it) and the raw NMEA log.
    - **Resights:** swim speeds and dive times of animals with resights (see *Resights* below).
    - **Error check:** checks the survey for mistakes (see *Error check* below).
    - **Summary:** the survey summary (below).
    - **Reports:** pick rows of Sightings, Events or Effort and some of their columns, and save them as CSV, HTML or PDF; **Run Reports…** saves several at once (see *Reports* below).
  - **Settings** has a second row of tabs:
    - **General:** map display, text size (tables, interface and the status bar), tracking and reminders, bearings, distances and the clock, and sleep.
    - **Basemap:** downloading areas for offline use, and the charts folder (see *Maps offline* below).
    - **Inputs:** the GPS / NMEA inputs.
    - **Shortcuts:** every keyboard shortcut and what it does.
    - **Dropdowns:** the species, event, behavior, observer, effort, visibility and weather lists, and the reticles. None of them can change while a survey is active.
    - **Templates:** a team's settings in one file (see *Templates* below).
    - **Guide:** the tutorial, with a list of its sections beside it (above it in a narrow pane) to jump to each one.
    - **About:** the version, the changelog, the diagnostic logs (**Save diagnostics…**), and **Updates**: **Check for updates** looks on GitHub for a newer Spyhop and can install it (with a backup of the old version) and restart. Tick *Check when Spyhop starts* to be told automatically when there's internet. **Uninstall or reinstall:**
      - **Reinstall a clean copy…** replaces the program with the latest version from GitHub and restarts; your surveys and (unless you tick reset) your settings are kept. A git checkout is reset to its branch on GitHub instead.
      - **Uninstall Spyhop…** removes the program and its shortcuts. Your settings and your survey data are deleted only if you tick them; survey data also needs DELETE typed, and a data folder you chose yourself is never deleted.
      - Neither works during a survey. A git checkout can be uninstalled or reinstalled only when it has no uncommitted changes and nothing unpushed; the dialog says why if not.
  - Clicking **Tools** or **Settings** returns to the one of its tabs you used last.
  - **?** buttons beside the headings in Survey, Tools and Settings hold the explanations: hover over one to read it, or click it to keep it open (click again, press Esc or click elsewhere to close it).
- **Summary** (Tools → Summary, or Ctrl/Cmd+4) shows:
  - the summary numbers, then the survey's start and end times, duration and details (platform, organization, chief scientist and their email)
  - **Save as HTML…** saves the summary as **one HTML file**, with an interactive map of the survey (track, sightings and events, with popups) at the top and the rest in the same order as the Summary tab. Waypoints aren't included, since they don't belong to a survey. It opens in any browser, even offline, with no Spyhop needed, so it's easy to email or share.
  - **Save as PDF…** saves the same summary as a PDF, with a map made for paper: zoomed to the extent of the survey, on the **Esri Ocean** basemap when there's internet (the offline coastline otherwise; a line under the map says which), with no text labels on the points, and a **legend** of the point symbols (by species and event type, with counts) under the map. The summary PDF in **Export Data…** is the same.
    - The offline coastline is the default base map; OpenStreetMap and Esri Ocean are offered when there's internet.
    - A copy goes in the survey's `exports` folder.
  - counts by species (sightings, number, calves, resights) and by event type. Resights aren't counted as sightings again: each sighting counts once, with the largest number and calves seen on the sighting or any of its resights.
  - **North Atlantic right whale sightings:** each one, with time, position, number, calves, field ID and notes
  - **observers on watch**: time each observer spent at Port, Recorder and Stbd while effort was ON, and their total
  - the range of environmental conditions (visibility, sea state, weather, glare) for the whole survey and on effort only
  - While effort is ON, *Time on effort*, the distances and the watch times count up live (marked ●).
- **Bottom of the data pane:** a description of the selected column (e.g. what **Ref** means). Start, End, Close, Export and Clear are in **Survey** only, so they can't be clicked by accident.

### Entering data

The tables work like a spreadsheet:

- Click a cell and start typing, or press Enter/F2 to edit. Enter saves, Tab saves and moves right, and Esc cancels. The arrow keys move between cells.
- **Dropdown cells** filter as you type and also match **species codes** (`huwh` finds Humpback whale).
- **Multi-select cells** (Behaviors) open a checklist: ↑/↓ move, Space ticks, a letter jumps to it (again for the next one), Enter saves. The highlighted behavior's definition is shown underneath. Edit the definitions in Settings → Dropdowns → Behaviors.
- **Map** checkboxes toggle with a click or the Space bar.
- **Lat/Lon** are accepted in almost any form: `41 30.5 N`, `41°30'30"N`, `41.508`, `4130.5N`. If you leave off N/S/E/W, it uses the vessel's hemisphere, so `70 20.5` near Cape Cod means 70°20.5′W. Choose DDM, DD or DMS display under **Settings → Lat/lon format**; every table updates at once. Files always store decimal degrees.
- **Times** are shown in the survey clock (Settings → General → Clock), with the zone in each cell (e.g. `15:52:22 EST`). Type `14:05` to change only the time of day. The files always store each time with its UTC offset, so switching the clock never changes data. The clock can be:
  - **From the platform's position:** the time zone at the GPS position, from an offline map (`tzfpy`), daylight saving included. At sea, the nearest coast's zone within 150 nm (so a survey off Cape Cod keeps Eastern time), and the nautical zone further out. Settings shows which zone was found and how; it's checked again after every 5 nm.
  - **This computer's time zone**, **UTC**, or **any fixed UTC offset** (UTC−12:00 … UTC+14:00, including half and quarter hours).
- **Reticle distances** (Settings → Dropdowns → Reticles): each entry of the reticles list is a **Unit**, `reticles-<name>` (e.g. `reticles-binos`), offered in the Unit column and as the default distance unit. With one, Dist is a reading, and Spyhop works out the distance from it and the sighting's **Alt** (filled in from the survey's Platform altitude; edit it if the height was different). It allows for the curvature of the earth (Lerczak & Hobbs 1998). A reading at or above the horizon gives no distance. Each entry has a **name** (letters, digits, `-`, `_` and `.`; no spaces) and says how readings are taken:
  - **Binocular reticles:** the number of reticle divisions counted down from the horizon to the animals. Choose the **magnification**, which suggests the angle of one division, and correct **Degrees per division** for your binoculars (check the manual or calibrate them). Many 7× and 10× marine binoculars have a 10-mil scale (0.573°); Fujinon 25×150 big-eyes are 0.0771° (Kinzey & Gerrodette 2001).
  - **Calibrated marks:** evenly spaced marks (e.g. on an aircraft's window or wing strut), counted down from the horizontal (mark 0). **Degrees per division** is the angle from one mark to the next (magnification isn't used), so mark *n* is *n* × that angle below the horizontal; type the mark number (it can be a fraction, e.g. 2.5) in Dist.
  - **Inclinometer degrees:** the angle below the horizontal, in degrees (90° is straight down).
  - The default list has `binos` (7×, 0.573°), `big-eyes` (25×, 0.0771°) and `incl` (inclinometer). Several can be used in one survey (e.g. big-eyes for distant animals and binos close in), and each sighting records which.
  - A position picked on the map is turned back into a reading (or into meters, for calibrated marks).
  - The reticles are part of the template, and like the other lists they can't be changed during a survey.
- **The Alt column** (Sightings, Settings → General → Altitude column): *Automatic* shows it for aerial surveys and hides it for shipboard and stationary ones; it can also be always shown or hidden. It is always kept in the file.
- **Trackline breaks** (Settings → General → Tracking): the trackline and the summary distances are broken where the platform would have moved faster than **30 kn** between two points (a GPS jump; use about 200 for aerial surveys), or where no position came in for **120 s**. 0 turns either off. The Error check lists each jump or gap (one that jumps away and back counts as one), and its **Fix** button adds an **ERROR** row to the Effort table one second after the last good track point before the stretch (so in the merged export it comes after that point), plus a row at its end that puts the effort and conditions back. ERROR counts as off effort, and the stretch isn't drawn.
- **Sightings:**
  - New rows get the time, vessel position and an auto-incrementing **SigNo** (the CSV column is SightNo). **FieldID** (after Images) is free text for your own ID (photo-ID, catalog number…). It becomes the sighting's map label. The cursor skips it on a new row so you go straight to Species. **Calves** takes a number or **NA** where calves don't apply (dead birds, fishing gear, vessels…).
  - Enter **Bearing** and **Distance**, and the animal's position (**SigLat/SigLon**) is calculated. With a `reticles-<name>` Unit, Dist is a reading instead (see *Reticle distances* below). Bearings can be negative and count back from 360 (−10 is stored as 350), which is handy for relative bearings to port. Without a bearing and distance, SigLat/SigLon are the vessel position.
  - The vessel heading is saved in the CSV (`VesHdg`, not shown in the table) so that bearings relative to the bow can be converted.
  - Each row stores its own bearing reference (**Ref**: M magnetic, T true, R relative to the bow, **C clock**) and distance **Unit**, so changing the defaults in Settings never changes old rows.
  - **Clock bearings (Ref C):** with Ref C, the Bearing cell offers 1 to 12 o'clock (or type the number). Each hour is 30° from the bow: 12 dead ahead, 3 the starboard beam, 6 astern, 9 the port beam. It's turned into a true bearing with the vessel heading recorded on the row. Choose C as the **Default bearing reference** in Settings → General to have it on every new sighting.
  - Magnetic bearings use the World Magnetic Model.
- **Resights** (another sighting of animals already recorded: closing in for photos, a focal follow): select the sighting and press **Add resight** (Ctrl/Cmd+Shift+L), greyed out when no sighting is selected. The new row gets the time and position as usual, **ResNo** (right after Calves; the CSV column is ResightOf) holds the first sighting's SigNo, and the species, Num, Calves, NumConf, IDrel and FieldID are copied from the row you selected, ready to correct. A resight of a resight is linked to the first sighting. You can also type a SigNo in **ResNo** to link rows afterwards, or clear it to unlink one.
  - Resights aren't counted again in the Summary (see *Summary*), and the Error check doesn't list them as off-effort sightings or their observer as off watch.
  - **Settings → General → Resights:** list the Sightings table in time order or with each sighting's **resights nested** under it (a resight's SigNo is indented either way); the resight markers' shape (or hidden), fill (outline, filled or faded), size and labels. The line through each sighting's resights is set with the other lines in Map display.
  - **Add resight** keeps the column you had selected, on the new row.
  - **Tools → Resights** lists each sighting that has resights: its **FieldID** (blank if none), the number of resights, the time span, the distance along the resights, the **average swim speed** (that distance over the time; in knots and km/h), the **net speed** (first sighting to last resight in a straight line), and the **dive times**. A dive time runs from a resight with a dive behavior (Fluke-up dive and Fluke-down dive to start with; tick others) to the next resight with **First surfacing** (a behavior in the default list; choose another if yours is named differently). **Resights…** shows each interval and dive; **Save as CSV…** saves them all. Speeds use the animals' positions (SigLat/SigLon) worked out from bearings and distances, so distance errors show up as speed, most of all over short intervals.
  - In the exports, the merged CSV has a **ResightOf** column: keep the rows where it's blank for first detections only (e.g. for encounter rates or detection distances).
- **Waypoints** (Tools → Waypoints; called Marks before 0.5.0): each waypoint has its own **Shape** (Circle, Diamond, Square, Triangle, Star) and **Color** (pick from the list or type a `#hex` code).
- **Events:** the default list has CTD casts, drifters, drones, tags, biopsies, **Mooring deployed/recovered**, plankton tows and **Other**. Vessels, marine debris and fishing gear (reported, recovered) are recorded as Sightings: they're at the end of the default species list. **ID** is free text for an instrument or sample ID (CTD cast number, tag ID, drifter ID…). Each event type has a short code in `event_types.csv` (the `event_code` column, e.g. `CTD`, `MOOD`). Type the code to pick the event, and the map label shows code + ID.
- **Effort:** the Effort column's values come from the **effort list** (Settings → Dropdowns → Effort). Each entry has a **name**, a **status** (on or off effort), a **definition** (shown in the drop-down) and a **color** (the track's color while that value is in force). The default list has **ON** (observers are on watch), **TRANSECT** (a systematic line-transect survey), **DIRECTED** (a directed survey or activity), **PHOTO-ID** (a photo-ID survey) and **FOLLOW** (a focal follow), all on effort, and **OFF** (observers off watch). The status decides what counts as on effort on the track, in the Summary (which also gives the time spent in each on-effort value), in reports (On effort only) and in the Error check. **Start**, **End** and **ERROR** are always in the list and always off effort; they can't be renamed or removed. The Toggle effort shortcut (Ctrl/Cmd+Shift+F) goes OFF, then back on as the last on-effort value you were on.
  - **Seg** (effort segment) is numbered by Spyhop: each Effort row whose status differs from the row before starts a new segment, and rows with the same status in a row share its number (e.g. TRANSECT, TRANSECT with new conditions, OFF, TRANSECT → 2, 2, 3, 4 after the Start row's 1). It's renumbered after every change, can't be typed, and is carried onto sightings and events in the merged CSV. Hide it in **Settings → General → Tables**.
  - The first row is always **Start** (added when the survey starts; it can't be changed or deleted), and **End** can only be the last row.
  - **Gstart**, **Gend** and **Gref** (glare start, end and reference) say where the glare is: from one bearing clockwise to the other, in the reference given (M, T, R, or C for clock bearings 1–12, picked from a list as for sightings). They're optional; the Error check asks for both ends and a reference, and checks the range.
  - **Vis** and **Weather** come from their lists in Settings → Dropdowns (part of the template). The Error check reads distances from the Vis names (e.g. `1-2 nm` is at most 2 nm).
  - A new row copies everything from the previous row except the notes. Right after the Start row, Effort is left blank for you to choose.
  - Start and End count as off effort in the summary and on the track.
  - In the track CSV, points are labeled with the Effort value in force (e.g. TRANSECT, OFF).
- **Insert row…** (every data tab): select a row, then choose whether the new row goes **after** or **before** it, and how its time and position are filled in: the **average** of the rows either side of it, **copied** from the row before or the row after, or **Use this time and the nearest vessel position** (type a time, e.g. `14:05`): the row goes in time order and its position is the vessel's at that time from the trackline (in proportion between the track points either side). Its Notes say how (e.g. *Inserted: time and position averaged from the rows before and after (10:00:00 and 10:20:00).*). Other columns are filled in as for a new row. You can insert rows into an ended survey to fill a gap; nothing can go before the Start row or after the End row.
- **Columns:** drag a column's header to move it, and drag the right edge of a header to change its width (double-click the edge for the default width). The order and widths are kept on this computer only (not in templates); **Settings → General → Tables** resets them all.
- **Sightings row colors** (Settings → General → Tables): **None**, **Alternating** rows, **Highlight resights** (the default: resights tinted) or **Group resights** (each sighting that has resights, and its resights, in a color of their own).
- Every edit is saved to disk immediately. Undo/redo is unlimited per tab.

### Keyboard shortcuts (Settings → Shortcuts)

| Keys (Cmd on Mac) | Action |
|---|---|
| Ctrl+Enter | Add a row to the data table in view (Sightings, Effort or Events), even from Survey, Tools or Settings; never a waypoint (also works while typing in a cell; that edit is saved first) |
| Ctrl+Shift+S / E / V / K | Add sighting / conditions row / event / waypoint |
| Ctrl+Shift+F | Add an effort row that switches effort ON↔OFF |
| Ctrl+Shift+R, Ctrl+Shift+H | Add a sighting pre-filled with North Atlantic right whale / Humpback whale |
| Ctrl+Shift+L | Add a resight of the selected sighting |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo in the table you're in (while typing in a box they undo the typing, as usual) |
| Ctrl+1 … 5 | Sightings, Effort, Events, Tools → Summary, Settings → General |
| Ctrl+PageUp/PageDown, Alt+←/→ | Previous/next tab |
| Ctrl+Shift+C | Center on the vessel |
| Ctrl+Shift+M | Minimize / restore the data tables |

**Changing them:** in **Settings → Shortcuts**, click a shortcut's keys and press the new ones, choose what it does from the list, and press **Save**.
- Shortcuts that add a row can pre-fill columns, e.g. `Species=Fin whale;Obs=OBS1`.
- Keys need Mod (Ctrl, or ⌘ on a Mac) or Alt, so they don't get in the way of typing; F1–F12 work alone.
- Keys used twice are flagged, and combinations that the browser or the computer may take (e.g. Ctrl+W) are marked.
- **Restore the default shortcuts** puts the original set back (press Save to keep it), and **Revert** discards unsaved changes.
- For many changes at once you can still edit `shortcuts.csv` in a spreadsheet and reload it.

### Drop-down lists (Settings → Dropdowns)

The **Species**, **Events**, **Behaviors**, **Observers**, **Effort**, **Visibility**, **Weather** and **Reticles** tabs edit the drop-down lists.
- Each entry has a name (initials, for observers), a code, and for species and events a color, typed as a name like `red` or picked. Behaviors also have a **definition**, shown at the bottom of the Behaviors checklist as each one is highlighted.
- **↑ ↓** set the order of the drop-down, **✕** removes an entry, **Add entry** and **Sort A–Z** do what they say, and **Save** keeps the changes.
- **Effort** entries have a status (on or off effort), a definition and a color; Start, End and ERROR can't be renamed or removed, and at least one entry must be on effort.
- Names and codes must be unique. Spyhop shows what's wrong and saves nothing until it's fixed.
- Renaming or removing an entry doesn't change rows already recorded; the Error check flags values that are no longer in the list.
- **While a survey is under way the lists are grayed out and can't be changed**, so they stay the same for the whole survey. End the survey to edit them. (Using a template during a survey is still possible, after a warning.)
- For many changes at once, the files (`species.csv` and so on) can still be edited in a spreadsheet and reloaded.

## Reports (Tools → Reports)

A report is a chosen part of one table: some rows, some columns. It updates as you change it and as records are added, and can be saved as CSV, HTML or PDF.

- **Table:** Sightings, Events or Effort. Sightings reports leave out resights: each group of animals appears once, as its first sighting (see *Resights*).
- **Species** (Sightings) or **Event types** (Events): the codes in this survey, with how many rows each has. Click one or more to keep only those; none picked keeps all. **Add a species…** finds any entry in the list, by code or name. A row matches when its species (or event type) has that code in the Dropdowns list, or was typed as the code itself; a name with no code is shown, and matched, by its name.
- **Columns:** tick the columns to show; **▲ ▼** set their order. Besides the table's own columns there are **Time** (date and time to the second), **Time (formatted)** (`2026-11-07 10:54 EST`: to the minute, with the time zone), **Date**, **Clock time**, **Position**, **Latitude**, **Longitude** (in the lat/lon format of Settings → General; for sightings the animals' position, SigLat/SigLon, or the vessel's if there is none) and the **Species code** or **Event code**.
- **More conditions:** **On effort only** (made while an on-effort value was in force), a **time range** (in the survey clock), and any number of conditions on a column: *is*, *is not*, *contains*, *doesn't contain*, *is blank*, *isn't blank*, *is more than*, *is less than*. All must hold.
- The result is in time order, with a **total** under number columns (Num, Calves). Click a row to show it in its table.
- **Export CSV…** (for R, Excel or a database), **HTML…** and **PDF…** save the report on screen in the `exports` folder and download a copy. The HTML and PDF pages have the survey name, its date (or first and last dates, if it ran over more than one day), the platform, organization, chief scientist and their email, then the table and its totals.
- **Saved reports:** **Save report…** keeps the current report by name; it then appears under *Saved reports*, one click away. A saved report that you change is marked • until you **Save changes** (or **Undo changes**); **Save as new…**, **Rename…** and **Delete…** do what they say.
  - Spyhop starts you off with **Right whales**, **Blue whales**, **Dead birds** and **Gear**.
  - Saved reports are part of the current template (`templates/current/spyhop-config.json`), so they travel in templates (Settings → Templates) and a team can hand out its standard reports.
- **Run Reports…** (top of the tab) saves several saved reports at once: tick the reports, the formats (CSV, HTML, PDF; any or all) and where to save them (the exports folder, or a folder you choose). It remembers your choices, and lists the files it saved with a button to open the folder.
- Each saved report is also offered in **Export Data…**, as a CSV.
- **PDFs** are printed by Google Chrome or Microsoft Edge, which Spyhop finds by itself. Set `SPYHOP_CHROME` to the path of another Chromium-based browser if needed.

## Online overlays (Tools → Overlays)

Live data from the internet, drawn over the map. Each one is also in the map's layers menu (marked *online* or *feed*), and the ones you leave on are on next time.

- **AIS vessels** from [Open Waters AIS](https://openwaters.io/ais/), a free network of coastal-authority feeds and volunteer receivers. Spyhop asks for the vessels in view every 30 s and when the map moves; zoom in if it says so (the area is limited). Each vessel is colored by type (cargo green, tanker red, passenger blue, fishing orange, sailing and pleasure purple, tugs and special craft teal, other gray): a triangle pointing the way it's heading when it's moving, a dot when it isn't, a diamond for an aid to navigation. Click one for its name, MMSI, type, speed, course, status, when it was last heard and the source, and its distance and bearing from your vessel. **Hide AIS vessels that aren't moving** thins a busy harbor. The map's credits line names the AIS networks (without station IDs, which can be very long); a vessel's popup gives its full source. AIS from the internet can be minutes old and misses vessels out of receiver range or without AIS: not for navigation or collision avoidance.
- **Weather radar, US:** NOAA NEXRAD base reflectivity mosaic, from the Iowa Environmental Mesonet (Iowa State University), updated every 5 minutes.
- **Weather radar, worldwide:** RainViewer's latest radar frame (every 10 minutes; the time is in the credits line), where radars exist. Free for personal and educational use; the detail stops at about zoom 7.
- **Radar opacity** applies to both.
- **Map feeds:** areas, lines or points from the web, such as management zones.
  - **Ready-made:** **Right whale Seasonal Management Areas (NOAA)** (mandatory 10-knot zones; drawn solid while in effect and dashed otherwise, and the popup says which with the dates) and **Right whale Slow Zones / DMAs (NOAA NEFSC)** (the voluntary Slow Zones in effect now).
  - **Any feed:** a name and an address: an ArcGIS address ending in `/FeatureServer/<number>` (one layer), `/FeatureServer` (all its layers) or `/MapServer/<number>`, or a link to a GeoJSON file. Spyhop checks it when you add it.
  - Each feed has **Show**, a color, how often to fetch it again (every 15 minutes to weekly), **Update now**, **Zoom to** and **Remove**. Click an area for its details.
  - Spyhop keeps the last copy of each feed (in `feeds/` in Spyhop's folder), so it still shows offline; if it couldn't update, the list says so and which copy is showing. Always check official notices: these are approximate.
- AIS and radar need the internet and aren't kept for offline use.

## Maps offline

- **Bundled coastline:** **Coastline (offline)** in the layers menu is a base map of the world coastline from Natural Earth (1:10 m scale), so you have a map even with no internet and nothing downloaded. Only the part in view is drawn, simplified to the zoom, so it stays quick. It is coarse, so don't navigate by it.
- **Online layers** (the map's layers button):
  - **Seascape depths (feet)**, the default: Open Waters' Seascape bathymetry, with depth shading and labeled contours in feet (Spyhop leaves out its spot soundings). While it's shown, the readout at the bottom left gives the **depth at the cursor** (below chart datum), next to the scale bar; it works offline wherever the map has been viewed or downloaded. Spyhop leaves out Seascape's OpenStreetMap background, so it looks the same online and offline (switch on another layer under it, or use Esri Ocean, for land detail). It's drawn with MapLibre GL (bundled), which loads the first time the layer is shown. Seascape is not an official chart and **not for navigation**.
  - Esri Ocean, Esri Imagery, NOAA charts (NOAA's chart display service), and OpenStreetMap.
- **Browsing cache:** everything an online layer shows is also saved on this computer as you view it (unless "Save tiles as you view them" is off), so areas you've looked at stay available offline.
- **Downloading an area for offline use** (Settings → Basemap): move the map to cover the survey area, choose the layer, the zoom range and a name (e.g. *Cape Cod Bay*), and press **Download** while you have internet.
  - The area is saved as **one file in the charts folder**, `<name>.mbtiles`. Downloading again with the same name adds to that file (a bigger area or more zooms); a file is only ever added to from the layer it was made from.
  - Spyhop shows roughly how many tiles that is before you start, and a progress bar while it runs.
  - Each zoom level has four times the tiles of the one before, so keep the highest zoom modest for a big area: 12–13 suits a day's survey area, 14–15 a harbor.
  - A layer's own top zoom is respected (Esri Ocean stops at 13), and zooming in past what was downloaded shows the saved tiles enlarged.
  - For Seascape, the file holds its depth tiles, contours, label fonts and the map style itself. Spyhop doesn't draw Seascape's OpenStreetMap background (and OpenStreetMap's tile policy forbids bulk downloading anyway), so download that area in **Esri Ocean** too if you want land detail offline. OpenStreetMap on its own can't be downloaded either.
  - When it finishes, Spyhop says how many tiles were saved and in which file, how many had no data (open ocean or land, which is normal), and how many failed and why. Press **Download** again to retry the ones that failed.
  - With no internet, Spyhop stops trying a server for a few seconds after repeated failures, so the map stays quick and draws from the saved tiles.
- **In the charts folder** (Settings → Basemap): a table of every `.mbtiles` file there, downloads and charts you added yourself, with what it was made from, its zooms, number of tiles, size and date, and the totals.
  - **Select** puts that file on the map on its own (zooming to its area if the map is elsewhere): only what is saved in it, as you'll have it at sea. The chart on the map is marked *On the map*; choose another map in the layers menu to go back.
  - **Delete** removes the file from the charts folder, after asking.
  - Each file is also listed under **Offline map tiles** in the map's layers menu. When you use the online layer it was made from (e.g. Seascape), Spyhop takes the tiles from the file before going online, so the map is quick and saves bandwidth.
  - A downloaded file works on any computer with Spyhop: copy it into that computer's charts folder and press **Refresh**.
- **MBTiles charts of your own:** put `.mbtiles` files (raster PNG/JPEG tiles) in the charts folder and press **Refresh** (or restart). Free, weekly-updated **NOAA nautical charts** for US waters are available at <https://distribution.charts.noaa.gov/ncds/>: click a region and download the MBTiles file. Downloads of Esri and NOAA layers are ordinary MBTiles files, so other map programs can open them too.
- The online map layers are built into Spyhop, so fixes arrive with updates. To add one of your own, create `tile_sources.csv` in the Spyhop folder with the columns `name,url,attribution,overlay,max_zoom,kind`: its layers are added after the built-in ones. The URL is an XYZ tile server, or an ArcGIS `export` URL using `{bbox}`, with kind `raster`. A MapLibre `style.json` URL uses kind `style`.

The online layers could not be tested from the machine this was built on, which had no internet. Check them once on a connected laptop before you sail.

## Surveys

Surveys are managed in **Survey**; the error check is in **Tools → Error check**.

- **Start New Survey…** asks for a name and the survey details, then adds the **Start** row to the Effort tab. The trackline starts recording.
  - The details are **platform name** (vessel, aircraft or station), **platform type**, **platform altitude (ft)**, **organization**, **chief scientist** and **chief scientist email**. They're filled in from your last survey and can be changed any time in Survey.
  - **Platform type** sets the map marker and how the trackline is kept:
    - **Shipboard:** a ship, turned to the heading.
    - **Aerial:** an aircraft, turned to the heading. The Sightings **Alt** column is shown.
    - **Stationary:** a tower. The platform doesn't move, so only the Start and End positions are recorded, with no trackline in between, and no heading vector is drawn. The status bar says *Stationary (no trackline)*.
    - **Other:** a dot. The trackline is recorded.
  - **Platform altitude (ft)** is the observers' average eye height above the water on a ship or station, or the usual survey altitude for an aircraft. It fills in each new sighting's Alt and turns reticle readings into distances (below). The Error check doesn't require it unless a reticle sighting needs it.
  - **Survey notes** (in Survey, below the details): general notes or a summary of the survey, as many lines as you like. They're shown in the Summary and its HTML and PDF files, and aren't carried over to the next survey.
  - They're saved with the survey as `<survey>_metadata.csv` and included in exports and the summary.
  - The name is used exactly as typed (only characters that file systems forbid, such as `/ : * ?`, become `_`), so use your team's own convention, e.g. `NEAQ_CCB_2026-11-04_A`. A name that's already in use is refused rather than changed.
  - If another survey is still active, you're asked whether to **End** it or just **Close** it (keeping it active) first.
- **End Survey…** adds an **End** row and stops the trackline. An ended survey can still be corrected, but no new rows can be added. To carry on, delete its End row in the Effort tab (or Undo).
- **Close Survey…** clears the tabs. Everything is already saved as you go. A closed survey that hasn't ended stays *active*, so you can continue it later.
- Below the current survey, **Folders** shows where surveys are saved, with links to open the folder and to change it (Settings → General → Folders).
- **Surveys in this folder** lists every survey with its status (Active/Ended), start and end times, and number of sightings. **Refresh** reads the folder again, e.g. after copying surveys into it.
  - Press **Open** to open one. If it's still active, you're asked whether to **Continue** it (tracking resumes) or just open it to look at or correct.
  - Surveys made before Start/End existed get a Start row added at the top, timed at their earliest record, with a notice.
- **Error check** (Tools → Error check): press **Run error check** before you finish a survey (or any time). It lists problems as **errors** (must fix), **warnings** (probably wrong) and **notes** (worth a look), and **Show** takes you to the row and column in the data table below (the row flashes), so the list and the data can be seen together. It doesn't change anything, except when you press a **Fix** button. **Save report…** downloads the list as a CSV. It checks:
  - **Survey details:** every field filled in, and a valid email.
  - **Required fields:** Sightings — everything except Behaviors, Bearing, Ref, Dist, Unit, Alt, ResNo, FieldID and Notes. Effort — everything except Notes (Start and End rows need only the time and position). Events — everything except ID and Notes.
  - **Valid values:** choices are in their lists; numbers, positions and times can be read; no time is in the future; nothing is before Start or after End; rows are in time order; no SigNo or EventNo is used twice; the survey starts with Start and has an End.
  - **Plausible values:** Num a whole number of at least 1 (flagged over 500); Calves not more than Num (or NA); Bearing 0–360° (negative bearings are stored as their 0–360 equivalent) and Dist not negative, given together and with their Ref and Unit; relative bearings have a heading; animals within 10 nm of the vessel and no further than the visibility on the Effort row in force; vessel positions within 0.5 nm of the trackline at that time; positions not on land (by the bundled coastline, ignoring the first 0.5 km); no track jumps or gaps beyond the trackline-break settings (each has a **Fix** button that marks it with an ERROR Effort row).
  - **Resights:** each ResNo names an existing sighting (one deleted or renumbered is flagged, and the row is counted as a sighting of its own), timed before the resight and of the same species. A **warning** when the animals would have swum faster than **30 kn** from one sighting of them to the next (positions from SigLat/SigLon, else the platform's).
  - **Protocol:** a new Effort row at least every 1.5 × the reminder interval while on effort; nobody in two watch positions at once; the sighting's observer is on watch; a sighting entered twice (same time, species, number and position) or a duplicated event (same type and ID within 30 s). A FieldID can be reused for different species, and two sightings of one species close together are fine. Notes list sightings off effort, effort in sea state above 5 or visibility under 0.5 nm, and observers on watch over 2 hours without a break.
  - The thresholds are at the top of `spyhop/qc.py`.
- **Keeping the computer awake** (Settings → General → Sleep): a computer that goes to sleep stops recording the trackline and NMEA data, so by default Spyhop stops it sleeping **during a survey** (from Start until End, or until the survey is closed). Choose **Always** to keep it awake whenever Spyhop is open, or **Never** to leave sleep to the computer's own settings. Tick **Keep the screen on too** to stop the screen turning off as well. Closing a laptop's lid still puts most laptops to sleep, and a laptop on battery runs down faster. When Spyhop quits, or crashes, the computer's own sleep settings apply again. (It uses `caffeinate` on a Mac, a Windows power request on Windows, and `systemd-inhibit` on Linux.)
- **Crash recovery:** if Spyhop is closed or crashes while a survey is active, it reopens that survey on the next start and asks whether to continue. Tracking resumes only once you say so.
- **Delete Survey Data…** is the only thing that deletes data. It needs two confirmations, the second by typing the survey name, and closes the survey.

## Your data

Spyhop's own folder holds your lists and settings:

- Windows: `%APPDATA%\Spyhop`
- Mac: `~/Library/Application Support/Spyhop`
- Linux: `~/.local/share/Spyhop`

Both folders are shown in **Settings → General → Folders**, each with an **Open folder** link.

**Templates:** a template is one small file (`<name>.spyhop-template.zip`) holding a team's settings: the lists and shortcuts (as CSV files) and a `spyhop-config.json` with the map display, saved reports, shared settings (clock, units, tracking, keep awake, raw NMEA log), the network GPS / NMEA inputs, the map feeds (their addresses, not their data) and which online overlays are on, the record of changes and the oldest Spyhop that can use it; and optionally waypoints, routes and overlays (ticked when saving). Settings are replaced; map feeds, waypoints, routes and overlays are only added, keeping any the computer already has. Serial GPS ports, the data folder, survey data and offline charts are never in a template. The current template is itself a template, unzipped, in `templates/current`; **Settings → Templates** lists the templates in `templates/saved`, with each one's latest change, whether it matches this computer, and which one is in use. **Use this template…** shows what would change and then replaces this computer's lists, shortcuts, display, reports and settings with the template's, with no merging (a backup is saved first in `templates/backups`; **Restore…** undoes it). **Update…** replaces a template with the current template, and **Save as a new template…** makes a new one; both ask for your name and what changed and add it to the template's record of changes. A team's template on the web is fetched with **Get a template from the web** → **Check**, and a copy is kept in the folder for offline use. **What can't change during a survey:** from Start until End, nothing that defines or works out the data can change: the drop-down lists (species, events, behaviors, observers, visibility, weather) and the reticles, the track point interval and trackline-break settings, and the magnetic variation. Their controls are greyed out, editing their files by hand is undone when they're read again, and a template that would change any of them can't be used until the survey ends. Shortcuts, map display, reports, overlays and display settings (clock, lat/lon format, units shown, default bearing reference and unit) can change at any time; each sighting stores its own bearing reference and unit. So the copy of the template kept with the survey is exactly what its data were recorded with. **Start New Survey** offers to save the current template first if it isn't saved, and each survey's details record the template and Spyhop version it was started with. See [TEMPLATES.md](TEMPLATES.md) for sharing and hosting templates.

The **survey data folder** holds the surveys (a folder each) and the waypoints. It's `data/` inside Spyhop's folder unless you choose another one under **Settings → General → Folders** (the Survey tab links there; **Choose folder…** opens your computer's folder chooser, or type/paste a path). It's remembered between sessions. If it isn't found at start-up (e.g. an unplugged drive), Spyhop uses the default for that session and tells you. Switching folders closes the open survey first.

**Survey packages** (Survey tab): **Save Survey Package…** saves the open survey as one file, `<survey>.spyhop-survey.zip` (downloaded, and kept in the survey's `exports/`), to move it to another computer, archive it or send it for checking. It holds the survey's files as Spyhop keeps them (so it can be edited again), the copy of its template, optionally its raw NMEA logs, and a `spyhop-survey.json` describing it, with a checksum of every file. Exports aren't included; for analysis use **Export Data**. **Open Survey Package…** (under *Surveys in this folder*) adds the survey to this data folder and opens it, with tracking off. Nothing is overwritten: if a survey of that name is already here, it asks for another name (its files are renamed to match). A damaged or incomplete package, one from a newer Spyhop, or a file that isn't a survey package is refused with the reason. An active survey stays active in the package; end it there if it's finished.

**A survey recorded with another template:** the Survey tab shows each survey's template, and says when its copy differs from the current template (for example, after the lists were edited, or when a survey from another team is opened). The data aren't changed either way. While the current template is in use, the drop-downs, colors and the Error check follow it, so values that aren't in its lists are flagged. **Compare and use the survey's template…** opens it in Settings → Templates, where **Use it** makes it the current template (with a backup first, as for any template). Surveys started before 0.36 have no copy; the survey details still name the template they were started with.

```
Spyhop/                                   (Spyhop's own folder)
  templates/
    current/   the current template (a template, unzipped):
               species.csv  event_types.csv  observers.csv  behaviors.csv   <- the lists (name, code; color for
                                                                               species and events; definition for behaviors)
               shortcuts.csv
               spyhop-config.json   <- shared settings, network GPS inputs, map feeds, online overlays,
                                       map display, saved reports, record of changes
    saved/     <name>.spyhop-template.zip   <- your templates
    backups/   the current template as it was before each other template was used
  spyhop-local.json   this computer's own settings (data folder, serial ports, window, last survey details,
                      the open survey) — never in a template
  charts/    *.mbtiles      overlays/  imported GeoJSON/GPX/KML
  routes/    saved routes (Tools → Routes), one GPX file each
  feeds/     the last copy of each map feed (Tools → Overlays)
  logs/      diagnostic logs (spyhop.log, crash.log, diagnostics zips)
  data/                                   (default survey data folder — or the one you chose)
    <survey name>/                <- one folder per survey (0.36)
      <survey>_sightings.csv  _effort.csv  _events.csv  _track.csv  _metadata.csv  _instruments.csv
      <survey>_template.zip      <- the template the survey was started with
      exports/   <survey>_export_<time>.zip, or a single exported file; summaries, reports, survey packages
      nmea_logs/ <survey>_nmea_<time>.nmea  <- raw NMEA, when recording is on
    waypoints.csv                 <- kept across surveys
    exports/   nmea_logs/         <- exports and raw NMEA made while no survey was open
```

- `<survey>_metadata.csv` holds the survey details, plus a few rows Spyhop writes itself: the Spyhop version the survey was started with (and last saved with), the saved template the current template came from, and whether it still matched it when the survey started.
- `<survey>_template.zip` is a copy of the current template (lists, shortcuts, map display, reports, shared settings) made when the survey started. Lists can't change during an active survey, so it is exactly what the survey was recorded with. It's an ordinary template: Settings → Templates can use it.
- Before 0.36 the survey files were at the top of the data folder, with their logs in `nmea_logs/` and exports in `exports/`; Spyhop 0.36 moves each survey into a folder of its own whenever it opens a data folder laid out the old way (nothing is overwritten).
- Before 0.28 the lists, shortcuts, `display.csv`, `settings/` and `reports/` were at the top of Spyhop's folder and templates were in the data folder; Spyhop 0.28 moves them into `templates/` and `spyhop-local.json` the first time it runs.

- The track CSV's **Effort** column is `Start` (from the Start row until the first ON or OFF), then `ON`/`OFF`, and `End` on the final point, written when you end the survey. A script can tell the start and end of the track apart from off-effort periods.
- The working CSVs have a **RowID** column. Spyhop uses it to tell rows apart, for undo/redo and for keeping open windows in step, because SightNo can be edited and Effort/Event rows have no other unique key. Leave it alone when you edit a file by hand. Exports leave it out.

- **Export Data…** asks which formats you want (it remembers your choice):
  - **Separate CSV files:** sightings, effort, events, track, instrument readings, survey details and waypoints, one file each, as Spyhop records them (without RowID). The track's Effort values are recalculated from the final Effort table.
  - **Merged CSV file** (`<survey>_merged.csv`): sightings, effort, events and the track points in one table, in time order, one row per record. `Record` says which it is (Sighting, Effort, Event or Track). Track rows have the position, `SOG` and `COG`, and their Effort label from the track file (Start, ON, OFF, End or ERROR). Every row also has the Spyhop version (SpyhopVersion) and the survey details (Survey, PlatformName, PlatformType, PlatformAltitudeFt, Organization, ChiefScientist, ChiefScientistEmail) and the effort and conditions in force at that time (Effort, Segment, Visibility, SeaState, Weather, Glare, GlareStart, GlareEnd, GlareRef, Port, Recorder, Starboard, from the latest Effort row at or before it; "no effort row yet" before the first). So each sighting can be analyzed with its conditions without a join. `Lat`/`Lon` is the vessel position (the event position for events); sightings keep SigLat/SigLon too, and the event ID is `EventID`.
  - **GPX file:** the track and waypoints, for GPS units and mapping apps.
  - **GeoJSON file:** the track split by effort, and points with all their columns, for QGIS or ArcGIS.
  - **Summary report:** the same page as Tools → Summary, as HTML, PDF or both (*Save the summary as*).
  - each saved **Report:** as CSV. (To save reports as HTML or PDF, or somewhere else, use **Run Reports…** in Tools → Reports.)

  One format is saved and downloaded as that file. Several (or the separate CSVs) come as **one zip**. Everything is also kept in the survey folder's `exports/`.
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
- three resizable panes (map, Survey/Tools/Settings, data tables), each of which can be minimized or maximized
- marker shape and color per tab, with species and event colors
- grid and UI font sizes

New or different:

- Markers are clickable, with popups.
- New map tools: measure, range rings, right-click "add here", lines from vessel to sighting, imported overlays, offline MBTiles, and downloaded areas saved in the charts folder.
- A Waypoints tab (in Tools), with map overlays.
- GeoJSON, GPX and merged-CSV export, chosen per export.
- An Instruments tab (in Tools) with live instrument readings and raw NMEA logging.
- An error check.
- Several NMEA inputs at once, with priority and a raw monitor.
- The keyboard opens dropdowns on Windows too. This was a known limitation in the plugin.
- Per-row bearing reference and distance unit.
- FieldID on Sightings and ID on Events.
- A clock in local time, UTC, any UTC offset, or the zone at the platform's position; a live Summary with environmental-condition ranges; reports of any table, saved by name and shared in templates.
- The Surfacings tab was dropped.
- An extra Glare column on Effort.
- **Check these before relying on old pipelines:**
  - The CSV column names are this app's own (see `spyhop/schema.py`). They may not match the plugin's `column_definitions.csv` exactly.
  - The Visibility, Weather and Images lists are best guesses.
  - Sea state is 0–9.

  All of these are defined in one file (`schema.py`) and are easy to change.
