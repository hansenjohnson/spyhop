"""Templates (Settings → Templates): a team's Spyhop settings in one small file, so every computer can
be set up to record the same way, and a computer can switch between templates.

The current template (the one in use) is kept unzipped in templates/current of Spyhop's folder:

    spyhop-config.json   everything that isn't a table: the record of changes, the shared settings, the
                         network GPS / NMEA inputs, the map feeds (addresses and how to draw them), which
                         online overlays to switch on, the map display and the saved reports
    species.csv, event_types.csv, observers.csv, behaviors.csv, shortcuts.csv
                         the drop-down lists and keyboard shortcuts (CSV, so they can be edited in a
                         spreadsheet)

A saved template (templates/saved/<name>.spyhop-template.zip) is a zip of those files, with the
oldest Spyhop that can use it and which optional parts it has in its spyhop-config.json, and
optionally waypoints.csv, routes/*.gpx and overlays/*.

Using a template replaces the lists, shortcuts, map display, saved reports (as a set, when the
template has any) and shared settings; the network inputs replace this computer's network inputs,
leaving serial ports, file replays and the simulator alone. Map feeds, waypoints, routes and overlays
are only added: one already on the computer is kept, and nothing is removed. The data folder, survey
data and offline charts are never in a template. A backup (itself a template) is saved in
templates/backups first; restoring the backup made before a template was used also takes away what
that template added.

A template has a data part (the lists and the data settings: fixed during a survey, copied into each
survey's folder) and preferences (everything else: may change at any time); see DATA_TABLES and part_of().

Nothing in a template is run: CSVs are checked for their columns, saved reports like any other, and
files Spyhop doesn't know are listed and left alone.
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
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from . import __version__, feeds, reports, schema
from .config import LOCKED_LISTS, LOCKED_SETTINGS, NETWORK_INPUTS, SHARED_SETTINGS, merge_network_inputs, without_colors

CONFIG = "spyhop-config.json"
FORMAT = 3
FORMAT_MIN = "0.28.0"            # the oldest Spyhop a template can say it needs
TEMPLATE_SUFFIX = ".spyhop-template.zip"
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 30
CACHE_S = 15 * 60

# the tables a template may hold, with the columns each must have
TABLES = {
    "species.csv": ["name"],
    "event_types.csv": ["name"],
    "observers.csv": ["name"],
    "behaviors.csv": ["name"],
    "visibility.csv": ["name"],
    "weather.csv": ["name"],
    "effort.csv": ["name", "status"],
    "reticles.csv": ["name", "method"],
    "shortcuts.csv": ["combo", "action"],
}
OPTIONAL = ("waypoints", "routes", "overlays")
WAYPOINTS = "waypoints.csv"
WAYPOINT_COLS = [h for h in schema.headers("marks") if h != "RowID"]
OVERLAY_EXT = (".geojson", ".json", ".gpx", ".kml")
ONLINE_KEYS = ("ais", "radar_us", "radar_world", "feeds", "radar_opacity", "hide_stopped")

# what each part is called in the check before using a template (and in "What changed")
SETTINGS_LABEL = "Settings (clock, units, bearings, keep awake, NMEA log)"
DATA_SETTINGS_LABEL = "Data settings (magnetic variation, track point interval, trackline breaks)"

# A template has two parts (0.40). The data part says what recorded values mean, how they are worked out
# and how they are reported (the lists, the data settings and the saved reports): it is copied into each
# survey's folder at Start, can't change during a survey, and is the only part compared with a survey's
# copy. The preferences (shortcuts, map display, the other shared settings, network inputs, map feeds)
# can change at any time, also during a survey.
# Waypoints, routes and overlays are extras, only ever added to a computer.
DATA_TABLES = tuple(f"{n}.csv" for n in LOCKED_LISTS)
PARTS = {"data": "Data (fixed during a survey)", "prefs": "Preferences (can change at any time)",
         "extra": "Added to this computer"}


def _with_other(name: str, text: str, hdr: list[str], rows: list[list[str]]) -> str:
    """A list's CSV with its Other entry (0.40: every list has one), added at the end if it's missing."""
    from .config import DEFAULT_LISTS, OTHER, other_row
    stem = name[:-4]
    if stem not in DEFAULT_LISTS or "name" not in hdr:
        return text
    i = hdr.index("name")
    if any(len(r) > i and r[i].strip().lower() == OTHER.lower() for r in rows[1:]):
        return text
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow([other_row(stem).get(c, "") for c in hdr])
    return text + ("" if text.endswith("\n") or not text else "\n") + out.getvalue()


def part_of(file: str) -> str:
    """"data", "prefs" or "extra" for a row of compare() (by its file label)."""
    if file in DATA_TABLES or file == DATA_SETTINGS_LABEL or file.startswith("Saved report: "):
        return "data"
    if file == WAYPOINTS or file.startswith(("routes/", "overlays/")):
        return "extra"
    return "prefs"


def _dict_rows(text: str | None) -> list[dict]:
    if text is None:
        return []
    return [r for r in csv.DictReader(io.StringIO(text)) if any((v or "").strip() for v in r.values())]
INPUTS_LABEL = "GPS / NMEA network inputs (UDP, TCP, gpsd)"
DISPLAY_LABEL = "Map display"

class TemplateError(Exception):
    """A message to show the user."""


# ------------------------------------------------------------------ names and folders
def is_template_name(name: str) -> bool:
    return str(name).lower().endswith(".zip")


def template_stem(name: str) -> str:
    """The name without .spyhop-template.zip or .zip."""
    n = str(name or "")
    for suf in (TEMPLATE_SUFFIX, ".zip"):
        if n.lower().endswith(suf):
            return n[: -len(suf)]
    return n


def safe_template_name(name) -> str:
    """A file name for a template Spyhop saves (<name>.spyhop-template.zip), or "" for none."""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", template_stem(str(name or "").strip())).strip(" .")
    return n + TEMPLATE_SUFFIX if n else ""


def templates_dir(cfg) -> Path:
    """templates/saved in Spyhop's folder."""
    return cfg.saved_dir


