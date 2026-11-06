"""Group config packs: a team's shared lists, shortcuts, map settings and report templates.

A pack is a zip (or a folder) holding any of the files in PACK_CSV, report templates in
`reports/*.json`, and `spyhop-config.csv`, a log of changes in plain CSV:

    Date,Changed by,Files,Notes
    2026-11-06,Hansen Johnson,species.csv,Added Dead bird

A team puts the pack on the web (a GitHub repository, a Dropbox or Google Drive link, any
website). Each computer checks the address in Survey → File → Group config, sees what would
change, and pulls it. Pulling replaces this computer's copy of each file the pack has; it
never merges. Report templates are replaced as a set when the pack has any. A backup zip of
the current files (itself a valid pack) can be saved first.

Nothing in a pack is run: CSVs are checked for their columns, report templates are checked
like any other, and files Spyhop doesn't know are listed and left alone.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from . import __version__, reports

MANIFEST = "spyhop-config.csv"
MANIFEST_HEADER = ["Date", "Changed by", "Files", "Notes"]
# the CSV files a pack may hold, with the columns each must have
PACK_CSV = {
    "species.csv": ["name"],
    "event_types.csv": ["name"],
    "observers.csv": ["name"],
    "behaviors.csv": ["name"],
    "shortcuts.csv": ["combo", "action"],
    "display.csv": ["key", "value"],
}
# in a backup made when there were no report templates, so pulling it removes any added since
NO_REPORTS = "reports/_no_report_templates.txt"
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 30
CACHE_S = 15 * 60


class PackError(Exception):
    """A message to show the user."""


# ------------------------------------------------------------------ addresses
def resolve(address: str) -> tuple[str, str]:
    """(kind, target) for what the user typed: ("file", path) for a zip or folder on this
    computer, else ("url", the address to download), with shared-link pages turned into
    direct downloads. A GitHub repository (or a folder in one) becomes its zip, and the
    folder is returned after a '#'."""
    a = (address or "").strip().strip('"')
    if not a:
        raise PackError("Enter the web address of your group's config pack.")
    if a.startswith("file://"):
        return "file", urllib.parse.unquote(urllib.parse.urlparse(a).path)
    if not re.match(r"^https?://", a, re.I):
        p = Path(a).expanduser()
        if p.is_absolute() or p.exists():
            return "file", str(p)
        raise PackError("That doesn't look like a web address (it should start with https://).")
    u = urllib.parse.urlparse(a)
    host = u.netloc.lower()
    parts = [x for x in u.path.split("/") if x]
    if host in ("github.com", "www.github.com") and len(parts) >= 2:
        owner, repo = parts[0], parts[1].removesuffix(".git")
        if len(parts) == 2:
            return "url", f"https://api.github.com/repos/{owner}/{repo}/zipball"
        if len(parts) >= 5 and parts[2] in ("blob", "raw") and parts[-1].lower().endswith(".zip"):
            # a zip committed to the repository: its raw download, not a zip of the repository
            return "url", f"https://raw.githubusercontent.com/{owner}/{repo}/{'/'.join(parts[3:])}"
        if len(parts) >= 4 and parts[2] in ("tree", "blob"):
            sub = "/".join(parts[4:])
            return "url", f"https://api.github.com/repos/{owner}/{repo}/zipball/{parts[3]}" + (f"#{sub}" if sub else "")
    if host.endswith("dropbox.com"):
        q = dict(urllib.parse.parse_qsl(u.query))
        q["dl"] = "1"
        return "url", urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q)))
    if host == "drive.google.com":
        m = re.search(r"/file/d/([^/]+)", u.path)
        fid = m.group(1) if m else dict(urllib.parse.parse_qsl(u.query)).get("id")
        if "/drive/folders/" in u.path:
            raise PackError("Google Drive can't download a folder from a link. Zip the pack, upload the zip, and share that file.")
        if fid:
            return "url", f"https://drive.google.com/uc?export=download&id={fid}"
    return "url", a


def fetch(address: str) -> tuple[dict[str, bytes], str]:
    """The pack's files as {path inside the pack: bytes}, and a short description of the source."""
    kind, target = resolve(address)
    if kind == "file":
        p = Path(target)
        if p.is_dir():
            files = {}
            for f in p.rglob("*"):
                if f.is_file() and not any(x.startswith(".") for x in f.relative_to(p).parts):
                    files[f.relative_to(p).as_posix()] = f.read_bytes()
            return files, str(p)
        if not p.is_file():
            raise PackError(f"There's no file or folder at {p}.")
        return _unzip(p.read_bytes(), ""), str(p)
    url, _, sub = target.partition("#")
    req = urllib.request.Request(url, headers={"User-Agent": f"Spyhop/{__version__}", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PackError(f"The web server refused (error {e.code}). The pack must be shared so anyone with the link can open it, without signing in.")
        if e.code == 404:
            raise PackError("Nothing was found at that address (error 404). Check the link, and that it's shared publicly.")
        raise PackError(f"The web server answered with error {e.code}.")
    except (urllib.error.URLError, OSError) as e:
        raise PackError(f"Couldn't reach that address. Are you online? ({getattr(e, 'reason', e)})")
    if len(data) > MAX_BYTES:
        raise PackError("That download is over 50 MB, which is far too big for a config pack.")
    if not data.startswith(b"PK"):
        head = data[:600].decode("utf-8", "replace").lower()
        if "<html" in head or "<!doctype" in head:
            raise PackError("That address gave a web page, not a zip file. Use a direct download link (see the help below), "
                            "and check the file is shared with anyone who has the link.")
        raise PackError("That address didn't give a zip file.")
    return _unzip(data, sub), url


def _unzip(data: bytes, sub: str) -> dict[str, bytes]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackError("The zip file is damaged.")
    out = {}
    for i in z.infolist():
        name = i.filename.replace("\\", "/")
        if i.is_dir() or name.startswith("/") or ".." in PurePosixPath(name).parts or "__MACOSX" in name:
            continue
        if i.file_size > MAX_BYTES:
            continue
        out[name] = z.read(i)
    if sub:
        # GitHub zips have one top folder (owner-repo-sha); the folder asked for is inside it
        tops = {n.split("/", 1)[0] for n in out}
        pre = (next(iter(tops)) + "/" if len(tops) == 1 else "") + sub.strip("/") + "/"
        out = {n[len(pre):]: b for n, b in out.items() if n.startswith(pre)}
        if not out:
            raise PackError(f"The folder {sub} isn't in that repository.")
    return out


# ------------------------------------------------------------------ reading a pack
def _root(files: dict[str, bytes]) -> str:
    """The folder inside the zip that holds the pack (zips often have one top folder)."""
    known = set(PACK_CSV) | {MANIFEST}
    cands = []
    for n in files:
        parts = n.split("/")
        if parts[-1] in known:
            cands.append("/".join(parts[:-1]))
        elif len(parts) >= 2 and parts[-2] == "reports" and (parts[-1].endswith(".json") or parts[-1] == NO_REPORTS.split("/")[1]):
            cands.append("/".join(parts[:-2]))
    if not cands:
        raise PackError("That doesn't look like a Spyhop config pack: it has none of spyhop-config.csv, "
                        "species.csv, observers.csv, event_types.csv, behaviors.csv, shortcuts.csv, display.csv "
                        "or reports/*.json.")
    return min(cands, key=lambda c: (c.count("/") if c else -1, c))


def _text(b: bytes, name: str) -> str:
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return b.decode("cp1252")             # saved by Excel on Windows
        except UnicodeDecodeError:
            raise PackError(f"{name} isn't a text file Spyhop can read (save it as CSV UTF-8).")


def _csv_rows(text: str) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]


def read_manifest(text: str) -> list[dict]:
    rows = _csv_rows(text)
    if not rows:
        return []
    hdr = [h.strip().lower() for h in rows[0]]
    idx = {k: (hdr.index(k.lower()) if k.lower() in hdr else None) for k in MANIFEST_HEADER}
    out = []
    for r in rows[1:]:
        g = lambda k: r[idx[k]].strip() if idx[k] is not None and idx[k] < len(r) else ""  # noqa: E731
        out.append({"date": g("Date"), "by": g("Changed by"), "files": g("Files"), "notes": g("Notes")})
    # newest first (ISO dates sort as text); on the same date, the row added last comes first
    order = sorted(range(len(out)), key=lambda i: (out[i]["date"], i), reverse=True)
    return [out[i] for i in order]


def read_pack(files: dict[str, bytes]) -> dict:
    """{csv: {name: text}, reports: {name: text} | None, manifest: [...], ignored: [...], problems: [...]}"""
    root = _root(files)
    pre = root + "/" if root else ""
    inside = {n[len(pre):]: b for n, b in files.items() if n.startswith(pre)}
    pack = {"csv": {}, "reports": None, "manifest": [], "manifest_text": "", "ignored": [], "problems": []}
    for name, b in sorted(inside.items()):
        if name == MANIFEST:
            try:
                pack["manifest_text"] = _text(b, name)
                pack["manifest"] = read_manifest(pack["manifest_text"])
            except PackError as e:
                pack["problems"].append(str(e))
        elif name in PACK_CSV:
            try:
                text = _text(b, name)
            except PackError as e:
                pack["problems"].append(str(e))
                continue
            rows = _csv_rows(text)
            hdr = [h.strip() for h in rows[0]] if rows else []
            missing = [c for c in PACK_CSV[name] if c not in hdr]
            if missing:
                pack["problems"].append(f"{name} needs the column{'s' if len(missing) > 1 else ''} "
                                        f"{', '.join(missing)} in its first row.")
            else:
                pack["csv"][name] = text
        elif name.startswith("reports/") and name.count("/") == 1 and name.endswith(".json"):
            fn = name.split("/", 1)[1]
            if pack["reports"] is None:
                pack["reports"] = {}
            try:
                text = _text(b, name)
                d = json.loads(text)
            except (PackError, ValueError) as e:
                pack["problems"].append(f"{name} isn't valid JSON ({e}).")
                continue
            if not (isinstance(d, dict) and d.get("enabled") is False):
                why = reports._validate(d, "pack")
                if why:
                    pack["problems"].append(f"{name}: {why}.")
                    continue
            pack["reports"][fn] = text
        elif name == NO_REPORTS:
            if pack["reports"] is None:
                pack["reports"] = {}
        elif name.startswith("reports/") and (name.endswith("README.md") or "/examples/" in name):
            continue
        else:
            pack["ignored"].append(name)
    return pack


# ------------------------------------------------------------------ comparing / applying
def _local_text(p: Path) -> str | None:
    try:
        return _text(p.read_bytes(), p.name)
    except (OSError, PackError):
        return None


def _norm(text: str | None) -> list[list[str]] | None:
    return None if text is None else [[c.strip() for c in r] for r in _csv_rows(text)]


def _count(text: str | None) -> int | None:
    rows = _norm(text)
    return None if rows is None else max(0, len(rows) - 1)


def compare(cfg, pack: dict) -> list[dict]:
    """What a pull would do, file by file: new | changed | same | removed."""
    out = []
    for name, text in pack["csv"].items():
        here = _local_text(cfg.root / name)
        st = "new" if here is None else ("same" if _norm(here) == _norm(text) else "changed")
        out.append({"file": name, "status": st, "here": _count(here), "pack": _count(text), "unit": "rows"})
    if pack["reports"] is not None:
        rdir = reports.user_dir(cfg)
        local = {p.name: p for p in rdir.glob("*.json")} if rdir.is_dir() else {}
        for fn, text in sorted(pack["reports"].items()):
            here = _local_text(local[fn]) if fn in local else None
            st = "new" if here is None else ("same" if _json_eq(here, text) else "changed")
            out.append({"file": f"reports/{fn}", "status": st, "unit": "report"})
        for fn in sorted(set(local) - set(pack["reports"])):
            out.append({"file": f"reports/{fn}", "status": "removed", "unit": "report"})
    order = {"changed": 0, "new": 1, "removed": 2, "same": 3}
    return sorted(out, key=lambda r: (order[r["status"]], r["file"]))


def _json_eq(a: str, b: str) -> bool:
    try:
        return json.loads(a) == json.loads(b)
    except ValueError:
        return a == b


def config_files(cfg) -> dict[str, Path]:
    """This computer's config files that a pack can hold, as {path in a pack: file}."""
    out = {n: cfg.root / n for n in PACK_CSV if (cfg.root / n).is_file()}
    rdir = reports.user_dir(cfg)
    if rdir.is_dir():
        out.update({f"reports/{p.name}": p for p in sorted(rdir.glob("*.json"))})
    if (cfg.root / MANIFEST).is_file():
        out[MANIFEST] = cfg.root / MANIFEST
    return out


def safe_pack_name(name) -> str:
    """A file name for a pack zip, or "" for none."""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip()).strip(" .")
    if not n:
        return ""
    return n if n.lower().endswith(".zip") else n + ".zip"


