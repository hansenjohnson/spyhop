# Spyhop user guide

Spyhop records a vessel-based (or aerial, or shore-based) marine mammal survey: sightings, effort and conditions, events, the trackline and instrument readings, all against a live chart. This guide starts with a **Quick start** that walks through a whole survey, then covers every part of Spyhop in detail. It's also in Spyhop itself, under **Settings → Guide**. For installing Spyhop and Python, see the [README](../README.md).

A word used throughout: a **template** is a team's whole setup in one file: the drop-down lists (species, observers, effort codes…), the reticles, the keyboard shortcuts, saved reports, the map display and shared settings, and the GPS / NMEA inputs. Every computer always has a *current template*, which is what you change when you edit a list in Settings. See [Templates](#templates).

## Quick start

### a. Find your way around

The window has **three panes** under the status bar:

- **Map** (top left): the vessel, its trackline (in the color of each effort value, thinner off effort), sightings, events and waypoints.
  - The layers button (top right of the map) switches what is drawn: the platform, track, sightings, events, other GPS sources (drones, buoys…) and overlays. The map tiles underneath are chosen in **Settings → Basemap**.
  - The buttons on the left: ⌖ follow the vessel, 📏 measure, ◎ range rings, ⤢ zoom to the whole survey.
  - Right-click the map to add a sighting, event or waypoint there, or to measure from there.
- **Survey, Tools and Settings** (top right):
  - **Survey** starts, ends, opens and exports surveys.
  - **Tools** holds Waypoints, Overlays, Routes, Instruments, Resights, Error check, Summary and Reports.
  - **Settings** holds General, Basemap, Inputs, Shortcuts, Dropdowns, Templates, Guide (this guide) and About.
  - The **?** beside a heading explains that section: hover to read it, click to keep it open.
- **Data tables** (along the bottom): **Sightings**, **Effort** and **Events**.
- **Status bar** (top): time, position, speed and course, the conditions-check countdown, the survey name, tracking and the effort in force.
  - If the GPS fix is lost, it says **NO GPS** or **GPS LOST**. If the computer's clock is more than 2 seconds off the GPS time, it says so.
  - Click the version number for Settings → About.

### b. Try it with the simulator

You don't need a GPS to try Spyhop. The simulator is a pretend vessel that steams on a fixed heading and speed, sending positions just as a real GPS would, plus made-up depth, wind, weather and engine readings. Use it to learn Spyhop, to train observers, or to test a setup before a survey.

**Switch it on**

1. Open **Settings → Inputs** and press **+ Add input**.
2. Give it a name (e.g. *Simulator*) and change its kind to **SIMULATOR**. Four boxes appear:
   - **Heading °T** and **Speed kn**: the course and speed it steams (for example 090 and 10).
   - **Start lat** and **Start lon**: where it starts, in decimal degrees (for example 41.9 and −70.33, in Cape Cod Bay; west and south are negative).
3. Set its **Role** to **Primary** (the input that gives the platform's position), and press **Apply** (it reads **Apply — unsaved changes** until you do). The vessel appears on the map and starts moving. The map follows it while the **⌖** button on the map is on (Ctrl/⌘+Shift+C centers on it once).
4. Open **Tools → Instruments** to see the readings it sends.

**Steer it**

- To turn, change **Heading °T** (or **Speed kn**) in Settings → Inputs and press **Apply**. The vessel turns at once, from where it is: it doesn't jump back to the start.
- To follow a planned route, turn at each waypoint as you would at sea (Tools → Routes shows the course of each leg).
- To move it somewhere else, change **Start lat** / **Start lon** and press **Apply**; it starts again from there.

**Practice a survey**

1. In the Survey tab, press **Start New Survey…** and call it something like *Practice*.
2. Record effort, sightings and events as described in *Record data* below: the simulator's positions, times and readings fill in the rows like a real GPS.
3. When you're done, **End Survey…**, then try the **Error check**, the **Summary** and **Export Data…** on it.
4. To get rid of it, open it and press **Delete Survey Data…**.

**Switch it off**

Untick or delete the simulator in Settings → Inputs, make your real GPS the **Primary**, and press **Apply** before a real survey. While the simulator is the primary, its pretend positions go into the data like real ones.

### c. Set up your template

The lists, shortcuts and settings Spyhop records with are the **current template**. If your team shares a template, start with that:

- **Settings → Templates → Get a template from the web:** paste the address your team gave you and press **Check**. Spyhop shows what would change; **Pull it** makes it this computer's current template (a backup of the old one is kept).
- Or, for a template file you've been sent, put it in the templates folder (**Open the templates folder**), press **Refresh**, and press **Use this template…** on it.

To change the template yourself:

- **Settings → Dropdowns:** the Species, Events, Behaviors, Observers, Effort, Visibility, Weather and Reticles lists. Edit, add, reorder or remove entries, then press **Save**.
- **Settings → Shortcuts:** the keyboard shortcuts, including ones that start a sighting of a given species.
- **Settings → Rules:** your team's own checks, such as "every CTD cast has an ID" (see [Rules](#rules)).
- **Settings → General** and **Tools → Reports:** shared settings, the map display and saved reports, which are part of the template too.

The lists and rules can't be changed while a survey is under way (only the lists' colors), so set them up beforehand; every list has an **Other** entry for anything unexpected. When it's ready, **Settings → Templates → Save as a new template…** keeps it as one file to share with the team. See [Templates](#templates) for the details.

### d. Plan a route

1. Open **Tools → Routes**. Saved routes are at the top; design a new one under **Create New Route**.
2. Set the **survey speed**, and choose **Manual**, **Systematic — parallel legs** or **Systematic — sawtooth**:
   - **Manual:** set the **start point** (type it, **Pick on the map**, or **Use the vessel position now**), press **Add points on the map** and click each waypoint. Drag them to adjust.
   - **Systematic — parallel legs:** set the start, the direction of the first leg, the number of legs, leg length and spacing. Spyhop draws back-and-forth lines.
   - **Systematic — sawtooth:** set the start, the survey direction (the way the pattern advances), leg length, the angle between legs and the number of legs, one way or with a return back through it. Spyhop draws a zig-zag.
3. The tables show each leg's course, distance and time, the totals and the finish time.
4. Press **Activate route**. The waypoints lock, the route stays on the map from every tab, and clicking a waypoint shows its distance, bearing and ETA from the vessel.
5. **Save route** (at the bottom) keeps it in the routes folder. **Export GPX…** downloads a copy for a chart plotter.

### e. Start a survey

1. In **Survey**, press **Start New Survey…**.
2. Enter the survey name in your team's own convention (it becomes the start of the file names), and the survey details: platform name and type, altitude, organization and chief scientist. For a **stationary** platform (a shore station or tower), you can type its position instead of using a GPS.
3. Spyhop checks the GPS and the computer's clock, offering to set the clock to the GPS time if it's more than 2 s off. It then adds the **Start** row to the Effort table, starts the trackline and opens the Effort tab.

If Spyhop is closed or crashes during a survey, it reopens the survey the next time and asks whether to continue.

### f. Record data

- **Effort:**
  - choose the effort value (ON, TRANSECT, DIRECTED, PHOTO-ID, FOLLOW or OFF by default, from Settings → Dropdowns → Effort), or add a row with Ctrl/⌘+Shift+F, which toggles between on effort and OFF and copies the current conditions
  - fill in visibility, sea state, weather, glare and who is at Port, Recorder and Starboard
  - a countdown in the status bar reminds you to update the conditions
- **Sightings:**
  - press **Add row**, Ctrl/⌘+Shift+S, or a species shortcut; the time and vessel position fill in
  - type the species, number, bearing and distance; Spyhop works out the animals' position (SigLat/SigLon) and draws it
  - or right-click the map where the animals are
  - another look at the same animals is a **resight**: select the first sighting and press **Add resight** (Ctrl/⌘+Shift+L), so they're counted once
- **Events** (CTD casts, drones, tags, biopsies…): Ctrl/⌘+Shift+V, or right-click the map.
- **Editing:**
  - Enter or double-click edits a cell, and Tab moves on. Drop-downs filter as you type.
  - Each table has **Undo** and **Redo**.
  - Type `14:05` in a time cell to change only the time of day.
- **Instruments:** **Tools → Instruments** shows depth, wind, water temperature and so on, from every input. Click one to plot it.

### g. End the survey and check for errors