def backups_dir(cfg) -> Path:
    return cfg.backups_dir


def _template_file(cfg, name: str) -> Path:
    """A template in the templates folder, by its file name (no folders)."""
    n = str(name or "")
    if not n or "/" in n or "\\" in n or n.startswith(".") or not is_template_name(n):
        raise TemplateError("That isn't the name of a template.")
    return templates_dir(cfg) / n


def in_templates_dir(cfg, path: str) -> bool:
    try:
        return Path(path).resolve().parent == templates_dir(cfg).resolve()
    except OSError:
        return False


# ------------------------------------------------------------------ addresses
def resolve(address: str) -> tuple[str, str]:
    """(kind, target) for what the user typed: ("file", path) for a zip or folder on this
    computer, else ("url", the address to download), with shared-link pages turned into
    direct downloads. A GitHub repository (or a folder in one) becomes its zip, and the
    folder is returned after a '#'."""
    a = (address or "").strip().strip('"')
    if not a:
        raise TemplateError("Enter the web address of your team's template.")
    if a.startswith("file://"):
        return "file", urllib.parse.unquote(urllib.parse.urlparse(a).path)
    if not re.match(r"^https?://", a, re.I):
        p = Path(a).expanduser()
        if p.is_absolute() or p.exists():
            return "file", str(p)
        raise TemplateError("That doesn't look like a web address (it should start with https://).")
    u = urllib.parse.urlparse(a)
    host = u.netloc.lower()
    parts = [x for x in u.path.split("/") if x]
    if host in ("github.com", "www.github.com") and len(parts) >= 2:
        owner, repo = parts[0], parts[1].removesuffix(".git")
        if len(parts) == 2:
            return "url", f"https://api.github.com/repos/{owner}/{repo}/zipball"
        if len(parts) >= 5 and parts[2] in ("blob", "raw") and is_template_name(parts[-1]):
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
            raise TemplateError("Google Drive can't download a folder from a link. Zip the template, upload the zip, and share that file.")
        if fid:
            return "url", f"https://drive.google.com/uc?export=download&id={fid}"
    return "url", a


def fetch(address: str) -> tuple[dict[str, bytes], str]:
    """The template's files as {path inside it: bytes}, and a short description of the source."""
    files, source, _name = fetch_named(address)
    return files, source


def _download_name(url: str, headers) -> str:
    """A file name for a downloaded template: the server's, else the address's, else made from the address."""
    cd = headers.get("Content-Disposition", "") if headers else ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd) or re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    u = urllib.parse.urlparse(url)
    parts = [x for x in u.path.split("/") if x]
    if parts and is_template_name(parts[-1]):
        return urllib.parse.unquote(parts[-1])
    if u.netloc == "api.github.com" and len(parts) >= 3:          # repos/<owner>/<repo>/zipball[/branch]
        return parts[2]
    return "template from " + (u.netloc or "the web")


def fetch_named(address: str) -> tuple[dict[str, bytes], str, str]:
    """fetch(), plus a file name for a copy of the template."""
    kind, target = resolve(address)
    if kind == "file":
        p = Path(target)
        if p.is_dir():
            files = {}
            for f in p.rglob("*"):
                if f.is_file() and not any(x.startswith(".") for x in f.relative_to(p).parts):
                    files[f.relative_to(p).as_posix()] = f.read_bytes()
            return files, str(p), p.name
        if not p.is_file():
            raise TemplateError(f"There's no file or folder at {p}.")
        return unzip(p.read_bytes(), ""), str(p), p.name
    url, _, sub = target.partition("#")
    req = urllib.request.Request(url, headers={"User-Agent": f"Spyhop/{__version__}", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = r.read(MAX_BYTES + 1)
            name = _download_name(r.geturl() or url, r.headers)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TemplateError(f"The web server refused (error {e.code}). The template must be shared so anyone with the link can open it, without signing in.")
        if e.code == 404:
            raise TemplateError("Nothing was found at that address (error 404). Check the link, and that it's shared publicly.")
        raise TemplateError(f"The web server answered with error {e.code}.")
    except (urllib.error.URLError, OSError) as e:
        raise TemplateError(f"Couldn't reach that address. Are you online? ({getattr(e, 'reason', e)})")
    if len(data) > MAX_BYTES:
        raise TemplateError("That download is over 50 MB, which is far too big for a template.")
    if not data.startswith(b"PK"):
        head = data[:600].decode("utf-8", "replace").lower()
        if "<html" in head or "<!doctype" in head:
            raise TemplateError("That address gave a web page, not a zip file. Use a direct download link (see the help below), "
                                "and check the file is shared with anyone who has the link.")
        raise TemplateError("That address didn't give a zip file.")
    if sub:
        name = f"{name} {sub.strip('/').replace('/', ' ')}"
    return unzip(data, sub), url, name


def unzip(data: bytes, sub: str = "") -> dict[str, bytes]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise TemplateError("The zip file is damaged.")
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
            raise TemplateError(f"The folder {sub} isn't in that repository.")
    return out


# ------------------------------------------------------------------ small helpers
def _text(b: bytes, name: str) -> str:
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return b.decode("cp1252")             # saved by Excel on Windows
        except UnicodeDecodeError:
            raise TemplateError(f"{name} isn't a text file Spyhop can read (save it as CSV UTF-8).")


def _csv_rows(text: str) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]


def _norm(text: str | None) -> list[list[str]] | None:
    return None if text is None else [[c.strip() for c in r] for r in _csv_rows(text)]


def _count(text: str | None) -> int | None:
    rows = _norm(text)
    return None if rows is None else max(0, len(rows) - 1)


def _local_text(p: Path) -> str | None:
    try:
        return _text(p.read_bytes(), p.name)
    except (OSError, TemplateError):
        return None


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="." + p.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, p)


