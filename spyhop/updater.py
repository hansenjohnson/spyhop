"""Checking for and installing Spyhop updates (Settings → About → Updates).

Updates come from GitHub, from the hansenjohnson/spyhop repository:
- the latest **release** (a tag such as v0.9.2, made with GitHub's "Draft a new release"), or
- if no release has been published yet, the version on the **main** branch.

Installing downloads that version as a zip, keeps a backup of the current program files
(in `<Spyhop folder>/updates/`), copies the new files over the program folder (never the
`.venv`, and never your data, which lives in Spyhop's own folder), and installs any new Python
packages. Spyhop then needs a restart. A program folder that is a git checkout is updated
with `git pull` instead.

SPYHOP_UPDATE_API overrides the GitHub API address (used by the tests).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

log = logging.getLogger("spyhop.update")

REPO = "hansenjohnson/spyhop"
REPO_URL = f"https://github.com/{REPO}"
API = os.environ.get("SPYHOP_UPDATE_API", f"https://api.github.com/repos/{REPO}")
PROGRAM_DIR = Path(__file__).resolve().parent.parent
SKIP = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "logs"}
TIMEOUT = 15


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple[int, ...] | None:
    m = re.match(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    return bool(a and b and a > b)


QUICK_TIMEOUT = 4      # 0.45: the check when Spyhop starts gives up this fast (offline at sea is normal)
_timeout = TIMEOUT


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"Spyhop/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=_timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise FileNotFoundError(url) from e
        if e.code in (403, 429):
            raise UpdateError("GitHub refused the request. It limits how often one network can ask (try again in an hour), "
                              "or a network filter may be blocking it.") from e
        raise UpdateError(f"GitHub answered {e.code} {e.reason}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("Couldn't reach GitHub. Check the internet connection and try again.") from e


def git_checkout() -> bool:
    return (PROGRAM_DIR / ".git").exists()


def check(quick: bool = False) -> dict:
    """What's available: {current, latest, newer, source ('release'|'main'), notes, url, zip, published}.
    quick: each request gives up after QUICK_TIMEOUT s (the check at start-up). It never installs anything:
    installing is install(), only ever after the person says yes."""
    global _timeout
    _timeout = QUICK_TIMEOUT if quick else TIMEOUT
    try:
        return _check()
    finally:
        _timeout = TIMEOUT


def _check() -> dict:
    info = {"current": __version__, "repo": REPO_URL, "git": git_checkout()}
    try:
        rel = json.loads(_get(f"{API}/releases/latest"))
        info.update(latest=str(rel.get("tag_name", "")).lstrip("v"), source="release",
                    notes=rel.get("body") or "", url=rel.get("html_url") or f"{REPO_URL}/releases",
                    zip=rel.get("zipball_url") or f"{API}/zipball/{rel.get('tag_name')}",
                    published=rel.get("published_at") or "", name=rel.get("name") or "")
    except FileNotFoundError:
        # no release published yet (or no repository): the version on the main branch
        try:
            meta = json.loads(_get(f"{API}/contents/spyhop/__init__.py?ref=main"))
            text = base64.b64decode(meta.get("content", "")).decode("utf-8", "replace")
        except FileNotFoundError:
            raise UpdateError(f"Spyhop's GitHub repository ({REPO_URL}) isn't there yet, so there's nothing to update from.")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        if not m:
            raise UpdateError("Couldn't read the version on GitHub.")
        notes = ""
        try:
            cl = json.loads(_get(f"{API}/contents/CHANGELOG.md?ref=main"))
            notes = _changelog_since(base64.b64decode(cl.get("content", "")).decode("utf-8", "replace"), __version__)
        except (FileNotFoundError, UpdateError, ValueError):
            pass
        info.update(latest=m.group(1), source="main", notes=notes, url=REPO_URL,
                    zip=f"{API}/zipball/main", published="", name="")
    info["newer"] = is_newer(info["latest"])
    return info


def _changelog_since(md: str, current: str) -> str:
    """The CHANGELOG sections newer than the running version."""
    out, keep = [], False
    for line in md.splitlines():
        m = re.match(r"^## +v?(\d+\.\d+(?:\.\d+)?)", line)
        if m:
            keep = is_newer(m.group(1), current)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


# --------------------------------------------------------------------- installing
def _program_files(root: Path):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP for part in rel.parts) or p.suffix in (".pyc", ".tmp"):
            continue
        if p.is_file():
            yield rel


def _backup(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"spyhop-{__version__}-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in _program_files(PROGRAM_DIR):
            z.write(PROGRAM_DIR / rel, f"spyhop/{rel.as_posix()}")
    return path


def _extract(data: bytes, into: Path) -> Path:
    """Unpack the downloaded zip (keeping execute permissions) and return the folder that holds the program."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for zi in z.infolist():
            name = zi.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise UpdateError("The download looks wrong (unsafe file names); nothing was changed.")
            target = into / name
            if zi.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(zi) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            mode = (zi.external_attr >> 16) & 0o777
            if mode & 0o111:
                target.chmod(target.stat().st_mode | 0o111)
    top = next((p.parent.parent for p in into.rglob("spyhop/__init__.py")
                if (p.parent.parent / "pyproject.toml").exists()), None)
    if top is None:
        raise UpdateError("The download doesn't contain Spyhop; nothing was changed.")
    return top


