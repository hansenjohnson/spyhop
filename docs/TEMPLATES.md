# Templates

A **template** is your team's Spyhop settings in one small file, so every computer can be set up to record the same way. It holds:

- the species, event types, observers and behaviors lists, and the keyboard shortcuts
- the map display (marker shapes and colors, track styles, text sizes)
- the saved reports (Tools → Reports)
- the shared settings: clock, units, tracking, keep awake, raw NMEA log, and the network GPS / NMEA inputs
- the map feeds and which online overlays are switched on
- and, if you choose, waypoints, routes and overlays

A computer can also switch between templates, for example a vessel crew's and an aerial crew's.

Offline charts are not in templates (they are far too big); copy them between computers separately (see the USER_GUIDE, *Offline charts*). Survey data, serial GPS ports and the data folder are never in a template either.

Templates are updated by hand: Spyhop never looks for a newer template, or changes anything, until someone presses **Check** or **Use this template…**.

## Where templates are kept

Templates live in the **`templates` folder in Spyhop's own folder** (Settings → General → Folders shows where that is):

| Folder | What it holds |
|---|---|
| `templates/current/` | **The current template**: `species.csv`, `event_types.csv`, `observers.csv`, `behaviors.csv`, `shortcuts.csv` and `spyhop-config.json`. It is a template, unzipped: everything you change in Settings → Dropdowns, Shortcuts, General and Inputs, and in Tools → Reports, is saved here. |
| `templates/saved/` | Your templates, `<name>.spyhop-template.zip`, and copies of the ones you got from the web. |
| `templates/backups/` | The current template as it was before each other template was used. |

This computer's own settings, which never go in a template (the data folder, serial ports, the window layout, the last survey details, which survey is open), are in `spyhop-local.json` next to the `templates` folder.

You can edit the files in `templates/current` by hand (keep a copy first), then press **Reload config files** (Settings → Dropdowns) or restart Spyhop.

## Managing templates

Templates are managed in **Settings → Templates**. Spyhop lists every template in `templates/saved`. For each one it shows the latest change, whether it matches the current template, and which template is in use. From the list you can:

- **Use this template…:** see what would change, then use it (a backup is saved first).
- **Update…:** replace the template with the current template, adding your name and what changed to its record of changes.
- **Download:** get the file, to upload it for the team.
- **Save as a new template…** (under the list): give it a name, your name and what changed.

Spyhop names the templates it saves **`<name>.spyhop-template.zip`**. They are ordinary zip files of the same files as `templates/current`, so they open in any zip tool. Spyhop also reads a template saved under another name ending in `.zip`.

**Starting a survey:** if the current template isn't saved as a template (or has changed since it was saved), Start New Survey offers to save it first (**Save as a new template…**, or **Update…** the template it came from), or to start without saving. Each survey's details record, behind the scenes, the Spyhop version and the saved template the current template came from, and whether it still matched that template when the survey started.

A team usually keeps its template on the web too, so each computer can get the latest when it has internet (**Get a template from the web**). Nothing is downloaded until someone presses **Check**. A template is small (usually well under 100 KB), so checking at sea costs very little. Spyhop keeps a copy of each template it gets from the web in the templates folder, so it can be used again offline.

## What's in a template

A template is a zip file (or, on GitHub, a repository or a folder in one) containing:

| File | What it is |
|---|---|
| `spyhop-config.json` | Everything that isn't a table (see below). |
| `species.csv`, `event_types.csv`, `observers.csv`, `behaviors.csv` | The drop-down lists. |
| `shortcuts.csv` | Keyboard shortcuts. |
| `waypoints.csv` | Waypoints (optional). |
| `routes/*.gpx` | Saved routes (optional). |
| `overlays/*` | Imported overlays: GeoJSON, GPX or KML (optional; past surveys shown as overlays are not included). |

The lists and shortcuts stay as CSV files so they can be edited in a spreadsheet. **`spyhop-config.json`** holds the rest:

| Key | What it is |
|---|---|
| `spyhop_template`, `min_spyhop`, `made_with`, `includes` | The template's format, the **oldest Spyhop that can use it**, the version that made it, and which optional parts it has. |
| `history` | The record of changes (see below). |
| `settings` | The shared settings. |
| `nmea_inputs` | The network GPS / NMEA inputs (UDP, TCP, gpsd). |
| `map_feeds` | Each map feed's name, address, color and refresh time. The feed's data isn't stored: each computer downloads it. |
| `online_overlays` | Which online overlays to switch on, and the radar opacity and hide-stopped setting. |
| `map_display` | The map display. |
| `reports` | The saved reports, by file name. |

**Only the parts in the template are changed.** For example, a template with only `species.csv` and `observers.csv` changes only those two lists on each computer.

**Lists, shortcuts, map display and settings are replaced.** The shared settings are: lat/lon format, clock (time zone), bearing reference, distance unit, magnetic variation, track point interval, track break speed and gap, effort reminder, keep the computer awake and the screen on, the raw NMEA log (on/off and time stamps), the Altitude column choice, and how reticle readings are taken (method, binocular magnification and degrees per division, calibrated marks). The template's network GPS / NMEA inputs replace this computer's network inputs; **serial ports, file replays and the simulator stay as they are**, since port names differ between computers. Everything else in Settings (the data folder, the view and split, follow vessel, the browsing cache…) belongs to the computer and is never in a template.

**Saved reports go as a set.** If the template has saved reports, each computer ends up with exactly those reports: any others of its own are removed. A template with no saved reports leaves each computer's reports alone.

