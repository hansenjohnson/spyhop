"""Local web server: REST API, websocket for live updates, tiles and static files."""
from __future__ import annotations

import asyncio
import mimetypes
import json
from datetime import datetime, timezone
from urllib.parse import quote
import logging
import os
import platform
import subprocess
import time
from pathlib import Path

from aiohttp import web, WSMsgType

from .recorder import Recorder, ValueErrorMsg
from . import awake, __version__, diag, feeds, reports, reticle, routes, schema, templates, uninstall, updater
from .browser import find_chrome, html_to_pdf, PdfError
from .sources import SourceManager, list_serial_ports, clean_path
from .store import safe_name
mimetypes.add_type("text/javascript", ".mjs")   # the MapLibre modules
from . import tiles as tiles_mod
from .tiles import TileService

log = logging.getLogger(__name__)
perf_log = logging.getLogger("spyhop.slow")


action_log = logging.getLogger("spyhop.action")
QUIET_POSTS = {"/api/client-log"}


@web.middleware
async def timing(request, handler):
    """Time every request; log slow ones and every action (POST) with its outcome, never its data."""
    t = time.perf_counter()
    status, note = 500, ""
    try:
        resp = await handler(request)
        status = resp.status
        if status >= 400 and isinstance(resp, web.Response) and resp.body:
            try:
                note = json.loads(resp.body).get("error", "")
            except (ValueError, TypeError, AttributeError):
                pass
        return resp
    except web.HTTPException as e:
        status = e.status
        raise
    finally:
        ms = (time.perf_counter() - t) * 1000
        perf = request.app.get("perf")
        if perf is not None and request.path != "/ws":
            perf.request(request.path, ms)
        if ms > App.SLOW_REQ_MS and request.path != "/ws":
            what = ("map tile from the internet" if request.path.startswith("/tiles/s/")
                    else "chart tile (MBTiles)" if request.path.startswith("/tiles/mb/") else request.path)
            perf_log.warning("slow request: %s took %.0f ms", what, ms)
        if request.method == "POST" and request.path not in QUIET_POSTS:
            outcome = "ok" if status < 400 else f"refused ({status}): {note}" if status < 500 else f"FAILED ({status}): {note}"
            (action_log.info if status < 500 else action_log.error)("%s %s in %.0f ms", request.path, outcome, ms)
WEB = Path(__file__).parent / "web"


