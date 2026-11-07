# Spyhop for developers

Spyhop is a small local web server (Python 3.10+, `aiohttp`) with the interface in a browser window. The browser code is plain ES modules with no build step and no framework. Leaflet and the coastline are bundled in `spyhop/web/vendor/`, so everything works offline.

## Running from source

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m spyhop --sim                 # add the GPS simulator
.venv/bin/pip install pytest && .venv/bin/python -m pytest tests
```

Useful options:

- `--data-dir PATH` keeps a test setup apart from your real Spyhop folder.
- `--no-browser` doesn't open a window.
- `-v` gives debug logging.

The server listens on <http://127.0.0.1:8765/>.

## Layout

```
spyhop/
  __main__.py     command line and start-up
  server.py       aiohttp routes, websocket push (vessel state every second, table changes as they happen)
  recorder.py     every edit goes through here: validation, computed fields, surveys, tracker, export
  store.py        CSV tables with atomic writes and undo/redo; the track file
  schema.py       the columns of each table, and the fixed lists
  config.py       Spyhop's folder, the default config CSVs, settings and their migrations
  nmea.py         NMEA 0183 parser, vessel state, instrument readings, raw log
  sources.py      inputs: serial, UDP, TCP, gpsd, file replay, simulator
  qc.py           the quality control check (thresholds in LIMITS)
  reports.py      Tools → Reports: report specs → rows and columns, CSV/HTML pages; saved reports in <Spyhop>/reports
  report_defs/    the starting saved reports, copied into that folder once
  routes.py       the routes folder (Tools → Routes): list, read, save, delete GPX files
  feeds.py        map feeds (Settings → Inputs): ArcGIS / GeoJSON fetch, presets, the saved copy in <Spyhop>/feeds
  configpack.py   config packs (Settings → Templates): read, compare, apply, save, fetch from the web, backups
  packparts.py    the pack parts added in 0.22: shared settings, network inputs, feeds, waypoints, routes, overlays, minimum version
  browser.py      finds Chrome/Edge for the app window and for PDF printing (headless --print-to-pdf)
  tzguess.py      the clock's time zone from the platform's position (tzfpy)
  diag.py         diagnostic logs, crash capture, performance snapshots, the diagnostics bundle
  shortcut.py     makes the Spyhop icon (Mac app, Windows shortcuts, Linux menu entry)
  geo.py          lat/lon parsing and formatting, bearings, destinations, magnetic variation
  tiles.py        tile cache proxy (raster and MapLibre styles), area downloads into charts-folder MBTiles files (ChartWriter), MBTiles reader
  web/
    index.html  css/app.css
    js/app.js            the application: tabs, panes, dialogs, websocket handling
    js/grid.js           the data tables
    js/map.js            the Leaflet map, markers, track, tools
    js/depth.js          the water depth at the cursor, read from Seascape's depth tiles
    js/planning.js       Tools → Routes: the route editor, activation, and the saved routes (/api/routes*)
    js/online.js         online overlays: AIS (/api/ais), radar (NEXRAD tiles, /api/radar/rainviewer), map feeds (/api/feeds*)
    js/reports.js        Tools → Reports and Run Reports (runs reports on the server, /api/reports*)
    js/plot.js           instrument time-series plots
    js/summary_html.js   the self-contained Summary page (HTML export)
    js/util.js           formatting, geodesy and small helpers
    vendor/              Leaflet, the Natural Earth coastline
docs/            TUTORIAL.md (also shown in Settings → About), USER_GUIDE.md, this file
tests/test_core.py   pytest
CHANGELOG.md     changes in each version (shown in Settings → About)
```

## Conventions

- **The version** is in `spyhop/__init__.py` (`__version__`, `VERSION_DATE`), and `pyproject.toml` reads it from there. MINOR is for features and PATCH for fixes. Add a CHANGELOG entry with every change.
- **Data files** are plain CSV with ISO 8601 times carrying their UTC offset.
  - The working files have a hidden `RowID` column; exports leave it out.
  - Column changes migrate existing files automatically (by column name, keeping a `.bak-<time>` copy).
  - New list entries and shortcut actions are added to users' files at start-up: see `NEW_LIST_ROWS`, `NEW_ACTIONS`, `REMOVED_ACTIONS` and `RENAMED_ACTIONS` in `config.py`.
- **Validation** happens on the server (`recorder.py`), never only in the browser.
- **State in the window:** settings panes redraw on every settings broadcast. Keep half-typed values in JS, not only in the DOM.
- **Map markers:** never set CSS `position` on a marker's icon class; it breaks Leaflet's placement.
- **Reports:** a group's report is a saved JSON spec (table, codes, columns, conditions), made in the app, not code. Keep `reports.py` independent of the rest; it reads the open survey through `rec.tables`, `rec.cfg` and `rec.tz()`.
- **Launchers** (`Start Spyhop (Mac).command`, `Start Spyhop (Windows).bat`, `start-spyhop.sh`) make `.venv` on first run. They reinstall `requirements.txt` when it changes, so a new dependency reaches existing installs.

## Publishing an update

Spyhop's **Settings → About → Updates** (`spyhop/updater.py`) installs from `github.com/hansenjohnson/spyhop`:

- **The latest release** (preferred). To publish one:
  1. bump `__version__` in `spyhop/__init__.py`
  2. add a CHANGELOG entry
  3. push
  4. on GitHub, *Releases → Draft a new release*, with a tag `vX.Y.Z` that matches the version and the CHANGELOG entry as the notes
- **The main branch,** until the first release exists. It's offered when its `spyhop/__init__.py` has a higher version, with the newer CHANGELOG sections as the notes.

Installing:

- downloads the zip and checks that it contains Spyhop and is newer
- backs up the current program files to `<Spyhop folder>/updates/`
- copies the new files over the program folder, skipping `.venv`, `.git` and caches, and removes package files the new version dropped
- runs `pip install -r requirements.txt`
- On macOS and Linux it can then restart in place (`os.execv`, same Terminal window and port; the window reloads when it sees the new version). On Windows the user restarts Spyhop.

A git checkout is updated with `git pull --ff-only` instead. `SPYHOP_UPDATE_API` points the updater at another API address; the tests use a local stand-in for GitHub.

## Tests

- `python -m pytest tests` covers parsing, storage and undo, the survey lifecycle, migrations, export, QC, the reports, the clock and the trackline-break fix.
- A PDF test runs when Chrome/Edge is found (or `SPYHOP_CHROME` points at one).
- The interface was tested with Playwright walkthroughs during development. Those scripts aren't in the repository, except `tests/ui_marker_positions.js`.