def _write_bytes(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="." + p.name + ".")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, p)


def version_tuple(v) -> tuple[int, ...] | None:
    m = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.(\d+))?\s*", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else None


def clean_min_version(v) -> str:
    """The minimum Spyhop version for a template being saved: x.y.z, from FORMAT_MIN to this version."""
    t = version_tuple(v or FORMAT_MIN)
    if not t:
        raise TemplateError("The minimum Spyhop version must look like 0.24.0.")
    if t < version_tuple(FORMAT_MIN):
        raise TemplateError(f"Templates need Spyhop {FORMAT_MIN} or newer, so the minimum can't be lower than that.")
    if t > version_tuple(__version__):
        raise TemplateError(f"The minimum can't be newer than this Spyhop ({__version__}).")
    return ".".join(map(str, t))


def _feed_url(f) -> str:
    try:
        return feeds.clean_url(f.get("url", ""))
    except feeds.FeedError:
        return str(f.get("url", ""))


def network_inputs(sources) -> list[dict]:
    return [dict(s) for s in (sources or []) if isinstance(s, dict) and s.get("type") in NETWORK_INPUTS]


def clean_online(d) -> dict | None:
    """Which online overlays to switch on: {ais, radar_us, radar_world, feeds: [addresses], radar_opacity, hide_stopped}."""
    if not isinstance(d, dict):
        return None
    out = {k: d[k] for k in ONLINE_KEYS if k in d}
    for k in ("ais", "radar_us", "radar_world", "hide_stopped"):
        if k in out:
            out[k] = bool(out[k])
    if "feeds" in out:
        out["feeds"] = [str(u) for u in out["feeds"] if isinstance(u, str)][:200] if isinstance(out["feeds"], list) else []
    if "radar_opacity" in out:
        try:
            out["radar_opacity"] = max(0.2, min(1.0, float(out["radar_opacity"])))
        except (TypeError, ValueError):
            out.pop("radar_opacity")
    return out or None


def _history_entry(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    g = lambda *ks: next((str(d[k]).strip() for k in ks if d.get(k) not in (None, "")), "")  # noqa: E731
    e = {"date": g("date"), "by": g("by"), "changed": g("changed", "files"), "notes": g("notes")}
    return e if any(e.values()) else None


def newest_first(history: list[dict]) -> list[dict]:
    """ISO dates sort as text; on the same date, the entry added last comes first."""
    order = sorted(range(len(history)), key=lambda i: (history[i].get("date", ""), i), reverse=True)
    return [history[i] for i in order]


# ------------------------------------------------------------------ this computer
def local_history(cfg) -> list[dict]:
    """The record of changes of the current template (the template it last used or saved), oldest first."""
    return [e for e in (_history_entry(x) for x in cfg.history) if e]


def save_local_history(cfg, history: list[dict]):
    cfg.save_history(history)


def log_change(cfg, by: str, changed: str, notes: str) -> dict:
    """Add an entry to this computer's record of changes. Returns it."""
    e = {"date": date.today().isoformat(), "by": by.strip(), "changed": changed.strip(), "notes": notes.strip()}
    save_local_history(cfg, local_history(cfg) + [e])
    return e


def shared_settings(cfg) -> dict:
    return cfg.shared_settings()


def local_reports(cfg) -> dict[str, str]:
    """The saved reports in use, as JSON text by file name."""
    return {fn: json.dumps(spec, indent=2, ensure_ascii=False) for fn, spec in sorted(cfg.reports.items())}


def local_waypoints(cfg) -> list[dict]:
    p = cfg.data_dir / "waypoints.csv"
    if not p.is_file():
        return []
    try:
        with open(p, newline="", encoding="utf-8-sig") as fh:
            return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]
    except (OSError, csv.Error):
        return []


def waypoints_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(WAYPOINT_COLS)
    for r in rows:
        w.writerow([r.get(c, "") or "" for c in WAYPOINT_COLS])
    return "﻿" + out.getvalue()


def local_overlays(cfg) -> dict[str, Path]:
    d = cfg.overlays_dir
    if not d.is_dir():
        return {}
    return {p.name: p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in OVERLAY_EXT and not p.name.startswith(("Survey - ", "."))}


def local_routes(cfg) -> dict[str, Path]:
    d = cfg.routes_dir
    return {p.name: p for p in sorted(d.glob("*.gpx")) if p.is_file()} if d.is_dir() else {}


def local_counts(cfg) -> dict:
    return {"waypoints": len(local_waypoints(cfg)), "routes": len(local_routes(cfg)), "overlays": len(local_overlays(cfg))}


def config_doc(cfg, include=(), min_spyhop=None, online=None, note: str = "", backup: bool = False) -> dict:
    """spyhop-config.json for the current template."""
    include = [k for k in OPTIONAL if k in (include or ())]
    history = local_history(cfg)
    if note:                                   # a backup notes itself in its own copy of the record
        history = history + [{"date": date.today().isoformat(), "by": "", "changed": "", "notes": note}]
    doc = {
        "spyhop_template": FORMAT,
        "min_spyhop": min_spyhop or FORMAT_MIN,
        "made_with": __version__,
        "includes": include,
        "history": history,
        "settings": shared_settings(cfg),
        "nmea_inputs": network_inputs(cfg.settings.get("nmea_sources")),
        "map_feeds": [{k: f[k] for k in ("id", "name", "url", "color", "refresh_min") if k in f}
                      for f in cfg.settings.get("online_feeds") or []],
        "map_display": dict(cfg.display),
    }
    o = clean_online(online)
    if o:
        doc["online_overlays"] = o
    reps = dict(cfg.reports)
    if reps or backup:            # {} in a backup: restoring it removes reports added since
        doc["reports"] = reps
    return doc