def open_path(p: Path):
    p = Path(p)
    system = platform.system()
    if system == "Windows":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _as_q(s: str) -> str:
    """A string for inside AppleScript double quotes."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _ps_q(s: str) -> str:
    """A string for inside PowerShell single quotes."""
    return str(s).replace("'", "''")


def choose_folder_dialog(start: str) -> str | None:
    """Native folder chooser via the operating system (no GUI toolkit needed)."""
    system = platform.system()
    try:
        if system == "Darwin":
            script = ('POSIX path of (choose folder with prompt "Choose the folder for Spyhop survey data" '
                      f'default location (POSIX file "{_as_q(start)}"))')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
            return r.stdout.strip().rstrip("/") or None if r.returncode == 0 else None
        if system == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$f.Description='Choose the folder for Spyhop survey data';"
                  f"$f.SelectedPath='{_ps_q(start)}';"
                  "if($f.ShowDialog() -eq 'OK'){$f.SelectedPath}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                               capture_output=True, text=True, timeout=600)
            return r.stdout.strip() or None
        for cmd in (["zenity", "--file-selection", "--directory", f"--filename={start}/"],
                    ["kdialog", "--getexistingdirectory", start]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except FileNotFoundError:
                continue
            return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ValueErrorMsg("Couldn't show a folder chooser on this computer — type or paste the folder's path instead.")


def choose_file_dialog(start: str, prompt: str = "Choose a file") -> str | None:
    """Native file chooser via the operating system (no GUI toolkit needed). `start` is a folder."""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (f'POSIX path of (choose file with prompt "{_as_q(prompt)}" '
                      f'default location (POSIX file "{_as_q(start)}"))')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
            return r.stdout.strip() or None if r.returncode == 0 else None
        if system == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$f=New-Object System.Windows.Forms.OpenFileDialog;"
                  f"$f.Title='{_ps_q(prompt)}';"
                  f"$f.InitialDirectory='{_ps_q(start)}';"
                  "$f.Filter='NMEA logs (*.nmea;*.txt;*.log)|*.nmea;*.txt;*.log|All files (*.*)|*.*';"
                  "if($f.ShowDialog() -eq 'OK'){$f.FileName}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                               capture_output=True, text=True, timeout=600)
            return r.stdout.strip() or None
        for cmd in (["zenity", "--file-selection", f"--title={prompt}", f"--filename={start}/"],
                    ["kdialog", "--getopenfilename", start]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except FileNotFoundError:
                continue
            return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ValueErrorMsg("Couldn't show a file chooser on this computer — type or paste the file's path instead.")


def json_ok(data=None, **kw):
    out = {"ok": True}
    if data is not None:
        out.update(data)
    out.update(kw)
    return web.json_response(out, dumps=lambda o: json.dumps(o, default=str))


def json_err(msg, status=400):
    return web.json_response({"ok": False, "error": msg}, status=status)


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except ValueErrorMsg as e:
        return json_err(str(e))
    except ValueError as e:
        return json_err(str(e))
    except web.HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("request failed")
        return json_err(f"Internal error: {e}", 500)


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    if request.path == "/" or request.path.startswith("/static/") and not request.path.startswith("/static/vendor/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp




def clean_pane_layout(v) -> dict:
    """The three panes' sizes and states (this computer only): fx (the map's share of the top), fy (the
    top's share of the height), min {map, util, data}, max (one pane filling the window, or none)."""
    v = v if isinstance(v, dict) else {}
    out = {}
    for k in ("fx", "fy"):
        try:
            out[k] = round(max(0.15, min(0.85, float(v[k]))), 4)
        except (KeyError, TypeError, ValueError):
            pass
    m = v.get("min") if isinstance(v.get("min"), dict) else {}
    out["min"] = {k: bool(m.get(k)) for k in ("map", "util", "data")}
    out["max"] = v.get("max") if v.get("max") in ("map", "util", "data") else None
    return out

def clean_column_layout(v) -> dict:
    """{tab: {order: [column keys], widths: {key: px}}}: only known tabs and columns, widths 30–800 px."""
    out = {}
    for tab, lay in (v or {}).items() if isinstance(v, dict) else []:
        if tab not in schema.TABS or not isinstance(lay, dict):
            continue
        keys = {c["key"] for c in schema.TABS[tab]["columns"]}
        order = [k for k in lay.get("order") or [] if k in keys]
        widths = {}
        for k, w in (lay.get("widths") or {}).items():
            try:
                if k in keys:
                    widths[k] = max(30, min(800, int(float(w))))
            except (TypeError, ValueError):
                pass
        if order or widths:
            out[tab] = {"order": list(dict.fromkeys(order)), "widths": widths}
    return out

class App:
    def __init__(self, data_dir: Path, extra_sources: list[dict] | None = None):
        self.rec = Recorder(data_dir)
        self.last_reports_dir: Path | None = None      # where Run Reports last saved
        self.sources = SourceManager(self.rec.decoder)
        self.tiles = TileService(self.rec.cfg)
        self.tiles.on_charts_changed = lambda: self._broadcast_soon({"type": "charts", "mbtiles": self.tiles.mbtiles_info()})
        self.clients: set[web.WebSocketResponse] = set()
        self.extra_sources = extra_sources or []
        self.rec.listeners.append(self._broadcast_soon)
        self._loop_task = None
        self.perf = diag.PerfMonitor()
        self.awake = awake.KeepAwake()
        self._nmea_lines0 = 0

    # -- websocket --------------------------------------------------------------
    def _broadcast_soon(self, msg: dict):
        data = json.dumps(msg, default=str)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(data))

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def ticker(self):
        n = 0
        while True:
            await asyncio.sleep(1)
            n += 1
            try:
                self.rec.tick_tracker()
                msg = {"type": "vessel", "vessel": self.rec.vessel(), "t": time.time(),
                       "inst": self.rec.decoder.instruments()}
                if n % 3 == 0:
                    msg["nmea"] = self.nmea_status(raw=False)
                    if self.tiles.prefetch_state["running"] or self.tiles.prefetch_state["total"]:
                        msg["prefetch"] = self.tiles.prefetch_state
                self._broadcast_soon(msg)
                if n % self.rec.INST_SAMPLE_S == 0:
                    self.rec.sample_instruments()
                if n % 2 == 0:
                    self.sync_awake()
                if n % diag.PerfMonitor.PERIOD_S == 0:
                    self.log_perf()
            except Exception:  # noqa: BLE001
                log.exception("ticker")

    def log_perf(self):
        total = sum(self.rec.decoder.counts.values())
        self.perf.lines, self._nmea_lines0 = total - self._nmea_lines0, total
        sv = self.rec.survey
        extra = {"windows": len(self.clients), "survey": sv["prefix"] if sv else "none",
                 "rows": "/".join(str(len(self.rec.tables[t].rows)) for t in ("sightings", "effort", "events", "marks")),
                 "track points": len(self.rec.track.points) if self.rec.track else 0,
                 "tracking": "on" if self.rec.tracking_on() else "off"}
        logging.getLogger("spyhop.perf").info(self.perf.snapshot(extra))

    def wanted_awake(self) -> str | None:
        s = self.rec.cfg.settings
        when = s.get("keep_awake", "survey")
        if when == "always" or (when == "survey" and self.rec.survey_active()):
            return "display" if s.get("keep_screen_on") else "system"
        return None

    def sync_awake(self):
        """Hold or release the keep-awake request to match the setting and the survey."""
        before = self.awake.status()
        self.awake.set(self.wanted_awake())
        now = self.awake.status()
        if now != before:
            self._broadcast_soon({"type": "awake", "awake": now})

    def nmea_status(self, raw=True) -> dict:
        d = self.rec.decoder
        out = {"sources": list(self.sources.status.values()), "counts": d.counts,
               "errors": d.errors, "log": self.rec.raw_log_status(),
               "position_source": d.state.source if d.state.updated and time.time() - d.state.updated < 10 else ""}
        if raw:
            out["raw"] = list(d.raw)[-60:]
        return out

    # -- lifecycle ------------------------------------------------------------------
    async def on_startup(self, app):
        srcs = list(self.rec.cfg.settings.get("nmea_sources") or []) + self.extra_sources
        await self.sources.start(srcs)
        self._loop_task = asyncio.create_task(self.ticker())
        self._watch_task = asyncio.create_task(self.stall_watch())
        app["perf"] = self.perf
        loop = asyncio.get_running_loop()

        def on_loop_error(loop, ctx):
            exc = ctx.get("exception")
            logging.getLogger("spyhop.crash").error("unhandled error in the server: %s", ctx.get("message"),
                                                    exc_info=(type(exc), exc, exc.__traceback__) if exc else None)
        loop.set_exception_handler(on_loop_error)
        if self.rec.cfg.settings.get("check_updates_on_start"):
            asyncio.create_task(self._startup_update_check())
        self.sync_awake()

    async def _startup_update_check(self):
        await asyncio.sleep(8)
        try:
            info = await asyncio.get_running_loop().run_in_executor(None, updater.check)
        except Exception as e:                       # offline at sea is normal: say nothing
            logging.getLogger("spyhop.update").info("update check at start-up: %s", e)
            return
        if info.get("newer"):
            self._broadcast_soon({"type": "update", "info": info})

    # -- slowness diagnostics: only prints when something is slow ----------------
    STALL_MS = 250       # the server was busy and couldn't answer anything for this long
    SLOW_REQ_MS = 1500   # one request took this long

    async def stall_watch(self):
        """Log when the event loop is blocked (everything waits while it is)."""
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.1)
            late = (time.perf_counter() - t - 0.1) * 1000
            self.perf.loop_lag(max(late, 0))
            if late > self.STALL_MS:
                perf_log.warning("server busy for %.0f ms (nothing could be answered meanwhile)", late)

    async def client_log(self, request):
        """Slow moments, errors and performance snapshots reported by the Spyhop window."""
        b = await request.json()
        for e in (b.get("events") or [])[:50]:
            perf_log.warning("window busy for %s ms%s", e.get("ms"), f" ({e['what']})" if e.get("what") else "")
        win = logging.getLogger("spyhop.window")
        for e in (b.get("errors") or [])[:20]:
            win.error("window error: %s%s", str(e.get("message", ""))[:500],
                      ("\n" + str(e["stack"])[:3000]) if e.get("stack") else "")
        if b.get("perf"):
            win.info("window perf: %s", str(b["perf"])[:500])
        if b.get("summary"):
            perf_log.warning("window: %s", b["summary"])
        return json_ok()

    async def diagnostics(self, request):
        cfg = self.rec.cfg
        extra = {"survey": self.rec.survey["prefix"] if self.rec.survey else "none",
                 "windows": len(self.clients),
                 "nmea_inputs": ", ".join(f"{s.get('name')}: {s.get('state')}" for s in self.sources.status.values()) or "none"}
        self.log_perf()
        z = await asyncio.get_running_loop().run_in_executor(
            None, diag.make_bundle, cfg, extra, diag.log_dir(cfg.root))
        log.info("diagnostics bundle saved: %s", z)
        return json_ok(name=z.name, path=str(z), url=f"/api/diagnostics/{quote(z.name)}")

    async def diagnostics_file(self, request):
        name = request.match_info["name"]
        p = diag.log_dir(self.rec.cfg.root) / name
        if "/" in name or "\\" in name or not p.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    async def inst_history(self, request):
        return json_ok(self.rec.instrument_history(request.query.get("key", "")))

    async def changelog(self, request):
        return self._markdown(Path(__file__).parent.parent / "CHANGELOG.md")

    async def tutorial(self, request):
        return self._markdown(Path(__file__).parent.parent / "docs" / "TUTORIAL.md")

    @staticmethod
    def _markdown(p: Path):
        try:
            return web.Response(text=p.read_text(encoding="utf-8"), content_type="text/markdown")
        except OSError:
            return web.Response(text="", content_type="text/markdown")

    async def on_cleanup(self, app):
        if self._loop_task:
            self._loop_task.cancel()
        if getattr(self, "_watch_task", None):
            self._watch_task.cancel()
        self.awake.release()
        await self.sources.stop()
        await self.tiles.close()
        if self.rec.rawlog:
            self.rec.rawlog.close()

    # -- handlers ---------------------------------------------------------------------
    async def index(self, request):
        return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    async def bootstrap(self, request):
        data = self.rec.bootstrap()
        data["mbtiles"] = self.tiles.mbtiles_info()
        data["nmea"] = self.nmea_status()
        data["awake"] = self.awake.status()
        cfg = self.rec.cfg
        data["about"] = diag.system_info(cfg.root, cfg.data_dir) | {"log_folder": str(diag.log_dir(cfg.root))}
        last = cfg.settings.get("last_version")
        data["about"]["updated_from"] = last if last and last != __version__ else ""
        if last != __version__:
            cfg.save_settings({"last_version": __version__})
        return json_ok(data)

    async def tab_add(self, request):
        tab = request.match_info["tab"]
        body = await request.json() if request.can_read_body else {}
        return json_ok(self.rec.new_row(tab, body.get("prefill"), body.get("lat"), body.get("lon")))

    async def tab_insert(self, request):
        tab = request.match_info["tab"]
        if tab not in schema.TABS:
            raise ValueErrorMsg("Unknown table.")
        body = await request.json()
        return json_ok(self.rec.insert_row(tab, str(body.get("id") or ""), str(body.get("method") or ""),
                                           "before" if body.get("where") == "before" else "after",
                                           str(body.get("time") or "")))

    async def add_resight(self, request):
        body = await request.json()
        return json_ok(self.rec.add_resight(str(body.get("id") or "")))

    async def tab_edit(self, request):
        tab = request.match_info["tab"]
        body = await request.json()
        return json_ok(self.rec.edit(tab, body["id"], body.get("updates", {})))

    async def tab_delete(self, request):
        body = await request.json()
        self.rec.delete(request.match_info["tab"], body["id"])
        return json_ok()

    async def tab_undo(self, request):
        return json_ok(done=self.rec.undo(request.match_info["tab"]))

    async def tab_redo(self, request):
        return json_ok(done=self.rec.redo(request.match_info["tab"]))

    async def qc(self, request):
        from .qc import run_qc
        loop = asyncio.get_running_loop()
        if self.rec.survey is None:
            raise ValueErrorMsg("Open a survey to check it.")
        return json_ok(report=await loop.run_in_executor(None, run_qc, self.rec))

    async def toggle_effort(self, request):
        return json_ok(self.rec.toggle_effort())

    async def survey_start(self, request):
        body = await request.json()
        self.rec.start_survey(body.get("name", ""), meta=body.get("meta"))
        return json_ok(survey=self.rec.survey_info())

    async def save_summary(self, request):
        """Store a summary HTML page (built in the browser) in the survey's exports folder."""
        body = await request.json()
        html = body.get("html") or ""
        if not self.rec.survey or not html.startswith("<!DOCTYPE html>"):
            raise ValueErrorMsg("Nothing to save.")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{self.rec.survey['prefix']}_summary_{stamp}.html"
        p = self.rec.cfg.export_dir / name
        p.write_text(html, encoding="utf-8")
        return json_ok(name=name, path=str(p), url=f"/api/download/{quote(name)}")

    async def survey_meta(self, request):
        body = await request.json()
        return json_ok(meta=self.rec.set_meta(body.get("updates", {})))

    async def survey_end(self, request):
        self.rec.end_survey()
        return json_ok(survey=self.rec.survey_info())

    async def survey_close(self, request):
        self.rec.close_survey()
        return json_ok()

    async def survey_open(self, request):
        body = await request.json()
        self.rec.open_survey(body.get("prefix", ""), resume=bool(body.get("resume")))
        return json_ok(survey=self.rec.survey_info())

    async def survey_resume(self, request):
        body = await request.json()
        self.rec.answer_resume(body.get("action", "later"))
        return json_ok(survey=self.rec.survey_info())

    async def survey_clear(self, request):
        body = await request.json()
        if not self.rec.survey or body.get("confirm") != self.rec.survey["prefix"]:
            raise ValueErrorMsg("Confirmation didn't match the survey name; nothing was deleted.")
        self.rec.clear_survey()
        return json_ok()

    # ---- survey packages (0.36): <survey>.spyhop-survey.zip
    async def survey_package_save(self, request):
        body = await request.json() if request.can_read_body else {}
        dest = await asyncio.get_running_loop().run_in_executor(None, self.rec.save_package, bool(body.get("logs")))
        return json_ok(name=dest.name, path=str(dest), size=dest.stat().st_size, url=f"/api/download/{quote(dest.name)}")

    async def survey_package_open(self, request):
        """Open a survey package sent as a file upload (multipart: file, and name for a new name)."""
        reader = await request.multipart()
        data, name = None, ""
        async for part in reader:
            if part.name == "name":
                name = (await part.text()).strip()
            elif part.filename:
                data = await part.read(decode=False)
        if not data:
            raise ValueErrorMsg("Choose a survey package (.spyhop-survey.zip) to open.")
        res = await asyncio.get_running_loop().run_in_executor(None, self.rec.open_package, data, name)
        if res.get("opened"):
            self._broadcast_soon({"type": "reload"})
        return json_ok(**res)

    async def data_dir(self, request):
        body = await request.json()
        self.rec.set_data_dir(body.get("path", ""))
        return json_ok(data_dir=str(self.rec.cfg.data_dir))

    async def pick_folder(self, request):
        """Show the computer's own folder chooser and return the chosen path (or null)."""
        loop = asyncio.get_running_loop()
        start = str(self.rec.cfg.data_dir)
        path = await loop.run_in_executor(None, choose_folder_dialog, start)
        return json_ok(path=path)

    async def pick_file(self, request):
        """Show the computer's own file chooser (for a FILE input's NMEA log) and return the path (or null)."""
        b = await request.json() if request.can_read_body else {}
        cur = clean_path(str(b.get("current") or ""))
        start = str(Path(cur).parent) if cur and Path(cur).parent.is_dir() else str(self.rec.cfg.nmea_log_dir)
        if not Path(start).is_dir():
            start = str(self.rec.cfg.data_dir)
        path = await asyncio.get_running_loop().run_in_executor(
            None, choose_file_dialog, start, str(b.get("prompt") or "Choose an NMEA log to replay"))
        return json_ok(path=path)

    async def export(self, request):
        body = await request.json() if request.can_read_body else {}
        f = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.rec.export(body.get("formats"), body.get("html"), body.get("report_as"), body.get("html_pdf")))
        return json_ok(name=f.name, path=str(f), folder=str(f.parent), zip=f.suffix == ".zip",
                       url=f"/api/download/{quote(f.name)}")

    async def download(self, request):
        name = request.match_info["name"]
        p = self.rec.cfg.export_dir / name
        if "/" in name or "\\" in name or not p.exists():
            raise web.HTTPNotFound()
        ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
        return web.FileResponse(p, headers={"Content-Disposition":
                                            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})

    async def settings(self, request):
        body = await request.json()
        updates = body.get("updates", {})
        restart = "nmea_sources" in updates
        try:
            from .config import LOCKED_SETTINGS
            locked = [LOCKED_SETTINGS[k] for k in updates if k in LOCKED_SETTINGS and updates[k] != self.rec.cfg.settings.get(k)]
            if locked and self.rec.survey_active():
                raise ValueErrorMsg(f"A survey is under way, so {', '.join(locked)} can't be changed until it ends "
                                    "(it changes how the data are recorded or worked out).")
            if updates.get("altitude_column") not in (None, "auto", "show", "hide"):
                raise ValueError("The Altitude column is auto, show or hide.")
            if updates.get("map_distance_unit") not in (None, "nm", "km", "m", "mi", "yd"):
                raise ValueError("The map distance unit is nm, km, m, mi or yd.")
            if updates.get("bearing_reference") not in (None, *schema.FIXED_LISTS["brgref"]):
                raise ValueError("The bearing reference is M, T, R or C.")
            if updates.get("segment_column") not in (None, "show", "hide"):
                raise ValueError("The effort segment column is show or hide.")
            if "column_layout" in updates:
                updates["column_layout"] = clean_column_layout(updates["column_layout"])
            if "smooth_vessel" in updates and not isinstance(updates["smooth_vessel"], bool):
                raise ValueError("Smooth vessel movement is on or off (true or false).")
            if "pane_layout" in updates:
                updates["pane_layout"] = clean_pane_layout(updates["pane_layout"])
        except (TypeError, ValueError) as e:
            raise ValueErrorMsg(str(e) if str(e) and not str(e).startswith("could not convert") else "That isn't a number.")
        self.rec.cfg.save_settings(updates)
        if "keep_awake" in updates or "keep_screen_on" in updates:
            self.sync_awake()
        if restart:
            await self.sources.start(list(self.rec.cfg.settings.get("nmea_sources") or [])
                                     + self.extra_sources)
        self._broadcast_soon({"type": "settings", "settings": self.rec.cfg.settings})
        return json_ok(settings=self.rec.cfg.settings)

    async def display(self, request):
        body = await request.json()
        self.rec.cfg.save_display(body.get("updates", {}))
        self._broadcast_soon({"type": "display", "display": self.rec.cfg.display})
        return json_ok(display=self.rec.cfg.display)

    async def save_list(self, request):
        b = await request.json()
        name = str(b.get("list", ""))
        if self.rec.survey_active() and not (name in self.rec.cfg.lists and self.rec.cfg.colors_only_change(name, b.get("rows") or [])):
            raise ValueErrorMsg("A survey is under way, so only the colors in the drop-down lists can be changed until it ends."
                                " Use Other for anything missing, and fill it in after the survey.")
        try:
            self.rec.cfg.save_list(name, b.get("rows") or [])
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        log.info("list %s saved from Settings → Dropdowns (%d rows)", b.get("list"), len(self.rec.cfg.lists.get(b.get("list"), [])))
        self._broadcast_soon({"type": "reload"})
        return json_ok()

    async def save_shortcuts(self, request):
        b = await request.json()
        tabs = {k: {c["key"] for c in v["columns"]} for k, v in schema.TABS.items()}
        try:
            self.rec.cfg.save_shortcuts(b.get("rows") or [], tabs)
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        self._broadcast_soon({"type": "reload"})
        return json_ok()

    async def reload_config(self, request):
        """Read templates/current (lists, shortcuts, spyhop-config.json) and spyhop-local.json again,
        e.g. after editing them by hand."""
        snap = self.rec.cfg.locked_snapshot() if self.rec.survey_active() else None
        self.rec.cfg.load()
        self.rec.cfg.reload()
        back = self.rec.cfg.restore_locked(snap) if snap else []
        self._broadcast_soon({"type": "reload"})
        return json_ok(kept=back, message=(f"A survey is under way, so these weren't changed (the files were put back): {', '.join(back)}." if back else ""))

    async def open(self, request):
        body = await request.json()
        what = body.get("what", "")
        cfg = self.rec.cfg
        targets = {"data": cfg.root, "app": cfg.root, "exports": cfg.export_dir, "charts": cfg.charts_dir,
                   "overlays": cfg.overlays_dir, "datafolder": cfg.data_dir,
                   "survey": cfg.survey_dir(self.rec.survey["prefix"]) if self.rec.survey else cfg.data_dir,
                   "nmealogs": cfg.nmea_log_dir, "logs": diag.log_dir(cfg.root),
                   "routes": cfg.routes_dir, "backups": cfg.backups_dir, "templates": cfg.saved_dir,
                   "current": cfg.current_dir}
        if what in targets:
            p = targets[what]
            if what in ("backups", "templates", "current", "nmealogs", "logs"):
                p.mkdir(parents=True, exist_ok=True)
        elif what.startswith("config:"):
            name = what.split(":", 1)[1]
            if name not in ("species", "event_types", "observers", "behaviors", "shortcuts"):
                raise ValueErrorMsg("Unknown config file")
            p = cfg.current_dir / f"{name}.csv"
        elif what == "reportsout":                       # the folder Run Reports last saved to
            if not self.last_reports_dir:
                raise ValueErrorMsg("No reports have been saved yet.")
            p = self.last_reports_dir
        elif what.startswith("export:"):
            p = cfg.export_dir / Path(what.split(":", 1)[1]).name
        else:
            raise ValueErrorMsg("Unknown target")
        try:
            open_path(p)
        except Exception as e:  # noqa: BLE001
            raise ValueErrorMsg(f"Couldn't open {p}: {e}")
        return json_ok(path=str(p))

    async def nmea(self, request):
        # listing serial ports can take a while on macOS, so keep it off the event loop
        ports = await asyncio.get_running_loop().run_in_executor(None, list_serial_ports)
        return json_ok(self.nmea_status(), ports=ports, all_sources=self.all_sources())

    async def nmea_sources(self, request):
        """Replace the GPS inputs. Entries marked session=True (e.g. from --sim) are
        used for this run only; the rest are saved in Settings."""
        b = await request.json()
        srcs = b.get("sources") or []
        for x in srcs:
            if x.get("type") == "file" and x.get("enabled", True):
                x["path"] = clean_path(str(x.get("path") or ""))
                if not x["path"]:
                    raise ValueErrorMsg("A FILE input needs the path of an NMEA log: press Choose… or paste it.")
                if not Path(x["path"]).is_file():
                    raise ValueErrorMsg(f"There's no file at {x['path']}. Check the path, or press Choose… to find it.")
        saved = [{k: v for k, v in x.items() if k != "session"} for x in srcs if not x.get("session")]
        self.extra_sources = [x for x in srcs if x.get("session")]
        self.rec.cfg.save_settings({"nmea_sources": saved})
        await self.sources.start(saved + self.extra_sources)
        self._broadcast_soon({"type": "settings", "settings": self.rec.cfg.settings})
        return json_ok(sources=self.all_sources())

    async def nmea_log(self, request):
        b = await request.json()
        st = self.rec.set_raw_logging(b.get("enabled"), b.get("timestamps"))
        self._broadcast_soon({"type": "settings", "settings": self.rec.cfg.settings})
        return json_ok(log=st)

    def all_sources(self) -> list[dict]:
        return (list(self.rec.cfg.settings.get("nmea_sources") or [])
                + [{**x, "session": True} for x in self.extra_sources])

    # -- tiles ------------------------------------------------------------------------
    async def tile_online(self, request):
        m = request.match_info
        r = await self.tiles.get_online(int(m["i"]), int(m["z"]), int(m["x"]), int(m["y"]))
        if r is None:
            raise web.HTTPNotFound()
        return web.Response(body=r[0], content_type=r[1],
                            headers={"Cache-Control": "max-age=86400"})

    # ---- MapLibre styles (Seascape) through the tile cache
    def _origin(self, request) -> str:
        return f"{request.scheme}://{request.host}"

    async def gl_style(self, request):
        style = await self.tiles.gl_style(int(request.match_info["i"]), self._origin(request))
        if style is None:
            raise web.HTTPNotFound(text="This map's style couldn't be loaded (no internet, and no saved copy).")
        return web.json_response(style, headers={"Cache-Control": "no-cache"})

    async def gl_tilejson(self, request):
        doc = await self.tiles.gl_tilejson(int(request.match_info["i"]), request.query.get("u", ""), self._origin(request))
        if doc is None:
            raise web.HTTPNotFound()
        return web.json_response(doc, headers={"Cache-Control": "no-cache"})

    async def gl_tile(self, request):
        m = request.match_info
        data, ctype, status = await self.tiles.gl_tile(int(m["i"]), request.query.get("u", ""), int(m["z"]), int(m["x"]), int(m["y"]))
        if data is None:
            # an empty or missing tile: MapLibre draws nothing there; 204 keeps its console quiet
            return web.Response(status=204 if status in (404, 204) else (403 if status == 403 else 504))
        headers = {"Cache-Control": "max-age=86400"}
        if ctype == "application/octet-stream":
            ctype = "application/x-protobuf"
            if data[:2] == b"\x1f\x8b":
                headers["Content-Encoding"] = "gzip"
        return web.Response(body=data, content_type=ctype, headers=headers)

    async def gl_glyphs(self, request):
        m = request.match_info
        url = self.tiles.fill_glyphs(request.query.get("u", ""), m["fontstack"], m["range"])
        data = await self.tiles.gl_file(int(m["i"]), url, "_glyphs")
        if data is None:
            raise web.HTTPNotFound()
        headers = {"Cache-Control": "max-age=604800"}
        if data[:2] == b"\x1f\x8b":
            headers["Content-Encoding"] = "gzip"
        return web.Response(body=data, content_type="application/x-protobuf", headers=headers)

    async def gl_sprite(self, request):
        m = request.match_info
        rest = m["rest"]
        cut = min([i for i in (rest.find("@"), rest.find(".")) if i >= 0] or [len(rest)])
        try:
            base = tiles_mod._unb64(rest[:cut])
        except ValueError:
            raise web.HTTPNotFound()
        data = await self.tiles.gl_file(int(m["i"]), base + rest[cut:], "_sprite")
        if data is None:
            raise web.HTTPNotFound()
        ctype = "application/json" if rest.endswith(".json") else "image/png"
        return web.Response(body=data, content_type=ctype, headers={"Cache-Control": "max-age=86400"})

    async def tile_mb(self, request):
        m = request.match_info
        r = self.tiles.get_mbtile(m["name"], int(m["z"]), int(m["x"]), int(m["y"]))
        if r is None:
            raise web.HTTPNotFound()
        return web.Response(body=r[0], content_type=r[1],
                            headers={"Cache-Control": "max-age=86400"})

    async def charts_rescan(self, request):
        self.tiles.rescan_charts()
        info = self.tiles.mbtiles_info()
        self._broadcast_soon({"type": "charts", "mbtiles": info})
        return json_ok(mbtiles=info)

    async def charts_delete(self, request):
        b = await request.json() if request.can_read_body else {}
        try:
            self.tiles.delete_chart(str(b.get("file") or ""))
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        log.info("chart deleted: %s", b.get("file"))
        info = self.tiles.mbtiles_info()
        self._broadcast_soon({"type": "charts", "mbtiles": info})
        return json_ok(mbtiles=info)

    # ---- a downloaded style area on its own (charts folder), for previews and as an offline layer
    async def off_style(self, request):
        style = self.tiles.offline_style(request.match_info["name"], self._origin(request))
        if style is None:
            raise web.HTTPNotFound()
        return web.json_response(style, headers={"Cache-Control": "no-cache"})

    async def off_tile(self, request):
        m = request.match_info
        data = self.tiles.offline_style_tile(m["name"], m["set"], int(m["z"]), int(m["x"]), int(m["y"]))
        if data is None:
            return web.Response(status=204)
        ctype, headers = tiles_mod.sniff_type(data), {"Cache-Control": "max-age=86400"}
        if ctype == "application/octet-stream":
            ctype = "application/x-protobuf"
            if data[:2] == b"\x1f\x8b":
                headers["Content-Encoding"] = "gzip"
        return web.Response(body=data, content_type=ctype, headers=headers)

    async def off_glyphs(self, request):
        m = request.match_info
        data = self.tiles.offline_glyphs(m["name"], m["fontstack"], m["range"])
        if data is None:
            raise web.HTTPNotFound()
        headers = {"Cache-Control": "max-age=604800"}
        if data[:2] == b"\x1f\x8b":
            headers["Content-Encoding"] = "gzip"
        return web.Response(body=data, content_type="application/x-protobuf", headers=headers)

    async def tiles_info(self, request):
        return json_ok(cache=self.tiles.cache_stats(), prefetch=self.tiles.prefetch_state,
                       mbtiles=self.tiles.mbtiles_info())

    async def tiles_prefetch(self, request):
        b = await request.json()
        if b.get("cancel"):
            self.tiles.cancel_prefetch()
            return json_ok()
        try:
            if b.get("dry_run"):
                plan = await self.tiles.plan_prefetch(int(b["source"]), b["bounds"], int(b["zmin"]), int(b["zmax"]))
                plan.pop("jobs")
                return json_ok(**plan)
            plan = await self.tiles.start_prefetch(int(b["source"]), b["bounds"], int(b["zmin"]), int(b["zmax"]),
                                                   name=str(b.get("name") or ""))
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(**plan)

    # -- overlays ---------------------------------------------------------------------
    async def overlay_get(self, request):
        name = Path(request.match_info["name"]).name
        p = self.rec.cfg.overlays_dir / name
        if not p.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    async def overlay_upload(self, request):
        reader = await request.multipart()
        saved = []
        async for part in reader:
            if part.filename:
                name = Path(part.filename).name
                if Path(name).suffix.lower() not in (".geojson", ".json", ".gpx", ".kml"):
                    raise ValueErrorMsg("Overlays must be GeoJSON, GPX or KML files.")
                data = await part.read(decode=False)
                (self.rec.cfg.overlays_dir / name).write_bytes(data)
                saved.append(name)
        self._broadcast_soon({"type": "overlays"})
        return json_ok(saved=saved)

    async def plan_gpx(self, request):
        """Save a planned trackline (built in the browser) as a GPX file in the exports folder."""
        b = await request.json()
        gpx = b.get("gpx") or ""
        if not gpx.startswith("<?xml") or "<gpx" not in gpx[:500]:
            raise ValueErrorMsg("That isn't a GPX file.")
        name = safe_name(b.get("name") or "plan") or "plan"
        out = self.rec.cfg.export_dir
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"{name}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.gpx"
        dest.write_text(gpx, encoding="utf-8")
        return json_ok(name=dest.name, path=str(dest), url=f"/api/download/{quote(dest.name)}")

    # ---- online overlays (map.js / online.js): AIS from Open Waters, RainViewer radar frames
    AIS_URL = os.environ.get("SPYHOP_AIS_URL", "https://ais.openwaters.io/v1/vessels")          # env: for tests
    RAINVIEWER_URL = os.environ.get("SPYHOP_RAINVIEWER_URL", "https://api.rainviewer.com/public/weather-maps.json")

    async def ais_vessels(self, request):
        """Vessels in a box from Open Waters AIS (GeoJSON), fetched by Spyhop so the window gets a
        plain answer offline. Answers for the same box are reused for 15 s."""
        try:
            parts = [float(x) for x in str(request.query.get("bbox", "")).split(",")]
            s_, w_, n_, e_ = parts
        except ValueError:
            raise ValueErrorMsg("bbox must be minLat,minLon,maxLat,maxLon")
        if not (-90 <= s_ < n_ <= 90 and -180 <= w_ <= 180 and -180 <= e_ <= 180):
            raise ValueErrorMsg("That box isn't on the map.")
        if (n_ - s_) * ((e_ - w_) % 360 or 360) > 100:
            return json_ok(features=[], too_big=True)
        key = ",".join(f"{v:.3f}" for v in (s_, w_, n_, e_))
        cache = getattr(self, "_ais_cache", None)
        if cache is None:
            cache = self._ais_cache = {}
        now = time.monotonic()
        hit = cache.get(key)
        if hit and now - hit[0] < 15:
            return json_ok(**hit[1])
        status, body, _ = await self.tiles._download(f"{self.AIS_URL}?bbox={key}")
        if status != 200:
            raise ValueErrorMsg("Couldn't get AIS vessels: " + (f"Open Waters AIS answered {status}" if status else "no internet connection"))
        try:
            data = json.loads(body)
        except ValueError:
            raise ValueErrorMsg("Open Waters AIS sent something that isn't GeoJSON.")
        out = {"features": data.get("features", []) if isinstance(data, dict) else []}
        for k in [k for k, v in cache.items() if now - v[0] > 60]:
            cache.pop(k, None)
        cache[key] = (now, out)
        return json_ok(**out)

    async def rainviewer_frames(self, request):
        """RainViewer's list of radar frames (the last 2 hours, every 10 minutes)."""
        hit = getattr(self, "_rv_cache", None)
        now = time.monotonic()
        if hit and now - hit[0] < 120:
            return json_ok(**hit[1])
        status, body, _ = await self.tiles._download(self.RAINVIEWER_URL)
        if status != 200:
            raise ValueErrorMsg("Couldn't get the radar frames: " + (f"RainViewer answered {status}" if status else "no internet connection"))
        try:
            d = json.loads(body)
            frames = [{"time": f["time"], "path": f["path"]} for f in d["radar"]["past"]]
            out = {"host": d["host"], "frames": frames}
        except (ValueError, KeyError, TypeError):
            raise ValueErrorMsg("RainViewer sent something unexpected.")
        self._rv_cache = (now, out)
        return json_ok(**out)

    # ---- online map feeds (Tools → Overlays → Online overlays; feeds.py)
    def _feeds(self) -> list[dict]:
        return [f for f in (self.rec.cfg.settings.get("online_feeds") or []) if isinstance(f, dict) and f.get("id")]

    def _feed_status(self, f: dict) -> dict:
        c = feeds.load_cache(self.rec.cfg, f["id"])
        return {**f, "fetched": c.get("fetched") if c else None, "count": len(c["features"]) if c else None}

    async def feeds_list(self, request):
        return json_ok(feeds=[self._feed_status(f) for f in self._feeds()], presets=feeds.PRESETS,
                       folder=str(feeds.feeds_dir(self.rec.cfg)))

    async def _fetch_feed(self, f: dict) -> list[dict]:
        try:
            feats = await feeds.fetch(self.tiles._download, f["url"])
        except feeds.FeedError as e:
            raise ValueErrorMsg(f"{f['name']}: {e}")
        feeds.save_cache(self.rec.cfg, f["id"], feats)
        return feats

    def _save_feeds(self, lst):
        self.rec.cfg.save_settings({"online_feeds": lst})
        self._broadcast_soon({"type": "feeds"})

    async def feed_add(self, request):
        b = await request.json()
        lst = self._feeds()
        try:
            f = feeds.clean({**(b.get("feed") or {}), "id": None}, lst)
        except feeds.FeedError as e:
            raise ValueErrorMsg(str(e))
        warning = None
        try:
            feats = await self._fetch_feed(f)
        except ValueErrorMsg as e:
            if "no internet connection" not in str(e):
                raise
            feats, warning = None, "Added, but there's no internet connection now: it will load when there is."
        lst.append(f)
        self._save_feeds(lst)
        return json_ok(feed=self._feed_status(f), count=None if feats is None else len(feats), warning=warning)

    async def feed_update(self, request):
        b = await request.json()
        lst = self._feeds()
        new = b.get("feed") or {}
        old = next((f for f in lst if f["id"] == new.get("id")), None)
        if not old:
            raise ValueErrorMsg("There's no feed like that.")
        try:
            f = feeds.clean({**old, **new}, lst)
        except feeds.FeedError as e:
            raise ValueErrorMsg(str(e))
        if f["url"] != old["url"]:
            feeds.drop_cache(self.rec.cfg, f["id"])
        self._save_feeds([f if x["id"] == f["id"] else x for x in lst])
        return json_ok(feed=self._feed_status(f))

    async def feed_delete(self, request):
        b = await request.json()
        lst = self._feeds()
        fid = str(b.get("id") or "")
        if not any(f["id"] == fid for f in lst):
            raise ValueErrorMsg("There's no feed like that.")
        feeds.drop_cache(self.rec.cfg, fid)
        self._save_feeds([f for f in lst if f["id"] != fid])
        return json_ok()

    async def feed_data(self, request):
        """A feed's features: the saved copy while it's fresh, else fetched again; the saved copy
        (marked stale) if that fails."""
        fid = request.query.get("id", "")
        f = next((x for x in self._feeds() if x["id"] == fid), None)
        if not f:
            raise ValueErrorMsg("There's no feed like that.")
        cache = feeds.load_cache(self.rec.cfg, fid)
        force = request.query.get("force") == "1"
        if cache and not force and time.time() - (cache.get("fetched") or 0) < f["refresh_min"] * 60:
            return json_ok(features=cache["features"], fetched=cache.get("fetched"))
        try:
            feats = await self._fetch_feed(f)
            return json_ok(features=feats, fetched=time.time())
        except ValueErrorMsg as e:
            if cache:
                return json_ok(features=cache["features"], fetched=cache.get("fetched"), stale=True, error=str(e))
            raise

    # ---- saved routes (Tools → Routes; routes.py)
    async def routes_list(self, request):
        return json_ok(routes=routes.list_routes(self.rec.cfg), folder=str(routes.routes_dir(self.rec.cfg)))

    async def route_file(self, request):
        try:
            return json_ok(gpx=routes.read(self.rec.cfg, request.query.get("file", "")))
        except routes.RouteError as e:
            raise ValueErrorMsg(str(e))

    async def route_save(self, request):
        b = await request.json()
        try:
            r = routes.save(self.rec.cfg, str(b.get("name") or ""), b.get("gpx") or "", b.get("replace") or None,
                            bool(b.get("overwrite")))
        except routes.RouteError as e:
            msg = str(e)
            if msg.startswith("exists:"):
                return json_ok(exists=msg.split(":", 1)[1])
            raise ValueErrorMsg(msg)
        self._broadcast_soon({"type": "routes"})
        return json_ok(route=r)

    async def route_delete(self, request):
        b = await request.json()
        try:
            routes.delete(self.rec.cfg, str(b.get("file") or ""))
        except routes.RouteError as e:
            raise ValueErrorMsg(str(e))
        self._broadcast_soon({"type": "routes"})
        return json_ok()

    # ---- the summary as a PDF (Tools → Summary; the page is built by the window)
    async def summary_pdf(self, request):
        b = await request.json()
        page = str(b.get("html") or "")
        if not page.startswith("<!DOCTYPE html>"):
            raise ValueErrorMsg("The summary page is missing.")
        prefix = safe_name((self.rec.survey or {}).get("prefix") or "no-survey")
        dest = self.rec.cfg.export_dir / f"{prefix}_summary_{time.strftime('%Y%m%d-%H%M%S')}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.get_running_loop().run_in_executor(None, html_to_pdf, page, dest, 6000)
        except PdfError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(name=dest.name, path=str(dest), url=f"/api/download/{quote(dest.name)}")

    # ---- reports (Tools → Reports; reports.py)
    async def reports_list(self, request):
        cfg = self.rec.cfg
        saved, errors = reports.load(cfg)
        return json_ok(reports=saved, errors=errors,
                       exports=str(cfg.export_dir), last_folder=str(self.last_reports_dir or ""),
                       columns={t: reports.columns(t) for t in reports.TABLES}, ops=reports.OPS,
                       pdf=find_chrome() is not None)

    @staticmethod
    def _report_spec(b) -> dict:
        try:
            return reports.clean(b.get("spec"))
        except reports.ReportError as e:
            raise ValueErrorMsg(str(e))

    def _reports_unlocked(self):
        """Saved reports are part of the data template, and reports read a finished survey: none can be run,
        saved or deleted during a survey (0.40)."""
        if self.rec.survey_active():
            raise ValueErrorMsg("Reports can't be run or changed during a survey: they're ready once it ends (End survey in the Survey tab).")

    async def report_run(self, request):
        self._reports_unlocked()
        b = await request.json()
        spec = self._report_spec(b)
        return json_ok(result=reports.run(self.rec, spec), counts=reports.counts(self.rec, spec["table"]))

    async def report_save(self, request):
        self._reports_unlocked()
        b = await request.json()
        try:
            f = reports.save(self.rec.cfg, b.get("spec") or {}, b.get("replace") or None)
        except reports.ReportError as e:
            raise ValueErrorMsg(str(e))
        self._broadcast_soon({"type": "reports"})
        return json_ok(report=f)

    async def report_delete(self, request):
        self._reports_unlocked()
        b = await request.json()
        try:
            reports.delete(self.rec.cfg, str(b.get("file", "")))
        except reports.ReportError as e:
            raise ValueErrorMsg(str(e))
        self._broadcast_soon({"type": "reports"})
        return json_ok()

    def _write_report(self, res: dict, fmt: str, dest: Path):
        if fmt == "pdf":
            html_to_pdf(reports.to_html(self.rec, res), dest, 3000)
            return
        text = reports.to_csv(res) if fmt == "csv" else reports.to_html(self.rec, res)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, dest)

    async def report_export(self, request):
        """Save one report (the one on screen) as CSV, HTML or PDF in the exports folder."""
        self._reports_unlocked()
        b = await request.json()
        spec, fmt = self._report_spec(b), b.get("format", "csv")
        if fmt not in ("csv", "html", "pdf"):
            raise ValueErrorMsg("Save as csv, html or pdf.")
        if self.rec.survey is None:
            raise ValueErrorMsg("Open a survey first.")
        res = reports.run(self.rec, spec)
        prefix = safe_name(self.rec.survey.get("prefix") or "no-survey")
        stem = reports.file_name(spec["name"] or "report")[:-5]
        dest = self.rec.cfg.export_dir / f"{prefix}_{stem}_{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.get_running_loop().run_in_executor(None, self._write_report, res, fmt, dest)
        except PdfError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(name=dest.name, path=str(dest), url=f"/api/download/{quote(dest.name)}", count=res["count"])

    async def reports_batch(self, request):
        """Run Reports: save the chosen saved reports, in the chosen formats, into a folder
        (the exports folder if none is given)."""
        self._reports_unlocked()
        b = await request.json()
        if self.rec.survey is None:
            raise ValueErrorMsg("Open a survey first.")
        cfg = self.rec.cfg
        files = [str(x) for x in (b.get("files") or [])]
        formats = [f for f in ("csv", "html", "pdf") if f in (b.get("formats") or [])]
        if not files:
            raise ValueErrorMsg("Choose at least one report.")
        if not formats:
            raise ValueErrorMsg("Choose at least one format.")
        if "pdf" in formats and find_chrome() is None:
            raise ValueErrorMsg("PDFs need Google Chrome or Microsoft Edge.")
        by_file = {f["file"]: f for f in reports.load(cfg)[0]}
        missing = [f for f in files if f not in by_file]
        if missing:
            raise ValueErrorMsg(f"There's no saved report {', '.join(missing)}.")
        raw = str(b.get("folder") or "").strip()
        folder = Path(raw).expanduser() if raw else cfg.export_dir
        if raw and not folder.is_absolute():
            raise ValueErrorMsg("Give the full path of the folder.")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueErrorMsg(f"Can't save in {folder}: {e}")
        prefix = safe_name(self.rec.survey.get("prefix") or "no-survey")
        stamp = time.strftime('%Y%m%d-%H%M%S')
        loop = asyncio.get_running_loop()
        saved = []
        for fn in files:
            spec = by_file[fn]
            res = reports.run(self.rec, spec)
            for fmt in formats:
                dest = folder / f"{prefix}_{fn[:-5]}_{stamp}.{fmt}"
                try:
                    await loop.run_in_executor(None, self._write_report, res, fmt, dest)
                except PdfError as e:
                    raise ValueErrorMsg(f"{spec['name']}: {e}")
                except OSError as e:
                    raise ValueErrorMsg(f"Can't write {dest}: {e}")
                saved.append({"report": spec["name"], "format": fmt, "name": dest.name, "count": res["count"]})
        self.last_reports_dir = folder
        return json_ok(folder=str(folder), files=saved)

    # ---- templates (Settings → Templates; templates.py)
    async def templates_check(self, request):
        """Check a template before using it: from a web address ({url}), a template in the templates
        folder ({template: file name}) or a backup ({backup: file name})."""
        b = await request.json() if request.can_read_body else {}
        cfg = self.rec.cfg
        if b.get("survey"):                # the template copy saved with a survey (0.36)
            p = self.rec.template_copy_path(Path(str(b["survey"])).name)
            if not p or not p.is_file():
                raise ValueErrorMsg("That survey has no copy of its template (it was started before Spyhop 0.36).")
            url, kind = str(p), "survey"
        elif b.get("template") or b.get("backup"):
            try:
                if b.get("template"):
                    url, kind = str(templates._template_file(cfg, b["template"])), "folder"
                else:
                    name = str(b["backup"])
                    if "/" in name or "\\" in name or not templates.is_template_name(name):
                        raise templates.TemplateError("That isn't the name of a backup.")
                    url, kind = str(templates.backups_dir(cfg) / name), "backup"
            except templates.TemplateError as e:
                raise ValueErrorMsg(str(e))
        else:
            url, kind = str(b.get("url", "")).strip(), "web"
            cfg.save_settings({"template_url": url})

        def work():
            files, source, name = templates.fetch_named(url)
            t = templates.read_template(files)
            if kind == "backup":       # restoring it also takes away what the template used after it added
                t["_undo"] = (cfg.settings.get("template_added") or {}).get(Path(url).name)
            return source, name, t, templates.compare(cfg, t)
        try:
            source, name, t, plan = await asyncio.get_running_loop().run_in_executor(None, work)
        except templates.TemplateError as e:
            raise ValueErrorMsg(str(e))
        if kind == "web" and templates.resolve(url)[0] == "file":
            kind = "folder" if templates.in_templates_dir(cfg, url) else "file"
        if kind == "survey":           # name it after the saved template it matched when the survey started
            rec_name = self.rec.read_meta_system(Path(str(b["survey"])).name).get("template_created", "")
            t["_current_name"] = rec_name or None
            name = rec_name or f"the template saved with {Path(str(b['survey'])).name}"
        t["_kind"], t["_name"] = kind, name
        return json_ok(token=templates.remember(url, t), source=source, files=plan, kind=kind, name=name,
                       history=t["history"][:8], ignored=t["ignored"], problems=t["problems"],
                       info=t.get("info"), online=templates.online_summary(t),
                       survey_active=self.rec.survey_active())

    async def templates_use(self, request):
        b = await request.json() if request.can_read_body else {}
        got = templates.recall(b.get("token", ""))
        if not got:
            raise ValueErrorMsg("That check is too old. Check the template again.")
        url, t = got
        cfg = self.rec.cfg
        during = self.rec.survey_active()       # then only the preferences (and colors) are used (0.40)
        backup = bool(b.get("backup"))
        cfg.save_settings({"template_backup": backup})
        kind = t.get("_kind", "web")

        def work():
            saved = templates.save_backup(cfg) if backup else None
            changed, done = templates.apply_all(cfg, t, data=not during)
            copy = None
            if kind in ("web", "file"):          # keep a copy in the templates folder, for use offline
                try:
                    copy = templates.keep_copy(cfg, t, t.get("_name") or "")
                except OSError as e:
                    log.warning("couldn't keep a copy of the template: %s", e)
            return saved, changed, done, copy
        try:
            saved, changed, done, copy = await asyncio.get_running_loop().run_in_executor(None, work)
        except templates.TemplateError as e:
            raise ValueErrorMsg(str(e))
        added_ids = self.rec.template_waypoints(done["waypoints"], done["remove_waypoints"])
        if done["inputs"]:
            await self.sources.start(list(cfg.settings.get("nmea_sources") or []) + self.extra_sources)
        if done["settings"]:
            self.rec.set_raw_logging()
            self.sync_awake()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        current = copy.name if copy else (Path(url).name if kind == "folder" else t.get("_current_name") if kind == "survey" else None)
        upd = {"template_fingerprints": {"from": "use", "when": now, "files": templates.fingerprints(cfg)},
               "template_current": {"name": current, "how": "backup" if kind == "backup" else "loaded", "when": now}}
        record = {k: v for k, v in (("waypoints", added_ids), ("routes", done["routes"]),
                                    ("overlays", done["overlays"]), ("feeds", done["feeds"])) if v}
        added = dict(cfg.settings.get("template_added") or {})
        if kind == "backup":
            added.pop(Path(url).name, None)
        if saved and record:
            added[saved.name] = {**record, "when": now}
        upd["template_added"] = dict(sorted(added.items(), key=lambda kv: kv[1].get("when", ""))[-20:])
        if kind in ("web", "file"):
            upd["template_last"] = {"url": url, "pulled": now, "latest": t["history"][0] if t["history"] else None,
                                    "changed": changed}
        cfg.save_settings(upd)
        log.info("template used from %s: %s", url, ", ".join(changed) or "no changes")
        for kind_ in ("feeds", "routes", "overlays"):
            self._broadcast_soon({"type": kind_})
        self._broadcast_soon({"type": "reload"})
        return json_ok(changed=changed, backup=str(saved) if saved else None, copy=copy.name if copy else None,
                       added={"waypoints": len(added_ids), "routes": len(done["routes"]),
                              "overlays": len(done["overlays"]), "feeds": len(done["feeds"])},
                       removed_waypoints=len(done["remove_waypoints"]), data_kept=done["data_kept"])

    async def templates_backup(self, request):
        try:
            p = await asyncio.get_running_loop().run_in_executor(None, templates.save_backup, self.rec.cfg)
        except templates.TemplateError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(path=str(p), folder=str(p.parent))

    async def templates_list(self, request):
        cfg = self.rec.cfg
        try:
            items, backups = await asyncio.get_running_loop().run_in_executor(
                None, lambda: (templates.list_templates(cfg), templates.list_backups(cfg)))
        except OSError as e:
            raise ValueErrorMsg(f"Couldn't read the templates folder: {e}")
        return json_ok(folder=str(templates.templates_dir(cfg)), templates=items, backups=backups,
                       backups_folder=str(templates.backups_dir(cfg)), current_folder=str(cfg.current_dir),
                       current=cfg.settings.get("template_current") or None,
                       status=templates.current_status(cfg))

    async def templates_status(self, request):
        """Is the current template saved as a template? (templates.current_status; asked before a survey starts)"""
        st = await asyncio.get_running_loop().run_in_executor(None, templates.current_status, self.rec.cfg)
        return json_ok(status=st)

    async def templates_changes(self, request):
        """What the record of changes' "What changed" should say: for a new template, the parts changed since
        the last time one was used or saved here; for updating a template ({name}), the parts that differ from it."""
        cfg = self.rec.cfg
        name = request.query.get("name", "")
        info = {"by": cfg.settings.get("template_author", ""), **templates.local_counts(cfg),
                "version": __version__, "min_default": templates.FORMAT_MIN}
        if name:
            try:
                t = templates.read_template_file(cfg, name)
                ti = t.get("info") or {}
                return json_ok(files=templates.changed_from_template(cfg, name), since="template_file",
                               includes=ti.get("includes"), min_spyhop=ti.get("min_spyhop"), **info)
            except templates.TemplateError as e:
                raise ValueErrorMsg(str(e))
        base = cfg.settings.get("template_fingerprints") or {}
        return json_ok(files=templates.changed_since(cfg, base.get("files")), since=base.get("from"),
                       when=base.get("when"), **info)

    async def templates_save(self, request):
        b = await request.json() if request.can_read_body else {}
        by, notes, changed, name = (str(b.get(k, "") or "").strip() for k in ("by", "notes", "changed", "name"))
        overwrite = bool(b.get("overwrite"))
        if not by or not notes:
            raise ValueErrorMsg("Give your name and what changed, for the template's record of changes.")
        cfg = self.rec.cfg
        include = [k for k in templates.OPTIONAL if k in (b.get("include") or [])]
        min_v, online = b.get("min_spyhop"), b.get("online")
        try:
            p = await asyncio.get_running_loop().run_in_executor(
                None, lambda: templates.save_template(cfg, name, by, changed, notes, overwrite, include, min_v, online))
        except templates.TemplateError as e:
            raise ValueErrorMsg(str(e))
        except OSError as e:
            raise ValueErrorMsg(f"Couldn't save the template: {e}")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cfg.save_settings({"template_author": by,
                           "template_fingerprints": {"from": "save", "when": now, "files": templates.fingerprints(cfg)},
                           "template_current": {"name": p.name, "how": "saved", "when": now}})
        log.info("template %s by %s: %s (%s)", "updated" if overwrite else "saved", by, notes, changed or "all")
        return json_ok(name=p.name, path=str(p), url=f"/api/templates/file/{quote(p.name)}")

    async def templates_file(self, request):
        """Download a template from the templates folder (to upload it for the team)."""
        try:
            p = templates._template_file(self.rec.cfg, request.match_info["name"])
        except templates.TemplateError as e:
            raise web.HTTPNotFound(text=str(e))
        if not p.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(p.name)}"})

    # ---- updates (Settings → About; updater.py)
    async def update_check(self, request):
        try:
            info = await asyncio.get_running_loop().run_in_executor(None, updater.check)
        except updater.UpdateError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(update=info)

    async def update_install(self, request):
        b = await request.json() if request.can_read_body else {}
        info = b.get("update")
        try:
            res = await asyncio.get_running_loop().run_in_executor(None, updater.install, self.rec.cfg, info)
        except updater.UpdateError as e:
            raise ValueErrorMsg(str(e))
        res["can_restart"] = updater.can_restart_in_place()
        return json_ok(result=res)

    async def update_restart(self, request):
        if not updater.can_restart_in_place():
            raise ValueErrorMsg("Close Spyhop's console window and start Spyhop again from its icon.")

        async def later():
            await asyncio.sleep(0.6)
            await self.sources.stop()
            self.awake.release()
            if self.rec.rawlog:
                self.rec.rawlog.close()
            updater.restart()
        asyncio.create_task(later())
        return json_ok(restarting=True)

    # ---- uninstall / reinstall (Settings → About; uninstall.py)
    def _uninstall_args(self, b):
        return (str(b.get("mode") or "uninstall"), bool(b.get("delete_settings")), bool(b.get("delete_data")))

    async def uninstall_plan(self, request):
        b = await request.json() if request.can_read_body else {}
        mode, ds, dd = self._uninstall_args(b)
        p = await asyncio.get_running_loop().run_in_executor(None, uninstall.plan, self.rec.cfg, mode, ds, dd)
        p["survey_active"] = bool(self.rec.survey_active())
        return json_ok(plan=p)

    async def uninstall_start(self, request):
        b = await request.json() if request.can_read_body else {}
        mode, ds, dd = self._uninstall_args(b)
        if self.rec.survey_active():
            raise ValueErrorMsg("A survey is under way. End it (Survey tab) before you uninstall or reinstall Spyhop.")
        try:
            res = await asyncio.get_running_loop().run_in_executor(
                None, lambda: uninstall.start(self.rec.cfg, mode, ds, dd, str(b.get("confirm") or ""), b.get("update")))
        except (uninstall.UninstallError, updater.UpdateError) as e:
            raise ValueErrorMsg(str(e))
        log.warning("%s: %s", mode, res["message"])
        self._broadcast_soon({"type": "closing", "message": res["message"]})

        def _exit():
            raise web.GracefulExit()            # stops run_app; on_cleanup closes the inputs and files

        async def later():
            await asyncio.sleep(1.0)
            await self.sources.stop()
            if self.rec.rawlog:
                self.rec.rawlog.close()
            asyncio.get_running_loop().call_soon(_exit)
        asyncio.create_task(later())
        return json_ok(result=res)

    async def qc_fix(self, request):
        """Error check → Fix: mark a trackline jump or GPS gap with an ERROR Effort row."""
        b = await request.json()
        fix = b.get("fix") or {}
        if fix.get("kind") != "track_break":
            raise ValueErrorMsg("Spyhop doesn't know how to fix that.")
        return json_ok(**self.rec.insert_track_break(str(fix.get("t0", "")), str(fix.get("t1", ""))))

    async def overlay_from_survey(self, request):
        """Draw another survey in the data folder as a map overlay."""
        b = await request.json()
        prefix = str(b.get("prefix") or "")
        try:
            name, gj = self.rec.survey_overlay(prefix)
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        (self.rec.cfg.overlays_dir / name).write_text(json.dumps(gj), encoding="utf-8")
        self._broadcast_soon({"type": "overlays"})
        return json_ok(name=name, features=len(gj["features"]))

    async def overlay_delete(self, request):
        name = Path(request.match_info["name"]).name
        p = self.rec.cfg.overlays_dir / name
        if p.exists():
            p.unlink()
        self._broadcast_soon({"type": "overlays"})
        return json_ok()

    def build(self) -> web.Application:
        app = web.Application(middlewares=[timing, errors, no_cache], client_max_size=1024 ** 3)     # survey packages with raw NMEA logs can be large
        r = app.router
        r.add_get("/", self.index)
        r.add_get("/ws", self.ws_handler)
        r.add_get("/api/bootstrap", self.bootstrap)
        r.add_post("/api/tab/{tab}/add", self.tab_add)
        r.add_post("/api/sightings/resight", self.add_resight)
        r.add_post("/api/tab/{tab}/insert", self.tab_insert)
        r.add_post("/api/tab/{tab}/edit", self.tab_edit)
        r.add_post("/api/tab/{tab}/delete", self.tab_delete)
        r.add_post("/api/tab/{tab}/undo", self.tab_undo)
        r.add_post("/api/tab/{tab}/redo", self.tab_redo)
        r.add_post("/api/toggle-effort", self.toggle_effort)
        r.add_post("/api/diagnostics", self.diagnostics)
        r.add_get("/api/diagnostics/{name}", self.diagnostics_file)
        r.add_get("/api/changelog", self.changelog)
        r.add_get("/api/tutorial", self.tutorial)
        r.add_get("/api/instruments/history", self.inst_history)
        r.add_post("/api/client-log", self.client_log)
        r.add_post("/api/qc", self.qc)
        r.add_post("/api/qc/fix", self.qc_fix)
        r.add_post("/api/update/check", self.update_check)
        r.add_post("/api/update/install", self.update_install)
        r.add_post("/api/update/restart", self.update_restart)
        r.add_post("/api/uninstall/plan", self.uninstall_plan)
        r.add_post("/api/uninstall/start", self.uninstall_start)
        r.add_post("/api/summary/pdf", self.summary_pdf)
        r.add_get("/api/reports", self.reports_list)
        r.add_post("/api/reports/run", self.report_run)
        r.add_post("/api/reports/save", self.report_save)
        r.add_post("/api/reports/delete", self.report_delete)
        r.add_post("/api/reports/export", self.report_export)
        r.add_post("/api/reports/batch", self.reports_batch)
        r.add_post("/api/survey/start", self.survey_start)
        r.add_post("/api/survey/end", self.survey_end)
        r.add_post("/api/survey/meta", self.survey_meta)
        r.add_post("/api/summary/save", self.save_summary)
        r.add_post("/api/survey/close", self.survey_close)
        r.add_post("/api/survey/open", self.survey_open)
        r.add_post("/api/survey/resume", self.survey_resume)
        r.add_post("/api/survey/clear", self.survey_clear)
        r.add_post("/api/survey/package/save", self.survey_package_save)
        r.add_post("/api/survey/package/open", self.survey_package_open)
        r.add_post("/api/data-dir", self.data_dir)
        r.add_post("/api/pick-folder", self.pick_folder)
        r.add_post("/api/pick-file", self.pick_file)
        r.add_post("/api/export", self.export)
        r.add_get("/api/download/{name}", self.download)
        r.add_post("/api/settings", self.settings)
        r.add_post("/api/display", self.display)
        r.add_post("/api/config/reload", self.reload_config)
        r.add_post("/api/config/list", self.save_list)
        r.add_post("/api/config/shortcuts", self.save_shortcuts)
        r.add_get("/api/templates", self.templates_list)
        r.add_get("/api/templates/status", self.templates_status)
        r.add_post("/api/templates/check", self.templates_check)
        r.add_post("/api/templates/use", self.templates_use)
        r.add_post("/api/templates/backup", self.templates_backup)
        r.add_post("/api/templates/save", self.templates_save)
        r.add_get("/api/templates/file/{name}", self.templates_file)
        r.add_get("/api/templates/changes", self.templates_changes)
        r.add_post("/api/open", self.open)
        r.add_get("/api/nmea", self.nmea)
        r.add_post("/api/nmea/sources", self.nmea_sources)
        r.add_post("/api/nmea/log", self.nmea_log)
        r.add_get("/tiles/s/{i}/{z}/{x}/{y}", self.tile_online)
        r.add_get("/tiles/mb/{name}/{z}/{x}/{y}", self.tile_mb)
        r.add_get("/tiles/gl/{i}/style.json", self.gl_style)
        r.add_get("/tiles/gl/{i}/tilejson", self.gl_tilejson)
        r.add_get("/tiles/gl/{i}/t/{z}/{x}/{y}", self.gl_tile)
        r.add_get("/tiles/gl/{i}/glyphs/{fontstack}/{range}", self.gl_glyphs)
        r.add_get("/tiles/gl/{i}/sprite/{rest}", self.gl_sprite)
        r.add_get("/api/tiles", self.tiles_info)
        r.add_post("/api/tiles/prefetch", self.tiles_prefetch)
        r.add_post("/api/tiles/rescan", self.charts_rescan)
        r.add_post("/api/tiles/delete", self.charts_delete)
        r.add_get("/tiles/off/{name}/style.json", self.off_style)
        r.add_get("/tiles/off/{name}/t/{set}/{z}/{x}/{y}", self.off_tile)
        r.add_get("/tiles/off/{name}/glyphs/{fontstack}/{range}", self.off_glyphs)
        r.add_get("/overlays/{name}", self.overlay_get)
        r.add_post("/api/overlays", self.overlay_upload)
        r.add_delete("/api/overlays/{name}", self.overlay_delete)
        r.add_post("/api/plan/gpx", self.plan_gpx)
        r.add_get("/api/ais", self.ais_vessels)
        r.add_get("/api/feeds", self.feeds_list)
        r.add_get("/api/feeds/data", self.feed_data)
        r.add_post("/api/feeds/add", self.feed_add)
        r.add_post("/api/feeds/update", self.feed_update)
        r.add_post("/api/feeds/delete", self.feed_delete)
        r.add_get("/api/radar/rainviewer", self.rainviewer_frames)
        r.add_get("/api/routes", self.routes_list)
        r.add_get("/api/routes/file", self.route_file)
        r.add_post("/api/routes/save", self.route_save)
        r.add_post("/api/routes/delete", self.route_delete)
        r.add_post("/api/overlays/survey", self.overlay_from_survey)
        r.add_static("/static/", WEB)
        app.on_startup.append(self.on_startup)
        app.on_cleanup.append(self.on_cleanup)
        return app