**Map feeds, waypoints, routes and overlays are only added.** Each computer gets the ones it doesn't have yet. One it already has is kept as it is: a map feed with the same address, a waypoint with the same name (or, unnamed, the same position), a route or overlay file with the same name. Nothing is ever removed, so waypoints marked at sea and a route someone is working on are safe. To replace one with the template's, delete it on that computer first, then use the template again.

**Online overlays** are switched on or off once, when the template is used; after that each computer can switch them as it likes.

**Minimum Spyhop version:** a template names the oldest Spyhop that can use it (0.28.0 at the lowest). A computer with an older Spyhop shows the template with a problem and won't use it until Spyhop is updated (Settings → About → Updates, again by hand).

Other files in the template, such as a README, are listed and left alone.

## The record of changes

Each template keeps a record of its changes, one entry per change: the date, who changed it, what changed, and notes. Spyhop adds an entry each time you save or update a template, and shows the latest changes when someone checks it. The list shows the latest change of every template, and which one this computer is using.

## Making and changing a template

1. Set up one computer the way the team wants: lists and shortcuts (**Settings → Dropdowns** and **Settings → Shortcuts**), Settings → General, the network inputs (**Settings → Inputs**) and online overlays (**Tools → Overlays**), and the waypoints, routes and overlays to hand out.
2. In **Settings → Templates**, press **Save as a new template…**, or **Update…** on the template you are changing.
3. Spyhop asks for **your name** and **what you changed** (and, for a new template, its name). It fills in **Parts changed** itself: for a new template, the parts changed since this computer last used or saved a template ("all" if it doesn't know); for an update, the parts that differ from that template.
   - **Also include:** tick **Waypoints**, **Routes** and **Overlays** to put them in the template (all of this computer's, with how many). Updating a template starts with that template's choice; a new template with the last choice made here. Keep **Which online overlays are switched on** ticked to hand out the overlays showing now.
   - **Needs Spyhop version … or newer:** the minimum version (0.28.0 at the lowest, this computer's version at the highest). Raise it when the team should all have updated before using this template.
4. To share it, press **Download** (or **Open the templates folder**) and publish the file as described below. Upload a new version in place of the old one at the same address. In Google Drive, right-click the file → **File information → Manage versions → Upload new version**, so the link stays the same.

Updating a template continues that template's own record of changes. A new template starts from this computer's record (the record of the template it last used).

## Where to put it

Use an address that downloads the template **without signing in**, because Spyhop doesn't sign in to anything:

- **GitHub** (recommended): a public repository holding the files. It keeps a history of every change, and anyone in the team can propose changes.
  - Paste the repository's address (`https://github.com/your-team/spyhop-template`), or a folder in it (`https://github.com/your-team/templates/tree/main/aerial`).
  - Spyhop downloads the latest version of the default branch, or of the branch named in the address.
- **A zip on GitHub:** commit the template's zip to a repository and paste the address of its page on GitHub. Spyhop downloads just that file. You can also attach the zip to a GitHub release and paste its download link.
- **Dropbox:** share the zip file (or the template folder) with "Anyone with the link", and paste that link. Spyhop turns it into a direct download.
- **Google Drive:** upload the **zip** (Drive can't download a folder from a link), share it with "Anyone with the link", and paste that link.
- **A website:** any `https://…/something.zip`.

SharePoint and OneDrive links within an organization usually require signing in, so they don't work here. Partners outside your organization also can't open them.

You can also type the **path of a zip or folder on this computer**, such as a template on a USB stick. Simpler still, copy the file into `templates/saved`: it then appears in the list (press **Refresh**).

## Using a template

1. Press **Use this template…** on a template in the list. For the team's template on the web, paste its address once under **Get a template from the web** (Spyhop remembers it) and press **Check**.
2. Spyhop lists what would happen to each part of the template: new, changed, same, removed, or *already here — this computer's is kept*, with row counts and the settings that would change (e.g. *Clock: local → UTC*). It also shows the minimum Spyhop version, which online overlays it switches on, the template's recent changes and any problems.
3. Leave **Save a backup of the current template first** ticked. Backups go in `templates/backups`.
4. Press **Use it** (or **Pull it** for a template from the web). The template's files replace the ones in `templates/current`, and the new lists, shortcuts, settings and inputs are used straight away, with no need to restart. A template from the web is also saved in `templates/saved`, replacing an older copy with the same name.

**A template with any problem isn't used at all.** Problems are parts Spyhop can't read: a list missing its `name` column, a `spyhop-config.json` that isn't valid, or a saved report with a mistake. Spyhop names them, and nothing on the computer changes.

**During a survey:** using a template is allowed, after a warning. Rows already recorded are never changed. If a template removes a list entry that earlier rows use, those rows keep their values, and the Error check flags them as "not in the list".

## Undoing it

Each backup is itself a template. The latest backups are listed under **Backups**; press **Restore…** on one, then **Restore**. **Open the backups folder** shows them all.

Backups always hold the computer's waypoints, routes, overlays, settings and saved reports (even when there are none, so restoring removes reports a template added). Restoring the backup made just before a template was used also **removes the map feeds, waypoints, routes and overlays that template added** (the list shows them as *Will be removed*), and puts the settings back.

## Before Spyhop 0.28

Until 0.27 the lists, shortcuts and settings were at the top of Spyhop's folder (with `settings/` and `reports/` folders), and templates were in the survey data folder. Spyhop 0.28 moves them into the `templates` folder the first time it runs. Templates saved by Spyhop 0.24–0.27 still work; *config packs* from 0.23 and before can't be read any more. Until Spyhop 1.0, templates and settings may change between versions without being converted.