def make_zip(cfg, note: str = "", backup: bool = False, include=(), min_spyhop: str | None = None,
             online: dict | None = None) -> bytes:
    """A zip of the current template: a template another computer can use, or a backup (which always
    has the waypoints, routes and overlays, and says when there were no saved reports)."""
    include = OPTIONAL if backup else include
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(CONFIG, json.dumps(config_doc(cfg, include, min_spyhop, None if backup else online, note, backup),
                                      indent=2, ensure_ascii=False))
        for name in TABLES:
            p = cfg.current_dir / name
            if p.is_file():
                z.write(p, name)
        if "waypoints" in include:
            z.writestr(WAYPOINTS, waypoints_csv(local_waypoints(cfg)))
        if "routes" in include:
            for n, p in local_routes(cfg).items():
                z.write(p, f"routes/{n}")
        if "overlays" in include:
            for n, p in local_overlays(cfg).items():
                z.write(p, f"overlays/{n}")
    return buf.getvalue()


# ------------------------------------------------------------------ reading a template
def _root(files: dict[str, bytes]) -> str:
    """The folder inside the zip that holds the template (zips often have one top folder)."""
    known = set(TABLES) | {CONFIG, WAYPOINTS}
    cands = []
    for n in files:
        parts = n.split("/")
        if parts[-1] in known:
            cands.append("/".join(parts[:-1]))
        elif len(parts) >= 2 and parts[-2] in ("routes", "overlays") and not parts[-1].startswith("."):
            cands.append("/".join(parts[:-2]))
    if not cands:
        raise TemplateError("That doesn't look like a Spyhop template: it has none of spyhop-config.json, "
                            "species.csv, observers.csv, event_types.csv, behaviors.csv or shortcuts.csv.")
    return min(cands, key=lambda c: (c.count("/") if c else -1, c))


def empty_template() -> dict:
    return {"csv": {}, "display": None, "reports": None, "history": [], "info": None, "settings": None,
            "waypoints": None, "routes": None, "overlays": None, "ignored": [], "problems": []}


def read_template(files: dict[str, bytes]) -> dict:
    """A template as Spyhop uses it:
    {csv: {table: text}, display: {key: value} | None, reports: {file: json text} | None (None: leave saved
     reports alone), history: [...] newest first, info: {format, min_spyhop, made_with, includes} | None,
     settings: {settings, nmea_inputs, map_feeds, online} | None, waypoints: [rows] | None,
     routes / overlays: {file: bytes} | None, ignored: [...], problems: [...]}"""
    root = _root(files)
    pre = root + "/" if root else ""
    inside = {n[len(pre):]: b for n, b in files.items() if n.startswith(pre)}
    t = empty_template()
    probs = t["problems"]
    config = None
    for name, b in sorted(inside.items()):
        top, _, rest = name.partition("/")
        try:
            if name == CONFIG:
                try:
                    config = json.loads(_text(b, name))
                except ValueError as e:
                    probs.append(f"{CONFIG} isn't valid JSON ({e}).")
                    continue
                if not isinstance(config, dict):
                    probs.append(f"{CONFIG} should hold a JSON object.")
                    config = None
            elif name in TABLES:
                text = _text(b, name)
                rows = _csv_rows(text)
                hdr = [h.strip() for h in rows[0]] if rows else []
                missing = [c for c in TABLES[name] if c not in hdr]
                if missing:
                    probs.append(f"{name} needs the column{'s' if len(missing) > 1 else ''} "
                                 f"{', '.join(missing)} in its first row.")
                else:
                    t["csv"][name] = _with_other(name, text, hdr, rows)
            elif name == WAYPOINTS:
                t["waypoints"] = _read_waypoints(_text(b, name), probs)
            elif top == "routes" and rest and "/" not in rest:
                if not rest.lower().endswith(".gpx") or rest.startswith("."):
                    t["ignored"].append(name)
                elif "<gpx" not in _text(b, name)[:2000]:
                    probs.append(f"{name} isn't a GPX file.")
                else:
                    t["routes"] = {**(t["routes"] or {}), rest: b}
            elif top == "overlays" and rest and "/" not in rest:
                if Path(rest).suffix.lower() not in OVERLAY_EXT or rest.startswith("."):
                    t["ignored"].append(name)
                else:
                    t["overlays"] = {**(t["overlays"] or {}), rest: b}
            else:
                t["ignored"].append(name)
        except TemplateError as e:
            probs.append(str(e))
        except ValueError as e:
            probs.append(f"{name} can't be read ({e}).")
    if config is not None:
        _read_config(t, config)
    t["history"] = newest_first(t["history"])
    info = t["info"] or {}
    need = version_tuple(info.get("min_spyhop"))
    if info.get("min_spyhop") and not need:
        probs.append(f"The minimum Spyhop version “{info.get('min_spyhop')}” isn't a version number.")
    elif need and need > version_tuple(__version__):
        probs.append(f"This template needs Spyhop {info['min_spyhop']} or newer, and this computer has {__version__}. "
                     f"Update Spyhop first (Settings → About), then use the template.")
    return t


def _read_config(t: dict, d: dict):
    probs = t["problems"]
    t["info"] = {"format": d.get("spyhop_template"), "min_spyhop": d.get("min_spyhop"), "made_with": d.get("made_with"),
                 "includes": [k for k in d.get("includes") or [] if k in OPTIONAL]}
    t["history"] = [e for e in (_history_entry(x) for x in d.get("history") or []) if e]
    if any(k in d for k in ("settings", "nmea_inputs", "map_feeds", "online_overlays")):
        t["settings"] = _read_settings(d.get("settings"), d.get("nmea_inputs"), d.get("map_feeds"),
                                       d.get("online_overlays"), probs, CONFIG)
    if isinstance(d.get("map_display"), dict):
        t["display"] = {str(k): str(v) for k, v in d["map_display"].items()}
    if "reports" in d:
        reps = d["reports"]
        if not isinstance(reps, dict):
            probs.append(f"{CONFIG}: reports should be an object of report files.")
            return
        t["reports"] = {} if t["reports"] is None else t["reports"]
        for fn, spec in reps.items():
            if not re.fullmatch(r"[^/\\]+\.json", str(fn)) or str(fn).startswith("."):
                probs.append(f"{CONFIG}: the saved report “{fn}” needs a file name like gear.json.")
                continue
            why = reports.validate(spec)
            if why:
                probs.append(f"{CONFIG}: the saved report {fn}: {why}.")
                continue
            t["reports"][fn] = json.dumps(spec, indent=2, ensure_ascii=False)