def fingerprints(cfg) -> dict[str, str]:
    """A hash of each config file a pack can hold (not the change log), to tell later which changed."""
    out = {}
    for name, p in config_files(cfg).items():
        if name == MANIFEST:
            continue
        text = _local_text(p)
        if text is None:
            continue
        body = json.dumps(_norm(text)) if name.endswith(".csv") else text.strip()
        out[name] = hashlib.sha1(body.encode("utf-8")).hexdigest()
    return out


def changed_since(cfg, before: dict | None) -> list[str] | None:
    """The config files added, changed or removed since `before` (fingerprints), or None if unknown."""
    if not before:
        return None
    now = fingerprints(cfg)
    names = sorted(set(now) | set(before))
    return [n for n in names if now.get(n) != before.get(n)]


def log_change(cfg, by: str, files: str, notes: str) -> list[str]:
    """Add a row to this computer's spyhop-config.csv (created if needed). Returns the row."""
    p = cfg.root / MANIFEST
    text = _local_text(p) if p.is_file() else None
    rows = _csv_rows(text) if text else []
    if not rows:
        rows = [MANIFEST_HEADER]
    row = [date.today().isoformat(), by.strip(), files.strip(), notes.strip()]
    rows.append(row)
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    _write(p, "\ufeff" + out.getvalue())
    return row