Open **Tools → Error check** and press **Run error check**. It lists **errors** (must fix: required fields left blank, values that aren't in the lists, impossible numbers), **warnings** (probably wrong: a sighting beyond the visibility, positions on land, GPS jumps) and **notes** (worth a look). Your team's [rules](#rules) are checked too. **Show** takes you to the row. A GPS jump or gap has a **Fix** button, which marks that stretch with an ERROR row in the Effort table: the trackline is broken there and the stretch counts as off effort.

Then, in **Survey**, press **End Survey…**. This adds the **End** row and stops the trackline. An ended survey can still be corrected, and deleting the End row makes it active again. **Close Survey…** puts a survey away without ending it.

### h. Summary, reports and export

- **Tools → Summary** (Ctrl/⌘+4): totals, survey details, species, observers, conditions and right whale sightings. **Save as HTML…** (with an interactive map) or **Save as PDF…**.
- **Tools → Reports** picks part of a table: choose the table, click the species or event types you want, pick the columns and any conditions, and **Export CSV…**, **HTML…** or **PDF…**. **Save report…** keeps it by name; **Run Reports…** saves all your saved reports at once. Reports are available once the survey has ended.
- **Survey → Export Data…** saves the separate CSV files, a merged time-ordered CSV with the conditions on every row, GPX, GeoJSON, the summary and your saved reports, in one zip.
- **Survey → Save Survey Package…** saves the whole survey as one file, to open on another computer with **Open Survey Package…**.

Your data are always on disk as plain CSV files in the survey's own folder (**Survey → Saved Surveys → Open Data Folder**), saved as you type, with a copy of the template the survey was started with.

### i. Keep Spyhop up to date

When Spyhop starts, it checks for a newer version (if there's internet) and asks before installing anything. You can also check any time in **Settings → About → Updates**. **Install** it and restart Spyhop when it asks. Your data and settings aren't touched, and the old version is kept as a backup. It's best to update between surveys, with internet.

## What's on screen

### The three panes

The **map** (top left), **Survey, Tools and Settings** (top right), and the **data tables** (Sightings, Effort and Events, across the full width at the bottom so their columns have room). A data table and a Survey/Tools/Settings page show at the same time (e.g. Sightings below, Tools → Summary above).

- **Resize:** drag the bar between the map and Survey/Tools/Settings, or the bar above the data tables (or click a bar and use the arrow keys; double-click it for the starting size).
- **Minimize** (▁ in a pane's header): the map or Survey/Tools/Settings shrinks to a thin strip at the side and the other takes the top (click the strip to bring it back); the data tables shrink to their tab bar (click a tab, or ▴, to bring them back; Ctrl/⌘+Shift+M toggles it). With both top panes minimized, the data tables get almost the whole window.
- **Maximize** (□): one pane fills the window; ❐ restores the three panes. Going to a tab in a hidden pane (e.g. with a shortcut) brings it back.
- **Reset the pane sizes** (Settings → General → Tables) goes back to the starting sizes; double-clicking a bar puts just that one back.
- The sizes and which panes are minimized are kept **on this computer** (like column widths), since they depend on the screen.
- **Bottom of the data pane:** a description of the selected column (e.g. what **Ref** means). Start, End, Close, Export and Delete are in **Survey** only, so they can't be clicked by accident.

### Status bar

- the time, with its zone (e.g. `14:31:05 EST`; choose the clock in Settings → General), and the position, with a warning if there is **NO GPS**, the **GPS is LOST** (no fix for 10 s), or the position is **NOT MOVING** (the GPS stopped updating while under way). A stationary survey with a station position shows **STATION**.
- speed, course and heading
- the **conditions-check countdown** (click it to open the Effort table; the interval is in Settings → General), which flashes when overdue
- the survey name, whether the trackline is being recorded (always while a survey is active), and the effort in force
- **Clock N s ahead of / behind the GPS**, only when the computer's clock is more than 2 s off (click it; see [Clock check](#clock-check))
- a red **GPS FALLBACK** banner across the top while a secondary input stands in for the primary (see [GPS and instruments](#gps-and-instruments))
- the Spyhop version (click it for Settings → About)

### Map

- **The vessel** (or aircraft, or station: its icon follows the platform type) with a heading vector (on/off and length in Settings → General → Map display).
  - **Smooth vessel movement** (Settings → General → Map display, on by default, this computer only): the vessel glides between GPS fixes instead of hopping once a second. Only the drawing is smoothed, so the icon can be up to about a second behind the latest fix; the data always use the real fixes. It jumps straight to the new position after a gap of more than 5 s or a jump of more than 300 m.
- **The trackline,** in the color of each Effort value (Settings → Dropdowns → Effort), thinner off effort. Set the on- and off-effort width and line style (solid, dashed, dotted, dash-dot), or hide either, in **Settings → General → Map display → Trackline**. The same section labels the survey **start** and **end** (both on by default), and can show the stretches flagged with GPS errors (see *Trackline breaks* below). Click the trackline for a track point's time, position, speed, course, effort and effort segment.
- **Trackline breaks:** the trackline on the map, in the HTML summary and in the Summary's distances is broken **only where the Effort table has an ERROR row**, so every break is in the data, for anyone to see. Nothing breaks it behind the scenes: a GPS jump or dropout is drawn as recorded until it's marked with the Error check's **Fix**. The flagged stretch is **hidden** unless **Show segments flagged with GPS errors** is ticked (Map display → Trackline); then it's drawn in the ERROR color, and clicking it gives a popup titled **Effort: ERROR** with its segment and notes.
- **Sighting, event and waypoint markers**, each with a label and a popup.
  - Default marker shapes and colors for sightings and events are in Settings → General → Map display; species and event-type colors from your lists take priority. Waypoints have their own shape and color on each row.
  - **Labels:** sightings show the species code plus the FieldID if there is one, e.g. `RIWH Eg-3720` (or the SigNo if there's no species yet); events show their event code and ID, e.g. `CTD C-07` (or E1, E2… if both are blank).
  - **Popups** show the essentials: for sightings the time, the animals' position, the species and the number (with calves); for events the time, position, event and ID; for all, the current distance and bearing from the vessel (kept up to date while the popup is open) and a link to the row in its table.
  - **Resights** are drawn smaller and as outlines by default (change their look in **Settings → General → Resights**).
- **Lines:** dashed lines from the vessel to each sighting (on by default), optionally a dotted line joining sightings with the same FieldID from oldest to newest, and a dotted line from each sighting through its resights. Each can be shown or hidden, with its own width and line style, in **Settings → General → Map display → Lines and vectors**.
- **Fading** (Map display): the trackline, sightings and events older than a number of **minutes** (30 by default) are dimmed; waypoints never fade.
- **Move the map to a sighting, event or waypoint selected in its table** (Map display, on by default).
- **Distances** on the map (the measuring tool, popups, routes and the Summary) are in the **Map distance unit** (Settings → General → Bearings, distances and time: nm, km, m, mi or yd), separate from the default distance **Unit** of new sightings.
- **Toolbar buttons:**
  - ⌖ follow the vessel
  - 📏 measure: click to add points, double-click or Esc to finish, click again to clear. Each leg shows the true and magnetic bearing and the distance, and the total.
  - ◎ range rings
  - ⤢ zoom to the whole survey. When Spyhop starts with a survey open, the map starts zoomed to the whole survey, with following off (⌖ turns it back on).
- **Layers menu** (top right): **Layers** (the **Platform icon**, **Effort** (the on-effort track), **Track** (the off-effort track), sightings, **resights** (their markers and the lines to and through them; the first sightings stay when it's off), events, waypoints, routes, imported overlays, range rings, a **graticule** (a lat/lon grid that adapts to the zoom), and each **other** GPS source in use) and **Online overlays** (AIS, weather radar, map feeds).
- **Right-click menu:** add a sighting, event or waypoint at that point; measure from here; copy the position.
- **Readout (bottom left):** the cursor position, its bearing and distance from the vessel, the depth at the cursor on the Seascape map, and a scale.
- **Map credits (ⓘ, bottom right):** click or tap it to see who made the map tiles; click it again, or the map, to fold them away.

### Tabs

- **Sightings**, **Effort** and **Events** in the data pane. Each has **Add row**, **Insert row…**, **Delete row**, **Undo**, **Redo** and **Columns…**. With no survey open, Spyhop opens on **Survey**.
- **Survey:** start, end, close and delete surveys; export data; save and open survey packages; the survey details and notes; the survey's template; and **Saved Surveys**, the surveys in the data folder.
- **Tools:**
  - **Waypoints:** the waypoints table.
  - **Overlays:** offline overlays (imported files and past surveys) and online overlays (AIS, weather radar, map feeds).
  - **Routes:** saved routes and the route being designed or activated.
  - **Instruments:** instrument readings (click one to plot it) and the raw NMEA log.
  - **Resights:** swim speeds and dive times of animals with resights.
  - **Error check**, **Summary** and **Reports**.
- **Settings:**
  - **General:** **Data collection** first (the settings that change what's recorded: the track point interval, a point every second by default, and the magnetic variation, greyed out with a yellow note while a survey is active; and the clock check), then reminders and sleep, bearings, distances and time, altitude and reticles, tables, resights, text size and the map display.
  - **Basemap:** the map tiles, downloading areas for offline use, and the charts folder.
  - **Inputs:** the GPS / NMEA inputs, and how "other" inputs are drawn.
  - **Shortcuts** and **Dropdowns:** the keyboard shortcuts and the drop-down lists of the current template.
  - **Rules:** your team's own checks, run by the Error check (see [Rules](#rules)).
  - **Templates:** using, saving and sharing templates.
  - **Sharing:** let phones, tablets or other screens on the network watch, view only (see [Sharing with other devices](#sharing-with-other-devices)).
  - **Guide:** this guide, with its contents beside it (above it in a narrow pane).
  - **About:** the version, the changelog, links to Spyhop's folders, the diagnostic logs (**Save diagnostics…**), updates, and uninstall or reinstall.
- Clicking **Tools** or **Settings** returns to the one of its tabs you used last.
- **?** buttons beside the headings in Survey, Tools and Settings hold the explanations: hover over one to read it, or click it to keep it open (click again, press Esc or click elsewhere to close it).

## Entering data

### Working in the tables

The tables work like a spreadsheet:

- Click a cell and start typing, or press Enter/F2 to edit. Enter saves, Tab saves and moves right, and Esc cancels. The arrow keys move between cells.
- **Drop-down cells** filter as you type and also match codes (`huwh` finds Humpback whale).
- **Multi-select cells** (Behaviors) open a checklist: ↑/↓ move, Space ticks, a letter jumps to it (again for the next one), Enter saves. The highlighted behavior's definition is shown underneath.
- **Map** checkboxes toggle with a click or the Space bar.
- **Lat/Lon** are accepted in almost any form: `41 30.5 N`, `41°30'30"N`, `41.508`, `4130.5N`. If you leave off N/S/E/W, Spyhop uses the vessel's hemisphere, so `70 20.5` near Cape Cod means 70°20.5′W. Choose DDM, DD or DMS display in **Settings → General → Lat/lon format**; every table updates at once. Files always store decimal degrees.
- **Times** are shown in the survey clock (Settings → General → Clock), with the zone in each cell (e.g. `15:52:22 EST`). Type `14:05` to change only the time of day. The files always store each time with its UTC offset, so switching the clock never changes data. The clock can be:
  - **From the platform's position:** the time zone at the GPS position, from an offline map, daylight saving included. At sea, the nearest coast's zone within 150 nm (so a survey off Cape Cod keeps Eastern time), and the nautical zone further out. Settings shows which zone was found and how; it's checked again every 5 nm.
  - **This computer's time zone**, **UTC**, or **any fixed UTC offset** (UTC−12:00 … UTC+14:00, including half and quarter hours).
- Every edit is saved to disk immediately. Undo/redo is unlimited per table.

### Sightings

- New rows get the time, vessel position and the next **SigNo** (the CSV column is SightNo). **FieldID** is free text for your own ID (photo-ID, catalog number…); it becomes the sighting's map label, and the cursor skips it on a new row so you go straight to Species. **Calves** takes a number, or **NA** where calves don't apply (dead birds, fishing gear, vessels…).
- Enter **Bearing** and **Distance**, and the animals' position (**SigLat/SigLon**) is worked out. Bearings can be negative and count back from 360 (−10 is stored as 350), which is handy for relative bearings to port. Without a bearing and distance, SigLat/SigLon are the vessel position. A position picked on the map gets its bearing and distance worked out backwards.
- Each row stores its own bearing reference (**Ref**: M magnetic, T true, R relative to the bow, **C clock**) and distance **Unit**, so changing the defaults in Settings never changes old rows. The vessel heading is saved in the CSV (`VesHdg`, not shown) so relative bearings can be converted. Magnetic bearings use the World Magnetic Model.
- **Clock bearings (Ref C):** the Bearing cell offers 1 to 12 o'clock. Each hour is 30° from the bow: 12 dead ahead, 3 the starboard beam, 6 astern, 9 the port beam. Choose C as the **Default bearing reference** in Settings → General to have it on every new sighting.
- **Reticle distances** (Settings → Dropdowns → Reticles): each entry of the reticles list is a **Unit**, `reticles-<name>` (e.g. `reticles-binos`), offered in the Unit column and as the default distance unit. With one, Dist is a reading, and Spyhop works out the distance from it and the sighting's **Alt** (filled in from the **Default observer altitude**, Settings → General → Altitude and reticles; edit it if the height was different), allowing for the curvature of the earth (Lerczak & Hobbs 1998). A reading at or above the horizon gives no distance. Each entry has a **name** (letters, digits, `-`, `_` and `.`; no spaces) and a method:
  - **Binocular reticles:** the number of divisions counted down from the horizon to the animals. Choose the **magnification**, which suggests the angle of one division, and correct **Degrees per division** for your binoculars. Many 7× and 10× marine binoculars have a 10-mil scale (0.573°); Fujinon 25×150 big-eyes are 0.0771° (Kinzey & Gerrodette 2001).
  - **Calibrated marks:** evenly spaced marks (e.g. on an aircraft's window or wing strut), counted down from the horizontal (mark 0). **Degrees per division** is the angle from one mark to the next; type the mark number (it can be a fraction, e.g. 2.5) in Dist.
  - **Inclinometer degrees:** the angle below the horizontal, in degrees (90° is straight down).
  - The default list has `binos` (7×, 0.573°), `big-eyes` (25×, 0.0771°) and `incl` (inclinometer). Several can be used in one survey, and each sighting records which.
- **Default observer altitude (ft)** (Settings → General → Altitude and reticles): the observers' eye height above the water on a ship or station, or the usual survey altitude for an aircraft. It fills in each new sighting's Alt, which turns reticle readings into distances. It's a shared setting, so it travels with the template.
- **The Alt column** (Settings → General → Altitude and reticles): *Automatic* shows it for aerial surveys and hides it for shipboard and stationary ones; it can also be always shown or hidden. It is always kept in the file.

### Resights

A resight is another sighting of animals already recorded: closing in for photos, a focal follow.

- Select the sighting and press **Add resight** (Ctrl/⌘+Shift+L). The new row gets the time and position as usual, **ResNo** (right after Calves; the CSV column is ResightOf) holds the first sighting's SigNo, and the species, Num, Calves, NumConf, IDrel and FieldID are copied, ready to correct. A resight of a resight is linked to the first sighting. You can also type a SigNo in **ResNo** to link rows afterwards, or clear it to unlink one.
- Resights aren't counted again in the Summary or in reports, and the Error check doesn't list them as off-effort sightings or their observer as off watch.
- **Resights** in the map's layers menu switches the resights on the map on or off.
- **Settings → General → Resights:** list the Sightings table in time order or with each sighting's **resights nested** under it; the resight markers' shape (or hidden), fill, size and labels.
- **Tools → Resights** lists each sighting that has resights: its FieldID, the number of resights, the time span, the distance along the resights, the **average swim speed**, the **net speed** (first sighting to last resight in a straight line), and the **dive times** (from a resight with a dive behavior, e.g. Fluke-up dive, to the next resight with First surfacing; choose the behaviors there). **Resights…** shows each interval and dive; **Save as CSV…** saves them all. Speeds use SigLat/SigLon worked out from bearings and distances, so distance errors show up as speed, most of all over short intervals.
- In the merged CSV, keep the rows where **ResightOf** is blank for first detections only (e.g. for encounter rates or detection distances).

### Effort

- The Effort column's values come from the **effort list** (Settings → Dropdowns → Effort). Each entry has a **name**, a **status** (on or off effort), a **definition** (shown in the drop-down) and a **color** (the track's color while that value is in force). The default list has **ON** (observers on watch), **TRANSECT** (a systematic line-transect survey), **DIRECTED** (a directed survey or activity), **PHOTO-ID** and **FOLLOW** (a focal follow), all on effort, and **OFF**. The status decides what counts as on effort on the track, in the Summary (which also gives the time in each on-effort value), in reports and in the Error check. **Start**, **End** and **ERROR** are always in the list and always off effort.
- The first row is always **Start** (added when the survey starts; it can't be changed or deleted), and **End** can only be the last row.
- A new row copies everything from the previous row except the notes. Right after the Start row, Effort is left blank for you to choose. The Toggle effort shortcut (Ctrl/⌘+Shift+F) goes OFF, then back on as the last on-effort value you were on.
- **Seg** (effort segment) is numbered by Spyhop: each Effort row whose status differs from the row before starts a new segment (e.g. TRANSECT, TRANSECT with new conditions, OFF, TRANSECT → 2, 2, 3, 4 after the Start row's 1). It's renumbered after every change and carried onto sightings and events in the merged CSV. Hide it in **Settings → General → Tables**.
- **Gstart**, **Gend** and **Gref** say where the glare is: from one bearing clockwise to the other, in the reference given (M, T, R, or C for clock bearings). When **Glare** is **None**, Gstart and Gend are **NA** (filled in by Spyhop); for any other glare they must be real bearings. **Gref** is **M** unless you change it.
- **Vis** and **Weather** come from their lists in Settings → Dropdowns. The Error check reads distances from the Vis names (e.g. `1-2 nm` is at most 2 nm).
- In the track CSV, points are labeled with the Effort value in force (Start, TRANSECT, OFF, End…).

### Events and waypoints

- **Events:** the default list has CTD casts, drifters, drones, tags, biopsies, moorings, plankton tows and **Other**. Vessels, marine debris and fishing gear are recorded as Sightings (they're at the end of the default species list). **ID** is free text for an instrument or sample ID (CTD cast number, tag ID…). Each event type has a short code (e.g. `CTD`); type the code to pick the event, and the map label shows code + ID.
- **Waypoints** (Tools → Waypoints): each has its own **Shape** (Circle, Diamond, Square, Triangle, Star) and **Color** (pick from the list or type a `#hex` code). Waypoints belong to no survey and are kept across surveys.

### Insert row, columns and row colors

- **Insert row…** (every data tab): select a row, then choose whether the new row goes **after** or **before** it, and how its time and position are filled in: the **average** of the rows either side, **copied** from the row before or after, or **Use this time and the nearest vessel position** (type a time, e.g. `14:05`: the row goes in time order and its position is the vessel's at that time from the trackline). Its Notes say how. You can insert rows into an ended survey to fill a gap; nothing can go before the Start row or after the End row.
- **Columns:** drag a column's header to move it, or use **Columns…**: the columns as chips; click to select one or more (Shift+click for a range) and drag them together to a new place, or move them with ← / →; **Save**, or **Reset** to the standard order. Drag the right edge of a header to change its width (double-click it for the default).
  - **Hiding columns:** in **Columns…**, select columns and press **Hide** (greyed there; **Show** puts selected ones back) to save screen space. Hidden columns are only left out of the table on screen: they're still recorded, in the files and in every export. While any are hidden, a **Show hidden columns** button next to Columns… brings them all back.
  - The order, widths and hidden columns are kept on this computer only; **Settings → General → Tables** resets them all.
- **Sightings row colors** (Settings → General → Tables): **None**, **Alternating**, **Highlight resights** (the default) or **Group resights** (each sighting and its resights in a color of their own).

### Keyboard shortcuts

| Keys (⌘ on a Mac) | Action |
|---|---|
| Ctrl+Enter | Add a row to the data table in view (Sightings, Effort or Events), even from Survey, Tools or Settings (also while typing in a cell; that edit is saved first) |
| Ctrl+Shift+S / E / V / K | Add a sighting / conditions row / event / waypoint |
| Ctrl+Shift+F | Add an effort row that switches effort ON↔OFF |
| Ctrl+Shift+R, Ctrl+Shift+H | Add a sighting pre-filled with North Atlantic right whale / Humpback whale |
| Ctrl+Shift+L | Add a resight of the selected sighting |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo in the table you're in (while typing in a box they undo the typing, as usual) |
| Ctrl+1 … 5 | Sightings, Effort, Events, Tools → Summary, Settings → General |
| Ctrl+PageUp/PageDown, Alt+←/→ | Previous/next tab |
| Ctrl+Shift+C | Center on the vessel |
| Ctrl+Shift+M | Minimize / restore the data tables |

**Mod** in Settings → Shortcuts is ⌘ (Command) on a Mac and Ctrl on Windows and Linux, so one template works on both. On a Mac the Control key isn't used for shortcuts.

These are the defaults; the shortcuts are part of the template. To change them, see [Editing the shortcuts](#editing-the-shortcuts).

## GPS and instruments

### Setting up inputs

Inputs are set up in **Settings → Inputs** (GPS / NMEA inputs).

- **Name each input** for its device, e.g. *Tablet GPS*, *External GPS*, *Ship's network*. Serial, UDP, TCP and gpsd inputs travel in the template with their names, so one template can list the inputs of every computer a team uses.
- **In use:** tick the inputs this computer runs. Which are in use, and their roles, are this computer's choice and are kept (by name) when a template is used; an input new to the computer comes in unticked.
- **Role:**
  - **Primary** (one): the platform's position, course, speed and heading for the survey: the track, the position of new rows, the vessel on the map.
  - **Secondary:** another of the platform's own inputs (a backup GPS, the depth sounder, the ship's network). Its readings appear in Tools → Instruments where the primary has none. It can stand in for the primary (below).
  - **Other:** something that isn't the platform at all: a drone, a drifting buoy, a second vessel. (An external GPS device on the platform itself, such as a USB puck, is a primary or secondary, not "other".) It's never used for the platform's position or readings.
- **Kind and connection:** what each input is and how it's reached (serial port and baud, UDP port, host and port, file, simulator settings). Changes take effect when you press **Apply**.
- **Mapping ‘Other’ inputs** (below the inputs): a row for each input in use that isn't the primary. Changes here are saved at once, without Apply:
  - **Show on the map:** a secondary is drawn as a purple point with its name; an other source is on the map unless unticked.
  - For an other source: its **Icon** (circle, square, triangle, diamond, star, a vessel, aircraft or drone that turns with its heading, or a tower), **Color**, **Line**, **Width**, **Trail** (the whole survey, the last 10 min to 3 hours, or none) and **Show name**. Each has its own entry in the map's layers menu, *<name> (other)*, drawn below the survey's own track and markers. **Click its icon** for its name, position, speed, heading, bearing and distance from the platform, and when it was last updated. If its GPS is lost (no position for 15 s), a red ✕ is drawn over its icon.
  - **Record track** (on unless unticked): while a survey is active, every fix is saved in the survey folder as `<survey>_<name>_gps.gpx`. With no survey open, a warning says the track is drawn but not saved.
- **Start New Survey** warns when there's no GPS position (no input in use, or nothing from the primary), with a link here. *Start anyway* starts the survey regardless. A stationary survey with a station position doesn't need a GPS (see [Survey details and platform types](#survey-details-and-platform-types)).
- **Fall back to a secondary** (off unless ticked): if the primary sends no position for 5 s, the position is taken from the first secondary with one (never an other source) until the primary is back, with a red **GPS FALLBACK** banner across the top of the window.

### Input kinds

| Input | Use it for |
|---|---|
| **Serial** | A USB GPS puck or an NMEA 0183 serial adapter. The port box lists the ports it finds. GPS pucks are usually 4800 or 9600 baud. |
| **UDP** (default: port 10110) | NMEA broadcast on the boat network by a multiplexer, plotter or OpenCPN. In OpenCPN, add a *Network → UDP → output* connection to 127.0.0.1:10110. |
| **TCP** | NMEA servers (multiplexers, Signal K's NMEA 0183 TCP stream on port 10110). |
| **GPSD** | Linux gpsd. |
| **File** | Replays an NMEA log in real time (or faster, with *Speed ×*). Spyhop's own raw logs are replayed at the pace they were recorded; plain NMEA files at the pace of their RMC/GGA times. Make it the primary to replay a survey's track. |
| **Simulator** | Practice and testing (see the [Quick start](#b-try-it-with-the-simulator)). |

Spyhop reads RMC, GGA, GLL and VTG for position, speed and course, and HDT, THS, HDG and HDM for heading. For the Instruments panel it also reads VHW and VBW (speed through water), DPT, DBT, DBS and DBK (depth), MWV, VWR, VWT and MWD (wind), MTW, MTA, MHU, MMB and MDA (weather), RPM (engines), ROT, RSA, and XDR transducers. The raw NMEA monitor at the bottom of Settings → Inputs shows exactly what is arriving.

### Instruments and NMEA logs

**Tools → Instruments** shows what comes in:

- **Instruments:** the latest reading of everything coming in, grouped as Navigation, Depth, Wind, Weather, Engine and Other transducers. Each tile shows the sentence and input it came from and how old it is, and turns gray after 15 seconds without an update.
- **Plots:** click any numeric reading to plot it since the start of the survey, with now/min/max/mean. While a survey is active, Spyhop saves every numeric reading of every input in use every 5 seconds in `<survey>_nmea.csv` (with the input's name and role), so the history survives a restart.
- **Raw NMEA log:** tick **Record raw NMEA to a file** to save every sentence from every input as it arrives, each line starting with the UTC time and the input name (untick that for plain NMEA). Logs go in the survey's `nmea_logs/` folder. A log can be played back as a **File** input.

## Surveys

### Starting a survey

**Start New Survey…** (in Survey) asks for a name and the survey details, then checks the GPS and the [clock](#clock-check), then adds the **Start** row to the Effort tab. The trackline starts recording.

- The name is used exactly as typed (only characters that file systems forbid, such as `/ : * ?`, become `_`), so use your team's own convention, e.g. `NEAQ_CCB_2026-11-04_A`. A name that's already in use is refused rather than changed.
- If another survey is still active, you're asked whether to **End** it or just **Close** it (keeping it active) first.
- If the current template has changed since it was last saved, Spyhop offers to save it first, and the survey records which template and Spyhop version it was started with. A copy of the current template is kept with the survey.

### Survey details and platform types

The details are **platform name** (vessel, aircraft or station), **platform type**, **organization**, **chief scientist** and **chief scientist email**. They're filled in from your last survey and can be changed any time in Survey.

- **Platform type** sets the map marker and how the trackline is kept:
  - **Shipboard:** a ship, turned to the heading.
  - **Aerial:** an aircraft, turned to the heading. The Sightings **Alt** column is shown.
  - **Stationary:** a tower. The platform doesn't move, so only the Start and End positions are recorded, with no trackline in between. The status bar says *Stationary (no trackline)*.
    - **Station latitude / longitude** (shown only for Stationary): the station's position, in any lat/lon format (e.g. `41 54.05 N`, `070 19.80 W`). When both are given, that position is the platform position for the whole survey (every row, the map), the status bar says **STATION**, and no GPS is needed: Start New Survey doesn't ask for a GPS fix or check the clock. Give both or neither; leave them blank to use the GPS. They can be corrected during the survey (new records use the new position).
  - **Other:** a dot. The trackline is recorded.
- The observers' height above the water is **Default observer altitude (ft)** in Settings → General → Altitude and reticles (see [Sightings](#sightings)).
- **Survey notes** (below the details): general notes or a summary of the survey, as many lines as you like. They're shown in the Summary and its HTML and PDF files.
- The details are saved with the survey as `<survey>_metadata.csv` and included in exports and the summary.

### Clock check

Every time in Spyhop comes from the computer's clock, so Spyhop compares it with the GPS time (from the RMC sentences, accurate to about a second).

- If they differ by more than **2 s**, the status bar shows **Clock N s ahead of / behind the GPS** (click it), and Start New Survey asks you to **Sync the clock, then start** (or **Start anyway**, or **Cancel**).
- **Sync** sets the computer's clock to the GPS time. It needs administrator rights, so the computer asks for your password (macOS, Linux) or for permission (Windows).
- Syncing is only possible **between surveys**, so times within a survey never jump.
- The check is also in **Settings → General → Data collection** (**Check / sync the clock…**).
- Each survey's details record the difference when it started (`clock_offset_at_start`, GPS minus computer, in seconds).

### Ending, closing and opening

- **End Survey…** adds an **End** row and stops the trackline. An ended survey can still be corrected, but no new rows can be added. To carry on, delete its End row in the Effort tab (or Undo).
- **Close Survey…** clears the tabs. Everything is already saved as you go. A closed survey that hasn't ended stays *active*, so you can continue it later.
- **Saved Surveys** lists every survey with its status (Active/Ended), start and end times and number of sightings, with **Open Data Folder**, **Open Survey Package…** and **Refresh** (reads the folder again, e.g. after copying surveys into it). Press **Open** to open one. An active survey records its trackline whenever it's open, so there's nothing to switch on or off.
- **Delete Survey Data…** is the only thing that deletes data. It needs two confirmations, the second by typing the survey name, and closes the survey.

### Keeping the computer awake and crash recovery

- **Keeping the computer awake** (Settings → General → Reminders and sleep): a computer that goes to sleep stops recording the trackline and NMEA data, so by default Spyhop stops it sleeping **during a survey**. Choose **Always** to keep it awake whenever Spyhop is open, or **Never** to leave sleep to the computer's own settings. Tick **Keep the screen on too** to stop the screen turning off as well. Closing a laptop's lid still puts most laptops to sleep.
- **Crash recovery:** if Spyhop is closed or crashes while a survey is active, it reopens that survey on the next start and asks whether to continue.

## Sharing with other devices

Phones, tablets or a screen on the bridge or in the galley can follow the survey live, **view only**: the map, the tables, the Summary, Reports, the instruments, resights, the Error check and this guide. Only the laptop running Spyhop enters or changes data and settings.

1. On the laptop, open **Settings → Sharing** and tick **Let other devices on this network watch**.
2. On the other device, join the same network (Wi-Fi or cable) and scan the QR code shown there, or type the address under it (for example `http://192.168.1.20:8766`).

Settings → Sharing lists who is watching (the Survey tab shows how many). **Disconnect all viewers** closes their connections.

- **A PIN** (optional, 4–12 letters or digits): viewers type it once on each device. Leave it blank to let anyone on the network watch. Changing the PIN, or Disconnect all viewers, asks every viewer for it again. A wrong PIN is refused, and each wrong try makes the next one wait longer.
- **What viewers see:** everything but the laptop's folders, its GPS / NMEA inputs and the details remembered from earlier surveys. The survey details shown in the Summary are included. Viewers see the settings tabs, but nothing there can be changed except how Spyhop looks in that browser: text size, the map display, columns, lat/lon format, clock. **Use the laptop's settings again** (in their Settings → General) undoes those. Each viewer also keeps its own tab, map view and Follow vessel choice.
- **Online overlays** (AIS, weather radar, map feeds) aren't offered to viewers, and a viewer's map uses only the map tiles already on the laptop (viewed before, downloaded areas and offline charts), so viewers never make the laptop use the internet.
- **If the laptop goes away** (asleep, Spyhop closed, out of range), viewers show **Lost connection to the laptop running Spyhop — retrying…** and pick up again by themselves when it's back.
- **The firewall:** the first time sharing is switched on, the computer may ask whether Python may accept incoming connections. Allow it. On Windows, allow it on **private networks**, and set the vessel's network to Private.
- **Can't connect?** Both devices must be on the same network. Many guest, hotel and some ship Wi-Fi networks keep devices apart ("client isolation"); a small travel router on board avoids that. The laptop's address can change from one trip to the next: scan the code again.
- **Keep the laptop awake** while others are watching: Settings → General → Keep the computer awake (during a survey, by default). A sleeping laptop stops sharing.
- On a phone, the panes are small: maximize one (□ on its heading) to use it full-screen. Tables scroll sideways, the map pans and pinch-zooms, and markers open their popup with a tap.

## Error check

**Tools → Error check:** press **Run error check** before you finish a survey (or any time). It lists problems as **errors** (must fix), **warnings** (probably wrong) and **notes** (worth a look). **Show** takes you to the row and column in the data table (the row flashes). It doesn't change anything, except when you press a **Fix** button. **Save report…** downloads the list as a CSV.

The counts of the last check (errors, warnings, notes) show at the right of the data tables' header, next to the Sightings, Effort and Events tabs; click them to open the Error check. A dot means the data has changed since. **What is checked** lists every check, with a link to your rules (Settings → Rules).

**Check automatically** runs the check quietly every 1, 2, 5, 10, 15 or 30 minutes while a survey is active (off by default). The counts next to the data tabs, the highlights in the tables are kept up to date, and a message pops up when a check finds more errors or warnings than the one before. It's a shared setting, so it travels with the template.

**Highlight in the tables** (next to the Show filter) colors each cell with a problem in the Sightings, Effort and Events tables, in the color of its level (red for errors, amber for warnings, blue for notes), for the levels ticked in Show. A problem with a whole row colors the row number; hover over a cell to read its problems. The colors are from the last check: run it again after fixing things. It's remembered on this computer.

It checks:

- **Survey details:** every field filled in (the station position and altitude only when needed), and a valid email.
- **Required fields:** Sightings: everything except Behaviors, Bearing, Ref, Dist, Unit, Alt, ResNo, FieldID and Notes. Effort: everything except Notes (Start and End rows need only the time and position). Events: everything except ID and Notes.
- **Valid values:** choices are in their lists; numbers, positions and times can be read; no time is in the future; nothing is before Start or after End; rows are in time order; no SigNo or EventNo is used twice; the survey starts with Start and has an End.
- **Plausible values:** Num a whole number of at least 1 (flagged over 500); Calves a whole number (or NA), with a warning when every animal is a calf; Bearing 0–360° and Dist not negative, given together and with their Ref and Unit; relative bearings have a heading; animals within 10 nm of the vessel and no further than the visibility; vessel positions within 0.5 nm of the trackline; positions not on land (by the bundled coastline, ignoring the first 0.5 km); glare bearings given when there's glare.
- **Trackline:** a jump faster than **50 kn** (shipboard, and when the platform type isn't set), **30 kn** (stationary) or **200 kn** (aerial and other), or a gap with no position for over **120 s** (or 3 track intervals, if longer). The limits are fixed, so every check of every survey uses the same ones. Each jump or gap has a **Fix** button that adds an **ERROR** row to the Effort table one second after the last good track point, plus a row at its end that puts the effort and conditions back. The trackline is broken there (see *Trackline breaks* in [Map](#map)), and ERROR counts as off effort.
- **Resights:** each ResNo names an existing earlier sighting of the same species; a **warning** when the animals would have swum faster than **30 kn** from one sighting to the next.
- **Other placeholders:** every row that uses **Other** from a list, to fill in after the survey.
- **Protocol:** a new Effort row at least every 1.5 × the reminder interval while on effort; nobody in two watch positions at once; the sighting's observer is on watch; a sighting entered twice or a duplicated event. Notes list sightings off effort, effort in sea state above 5 or visibility under 0.5 nm, and observers on watch over 2 hours without a break.
- **Rules:** each row that breaks one of your team's [rules](#rules), at the rule's level and with its message. A note says when a rule names a value that's no longer in its list.

### Rules

**Settings → Rules** holds your team's own checks of the values in one row of **Sightings**, **Effort** or **Events**. Each rule reads as a sentence: *if* every "if" condition is true, *then* every "then" condition must be true too. For example:

| Table | If | Then |
|---|---|---|
| Events | Event is CTD cast | ID isn't blank |
| Effort | Weather is Fog | Glare is not Severe |
| Sightings | Behaviors includes Mom/calf | Calves > 0 |
| Sightings | Species is Unid. large whale | IDrel is Definite |
| Sightings | Calves ≥ 0 | Num ≥ [Calves] |

The last one is the rule Spyhop starts with: there can't be more calves than animals.

- **Add a Sightings / Effort / Events rule**, then for each condition choose a column, a test and a value. The tests depend on the column: **is**, **is not**, **is one of**, **contains** and their opposites for text and choices; **includes** and **doesn't include** for Behaviors; **=**, **≠**, **>**, **≥**, **<** and **≤** for numbers; and **is blank** / **isn't blank** for any column. The value box offers the column's list entries.
- **A value in [brackets] is another column of the same row**, e.g. Num ≥ [Calves]. For **is one of**, separate the values with `|` (`Fog | Rain`).
- **+ and** adds a condition. A rule with no "if" conditions applies to every row.
- **A condition on a blank cell is false**, except **is blank**. So a rule doesn't apply to a row whose "if" cell is blank, and a "then" condition fails on a blank cell. Number tests are false unless both sides are numbers (NA isn't one; use **is NA**).
- **Level:** whether a broken rule is an error, a warning or a note. **Message:** what the Error check says (blank: the rule itself). **On:** untick to keep a rule without checking it. For Sightings, **Resights** says whether resights are checked too.
- **Test on this survey** lists the rows of the open survey that break the rule as it is on screen, saved or not; click one to go to it. It works during a survey too.
- **Save** keeps the rules; Spyhop says what's wrong and saves nothing until it's fixed. **Revert** discards unsaved changes.
- The rules are in the template (`rules.csv`, in its data part), so every computer using it checks the same way, and **they can't change during a survey**. For many changes at once, edit `rules.csv` like the lists, and press **Reload from the file**.

## Summary

**Tools → Summary** (Ctrl/⌘+4) shows:

- the summary numbers (sightings, number of animals, species, time on effort, on-effort and track distances, events), then the survey's start and end times, duration, details and notes
- the time spent in each on-effort value
- counts by species (sightings, number, calves) and by event type. Resights aren't counted again: each sighting counts once, with the largest number and calves seen on it or any of its resights.
- **North Atlantic right whale sightings:** each one, with time, position, number, calves, field ID and notes
- **observers on watch:** the time each observer spent at Port, Recorder and Stbd while on effort, and their total
- the range of environmental conditions (visibility, sea state, weather, glare) for the whole survey and on effort only
- While on effort, *Time on effort*, the distances and the watch times count up live (marked ●).

**Save as HTML…** saves the summary as **one HTML file**, with an interactive map of the survey (track, sightings and events, with popups) at the top. It opens in any browser, even offline, so it's easy to email or share. **Save as PDF…** saves the same summary as a PDF, with a map made for paper: zoomed to the survey, on the **Esri Ocean** basemap when there's internet (the offline coastline otherwise), and a **legend** of the point symbols. PDFs need Google Chrome or Microsoft Edge. A copy of each goes in the survey's `exports` folder.

## Reports

**Tools → Reports:** a report is a chosen part of one table: some rows, some columns. It updates as you change it, and can be saved as CSV, HTML or PDF.

**Reports are ready when the survey ends.** During a survey the Reports tab is locked: reports can't be run, saved, changed or deleted. Saved reports are part of the template, like the drop-down lists, so every computer reports a survey the same way.

- **Table:** Sightings, Events or Effort. Sightings reports leave out resights: each group of animals appears once, as its first sighting.
- **Species** (Sightings) or **Event types** (Events): the codes in this survey, with how many rows each has. Click one or more to keep only those; none picked keeps all. **Add a species…** finds any entry in the list.
- **Columns:** tick the columns to show; **▲ ▼** set their order. Besides the table's own columns there are **Time**, **Time (formatted)** (`2026-11-07 10:54 EST`), **Date**, **Clock time**, **Position**, **Latitude**, **Longitude** (in the lat/lon format of Settings → General; for sightings the animals' position) and the **Species code** or **Event code**.
- **More conditions:** **On effort only**, a **time range**, and any number of conditions on a column: *is*, *is not*, *contains*, *doesn't contain*, *is blank*, *isn't blank*, *is more than*, *is less than*. All must hold.
- The result is in time order, with a **total** under number columns (Num, Calves). Click a row to show it in its table.
- **Export CSV…**, **HTML…** and **PDF…** save the report in the `exports` folder and download a copy. The HTML and PDF pages have the survey name, dates, platform, organization and chief scientist, then the table and its totals.
- **Saved reports:** **Save report…** keeps the current report by name. A saved report that you change is marked • until you **Save changes** (or **Undo changes**); **Save as new…**, **Rename…** and **Delete…** do what they say. Spyhop starts you off with **Right whales**, **Blue whales**, **Dead birds** and **Gear**.
- **Run Reports…** saves several saved reports at once: tick the reports, the formats and where to save them. Each saved report is also offered in **Export Data…**, as a CSV.

## Planning routes

**Tools → Routes.** **Saved Routes** (top of the tab) lists the routes in the `routes` folder in Spyhop's folder, one GPX file each, with its mode, waypoints, length and when it was saved:

- **Show** puts a route on the map on every tab, in its own color (**Routes** in the map's layers menu switches all routes on or off). Click a waypoint for its position and distance from the vessel. **Show all** / **Hide all**.
- **Open** loads a route into the editor below, to change it or activate it (Spyhop asks first if the route you're editing has unsaved changes). **Close** puts it away. **Zoom to** and **Delete** (after asking).
- **New route** starts an empty one; **Import GPX…** loads a GPX file; **Open the routes folder**; **Refresh** picks up GPX files copied into the folder. A GPX file that wasn't made by Spyhop opens as a manual route.

**Create New Route:** the current route is drawn on the map with numbered waypoints and kept between sessions. While it's a **draft** it shows only while the Routes tab is open; once **activated** it stays on the map from every tab.

- **Survey speed** (kn) sets the times.
- **Start point:** type its latitude and longitude, press **Pick on the map** and click, or press **Use the vessel position now**. Switching between modes keeps it.
- **Manual:** set the start point, then press **Add points on the map** and click where each further waypoint should go. Drag a waypoint to move it; **Undo last point** or ✕ in the waypoint list takes points off.
- **Systematic — parallel legs** ("lawnmower"): the **survey direction** (the bearing of leg 1), the **number of legs**, the **leg length** and **leg spacing** (nm), and which side the next leg goes to. Drag waypoint 1 to move the whole pattern.
- **Systematic — sawtooth** (zig-zag, no crossings): the **survey direction** (the way the whole pattern advances), the **leg length**, the **angle between legs**, whether the first leg goes to starboard or port, the **number of legs**, and **One way** or **Return** (a crossover leg at the far end onto a reciprocal sawtooth that comes back through the outbound one).
- **Activate route** locks the waypoints and keeps the route on the map from every tab; **Deactivate** to edit it again. **Close route** empties the editor; **Clear waypoints** removes its waypoints but keeps it open; **Zoom to route**.
- **Tables:** **Legs** (from/to, course, distance, time, running totals and the ETA if you start now), **Totals** and **Waypoints**. Times assume the survey speed and no time for turns.
- **Appearance:** color, line style, line width and waypoint size, saved with the route.
- **Active route waypoints:** click one for its position, its distance and bearing from the vessel, and its **ETA** following the route from where the vessel is now (or *passed*), kept up to date as the vessel moves.
- **Save route** keeps it in the routes folder under its name; **Save as new…** saves a copy under another name. **Export GPX…** downloads it for a chart plotter or other navigation software. A GPX saved by Spyhop holds the whole design, so it opens again exactly.

## Overlays and maps

### Offline overlays

**Tools → Overlays → Offline overlays:** import GeoJSON, GPX or KML files, **show or hide** each one, zoom to one, or remove it; and add **past surveys** in the data folder as overlays (their trackline, sightings and events; press **Update** after changing one). Click an overlay's **color** to draw it in another color (↺ goes back to its own). *Imported overlays* in the map's layers menu switches them all on or off.

### Online overlays

Live data from the internet, drawn over the map (Tools → Overlays, below the offline ones). Each is also in the map's layers menu, and the ones you leave on are on next time.

- **AIS vessels** from [Open Waters AIS](https://openwaters.io/ais/), a free network of coastal-authority feeds and volunteer receivers. Spyhop asks for the vessels in view every 30 s and when the map moves. Each vessel is colored by type: a triangle pointing the way it's heading when it's moving, a dot when it isn't. Click one for its name, MMSI, type, speed, course, status, when it was last heard, and its distance and bearing from your vessel. **Hide AIS vessels that aren't moving** thins a busy harbor. AIS from the internet can be minutes old and misses vessels out of receiver range: **not for navigation or collision avoidance**.
- **Weather radar, US** (NOAA NEXRAD, from the Iowa Environmental Mesonet, every 5 minutes) and **worldwide** (RainViewer, every 10 minutes, where radars exist). **Radar opacity** applies to both.
- **Map feeds:** areas, lines or points from the web, such as management zones.
  - **Ready-made:** **Right whale Seasonal Management Areas (NOAA)** (drawn solid while in effect and dashed otherwise) and **Right whale Slow Zones / DMAs (NOAA NEFSC)**.
  - **Any feed:** a name and an address: an ArcGIS address ending in `/FeatureServer/<number>`, `/FeatureServer` or `/MapServer/<number>`, or a link to a GeoJSON file.
  - Each feed has **Show**, a color, how often to fetch it again, **Update now**, **Zoom to** and **Remove**. Spyhop keeps the last copy of each feed, so it still shows offline. Always check official notices: these are approximate.
- AIS and radar need the internet and aren't kept for offline use. The map feeds (their addresses) and which online overlays are on are part of the template.

### Base maps and offline charts

- **Map tiles** (Settings → Basemap): **Online map tiles** and **Offline map tiles** (the files in the charts folder, and the built-in **Coastline (offline)**). The choice is remembered on this computer.
- **Coastline (offline):** the world coastline from Natural Earth (1:10 m), so you have a map even with no internet and nothing downloaded. It is coarse: don't navigate by it.
- **Online layers:** **Seascape depths (feet)**, the default (Open Waters' bathymetry, with depth shading and labeled contours; the readout gives the depth at the cursor; not an official chart and **not for navigation**), Esri Ocean, Esri Imagery, NOAA charts and OpenStreetMap.
- **Browsing cache:** everything an online layer shows is saved on this computer as you view it, so areas you've looked at stay available offline.
- **Download an area for offline use** (Settings → Basemap): move the map to cover the survey area, choose the layer, the zoom range and a name (e.g. *Cape Cod Bay*), and press **Download** while you have internet.
  - The area is saved as one file in the charts folder, `<name>.mbtiles`. Downloading again with the same name adds to it.
  - Spyhop shows roughly how many tiles that is first, and a progress bar while it runs. Each zoom level has four times the tiles of the one before, so keep the highest zoom modest for a big area: 12–13 suits a day's survey area, 14–15 a harbor.
  - Seascape doesn't include land detail; download the area in **Esri Ocean** too if you want it. OpenStreetMap can't be downloaded (its tile policy forbids it).
- **In the charts folder** (Settings → Basemap): every `.mbtiles` file, with what it was made from, its zooms, tiles, size and date. **Select** puts one on the map on its own, as you'll have it at sea; **Delete** removes it. A file works on any computer with Spyhop: copy it into that computer's charts folder and press **Refresh**.
- **MBTiles charts of your own:** put `.mbtiles` files in the charts folder and press **Refresh**. Free, weekly-updated **NOAA nautical charts** for US waters are at <https://distribution.charts.noaa.gov/ncds/>.
- To add an online layer of your own, create `tile_sources.csv` in Spyhop's folder with the columns `name,url,attribution,overlay,max_zoom,kind` (kind `raster` for an XYZ tile server or an ArcGIS `export` URL using `{bbox}`, or `style` for a MapLibre `style.json`).

Offline charts are never part of a template (they're far too big); copy them between computers separately.

## Templates

### What's in a template

A **template** is one small file, `<name>.spyhop-template.zip`, holding a team's whole setup. It has two parts:

- **The data part**, which defines or works out what's recorded, and so can't change during a survey:
  - the drop-down lists: species, event types, behaviors, observers, effort, visibility and weather
  - the reticles
  - the rules (Settings → Rules)
  - the saved reports
  - the track point interval and the magnetic variation
- **The preferences**, which can change at any time:
  - the keyboard shortcuts
  - the map display (markers, trackline, lines, fading, overlay colors)
  - shared settings: lat/lon format, clock, default bearing reference and distance unit, map distance unit, effort reminder, keep awake, raw NMEA log, altitude and segment columns, automatic error check
  - the named GPS / NMEA inputs (serial, UDP, TCP, gpsd), with each "other" input's look on the map
  - the map feeds (their addresses, not their data) and which online overlays are on
- **Optionally** (ticked when saving): waypoints, routes and offline overlays. These are only ever added to a computer, never replacing what it already has.
- **A record of changes** (who changed what, and when) and the oldest Spyhop that can use it.

Never in a template: survey data, offline charts, file replays and the simulator, and this computer's own choices (which inputs are in use and which is the primary, the window layout, column widths, the last survey details), which are kept in `spyhop-local.json`.

Every computer has a **current template**: the one in use, kept unzipped in `templates/current` in Spyhop's folder. Editing a list in Settings → Dropdowns, a shortcut in Settings → Shortcuts, a rule in Settings → Rules, or a setting in Settings → General changes the current template.

### Drop-down lists

**Settings → Dropdowns** edits the lists of the current template: **Species**, **Events**, **Behaviors**, **Observers**, **Effort**, **Visibility**, **Weather** and **Reticles**.

- Each entry has a name (initials, for observers), a code, and for species and events a color (typed as a name like `red`, or picked). Behaviors have a **definition**, shown in the Behaviors checklist; effort entries have a status, a definition and a color.
- **↑ ↓** set the order of the drop-down, **✕** removes an entry, **Add entry** and **Sort A–Z** do what they say, and **Save** keeps the changes.
- Names and codes must be unique. Spyhop shows what's wrong and saves nothing until it's fixed.
- Renaming or removing an entry doesn't change rows already recorded; the Error check flags values that are no longer in the list.
- **Start**, **End** and **ERROR** in the effort list can't be renamed or removed, and at least one effort entry must be on effort.
- **Every list has Other**, the placeholder for anything missing from it (the reticles have **reticles-Other**, which keeps the reading but works out no distance). Record such a row as Other, with a note, and after the survey add the right entry and replace Other; the Error check lists every row that uses it. Other can't be renamed or removed.
- **While a survey is under way only the colors can be changed.** End the survey to edit the lists.
- **Many changes at once:** each list is a CSV file in the current template (`species.csv`, `observers.csv`, `event_types.csv`, `behaviors.csv`, `effort.csv`, `visibility.csv`, `weather.csv`, `reticles.csv`). **Open** opens it in your spreadsheet program; edit it, keep the header row as it is, save it, and press **Reload from the file**.

### Editing the shortcuts

In **Settings → Shortcuts**, click a shortcut's keys and press the new ones, choose what it does from the list, and press **Save**.

- Shortcuts that add a row can pre-fill columns, e.g. `Species=Fin whale;Obs=OBS1`.
- **Focus:** the column selected in the new row of a shortcut that adds a row (or a resight), ready to type in; for example, Num for a species shortcut, so you can type the number straight away. Blank selects the first empty column, as Add row does.
- Keys need Mod (⌘ Command on a Mac, Ctrl on Windows and Linux) or Alt (Option on a Mac), so they don't get in the way of typing; F1–F12 work alone. On a Mac the Control key can't be used.
- Keys used twice are flagged, and combinations the browser or the computer may take (e.g. Ctrl+W) are marked.
- **Restore the default shortcuts** puts the original set back (press Save to keep it), and **Revert** discards unsaved changes.
- For many changes at once, edit `shortcuts.csv` the same way as the lists, and press **Reload from the file**.

### Using, saving and sharing templates

**Settings → Templates** lists the templates in the templates folder (`templates/saved`), with each one's latest change, whether it matches this computer, and which one is in use.

- **Use this template…** shows what would change, grouped as data, preferences and added items, then replaces this computer's current template with it, with no merging. A backup of the current template is kept first (**Backups → Restore…** undoes it).
- **Save as a new template…** saves the current template as a new file; **Update…** replaces a saved template with the current template. Both ask for your name and what changed, and add it to the template's record of changes (a new template's record starts fresh, with that entry first).
- **Get a template from the web:** paste the template's web address and press **Check** to see what would change, then **Pull it**. A copy is kept in the templates folder for offline use. A team can keep its template on Google Drive, Dropbox or GitHub, and each computer gets the latest with one button. See [TEMPLATES.md](TEMPLATES.md) for sharing and hosting templates.
- **Open the current template** opens its folder, for editing files by hand.

### What can't change during a survey

From Start until End, nothing in the template's data part can change: the drop-down lists (except their colors), the reticles, the rules, the saved reports, the track point interval and the magnetic variation. Their controls are greyed out, editing their files by hand is undone when they're read again, and **using a template during a survey takes only its preferences** (and list colors): its data part waits until the survey ends. So the copy of the template kept with each survey is exactly what its data were recorded with.

### A survey recorded with another template

Each survey keeps a copy of the template it was started with (`<survey>_template.zip`). The Survey tab shows each survey's template, and says when its copy differs from the current template (for example, after the lists were edited, or when a survey from another team is opened). The data aren't changed either way, but the drop-downs, colors and the Error check follow the current template. **Compare and use the survey's template…** opens it in Settings → Templates, where **Use it** makes it the current template (with a backup first).

## Your data

### Folders

Spyhop's own folder holds your templates, settings and surveys:

- Windows: `%APPDATA%\Spyhop`
- Mac: `~/Library/Application Support/Spyhop`
- Linux: `~/.local/share/Spyhop`

Spyhop's folder, the survey data folder, the program folder and the diagnostic logs are listed in **Settings → About**; click one to open it.

```
Spyhop/                                   (Spyhop's own folder)
  templates/
    current/   the current template (unzipped): species.csv, observers.csv, event_types.csv,
               behaviors.csv, effort.csv, visibility.csv, weather.csv, reticles.csv,
               shortcuts.csv, and spyhop-config.json (settings, inputs, map display,
               map feeds, saved reports, record of changes)
    saved/     <name>.spyhop-template.zip   your templates
    backups/   the current template as it was before each other template was used
  spyhop-local.json   this computer's own settings (never in a template)
  charts/    *.mbtiles          overlays/   imported GeoJSON/GPX/KML
  routes/    saved routes, one GPX file each
  feeds/     the last copy of each map feed
  logs/      diagnostic logs
  data/                                   (the survey data folder)
    <survey name>/                one folder per survey
      <survey>_sightings.csv  _effort.csv  _events.csv  _track.csv  _metadata.csv  _nmea.csv
      <survey>_<name>_gps.gpx     the track of each "other" input
      <survey>_template.zip       the template the survey was started with
      exports/     exports, summaries, reports and survey packages
      nmea_logs/   raw NMEA logs
    waypoints.csv                 kept across surveys
```

The survey data folder is always `data/` inside Spyhop's folder, so every computer keeps its surveys in the same place; **Open Data Folder** in the Survey tab opens it. To move surveys between computers, use survey packages.

### Survey files

- `<survey>_metadata.csv` holds the survey details, plus rows Spyhop writes itself: the Spyhop version, the template the survey was started with, and the clock difference at the start.
- The track CSV's **Effort** column is `Start` from the start, then the Effort value in force, and `End` on the final point. A script can tell the start and end of the track apart from off-effort periods.
- The working CSVs have a **RowID** column. Spyhop uses it to tell rows apart (for undo/redo and for keeping open windows in step). Leave it alone if you edit a file by hand. Exports leave it out.
- When a new version adds or removes columns, survey files are updated automatically: data is carried over by column name and a copy of the original is kept as `*.csv.bak-<time>`. Nothing is overwritten.
- If a CSV is open in Excel on Windows, saving can fail. Spyhop warns you, keeps the edit in memory and saves it with your next change. It's safer to open exported copies than the live files.

### Survey packages

**Save Survey Package…** (Survey tab) saves the open survey as one file, `<survey>.spyhop-survey.zip` (downloaded, and kept in the survey's `exports/`), to move it to another computer, archive it or send it for checking. It holds the survey's files as Spyhop keeps them (so it can be edited again), the copy of its template, optionally its raw NMEA logs, and a description with a checksum of every file. Exports aren't included; for analysis use **Export Data**.

**Open Survey Package…** (under *Saved Surveys*) adds the survey to this data folder and opens it. Nothing is overwritten: if a survey of that name is already here, it asks for another name. A damaged or incomplete package, or one from a newer Spyhop, is refused with the reason. An active survey stays active in the package; end it there if it's finished.

### Export

**Export Data…** (Survey tab) asks which formats you want (it remembers your choice):

- **Separate CSV files:** sightings, effort, events, track, instrument readings, other inputs' tracks, survey details and waypoints, one file each, as Spyhop records them (without RowID). The track's Effort values are recalculated from the final Effort table.
- **Merged CSV file** (`<survey>_merged.csv`): sightings, effort, events and the track points in one table, in time order, one row per record. `Record` says which it is (Sighting, Effort, Event or Track). Every row also has the Spyhop version, the survey details, and the effort and conditions in force at that time (Effort, Segment, Visibility, SeaState, Weather, Glare, GlareStart, GlareEnd, GlareRef, Port, Recorder, Starboard), so each sighting can be analyzed with its conditions without a join. `Lat`/`Lon` is the vessel position; sightings keep SigLat/SigLon too.
- **GPX file:** the track and waypoints, for GPS units and mapping apps.
- **GeoJSON file:** the track split by effort, and points with all their columns, for QGIS or ArcGIS.
- **Summary report:** the same page as Tools → Summary, as HTML, PDF or both.
- each saved **report**, as CSV (available once the survey has ended).

One format is saved and downloaded as that file; several come as **one zip**. Everything is also kept in the survey folder's `exports/`.

## Quitting, updates and diagnostics

- **One Spyhop at a time:** only one Spyhop runs on a computer, so every survey is recorded in one place. Opening the icon again just opens a window onto the one that's running.
- **Quitting:** close the Terminal (or console) window that opened with Spyhop, or press Ctrl+C in it. Your data are saved as you go, so quitting never loses anything. Closing only Spyhop's own window leaves it running, still recording the track; open the icon again to get the window back.
- **Updates** (Settings → About → Updates): Spyhop checks for a newer version when it starts (if there's internet), and **Check for updates** looks any time. It always asks before installing, keeps a backup of the old version, and restarts.
- **Reinstall a clean copy…** replaces the program with the latest version and restarts, keeping your surveys and (unless you tick reset) your settings. **Uninstall Spyhop…** removes the program and its shortcuts; your settings and survey data are deleted only if you tick them. Neither works during a survey.
- **Diagnostic logs:** Spyhop keeps a log in `logs/` in its folder. It records the version and system at start-up, each action and whether it worked (never the data itself), errors, slow moments and a performance snapshot every 5 minutes. **Settings → About → Save diagnostics…** zips the logs, settings, a listing of Spyhop's folders and system details into one file to send with a bug report. It has no survey data and no team or observer names.
- **If Spyhop feels slow:** the Terminal window prints a line starting `spyhop.slow` whenever something takes too long. Copy those lines when reporting slowness.