def _read_settings(settings, inputs, map_feeds, online, probs, where) -> dict:
    out = {"settings": {}, "nmea_inputs": None, "map_feeds": [], "online": None}
    for k, v in (settings or {}).items() if isinstance(settings, dict) else ():
        if k in SHARED_SETTINGS:
            out["settings"][k] = v
    if isinstance(inputs, list):
        out["nmea_inputs"] = network_inputs(inputs)
    for f in map_feeds or [] if isinstance(map_feeds, list) else []:
        try:
            out["map_feeds"].append(feeds.clean(f))
        except (feeds.FeedError, AttributeError) as e:
            probs.append(f"{where}: the map feed “{(f or {}).get('name', '?') if isinstance(f, dict) else '?'}”: {e}")
    out["online"] = clean_online(online)
    return out


def _read_waypoints(text: str, probs) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and not {"Lat", "Lon"} <= set(rows[0].keys()):
        probs.append(f"{WAYPOINTS} needs Lat and Lon columns.")
        return []
    out = []
    for r in rows:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("Lat") and r.get("Lon"):
            out.append({c: r.get(c, "") for c in WAYPOINT_COLS})
    return out


def template_to_zip(t: dict) -> bytes:
    """A template (as read) saved again as a zip, e.g. a copy of one pulled from the web. Older
    templates are written in the current form."""
    doc = {"spyhop_template": FORMAT, "min_spyhop": (t.get("info") or {}).get("min_spyhop") or FORMAT_MIN,
           "made_with": (t.get("info") or {}).get("made_with") or __version__,
           "includes": [k for k in OPTIONAL if t.get(k) is not None],
           "history": list(reversed(t["history"]))}
    s = t.get("settings")
    if s:
        doc["settings"] = s["settings"]
        if s["nmea_inputs"] is not None:
            doc["nmea_inputs"] = s["nmea_inputs"]
        doc["map_feeds"] = s["map_feeds"]
        if s.get("online"):
            doc["online_overlays"] = s["online"]
    if t.get("display") is not None:
        doc["map_display"] = t["display"]
    if t.get("reports") is not None:
        doc["reports"] = {fn: json.loads(text) for fn, text in t["reports"].items()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(CONFIG, json.dumps(doc, indent=2, ensure_ascii=False))
        for name, text in t["csv"].items():
            z.writestr(name, text)
        if t.get("waypoints") is not None:
            z.writestr(WAYPOINTS, waypoints_csv(t["waypoints"]))
        for key in ("routes", "overlays"):
            for fn, b in (t.get(key) or {}).items():
                z.writestr(f"{key}/{fn}", b)
    return buf.getvalue()


# ------------------------------------------------------------------ comparing
def _fmt(v):
    return "on" if v is True else "off" if v is False else ("—" if v in (None, "") else str(v))


def _wp_key(r):
    n = (r.get("Name") or "").strip().lower()
    return ("name", n) if n else ("pos", (r.get("Lat") or "").strip(), (r.get("Lon") or "").strip())


def _norm_src(x):
    return {k: v for k, v in x.items() if k != "session"}


def _report_name(text: str, fn: str) -> str:
    try:
        return json.loads(text).get("name") or fn
    except (ValueError, AttributeError):
        return fn


def compare(cfg, t: dict) -> list[dict]:
    """What using the template would do, part by part. Statuses: new, changed, same, kept (here already and
    different: this computer's is kept), removed (saved reports replaced as a set; what a template added,
    when restoring the backup made before it)."""
    out = []
    for name, text in t["csv"].items():
        here = _local_text(cfg.current_dir / name)
        st = "new" if here is None else ("same" if _norm(here) == _norm(text) else "changed")
        row = {"file": name, "status": st, "here": _count(here), "in_template": _count(text), "unit": "rows"}
        if st == "changed" and name in DATA_TABLES and without_colors(_dict_rows(here)) == without_colors(_dict_rows(text)):
            row.update(colors_only=True, detail="only colors differ (they may change during a survey)")
        out.append(row)
    if t["display"] is not None:
        here = cfg.display
        diffs = [f"{k}: {here.get(k, '—')} → {v}" for k, v in t["display"].items() if str(here.get(k, "")) != v]
        out.append({"file": DISPLAY_LABEL, "status": "changed" if diffs else "same", "unit": "settings",
                    "detail": "; ".join(diffs[:6]) + (f"; and {len(diffs) - 6} more" if len(diffs) > 6 else "")})
    if t["reports"] is not None:
        local = local_reports(cfg)
        for fn, text in sorted(t["reports"].items()):
            here = local.get(fn)
            st = "new" if here is None else ("same" if _json_eq(here, text) else "changed")
            out.append({"file": f"Saved report: {_report_name(text, fn)}", "key": f"reports/{fn}", "status": st, "unit": "report"})
        for fn in sorted(set(local) - set(t["reports"])):
            out.append({"file": f"Saved report: {_report_name(local[fn], fn)}", "key": f"reports/{fn}",
                        "status": "removed", "unit": "report"})
    s = t.get("settings")
    if s:
        here = cfg.settings
        diff = lambda keys: [f"{SHARED_SETTINGS[k]}: {_fmt(here.get(k))} → {_fmt(v)}" for k, v in s["settings"].items()  # noqa: E731
                             if k in keys and here.get(k) != v]
        locked = [k for k in s["settings"] if k in LOCKED_SETTINGS]
        if locked:
            d = diff(locked)
            out.append({"file": DATA_SETTINGS_LABEL, "status": "changed" if d else "same", "detail": "; ".join(d), "unit": "settings"})
        d = diff([k for k in s["settings"] if k not in LOCKED_SETTINGS])
        out.append({"file": SETTINGS_LABEL, "status": "changed" if d else "same", "detail": "; ".join(d), "unit": "settings"})
        if s["nmea_inputs"] is not None:
            mine = network_inputs(here.get("nmea_sources"))
            desc = lambda L: ", ".join(f"{x['type'].upper()} {x.get('host', '') + ':' if x.get('host') else ''}{x.get('port', '')}"  # noqa: E731
                                       + ("" if x.get("enabled", True) else " (off)") for x in L) or "none"
            same = [_norm_src(x) for x in mine] == [_norm_src(x) for x in s["nmea_inputs"]]
            out.append({"file": INPUTS_LABEL, "status": "same" if same else "changed", "unit": "settings",
                        "detail": "" if same else f"{desc(mine)} → {desc(s['nmea_inputs'])}; serial ports are left as they are"})
        mine = {_feed_url(f): f for f in here.get("online_feeds") or []}
        for f in s["map_feeds"]:
            m = mine.get(_feed_url(f))
            st = "new" if not m else "same" if (m.get("name"), m.get("color"), m.get("refresh_min")) == (f["name"], f["color"], f["refresh_min"]) else "kept"
            out.append({"file": f"Map feed: {f['name']}", "status": st, "unit": "feed",
                        "detail": "" if st != "kept" else f"this computer calls it “{m.get('name')}” ({m.get('color')}); kept"})
    if t.get("waypoints") is not None:
        mine = {_wp_key(r): r for r in local_waypoints(cfg)}
        new = [r for r in t["waypoints"] if _wp_key(r) not in mine]
        kept = [r for r in t["waypoints"] if _wp_key(r) in mine
                and (mine[_wp_key(r)].get("Lat"), mine[_wp_key(r)].get("Lon")) != (r.get("Lat"), r.get("Lon"))]
        detail = []
        if new:
            detail.append(", ".join(r["Name"] or "(no name)" for r in new[:6]) + (f" and {len(new) - 6} more" if len(new) > 6 else ""))
        if kept:
            detail.append(f"{len(kept)} with the same name here in another place, kept as they are here ({', '.join(r['Name'] for r in kept[:4])})")
        out.append({"file": WAYPOINTS, "status": "new" if new else "kept" if kept else "same", "unit": "waypoints",
                    "detail": "; ".join(detail), "here": len(mine), "in_template": len(t["waypoints"]), "add": len(new)})
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        for fn, b in sorted((t.get(key) or {}).items()):
            p = local.get(fn)
            st = "new" if not p else "same" if p.read_bytes() == b else "kept"
            out.append({"file": f"{key}/{fn}", "status": st, "unit": key[:-1],
                        "detail": "different here; this computer’s copy is kept" if st == "kept" else ""})
    if t.get("_undo"):
        out.extend(undo_rows(cfg, t["_undo"]))
    for r in out:
        r["part"] = part_of(r["file"])
    order = {"changed": 0, "new": 1, "removed": 2, "kept": 3, "same": 4}
    return sorted(out, key=lambda r: (order[r["status"]], r["file"]))


def data_differs(cfg, t: dict, plan: list[dict] | None = None) -> list[str]:
    """The data parts (lists, data settings) of the current template that differ from a template's, not
    counting colors: what can't change during a survey, and what a survey's template copy is checked for."""
    return [r["file"] for r in (plan if plan is not None else compare(cfg, t))
            if r["part"] == "data" and r["status"] not in ("same", "kept") and not r.get("colors_only")]


def _json_eq(a: str, b: str) -> bool:
    try:
        return json.loads(a) == json.loads(b)
    except ValueError:
        return a == b


def undo_rows(cfg, undo: dict) -> list[dict]:
    rows = []
    ids = set(undo.get("waypoints") or [])
    if ids:
        n = sum(1 for r in local_waypoints(cfg) if r.get("RowID") in ids)
        if n:
            rows.append({"file": WAYPOINTS, "status": "removed", "unit": "waypoints",
                         "detail": f"{n} added by the template used after this backup"})
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        for fn in undo.get(key) or []:
            if fn in local:
                rows.append({"file": f"{key}/{fn}", "status": "removed", "unit": key[:-1],
                             "detail": "added by the template used after this backup"})
    mine = {f.get("id"): f for f in cfg.settings.get("online_feeds") or []}
    for fid in undo.get("feeds") or []:
        if fid in mine:
            rows.append({"file": f"Map feed: {mine[fid].get('name')}", "status": "removed", "unit": "feed",
                         "detail": "added by the template used after this backup"})
    return rows


def online_summary(t) -> dict | None:
    """The template's online overlays, with the names of the map feeds it switches on (for the check)."""
    s = t.get("settings") or {}
    d = s.get("online")
    if not d:
        return None
    names = {_feed_url(f): f["name"] for f in s.get("map_feeds") or []}
    return {**d, "feed_names": [names.get(u, u) for u in d.get("feeds") or []]}


def fingerprints(cfg) -> dict[str, str]:
    """A hash of each part of the current template a template can hold, by its label in compare(),
    to tell later what changed."""
    t = read_template(unzip(make_zip(cfg, include=OPTIONAL)))
    h = lambda o: hashlib.sha1(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()  # noqa: E731
    out = {name: h(_norm(text)) for name, text in t["csv"].items()}
    out[DISPLAY_LABEL] = h(t["display"])
    for fn, text in (t["reports"] or {}).items():
        out[f"Saved report: {_report_name(text, fn)}"] = h(json.loads(text))
    s = t["settings"] or {}
    out[SETTINGS_LABEL] = h({k: v for k, v in (s.get("settings") or {}).items() if k not in LOCKED_SETTINGS})
    out[DATA_SETTINGS_LABEL] = h({k: v for k, v in (s.get("settings") or {}).items() if k in LOCKED_SETTINGS})
    out[INPUTS_LABEL] = h(s.get("nmea_inputs"))
    for f in s.get("map_feeds") or []:
        out[f"Map feed: {f['name']}"] = h(f)
    out[WAYPOINTS] = h(t["waypoints"])
    for key in ("routes", "overlays"):
        for fn, b in (t.get(key) or {}).items():
            out[f"{key}/{fn}"] = hashlib.sha1(b).hexdigest()
    return out


def changed_since(cfg, before: dict | None) -> list[str] | None:
    """The parts added, changed or removed since `before` (fingerprints), or None if unknown."""
    if not before:
        return None
    now = fingerprints(cfg)
    return [n for n in sorted(set(now) | set(before)) if now.get(n) != before.get(n)]


# ------------------------------------------------------------------ using a template
def apply_all(cfg, t: dict, data: bool = True) -> tuple[list[str], dict]:
    """Use a template: replace this computer's lists, shortcuts, map display, saved reports and shared
    settings with the template's; add its map feeds, routes and overlays that aren't here yet.
    Returns (what changed, what was added); its waypoints are for the caller to add (the recorder
    holds that table): {settings, inputs, feeds, routes, overlays, waypoints, remove_waypoints, online,
    data_kept}. With data=False (during a survey) the data part is left as it is (data_kept lists what
    differed), except colors."""
    if t["problems"]:
        raise TemplateError("The template has problems, so nothing was changed:\n" + "\n".join(t["problems"]))
    plan = compare(cfg, t)
    kept = [] if data else data_differs(cfg, t, plan)
    for name, text in t["csv"].items():
        if name in kept:
            continue
        _write(cfg.current_dir / name, text)
    if t["display"] is not None:
        cfg.save_display(t["display"], replace=True)
    if t["reports"] is not None and (data or not any(f.startswith("Saved report: ") for f in kept)):
        cfg.save_reports({fn: json.loads(text) for fn, text in t["reports"].items()})
    done = _apply_parts(cfg, t, data)
    done["data_kept"] = kept
    if t["history"]:
        save_local_history(cfg, list(reversed(t["history"])))
    cfg.ensure_defaults()          # a list the template doesn't have keeps the one in use (or the default)
    cfg.reload()
    return [r["file"] for r in plan if r["status"] not in ("same", "kept") and r["file"] not in kept], done


def _apply_parts(cfg, t: dict, data: bool = True) -> dict:
    done = {"settings": False, "inputs": False, "feeds": [], "routes": [], "overlays": [], "waypoints": [],
            "remove_waypoints": [], "online": None}
    s = t.get("settings")
    if s:
        upd = {k: v for k, v in s["settings"].items() if cfg.settings.get(k) != v and (data or k not in LOCKED_SETTINGS)}
        if s["nmea_inputs"] is not None:
            mine = list(cfg.settings.get("nmea_sources") or [])
            new = merge_network_inputs(mine, s["nmea_inputs"])
            if new != mine:
                upd["nmea_sources"] = new
                done["inputs"] = True
        feeds_now = [dict(f) for f in cfg.settings.get("online_feeds") or []]
        urls = {_feed_url(f) for f in feeds_now}
        for f in s["map_feeds"]:
            if _feed_url(f) in urls:
                continue
            f = dict(f)
            if any(x.get("id") == f["id"] for x in feeds_now):
                f["id"] = feeds.clean({**f, "id": ""})["id"]
            base, n = f["name"], 2
            while any(x.get("name", "").lower() == f["name"].lower() for x in feeds_now):
                f["name"] = f"{base} ({n})"
                n += 1
            feeds_now.append(f)
            urls.add(_feed_url(f))
            done["feeds"].append(f["id"])
        if done["feeds"]:
            upd["online_feeds"] = feeds_now
        if s.get("online"):
            done["online"] = upd["online_display"] = {**s["online"], "stamp": f"{time.time():.3f}"}
        done["settings"] = bool(set(upd) - {"nmea_sources", "online_feeds", "online_display"})
        if upd:
            cfg.save_settings(upd)
    if t.get("waypoints"):
        mine = {_wp_key(r) for r in local_waypoints(cfg)}
        for r in t["waypoints"]:
            if _wp_key(r) not in mine:
                done["waypoints"].append(dict(r))
                mine.add(_wp_key(r))
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        d = cfg.routes_dir if key == "routes" else cfg.overlays_dir
        for fn, b in (t.get(key) or {}).items():
            if fn not in local and not (d / fn).exists():
                _write_bytes(d / fn, b)
                done[key].append(fn)
    undo = t.get("_undo")
    if undo:
        done["remove_waypoints"] = list(undo.get("waypoints") or [])
        for key in ("routes", "overlays"):
            d = cfg.routes_dir if key == "routes" else cfg.overlays_dir
            for fn in undo.get(key) or []:
                p = d / Path(fn).name
                if p.is_file():
                    p.unlink()
        gone = set(undo.get("feeds") or [])
        if gone:
            cfg.save_settings({"online_feeds": [f for f in cfg.settings.get("online_feeds") or [] if f.get("id") not in gone]})
            for fid in gone:
                feeds.cache_path(cfg, fid).unlink(missing_ok=True)
    return done


def apply(cfg, t: dict) -> list[str]:
    """apply_all() without Spyhop's recorder: waypoints are written to waypoints.csv directly."""
    changed, done = apply_all(cfg, t)
    add_waypoints_to_file(cfg, done["waypoints"], done["remove_waypoints"])
    return changed


def add_waypoints_to_file(cfg, rows: list[dict], remove_ids=()) -> list[str]:
    if not rows and not remove_ids:
        return []
    header = schema.headers("marks")
    gone = set(remove_ids or ())
    existing = [r for r in local_waypoints(cfg) if r.get("RowID") not in gone]
    ids = []
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    for r in existing:
        w.writerow([r.get(c, "") or "" for c in header])
    for r in rows:
        rid = uuid.uuid4().hex[:12]
        ids.append(rid)
        w.writerow([rid if c == "RowID" else r.get(c, "") for c in header])
    _write(cfg.data_dir / "waypoints.csv", "﻿" + out.getvalue())
    return ids


# ------------------------------------------------------------------ the templates folder
def list_templates(cfg) -> list[dict]:
    """The templates in the templates folder, newest first, each compared with the current template."""
    d = templates_dir(cfg)
    out = []
    files = [p for p in d.iterdir() if p.is_file() and not p.name.startswith(".") and is_template_name(p.name)] if d.is_dir() else []
    for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        item = {"name": p.name, "path": str(p), "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")}
        try:
            t = read_template(unzip(p.read_bytes()))
            plan = compare(cfg, t)
            item.update(latest=t["history"][0] if t["history"] else None, changes=len(t["history"]),
                        problems=t["problems"][:3], differs=[r["file"] for r in plan if r["status"] not in ("same", "kept")],
                        info=t["info"])
            item["matches"] = not t["problems"] and not item["differs"]
        except TemplateError as e:
            item["error"] = str(e)
        out.append(item)
    return out


def list_backups(cfg, limit: int = 20) -> list[dict]:
    d = backups_dir(cfg)
    files = [p for p in d.iterdir() if p.is_file() and is_template_name(p.name)] if d.is_dir() else []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "path": str(p), "size": p.stat().st_size,
             "modified": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")}
            for p in files[:limit]]