def make_zip(cfg, note: str = "", backup: bool = False) -> bytes:
    """A zip of this computer's config files: a backup, and a pack another computer can pull.
    A backup also records "no report templates" when there were none, so pulling it undoes exactly."""
    buf = io.BytesIO()
    files = config_files(cfg)
    manifest = files.pop(MANIFEST, None)
    text = _local_text(manifest) if manifest else None
    rows = _csv_rows(text) if text else []
    if not rows:
        rows = [MANIFEST_HEADER]
    if note:                                   # a backup notes itself in its own copy of the log
        rows.append([date.today().isoformat(), "", "", note])
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, "\ufeff" + out.getvalue())       # the BOM makes Excel read it as UTF-8
        for name, p in files.items():
            z.write(p, name)
        if backup and not any(n.startswith("reports/") for n in files):
            z.writestr(NO_REPORTS, "This computer had no report templates of its own when this was made.\n"
                                   "Pulling this pack removes any added since. Delete this file to leave templates alone.\n")
    return buf.getvalue()


def save_backup(cfg, folder: str | Path | None) -> Path:
    d = Path(folder).expanduser() if folder else cfg.root / "config_backups"
    if folder and not d.is_absolute():
        raise PackError("Give the full path of the backup folder.")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise PackError(f"Can't use {d} for the backup: {e}")
    p = d / f"spyhop-config-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    p.write_bytes(make_zip(cfg, f"Backup of this computer's config files (Spyhop {__version__})", backup=True))
    return p


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, p)


