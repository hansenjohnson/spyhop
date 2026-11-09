"""The one-time move from the 0.27 folder layout to the 0.28 one. Delete this module (and its call in
Config.__init__) before 1.0.0.

0.27 kept the lists, shortcuts.csv and display.csv at the top of Spyhop's folder, the settings,
the open survey and the template history in settings/, saved reports in reports/, and templates in
<survey data folder>/templates (with backups/ inside). 0.28 keeps the current template in
templates/current, templates in templates/saved and templates/backups, and this computer's settings
in spyhop-local.json. See config.Config.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

LISTS = ("species", "event_types", "observers", "behaviors")
TEMPLATE_EXT = (".zip", ".spyhop")


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _move(src: Path, dst: Path) -> bool:
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return True


def _rmdir_if_empty(d: Path):
    try:
        d.rmdir()
    except OSError:
        pass


def move_old_layout(cfg) -> bool:
    """Move a 0.27 layout into the 0.28 one. Returns True if anything was moved."""
    from .config import SHARED_SETTINGS, NETWORK_INPUTS, DEFAULT_SETTINGS, TEMPLATE_FORMAT, CONFIG_FILE, LOCAL_FILE
    root = cfg.root
    old_settings = root / "settings"
    markers = [root / f"{n}.csv" for n in LISTS] + [root / "shortcuts.csv", root / "display.csv", old_settings / "settings.json"]
    if cfg.config_path.exists() or not any(p.exists() for p in markers):
        return False
    cur = cfg.current_dir
    cur.mkdir(parents=True, exist_ok=True)
    for n in LISTS + ("shortcuts",):
        _move(root / f"{n}.csv", cur / f"{n}.csv")

    settings = _json(old_settings / "settings.json") or {}
    settings = settings if isinstance(settings, dict) else {}
    display = {}
    try:
        with open(root / "display.csv", newline="", encoding="utf-8-sig") as fh:
            display = {r["key"].strip(): (r.get("value") or "").strip() for r in csv.DictReader(fh) if (r.get("key") or "").strip()}
    except (OSError, KeyError, csv.Error):
        pass
    history = _json(old_settings / "template_history.json")
    history = history if isinstance(history, list) else []
    reports = {}
    rdir = root / "reports"
    if rdir.is_dir():
        for p in sorted(rdir.glob("*.json")):
            d = _json(p)
            if isinstance(d, dict) and "id" not in d and "where" not in d:      # not a pre-0.19 report template
                reports[p.name] = d
    else:
        for p in sorted((Path(__file__).parent / "report_defs").glob("*.json")):
            d = _json(p)
            if isinstance(d, dict):
                reports[p.name] = d
    survey = _json(old_settings / "current_survey.txt")

    sources = [x for x in settings.get("nmea_sources") or [] if isinstance(x, dict)]
    doc = {"spyhop_template": TEMPLATE_FORMAT, "history": history,
           "settings": {k: settings[k] for k in SHARED_SETTINGS if k in settings},
           "nmea_inputs": [x for x in sources if x.get("type") in NETWORK_INPUTS],
           "map_feeds": settings.get("online_feeds") or [],
           "map_display": display, "reports": reports}
    if settings.get("online_display"):
        doc["online_overlays"] = settings["online_display"]
    local = {k: v for k, v in settings.items() if k in DEFAULT_SETTINGS and k not in SHARED_SETTINGS
             and k not in ("online_feeds", "online_display")}
    (cur / CONFIG_FILE).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / LOCAL_FILE).write_text(json.dumps({"settings": local, "current_survey": survey if isinstance(survey, dict) else None},
                                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # templates and their backups, from the survey data folder (the 0.14–0.23 config_packs folder too)
    data = Path(settings.get("data_dir") or root / "data").expanduser()
    moved_templates = 0
    for name in ("templates", "config_packs"):
        d = data / name
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.name.lower().endswith(TEMPLATE_EXT):
                moved_templates += _move(p, cfg.saved_dir / p.name)
        b = d / "backups"
        if b.is_dir():
            for p in sorted(b.iterdir()):
                if p.is_file():
                    _move(p, cfg.backups_dir / p.name)
            _rmdir_if_empty(b)
        _rmdir_if_empty(d)

    # what 0.27 kept and 0.28 doesn't need
    for p in (root / "display.csv", root / "tile_sources.csv", root / "spyhop-config.csv"):
        p.unlink(missing_ok=True)
    for d in (old_settings, rdir, root / "filters"):
        shutil.rmtree(d, ignore_errors=True)
    cfg.notices.append("Spyhop's files have a new layout: the current template is in templates/current (lists, shortcuts and "
                       "spyhop-config.json), saved templates are in templates/saved"
                       + (f" ({moved_templates} moved from the data folder)" if moved_templates else "")
                       + ", and this computer's own settings are in spyhop-local.json.")
    return True


JUNK = {".ds_store", "thumbs.db", "desktop.ini"}


def tidy_data_folder(cfg) -> None:
    """A templates (or 0.14–0.23 config_packs) folder left in the survey data folder: templates go to
    templates/saved, backups to templates/backups, system clutter (.DS_Store…) is deleted, and the folder
    goes once it's empty. Runs at every start, since the data folder can be changed or plugged in later."""
    moved, left = 0, []
    for name in ("templates", "config_packs"):
        d = Path(cfg.data_dir) / name
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*"), key=lambda q: len(q.parts), reverse=True):
            low = p.name.lower()
            try:
                if p.is_dir():
                    _rmdir_if_empty(p)
                elif low in JUNK or low.startswith("._"):
                    p.unlink()
                elif low.endswith(TEMPLATE_EXT):
                    dest = (cfg.backups_dir if p.parent.name == "backups" else cfg.saved_dir) / p.name
                    if dest.exists():
                        if dest.read_bytes() == p.read_bytes():
                            p.unlink()
                        else:
                            left.append(str(p))
                    else:
                        _move(p, dest)
                        moved += 1
                else:
                    left.append(str(p))
            except OSError:
                left.append(str(p))
        _rmdir_if_empty(d)
    if moved:
        cfg.notices.append(f"Moved {moved} template file{'s' if moved > 1 else ''} from the data folder to templates/saved in Spyhop's folder.")
    if left:
        cfg.notices.append("The data folder still has a templates folder with files Spyhop doesn't know what to do with: "
                           + ", ".join(left[:4]) + (" …" if len(left) > 4 else "") + ". Move or delete them yourself.")