def read_template_file(cfg, name: str) -> dict:
    p = _template_file(cfg, name)
    if not p.is_file():
        raise TemplateError(f"There's no template called {name} in {p.parent}.")
    return read_template(unzip(p.read_bytes()))


def changed_from_template(cfg, name: str) -> list[str]:
    """The parts that differ between this computer and a template in the folder."""
    return [r["file"] for r in compare(cfg, read_template_file(cfg, name)) if r["status"] not in ("same", "kept")]


def save_template(cfg, name: str, by: str, changed: str, notes: str, overwrite: bool = False,
                  include=(), min_spyhop: str | None = None, online: dict | None = None) -> Path:
    """Save the current template as a template in the templates folder, adding an entry to its record of
    changes. A new template continues this computer's record; updating one continues the record of the
    template replaced. include: any of OPTIONAL (waypoints, routes, overlays)."""
    min_spyhop = clean_min_version(min_spyhop)
    if overwrite:
        p = _template_file(cfg, name)
        if not p.is_file():
            raise TemplateError(f"There's no template called {name} to update.")
        try:
            old = read_template(unzip(p.read_bytes()))["history"]
        except TemplateError:
            old = []
        if old:
            save_local_history(cfg, list(reversed(old)))
    else:
        fn = safe_template_name(name)
        if not fn:
            raise TemplateError("Give the template a name.")
        p = templates_dir(cfg) / fn
        if p.exists() or any(template_stem(q.name).lower() == template_stem(fn).lower()
                             for q in (p.parent.iterdir() if p.parent.is_dir() else []) if is_template_name(q.name)):
            raise TemplateError(f"There's already a template called {template_stem(fn)}. Choose another name, or use Update on that template.")
    log_change(cfg, by, changed or "all", notes)
    _write_bytes(p, make_zip(cfg, include=include, min_spyhop=min_spyhop, online=online))
    return p


