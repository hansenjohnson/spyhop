# Config packs

A **config pack** holds one set of Spyhop config files: the species, event types, observers and behaviours lists, keyboard shortcuts, map display, report templates and saved filters. It lets a team use the same lists on every computer, and lets one computer switch between setups (for example a vessel crew and an aerial crew).

Packs are managed in **Settings → Templates**. They are kept in the **`config_packs` folder in the survey data folder**, and Spyhop lists every pack there. For each one it shows the latest change, whether it matches this computer's config, and which pack is in use. From the list you can:

- **Use this pack…:** see what would change, then overwrite this computer's config files with the pack's (a backup is saved first).
- **Overwrite…:** replace the pack with this computer's config, adding your name and what changed to its record of changes.
- **Download:** get the file, to upload it for the team.
- **Save this computer's config as a new pack…** (under the list): give it a name, your name and what changed.

Spyhop names the packs it saves **`<name>.spyhop.zip`**. They are ordinary zip files, so they open in any zip tool, and the double ending marks them as Spyhop packs. Spyhop also reads packs named `.zip` or `.spyhop`.

A team usually keeps its pack on the web too, so each computer can get the latest when it has internet (**Get a pack from the web**). Nothing is downloaded until someone presses **Check**. A pack is small (usually well under 100 KB), so checking at sea costs very little. Spyhop keeps a copy of each pack it pulls in the config packs folder, so it can be used again offline.

## What's in a pack

A pack is a zip file (or, on GitHub, a repository or a folder in one) containing any of these:

| File | What it is |
|---|---|
| `spyhop-config.csv` | The record of changes (see below). Optional, but strongly recommended. |
| `species.csv`, `event_types.csv`, `observers.csv`, `behaviors.csv` | The drop-down lists. |
| `shortcuts.csv` | Keyboard shortcuts. |
| `display.csv` | Map display: marker shapes and colours, track styles, text sizes. Leave it out if each person should keep their own. |
| `reports/*.json` | Report templates (see `spyhop/report_defs/README.md`). |
| `filters/*.json` | Saved filters (Tools → Filter), one file each. |

**Only the files in the pack are changed.** For example, a pack with only `species.csv` and `observers.csv` changes only those two lists on each computer.

**Report templates go as a set.** If the pack has a `reports` folder with templates in it, each computer ends up with exactly those templates: any other templates of its own are removed. A pack with no templates leaves each computer's templates alone. **Saved filters** work the same way: a pack with a `filters` folder replaces each computer's saved filters with its own.

Survey data, waypoints and personal settings (data folder, GPS inputs, clock, sleep and the rest of Settings → General) are never in a pack and never changed by one.

Other files in the pack, such as a README, are listed and left alone.

## The record of changes: `spyhop-config.csv`

A plain CSV that you can edit in Excel, with one row per change:

| Date | Changed by | Files | Notes |
|---|---|---|---|
| 2026-10-01 | H. Johnson | all | First version of the team pack |
| 2026-11-06 | H. Johnson | species.csv; reports/gear.json | Added Dead bird; gear report shows IDs |

- Write dates as `YYYY-MM-DD`, so they sort properly.
- Add a row each time you change the pack. The rows can be in any order; Spyhop shows the newest first.
- When someone checks the pack, Spyhop shows them the latest changes. The list shows the latest change of every pack, and which one this computer is using.
- In Excel, use **File → Save As → CSV UTF-8**, to keep accented names.

## Making and changing a pack

1. Set up the lists and shortcuts the way the team wants (**Settings → Dropdowns** and **Settings → Shortcuts**).
2. In **Settings → Templates**, press **Save this computer's config as a new pack…**, or **Overwrite…** on the pack you are updating.
3. Spyhop asks for **your name** and **what changed** (and, for a new pack, its name). It fills in **Files changed** itself: for a new pack, the files changed since this computer last used or saved a pack ("all" if it doesn't know); for an overwrite, the files that differ from that pack. It adds this as a row to the pack's `spyhop-config.csv` and saves the pack in the config packs folder.
4. To leave a file out (such as `display.csv`), unzip the pack, delete the file, and zip it again.
5. To share it, press **Download** (or **Open the config packs folder**) and publish the file as described below. Upload a new version in place of the old one at the same address. In Google Drive, right-click the file → **File information → Manage versions → Upload new version**, so the link stays the same.

Overwriting a pack continues that pack's own record of changes. A new pack starts from this computer's record (the record of the pack it last used).

## Where to put it

Use an address that downloads the pack **without signing in**, because Spyhop doesn't sign in to anything:

- **GitHub** (recommended): a public repository holding the files. It keeps a history of every change, and anyone in the team can propose changes.
  - Paste the repository's address (`https://github.com/your-team/spyhop-config`), or a folder in it (`https://github.com/your-team/configs/tree/main/aerial`).
  - Spyhop downloads the latest version of the default branch, or of the branch named in the address.
- **A zip on GitHub:** commit the pack's zip to a repository (for example `configs/neaq-aerial.zip`) and paste the address of its page on GitHub. Spyhop downloads just that file. You can also attach the zip to a GitHub release and paste its download link. Zip the pack again each time you change it.
- **Dropbox:** share the zip file (or the pack folder) with "Anyone with the link", and paste that link. Spyhop turns it into a direct download.
- **Google Drive:** upload the **zip** (Drive can't download a folder from a link), share it with "Anyone with the link", and paste that link.
- **A website:** any `https://…/something.zip`.

SharePoint and OneDrive links within an organisation usually require signing in, so they don't work here. Partners outside your organisation also can't open them.

You can also type the **path of a zip or folder on this computer**, such as a pack on a USB stick. Simpler still, copy the file into the config packs folder: it then appears in the list.

## Using a pack

1. Press **Use this pack…** on a pack in the list. For the team's pack on the web, paste its address once under **Get a pack from the web** (Spyhop remembers it) and press **Check**.
2. Spyhop lists every file in the pack and what would happen to it (new, changed, same, or removed), with row counts. It also shows the pack's recent changes and any problems.
3. Leave **Save a backup of this computer's config files first** ticked. By default backups go in `config_packs/backups` in the survey data folder; you can choose another folder.
4. Press **Use it and overwrite** (or **Pull and overwrite** for a web pack). The new lists, shortcuts and templates are used straight away, with no need to restart. A web pack is also saved in the config packs folder, replacing an older copy with the same name.

**Nothing is merged.** Each file from the pack replaces this computer's copy, so changes made on this computer to those files are lost, apart from the backup. If a file should differ on one computer, leave it out of the pack.

**A pack with any problem isn't pulled at all.** Problems are files Spyhop can't read: a list missing its `name` column, or a report template or saved filter with a mistake. Spyhop names the problem files, and nothing on the computer changes.

**During a survey:** using a pack is allowed, after a warning. Rows already recorded are never changed. If a pull removes a list entry that earlier rows use, those rows keep their values, and Quality Control flags them as "not in the list".

## Undoing it

Each backup is itself a pack. The latest backups are listed under **Backups**; press **Restore…** on one, then **Restore and overwrite**. **Open the backups folder** shows them all.

A backup made when the computer had no report templates (or saved filters) of its own includes a small marker file, so restoring it also removes the ones the pack added.

Backups saved before Spyhop 0.14.0 are in the `config_backups` folder in Spyhop's own folder. To restore one, copy it into the backups folder, or type its path under **Get a pack from the web**.
