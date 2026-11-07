# Spyhop tutorial

Spyhop records a vessel-based whale survey: sightings, effort and conditions, events, the trackline and instrument data, all against a live chart. This tour covers the basics. It's also in Spyhop itself, under **Settings → About**.

## Find your way around

- **Map** (left): the vessel, its trackline (green on effort, a thinner grey line off effort), sightings, events and waypoints.
  - The layers button (top right) switches base maps and overlays.
  - The buttons on the left: ⌖ follow the vessel, 📏 measure, ◎ range rings, ⤢ zoom to the whole survey.
  - Right-click the map for: add a sighting, event or waypoint here; measure from here; **Start route here**.
- **Tabs** (right):
  - **Sightings**, **Effort** and **Events** are the data tables.
  - **Survey** starts, ends, opens and exports surveys.
  - **Tools** holds Waypoints, Overlays, Route, Instruments, Quality Control, Summary and Reports.
  - **Settings** holds General, Basemap, Inputs, Shortcuts, Dropdowns, Templates and About.
- **Status bar** (top): time, position, speed, survey name, tracking and effort state.
  - If the GPS fix is lost, it says **NO GPS** or **GPS LOST**.
  - Click the version number to come back here.

## Try it with the simulator

You don't need a GPS to try Spyhop.

1. Open **Tools → Instruments** and press **+ Add input**.
2. Change the new input's type to **SIMULATOR**, and set a heading, speed and start position.
3. Press **Apply**. A simulated vessel appears on the map and moves at that speed.
4. Untick or delete the simulator input when you connect a real GPS. While one is ticked, its fake positions go into the data like real ones.

From a terminal you can also run `python -m spyhop --sim`, which adds the simulator for that session only.

## Set up your lists (config files)

Edit the drop-down lists in **Settings → Dropdowns** (Species, Events, Behaviors, Observers) and the keyboard shortcuts in **Settings → Shortcuts**, then press **Save**. The lists can't be changed while a survey is under way.

Behind the scenes they are plain CSV files, which you can also edit in Excel, Numbers or a text editor for big changes. Each editor has an **Open** button for its file and a **Reload from the file** button:

- **species.csv:** species names, map colours and codes (e.g. `RIWH`). The code labels sightings on the map, and Reports use it.
- **observers.csv:** observer codes and full names. `NA` (None) is a placeholder for an empty watch position, and can fill several positions at once.
- **event_types.csv:** event names, colours and codes (e.g. `GRPT` for Gear Reported).
- **behaviors.csv**, and **display.csv** (the map's look, also set in Settings → General).
- **shortcuts.csv:** keyboard shortcuts.
  - Each row has a key (e.g. `Mod+Shift+R`; Mod is Ctrl on Windows and ⌘ on a Mac), an action, and optional prefills.
  - For example, `Species=North Atlantic right whale` makes the shortcut start a right whale sighting.
  - **Settings → Shortcuts** lists them all.

After editing a file, save it and press **Reload config files**. Keep the header row as it is. Spyhop adds new columns and entries itself when it is updated.

If your team shares its config files, use **Settings → Templates** instead. Paste the address of the team's pack under **Get a pack from the web** and press **Check** to see what would change, then **Pull and overwrite**; or press **Use this pack…** on a pack already in the list. This overwrites this computer's copies of the pack's files, so keep the backup option ticked. To save your own setup as a pack, press **Save this computer's config as a new pack…**. See docs/CONFIG_PACKS.md.

## Plan a route

1. Open **Tools → Route**, or right-click the map and choose **Start route here**.
2. Set the **survey speed**, and choose **Manual** or **Systematic**:
   - **Manual:** press **Add points on the map** and click each waypoint. Drag them to adjust.
   - **Systematic:** set the start, the direction of the first leg, the number of legs, leg length and spacing. Spyhop draws back-and-forth lines.
3. The tables show each leg's course, distance and time, the totals and the finish time.
4. Press **Activate route**. The waypoints lock, the route stays on the map from every tab, and clicking a waypoint shows its distance and bearing from the vessel.
5. **Save as map overlay** to keep the route, or **Export GPX…** for a chart plotter. **Import GPX…** loads a saved route back.

## Start a survey

1. In **Survey**, press **Start New Survey…**.
2. Enter the survey name in your team's own convention (it becomes the start of the file names). Fill in the survey details: platform, organization and chief scientist.
3. Spyhop adds the **Start** row to the Effort table, switches the trackline on and opens the Effort tab.

If Spyhop is closed or crashes during a survey, it reopens the survey the next time and asks whether to continue.

## Record data

- **Effort:**
  - add a row with Ctrl/⌘+Shift+F, which toggles effort ON and OFF and copies the current conditions
  - fill in visibility, sea state, weather, glare and who is at Port, Recorder and Starboard
  - a countdown in the status bar reminds you to update the conditions
- **Sightings:**
  - press **Add row**, Ctrl/⌘+Shift+S, or a species shortcut; the time and vessel position fill in
  - type the species, number, bearing and distance; Spyhop works out the animal's position (SigLat/SigLon) and draws it
  - or right-click the map where the animals are
- **Events** (CTD casts, gear reported or recovered, other): Ctrl/⌘+Shift+V, or right-click the map.
- **Editing:**
  - Enter or double-click edits a cell, and Tab moves on. Drop-downs filter as you type.
  - Each table has **Undo** and **Redo**.
  - Type `14:05` in a time cell to change only the time of day.
- **Instruments:** **Tools → Instruments** shows depth, wind, water temperature and so on, from your network. Click one to plot it. You can also log the raw NMEA there.

## End the survey

In **Survey**, press **End Survey**. This adds the **End** row and switches the trackline off. An ended survey can still be corrected, and deleting the End row makes it active again. **Close Survey** puts it away without ending it.

## Check for errors

Open **Tools → Quality Control** and press **Run quality control check**. It lists:

- **errors:** must fix, e.g. required fields left blank, values that aren't in the lists, impossible numbers
- **warnings:** probably wrong, e.g. a sighting beyond the visibility, positions on land, GPS jumps
- **notes:** worth a look

**Show** takes you to the row. A GPS jump or gap has a **Fix** button, which marks that stretch with an ERROR row in the Effort table so it's left out of the trackline and the effort totals. **Save report…** keeps the list as a CSV.

## Summary and Reports

- **Tools → Summary** (Ctrl/⌘+4): totals, survey details, species, observers, conditions, a map, and right whale sightings. **Save as HTML…** or **Save as PDF…** (PDF needs Google Chrome or Microsoft Edge).
- **Tools → Reports** picks part of a table and saves it:
  1. Choose **Sightings**, **Events** or **Effort**.
  2. Click the species (or event types) you want; the chips show how many of each are in this survey.
  3. Open **Columns** to tick the columns and set their order.
  4. **More conditions** adds *on effort only*, a time range, or rules such as *Num is more than 5*.
  5. **Export CSV…**, **HTML…** or **PDF…**.

  **Save report…** keeps it by name for next time. Spyhop starts you off with Right whales, Blue whales, Dead birds and Gear. **Run Reports…** saves any of your saved reports at once, in the formats and folder you choose: handy at the end of the day.

## Export the data

In **Survey**, press **Export Data…** and choose any of:

- the separate CSV files
- a merged CSV (sightings, effort, events and track points in time order, with the conditions on every row)
- GPX
- GeoJSON
- the summary, as HTML, PDF or both
- your saved reports, as CSV

Several files are saved together as one zip. Everything goes in the `exports` folder inside the survey data folder, and a copy downloads.

## Keep Spyhop up to date

In **Settings → About → Updates**, press **Check for updates**. If there's a newer version, **Install** it and restart Spyhop. Your data and settings aren't touched, and the old version is kept as a backup. It's best to do this between surveys, with internet.

Your data are also always on disk as plain CSV files, in the survey data folder (**Survey** shows where), saved as you type.