def apply(cfg, pack: dict) -> list[str]:
    """Replace this computer's files with the pack's. Returns the files changed."""
    if pack["problems"]:
        raise PackError("The pack has problems, so nothing was changed:\n" + "\n".join(pack["problems"]))
    plan = compare(cfg, pack)
    for name, text in pack["csv"].items():
        _write(cfg.root / name, text)
    if pack["reports"] is not None:
        rdir = reports.user_dir(cfg)
        rdir.mkdir(parents=True, exist_ok=True)
        for fn, text in pack["reports"].items():
            _write(rdir / fn, text)
        for p in rdir.glob("*.json"):
            if p.name not in pack["reports"]:
                p.unlink()
    if pack["manifest_text"]:
        _write(cfg.root / MANIFEST, pack["manifest_text"])
    cfg.ensure_defaults()          # adds columns a newer Spyhop needs; never removes anything
    cfg.reload()
    return [r["file"] for r in plan if r["status"] != "same"]


# ------------------------------------------------------------------ cache between check and pull
_cache: dict[str, tuple[float, str, dict]] = {}


def remember(address: str, pack: dict) -> str:
    now = time.monotonic()
    for k in [k for k, v in _cache.items() if now - v[0] > CACHE_S]:
        _cache.pop(k, None)
    token = secrets.token_hex(8)
    _cache[token] = (now, address, pack)
    return token


def recall(token: str) -> tuple[str, dict] | None:
    v = _cache.get(token or "")
    if not v or time.monotonic() - v[0] > CACHE_S:
        return None
    return v[1], v[2]