def install(cfg, info: dict | None = None) -> dict:
    """Install the version check() found. Returns {installed, backup, packages, restart, message}."""
    if git_checkout():
        if not shutil.which("git"):
            raise UpdateError("This copy of Spyhop is a git checkout, but git isn't installed. Update it with git pull.")
        r = subprocess.run(["git", "-C", str(PROGRAM_DIR), "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise UpdateError(f"git pull didn't work: {(r.stderr or r.stdout).strip()[-400:]}")
        pk = _install_packages()
        return {"installed": "latest", "backup": None, "packages": pk, "restart": True,
                "message": (r.stdout.strip() or "Updated with git pull.")}
    info = info or check()
    if not info.get("newer"):
        raise UpdateError(f"Spyhop {__version__} is already the latest version.")
    if not os.access(PROGRAM_DIR, os.W_OK):
        raise UpdateError(f"Spyhop can't write to its program folder ({PROGRAM_DIR}). Download the new version from {REPO_URL} instead.")
    data = _get(info["zip"], accept="application/vnd.github+json")
    with tempfile.TemporaryDirectory(prefix="spyhop_update_") as tmp:
        top = _extract(data, Path(tmp))
        got = re.search(r'__version__\s*=\s*"([^"]+)"', (top / "spyhop" / "__init__.py").read_text(encoding="utf-8"))
        if not got or not is_newer(got.group(1)):
            raise UpdateError("The download isn't newer than this version; nothing was changed.")
        backup = _backup(cfg.root / "updates")
        new_files = set(_program_files(top))
        for rel in new_files:
            dst = PROGRAM_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmpf = dst.with_name(dst.name + ".tmp")
            shutil.copyfile(top / rel, tmpf)
            if (top / rel).stat().st_mode & 0o111:
                tmpf.chmod(tmpf.stat().st_mode | 0o111)
            os.replace(tmpf, dst)
        # program files the new version no longer has (only inside the package, never your files elsewhere)
        for rel in _program_files(PROGRAM_DIR / "spyhop"):
            if Path("spyhop") / rel not in new_files:
                try:
                    (PROGRAM_DIR / "spyhop" / rel).unlink()
                except OSError:
                    pass
    log.info("updated Spyhop %s -> %s (backup %s)", __version__, got.group(1), backup)
    pk = _install_packages()
    return {"installed": got.group(1), "backup": str(backup), "packages": pk, "restart": True,
            "message": f"Spyhop {got.group(1)} is installed. Restart Spyhop to use it."}


def _install_packages() -> str:
    """Install the Python packages the new version lists, and tell the launcher they're done."""
    req = PROGRAM_DIR / "requirements.txt"
    if not req.exists():
        return "none needed"
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"not installed ({e}); the start file will try again"
    if r.returncode:
        log.warning("pip install after update failed: %s", r.stderr[-800:])
        return "not installed; the start file will try again next time"
    stamp = PROGRAM_DIR / ".venv" / "requirements.installed"
    if stamp.parent.is_dir():
        try:
            shutil.copyfile(req, stamp)
        except OSError:
            pass
    return "up to date"


def can_restart_in_place() -> bool:
    # macOS and Linux: replace this process (same Terminal window). On Windows, ask the user.
    return os.name == "posix"


def restart():
    """Start the new version in this process (same Terminal window and port), without a new window."""
    args = [a for a in sys.argv[1:] if a not in ("--browser", "--window")]
    if "--no-browser" not in args:
        args.append("--no-browser")
    log.info("restarting Spyhop after an update")
    logging.shutdown()
    os.chdir(PROGRAM_DIR)
    os.environ["SPYHOP_RESTARTED"] = "1"          # 0.46: wait for the old one to let go of the one-Spyhop lock
    os.execv(sys.executable, [sys.executable, "-m", "spyhop", *args])
