"""Create a double-clickable "Spyhop" shortcut.

    python -m spyhop --install-shortcut [--if-needed]

The shortcut opens the "Start Spyhop" file in a Terminal / console window, the
same as double-clicking that file. Spyhop needs that window: run as a hidden
background process, macOS (and Windows on battery) slow it down to save power.

macOS:   Spyhop.app in Applications (or ~/Applications if that isn't writable), plus a link on the Desktop.
Windows: Spyhop shortcuts on the Desktop and in the Start menu.
Linux:   a Spyhop entry in the applications menu, plus one on the Desktop.

The shortcut is built on this computer rather than shipped in the zip.
macOS and Windows block files downloaded from the internet until you approve
them; a shortcut made locally isn't marked as downloaded, so it opens with no
warnings. It also points at this folder, so if you move the Spyhop folder,
run the set-up file again.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

HERE = Path(__file__).resolve().parent          # the spyhop package
ROOT = HERE.parent                               # the folder with the launchers
IMG = HERE / "web" / "img"




def _q(s: str | Path) -> str:
    """Quote for a bash script."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def _plain(p) -> str:
    """Text safe inside a double-quoted bash and AppleScript string."""
    return "".join(c for c in str(p) if c not in '"$`\\')


MARKER = ROOT / ".venv" / "spyhop_shortcut.txt"   # which folder the shortcut was made for
BUNDLE_ID = "org.spyhop.launcher"


def _mac_app_dirs() -> list[Path]:
    return [Path("/Applications"), Path.home() / "Applications"]


def _is_ours(app: Path) -> bool:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == BUNDLE_ID
    except (OSError, plistlib.InvalidFileException):
        return False


def install_mac(apps_dir: Path | None = None, desktop: Path | None = None) -> list[Path]:
    if apps_dir is None:
        apps_dir = next((d for d in _mac_app_dirs()[:1] if d.is_dir() and os.access(d, os.W_OK)),
                        Path.home() / "Applications")
        apps_dir.mkdir(exist_ok=True)
        for other in _mac_app_dirs():        # remove an older Spyhop.app elsewhere, so there's only one
            old = other / "Spyhop.app"
            if other != apps_dir and old.exists() and _is_ours(old):
                shutil.rmtree(old, ignore_errors=True)
    desktop = desktop if desktop is not None else Path.home() / "Desktop"
    app = apps_dir / "Spyhop.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir(parents=True)
    shutil.copy2(IMG / "spyhop.icns", app / "Contents" / "Resources" / "Spyhop.icns")
    (app / "Contents" / "Resources" / "folder.txt").write_text(str(ROOT))
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleName": "Spyhop",
            "CFBundleDisplayName": "Spyhop",
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleVersion": __version__,
            "CFBundleShortVersionString": __version__,
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "Spyhop",
            "CFBundleIconFile": "Spyhop",
            "LSMinimumSystemVersion": "10.13",
            "NSHighResolutionCapable": True,
        }, f)
    script = f"""#!/bin/bash
# Opens "Start Spyhop (Mac).command" from {ROOT} in Terminal.
# Made by "python -m spyhop --install-shortcut". If the Spyhop folder moves, double-click that file in its new place.
CMD={_q(ROOT / "Start Spyhop (Mac).command")}
if [ ! -f "$CMD" ]; then
  osascript -e "display alert \\"Spyhop cannot find its folder\\" message \\"It was in {_plain(ROOT)}. If you moved the Spyhop folder, double-click Start Spyhop (Mac) in its new place to update this icon.\\""
  exit 1
fi
open -a Terminal "$CMD"
"""
    exe = app / "Contents" / "MacOS" / "Spyhop"
    exe.write_text(script)
    exe.chmod(0o755)
    made = [app]
    if desktop and desktop.is_dir():
        link = desktop / "Spyhop"
        if link.is_symlink() or link.is_file():
            link.unlink()
        if not link.exists():
            link.symlink_to(app)
            made.append(link)
    return made


def install_windows() -> list[Path]:
    bat = ROOT / "Start Spyhop (Windows).bat"
    icon = IMG / "spyhop.ico"
    ps = r"""
$ErrorActionPreference = 'Stop'
$sh = New-Object -ComObject WScript.Shell
$made = @()
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  if (-not $dir) { continue }
  $path = Join-Path $dir 'Spyhop.lnk'
  $s = $sh.CreateShortcut($path)
  $s.TargetPath = '%BAT%'
  $s.WorkingDirectory = '%ROOT%'
  $s.IconLocation = '%ICON%,0'
  $s.Description = 'Spyhop whale survey recorder'
  $s.Save()
  $made += $path
}
$made -join "`n"
""".replace("%BAT%", str(bat).replace("'", "''")).replace("%ROOT%", str(ROOT).replace("'", "''")) \
       .replace("%ICON%", str(icon).replace("'", "''"))
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "PowerShell could not make the shortcut")
    return [Path(p) for p in out.stdout.split("\n") if p.strip()]


def install_linux(apps_dir: Path | None = None, desktop: Path | None = None) -> list[Path]:
    apps_dir = apps_dir or Path.home() / ".local" / "share" / "applications"
    desktop = desktop if desktop is not None else Path.home() / "Desktop"
    apps_dir.mkdir(parents=True, exist_ok=True)
    entry = f"""[Desktop Entry]
Type=Application
Name=Spyhop
Comment=Whale survey recorder
Exec=bash "{ROOT / 'start-spyhop.sh'}"
Path={ROOT}
Icon={IMG / 'spyhop.png'}
Terminal=true
Categories=Science;Education;
"""
    made = []
    for d in (apps_dir, desktop):
        if d and d.is_dir():
            p = d / "spyhop.desktop"
            p.write_text(entry)
            p.chmod(0o755)
            made.append(p)
    return made


def installed() -> bool:
    """True if a shortcut for this folder has already been made."""
    try:
        if MARKER.read_text().strip() != str(ROOT):
            return False
    except OSError:
        return False
    if sys.platform == "darwin":
        return any((d / "Spyhop.app").exists() for d in _mac_app_dirs())
    return True


def install() -> list[Path]:
    if sys.platform == "darwin":
        made = install_mac()
    elif sys.platform.startswith("win"):
        made = install_windows()
    else:
        made = install_linux()
    try:
        MARKER.write_text(str(ROOT))
    except OSError:
        pass
    return made


def main(if_needed: bool = False) -> int:
    if if_needed and installed():
        return 0
    try:
        made = install()
    except Exception as e:  # noqa: BLE001 — report any failure plainly
        print(f"Couldn't make the Spyhop icon: {e}")
        return 1
    print("Made the Spyhop icon:")
    for p in made:
        print(f"  {p}")
    if sys.platform == "darwin":
        print("It's in Applications (and Launchpad) and on your Desktop. Drag it to the Dock to keep it handy.")
        try:   # show it in Finder, so it's easy to find the first time
            subprocess.run(["open", "-R", str(made[0])], check=False, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    elif sys.platform.startswith("win"):
        print("It's on your Desktop and in the Start menu. Right-click it to pin it to the taskbar.")
    print("The icon opens Spyhop in a window like this one: keep that window open while you use Spyhop.")
    return 0
