# Spyhop

Spyhop is a python-based data recorder for marine mammal surveys. It reads GPS and instruments over NMEA 0183, shows a live chart, and logs **sightings, effort and environmental conditions, events, the trackline and instrument readings and more** to plain CSV files as you type. It also has some handy features for survey planning, error checking, and reporting. Best of all, it's totally free, open source, runs on any laptop (Mac, Windows or Linux) and needs no internet once installed.

![Spyhop](docs/screenshot.png)

> **Active development.** Spyhop is developed for our own vessel-based whale surveys at the New England Aquarium, and its default lists, checks and reports follow our protocols. Other groups are welcome to use and adapt it: lists, shortcuts and reports are config files, not code. Expect changes between versions, and check the exported columns against your own pipelines before relying on them. Version: see [CHANGELOG.md](CHANGELOG.md) (also shown in Spyhop under Settings → About).

## Features

- **Data entry built for the flying bridge:**
  - Sightings, Effort and Events tables with drop-downs that filter as you type, keyboard shortcuts (including species shortcuts) and per-table undo/redo
  - time and position filled in from the GPS, conditions copied forward, and a reminder to update the conditions
  - **resights**: link a later look at the same animals to the first sighting, so they're counted once
  - sighting positions worked out from bearing and distance, including **reticle** readings (binoculars, calibrated marks or an inclinometer) and **clock bearings** (1–12 o'clock)
  - columns you can reorder and resize, and three resizable panes: the map, Survey/Tools/Settings, and the data tables
- **Your own effort codes:** an Effort list (ON, TRANSECT, DIRECTED, PHOTO-ID, FOLLOW, OFF… by default) with a status (on or off effort), a definition and a color for each, used on the map, in the Summary, in reports and in the Error check
- **Platforms:** shipboard, aerial (with altitude) and **stationary** surveys. A stationary survey can use a fixed station position instead of a GPS.
- **Live chart:**
  - vessel, trackline (colored by effort, with Start and End labels), sightings, events and waypoints
  - measure tool, range rings, imported overlays (GeoJSON, GPX, KML), and past surveys as overlays
  - offline coastline, online base maps with a tile cache, and NOAA MBTiles charts offline
- **GPS and instruments:**
  - serial/USB, UDP, TCP, gpsd and file replay inputs, each named for its device, so one template can hold the inputs of every computer a team uses
  - one **primary** input for the platform, **secondary** inputs (a backup GPS, the depth sounder), with an optional fallback to a secondary and a red banner while it's used
  - **other** sources, such as a drone, a drifting buoy or a second vessel, each with its own icon, color and trail on the map and its own track file
  - depth, wind, weather and engine readings with time-series plots, every reading logged with its source
  - raw NMEA logging, and a built-in **simulator** for practice
- **Accurate times:** Spyhop checks the computer's clock against the GPS and, if they differ by more than 2 seconds, offers to set the clock before a survey starts
- **Route planning:**
  - manual or systematic (parallel-leg and sawtooth) tracklines, with leg times at the survey speed
  - save any number of routes, show them on the chart and open them to edit
  - activate a route to keep it on the chart, with ETAs at each waypoint
  - GPX export and import
- **Online overlays** (when there's internet): AIS vessels from Open Waters AIS, US (NOAA NEXRAD) and worldwide (RainViewer) weather radar, and map feeds from ArcGIS or GeoJSON, with NOAA's right whale Seasonal Management Areas and Slow Zones ready to add; feeds stay available offline
- **Survey management:**
  - Start, End and Close, with crash recovery that asks to continue the survey
  - each survey in **its own folder**, with a copy of the template it was recorded with
  - **survey packages**: one checked `.spyhop-survey.zip` file to move a whole survey to another computer and open it there
  - survey details (platform, organization, chief scientist, notes)
  - keeps the computer from going to sleep during a survey (optional)
  - a clock in local time, UTC, any offset, or the zone at the vessel's position
  - only one Spyhop runs on a computer at a time, so two windows can't write to the same survey
- **Error check:**
  - required fields, list values, plausible numbers and bearings, resights
  - positions on land, sightings beyond the visibility, observer rules, and more
  - **Rules:** your team's own checks, built as sentences (*if* Event is CTD cast *then* ID isn't blank), carried in the template
  - optionally runs by itself every few minutes during a survey
  - GPS jumps and gaps, each with a one-click **Fix** that marks it with an ERROR Effort row. The trackline is broken only there, so every change to the track is in the data for anyone to see.
- **Summary and reports:**
  - a Summary (totals, conditions, observers, a map), saved as HTML or PDF
  - **Reports:** pick species or event types, conditions and columns from any table, see the result live, and save it as CSV, HTML or PDF; save reports by name, share them in templates, and run them all at once
- **Templates:** save a team's setup as one small `.spyhop-template.zip` file: its **data part** (the lists, reticles, saved reports and the settings that change what's recorded) and its **preferences** (shortcuts, map display, inputs, map feeds), and optionally waypoints, routes and overlays. Switch between templates, and share one with the team on the web (e.g. Google Drive, Dropbox or GitHub). Each computer gets the latest with one button and keeps a backup. During a survey the data part is locked, so every record of a survey is made with the same lists and settings.
- **Export:** separate CSVs, a merged time-ordered CSV (sightings, effort, events and track) with the conditions on every row, GPX, GeoJSON, the summary and saved reports, in one zip.
- **Help built in:** the user guide, with a quick start and contents, in **Settings → Guide**, a **?** next to each section heading, a description of every column, and in-app updates.

