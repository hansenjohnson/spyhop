# Group config packs

A **config pack** lets a team share one set of Spyhop config files: the species, event types, observers and behaviours lists, keyboard shortcuts, map display and report templates. Someone in the team keeps the pack on the web. Each computer pulls the latest pack from **Survey → Settings → Group config** whenever it has an internet connection.

Nothing is downloaded until someone presses **Check for new config**. A pack is small (usually well under 100 KB), so checking at sea costs very little.

## What's in a pack

A pack is a zip file (or, on GitHub, a repository or a folder in one) containing any of these:

| File | What it is |
|---|---|
| `spyhop-config.csv` | The record of changes (see below). Optional, but strongly recommended. |
| `species.csv`, `event_types.csv`, `observers.csv`, `behaviors.csv` | The drop-down lists. |
| `shortcuts.csv` | Keyboard shortcuts. |
| `display.csv` | Map display: marker shapes and colours, track styles, text sizes. Leave it out if each person should keep their own. |
| `reports/*.json` | Report templates (see `spyhop/report_defs/README.md`). |

**Only the files in the pack are changed.** For example, a pack with only `species.csv` and `observers.csv` changes only those two lists on each computer.

**Report templates go as a set.** If the pack has a `reports` folder with templates in it, each computer ends up with exactly those templates: any other templates of its own are removed. A pack with no templates leaves each computer's templates alone.

Survey data, waypoints and personal settings (data folder, GPS inputs, clock, sleep and the rest of Survey → Settings) are never in a pack and never changed by one.

Other files in the pack, such as a README, are listed and left alone.

## The record of changes: `spyhop-config.csv`

A plain CSV that you can edit in Excel, with one row per change:

| Date | Changed by | Files | Notes |
|---|---|---|---|
| 2026-10-01 | H. Johnson | all | First version of the team pack |
| 2026-11-06 | H. Johnson | species.csv; reports/gear.json | Added Dead bird; gear report shows IDs |

- Write dates as `YYYY-MM-DD`, so they sort properly.
- Add a row each time you change the pack. The rows can be in any order; Spyhop shows the newest first.
- When someone checks the pack, Spyhop shows them the latest changes. After a pull, the latest change is shown in Settings, so anyone can see which version a computer has.
- In Excel, use **File → Save As → CSV UTF-8**, to keep accented names.

## Making a pack

1. On a computer whose config files are set up the way the team wants, open **Survey → Settings → Group config** and press **Make a pack from this computer**. This downloads a zip with all the config files and a starter `spyhop-config.csv`.
2. Unzip it. Delete any files the team shouldn't share, such as `display.csv`.
3. Edit the `Notes` in `spyhop-config.csv`, and add your name under `Changed by`.
4. Zip the folder again, or put the files in a GitHub repository, and publish it as described below.

To change the pack later, edit the files, add a row to `spyhop-config.csv`, and publish the new version at the same address.

Before publishing a change, it's worth checking that it pulls cleanly. Type the path of the zip or folder on your own computer into **Web address of the pack** and press **Check for new config**: Spyhop lists any problems without changing anything.

## Where to put it

Use an address that downloads the pack **without signing in**, because Spyhop doesn't sign in to anything:

- **GitHub** (recommended): a public repository holding the files. It keeps a history of every change, and anyone in the team can propose changes.
  - Paste the repository's address (`https://github.com/your-team/spyhop-config`), or a folder in it (`https://github.com/your-team/configs/tree/main/aerial`).
  - Spyhop downloads the latest version of the default branch, or of the branch named in the address.
- **Dropbox:** share the zip file (or the pack folder) with "Anyone with the link", and paste that link. Spyhop turns it into a direct download.
- **Google Drive:** upload the **zip** (Drive can't download a folder from a link), share it with "Anyone with the link", and paste that link.
- **A website:** any `https://…/something.zip`.

SharePoint and OneDrive links within an organisation usually require signing in, so they don't work here. Partners outside your organisation also can't open them.

You can also type the **path of a zip or folder on this computer**, such as a pack copied from a USB stick, or a backup.

## Pulling on each computer

1. Open **Survey → Settings → Group config**, paste the address once (Spyhop remembers it), and press **Check for new config**.
2. Spyhop lists every file in the pack and what would happen to it (new, changed, same, or removed), with row counts. It also shows the pack's recent changes and any problems.
3. Leave **Save a backup of this computer's config files first** ticked. You can choose where the backup goes; by default it's the `config_backups` folder inside the Spyhop folder.
4. Press **Pull and overwrite**. The new lists, shortcuts and templates are used straight away, with no need to restart.

**Nothing is merged.** Each file from the pack replaces this computer's copy, so changes made on this computer to those files are lost, apart from the backup. If a file should differ on one computer, leave it out of the pack.

**A pack with any problem isn't pulled at all.** Problems are files Spyhop can't read: a list missing its `name` column, or a report template with a mistake. Spyhop names the problem files, and nothing on the computer changes.

**During a survey:** pulling is allowed, after a warning. Rows already recorded are never changed. If a pull removes a list entry that earlier rows use, those rows keep their values, and Quality Control flags them as "not in the list".

## Undoing a pull

Each backup is itself a pack. To go back, type the backup's path (shown after the pull, and kept in the backups folder; **Open the backups folder** opens it) into **Web address of the pack**, then press **Check** and **Pull**.

A backup made when the computer had no report templates of its own includes a small marker file, so pulling it also removes the templates the pull added.