def _core_differs(cfg, t: dict) -> list[str]:
    """The parts of the current template (not waypoints, routes or overlays) that differ from a template."""
    return [r["file"] for r in compare(cfg, t) if r["status"] not in ("same", "kept")
            and r["file"] != WAYPOINTS and not r["file"].startswith(("routes/", "overlays/"))]


def current_status(cfg) -> dict:
    """Is the current template saved as a template? {name: the template it matches (or came from), saved:
    True if templates/saved has a template with the same lists, shortcuts, settings, display and
    reports, changed: the parts that differ from the template it came from}. Waypoints, routes and
    overlays don't count: they change during surveys."""
    cur = cfg.settings.get("template_current") or {}
    first = cur.get("name") if cur.get("how") in ("loaded", "saved") else None
    names = [p.name for p in sorted(templates_dir(cfg).glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)]
    if first in names:
        names.remove(first)
        names.insert(0, first)
    changed = None
    for n in names:
        try:
            diff = _core_differs(cfg, read_template_file(cfg, n))
        except TemplateError:
            continue
        if n == first:
            changed = diff
        if not diff:
            return {"name": n, "saved": True, "changed": []}
    return {"name": first or "", "saved": False, "changed": changed if changed is not None else []}


def keep_copy(cfg, t: dict, filename: str) -> Path:
    """Save a template pulled from elsewhere in the templates folder, replacing an older copy with the same name."""
    p = templates_dir(cfg) / (safe_template_name(filename) or "template" + TEMPLATE_SUFFIX)
    _write_bytes(p, template_to_zip(t))
    return p


def save_backup(cfg) -> Path:
    d = backups_dir(cfg)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise TemplateError(f"Can't use {d} for the backup: {e}")
    p = d / f"spyhop-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}{TEMPLATE_SUFFIX}"
    n = 2
    while p.exists():
        p = d / f"spyhop-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}{TEMPLATE_SUFFIX}"
        n += 1
    p.write_bytes(make_zip(cfg, f"Backup of the current template (Spyhop {__version__})", backup=True))
    return p


# ------------------------------------------------------------------ cache between check and use
_cache: dict[str, tuple[float, str, dict]] = {}


def remember(address: str, t: dict) -> str:
    now = time.monotonic()
    for k in [k for k, v in _cache.items() if now - v[0] > CACHE_S]:
        _cache.pop(k, None)
    token = secrets.token_hex(8)
    _cache[token] = (now, address, t)
    return token


def recall(token: str) -> tuple[str, dict] | None:
    v = _cache.get(token or "")
    if not v or time.monotonic() - v[0] > CACHE_S:
        return None
    return v[1], v[2]