## System requirements

- **Operating system:** macOS 12 (Monterey) or newer, on Apple silicon or Intel; or Windows 10 or 11 (64-bit). Linux works too.
- **Python:** 3.10 or newer (3.12 or 3.13 recommended). See [Installation](#installation) below.
- **Browser:** Google Chrome or Microsoft Edge are recommended. Spyhop opens in a Chrome/Edge "app" window, and they're needed for saving reports as PDF. Without either, Spyhop opens in your default browser.
- **Internet:** once, the first time Spyhop starts (and after an update that adds packages), to install its Python packages. It's not needed after that.
- **Disk:** roughly 100 MB with its Python packages, plus your data and any offline charts.
- **Screen:** 1280 × 800 or larger is comfortable.
- **GPS:** any NMEA 0183 source: a USB GPS, or a ship's network sending NMEA over UDP or TCP. You don't need one to try Spyhop: use the simulator. A stationary survey can use a typed-in station position instead.
- **Administrator rights** (optional): only to let Spyhop set the computer's clock to the GPS time. Everything else works without them.

## Installation

Pick your operating system below. Each section covers installing Python, then Spyhop.

Spyhop is written in Python, so the computer needs Python 3.10 or newer. You install Python once. Spyhop then makes its own private copy of the packages it needs, in a `.venv` folder inside the Spyhop folder, so it won't interfere with other Python programs on the computer, and they won't interfere with it.

### Mac

#### Python

1. **Check whether it's already installed:** open **Terminal** (Applications → Utilities), type `python3 --version` and press Return. If it shows `Python 3.10` or higher (e.g. `Python 3.13.1`), skip to [Spyhop](#spyhop-1). If it shows an older version, an error, or a prompt to install developer tools, carry on.
2. Go to [python.org/downloads/macos](https://www.python.org/downloads/macos/) and download the **macOS 64-bit universal2 installer** of the latest Python 3 release (it works on Apple silicon and Intel Macs).
3. Open the downloaded `.pkg` file and follow the steps (Continue, Agree, Install). It asks for your Mac password.
4. When it finishes, a Finder window opens on the new **Python 3.x** folder in Applications. Double-click **Install Certificates.command** in it. This lets Python make secure internet connections, which Spyhop uses to check for updates and load online maps. Without it these can fail with a "certificate verify failed" error.
5. Open a **new** Terminal window and type `python3 --version` to check that it shows the new version.

Don't use the `python3` that comes with Apple's Command Line Tools or Xcode: on many Macs it's Python 3.9, which is too old. Homebrew's Python (`brew install python`) also works if you already use Homebrew.

#### Spyhop

1. Download Spyhop from the [latest release](https://github.com/hansenjohnson/spyhop/releases/latest): under **Assets**, click **Source code (zip)**. Unzip it.
   - **Rename the folder** from `spyhop-0.48.0` (or similar) to `spyhop`. In-app updates replace the files in place, so the folder keeps its name; a version number in it would soon be wrong.
   - Put the folder where it will stay, e.g. in Documents, **before** the first start: the Spyhop icon points at this folder.
   - Developers can `git clone https://github.com/hansenjohnson/spyhop.git` instead. Spyhop then updates itself with `git pull`.
2. Double-click **`Start Spyhop (Mac).command`**.
   - macOS blocks it the first time because it was downloaded. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to the message about it, then double-click the file again.
   - On older macOS: right-click it, choose **Open**, then **Open**.
3. The first start takes a minute: it sets up Spyhop's Python packages in `.venv` (it needs internet) and adds a **Spyhop** icon to **Applications** and the **Desktop**. Drag the icon to the Dock to keep it handy.

See [Starting, quitting and updating](#starting-quitting-and-updating) and, if anything goes wrong, [Troubleshooting](#troubleshooting).

### Windows

#### Python

1. **Check whether it's already installed:** open **Command Prompt** (search for *cmd* in the Start menu), type `py --version` and press Enter. If it shows `Python 3.10` or higher (e.g. `Python 3.13.1`), skip to [Spyhop](#spyhop-2). If it shows an older version or an error, carry on.
2. Go to [python.org/downloads/windows](https://www.python.org/downloads/windows/) and download the **Windows installer (64-bit)** of the latest Python 3 release.
3. Run it. On its first screen, **tick "Add python.exe to PATH"** at the bottom, then click **Install Now**. (Leave "Use admin privileges when installing py.exe" ticked if it's offered.)
4. If it offers **Disable path length limit** at the end, click it (it needs administrator rights, and avoids problems with long folder names).
5. Open a **new** Command Prompt and type `py --version` to check.

If typing `python` opens the Microsoft Store instead, that's Windows' shortcut, not Python. Spyhop uses `py`, which the python.org installer adds, so you can ignore it (or turn it off in **Settings → Apps → Advanced app settings → App execution aliases**). The Microsoft Store version of Python isn't recommended for Spyhop.

#### Spyhop

1. Download Spyhop from the [latest release](https://github.com/hansenjohnson/spyhop/releases/latest): under **Assets**, click **Source code (zip)**. Unzip it (right-click → **Extract All…**).
   - **Rename the folder** from `spyhop-0.48.0` (or similar) to `spyhop`. In-app updates replace the files in place, so the folder keeps its name; a version number in it would soon be wrong.
   - Windows often unzips into a folder inside a folder of the same name (`spyhop-0.48.0\spyhop-0.48.0`). Use the inner one, which contains `README.md` and the start files.
   - Put the folder where it will stay, e.g. in Documents, **before** the first start: the Spyhop icon points at this folder.
   - Developers can `git clone https://github.com/hansenjohnson/spyhop.git` instead. Spyhop then updates itself with `git pull`.
2. Double-click **`Start Spyhop (Windows).bat`**. If Windows says it protected your PC, click **More info → Run anyway**.
3. The first start takes a minute: it sets up Spyhop's Python packages in `.venv` (it needs internet) and adds a **Spyhop** icon to the **Desktop** and the **Start menu**. Right-click the icon to pin it to the taskbar.

See [Starting, quitting and updating](#starting-quitting-and-updating) and, if anything goes wrong, [Troubleshooting](#troubleshooting).

### Linux

#### Python

Most distributions include Python 3.10 or newer. Check with `python3 --version`. On Debian and Ubuntu, also install the venv module: `sudo apt install python3-venv`.

#### Spyhop

Download and unzip the [latest release](https://github.com/hansenjohnson/spyhop/releases/latest) (or `git clone` the repository), rename the folder to `spyhop`, put it where it will stay, then run `./start-spyhop.sh` in it. It also adds Spyhop to the applications menu.

See [Starting, quitting and updating](#starting-quitting-and-updating) and, if anything goes wrong, [Troubleshooting](#troubleshooting).

### Troubleshooting

- **"Python 3.10 or newer is needed"** when Spyhop starts: Python isn't installed, or the computer can't find it. Install it as above, then open a new Terminal or Command Prompt (or restart the computer) and try again.
- **The first start stops with an error while installing packages:** check the internet connection, then delete the `.venv` folder inside the Spyhop folder and start Spyhop again. It sets everything up from the beginning.
- **After installing a newer Python**, delete the `.venv` folder too, so Spyhop rebuilds it with the new Python.
- **Behind a firewall or proxy** (e.g. a university or agency network), the package install may be blocked. Try another network for the first start, or ask IT to allow `pypi.org` and `files.pythonhosted.org`.
- Still stuck? See [Feedback](#feedback) below.

### Starting, quitting and updating

- **Start Spyhop with its icon.** It opens a Terminal (or console) window, which *is* Spyhop running, and then Spyhop's own window. **Keep the Terminal window open while you work.**
- Only one Spyhop runs on a computer. Starting it again (from the icon or another folder) opens another window onto the Spyhop that's already running.
- **To quit,** close the Terminal window, or press Ctrl+C in it. Everything is saved as you type, so quitting never loses data. A survey that was active is offered again the next time.
- **Updates:** when Spyhop starts, it checks for a new version (if there's internet) and asks before installing anything. You can also check any time in **Settings → About → Updates**. Restart Spyhop when it asks.
  - It updates from this repository's latest release (or `git pull` if you cloned the repository).
  - It keeps a backup of the old version and never touches your data.
  - Your templates, settings and surveys live in Spyhop's own folder, not in the program folder, so they carry over. **Settings → About** has links to open each folder:
    - **Mac:** `~/Library/Application Support/Spyhop`
    - **Windows:** `%APPDATA%\Spyhop`
    - **Linux:** `~/.local/share/Spyhop`
  - Surveys are in its `data` folder, one folder per survey (**Survey → Saved Surveys → Open Data Folder**).
- If you move or rename the program folder later, double-click the start file in its new place once to update the icon.

## Starting a survey

1. **Connect the GPS.** In **Settings → Inputs**, press **+ Add input**, name it for its device and choose its kind:
   - **SERIAL** for a USB GPS (pick its port)
   - **UDP** or **TCP** for a ship's network
   - **SIMULATOR** to practice

   Make it the **Primary** and press **Apply**. The status bar shows the position once there's a fix, and **Tools → Instruments** shows everything coming in.
2. **Check your lists** (once): species, event types, behaviors, observers, effort codes, visibility, weather and reticles are in **Settings → Dropdowns**, and the keyboard shortcuts in **Settings → Shortcuts**. If your team shares a template, use it from **Settings → Templates** instead. The lists can't change during a survey, so set them up beforehand (each list has an **Other** entry for anything unexpected).
3. **Plan the route** (optional): **Tools → Routes**, then **Save route** and **Activate route**.
4. **Start:** in **Survey**, press **Start New Survey…**. Enter a name (in your team's own naming convention) and the survey details: platform name and type (for a stationary platform, its position if there's no GPS), organization and chief scientist. Spyhop then checks the GPS and the computer's clock, adds the *Start* row to Effort and starts the trackline.
5. **Go on effort:** Ctrl+Shift+F (⌘⇧F on a Mac) adds an Effort row that switches effort ON or OFF. Fill in the conditions and the observers.
6. **Record sightings and events:** press **Add row** in the Sightings or Events tab, use a shortcut (Ctrl/⌘+Shift+S for a sighting, Ctrl/⌘+Shift+V for an event), or right-click the map.
7. **Finish:** **Tools → Error check → Run error check** and fix what it finds, then **Survey → End Survey…** and **Export Data…** (or **Save Survey Package…** to move the survey to another computer).

The **Quick start** of the user guide, in **Settings → Guide** (also [docs/USER_GUIDE.md](docs/USER_GUIDE.md#quick-start)), walks through all of this, including the simulator, templates, error checking and reports.

## Documentation

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md): the user guide (also in Spyhop under **Settings → Guide**): a quick start that walks through a survey, then every tab, templates, the files Spyhop writes, export formats and offline maps.
- [docs/TEMPLATES.md](docs/TEMPLATES.md): sharing a team's template (lists, settings, saved reports and more) across computers.
- [docs/DEVELOPERS.md](docs/DEVELOPERS.md): running from source, the code layout and the tests.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.

## Feedback

Please report problems and suggestions as GitHub issues. For a bug, **Settings → About → Save diagnostics…** makes a zip of Spyhop's logs and settings (no survey data and no team names) that you can attach.

## License

Spyhop is free software, released under the [GNU General Public License v3.0 or later](LICENSE). You can use, share and change it; if you distribute a modified version, it must also be under the GPL, with its source code available.
