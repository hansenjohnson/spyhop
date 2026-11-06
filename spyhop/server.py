"""Local web server: REST API, websocket for live updates, tiles and static files."""
from __future__ import annotations

import asyncio
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
from . import awake, configpack, __version__, diag, reports, schema, updater
from .browser import find_chrome, html_to_pdf, PdfError
from .sources import SourceManager, list_serial_ports
from .store import safe_name
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


def choose_folder_dialog(start: str) -> str | None:
    """Native folder chooser via the operating system (no GUI toolkit needed)."""
    system = platform.system()
    try:
        if system == "Darwin":
            script = ('POSIX path of (choose folder with prompt "Choose the folder for Spyhop survey data" '
                      f'default location (POSIX file "{start}"))')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
            return r.stdout.strip().rstrip("/") or None if r.returncode == 0 else None
        if system == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$f.Description='Choose the folder for Spyhop survey data';"
                  f"$f.SelectedPath='{start}';"
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


class App:
    def __init__(self, data_dir: Path, extra_sources: list[dict] | None = None):
        self.rec = Recorder(data_dir)
        self.sources = SourceManager(self.rec.decoder)
        self.tiles = TileService(self.rec.cfg)
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
               "errors": d.errors, "log": self.rec.raw_log_status()}
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
            None, diag.make_bundle, cfg.root, cfg.data_dir, cfg.settings_path, extra, diag.log_dir(cfg.root))
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
            raise ValueErrorMsg("Confirmation didn't match the survey name; nothing was cleared.")
        self.rec.clear_survey()
        return json_ok()

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
        if self.rec.survey_active():
            raise ValueErrorMsg("A survey is under way, so the drop-down lists can't be changed until it ends.")
        try:
            self.rec.cfg.save_list(str(b.get("list", "")), b.get("rows") or [])
        except ValueError as e:
            raise ValueErrorMsg(str(e))
        log.info("list %s saved from Survey → Dropdowns (%d rows)", b.get("list"), len(self.rec.cfg.lists.get(b.get("list"), [])))
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
        self.rec.cfg.reload()
        self._broadcast_soon({"type": "reload"})
        return json_ok()

    async def open(self, request):
        body = await request.json()
        what = body.get("what", "")
        cfg = self.rec.cfg
        targets = {"data": cfg.root, "app": cfg.root, "exports": cfg.export_dir, "charts": cfg.charts_dir,
                   "overlays": cfg.overlays_dir, "survey": cfg.data_dir, "datafolder": cfg.data_dir,
                   "nmealogs": cfg.data_dir / "nmea_logs", "logs": diag.log_dir(cfg.root),
                   "reports": reports.user_dir(cfg),
                   "backups": Path(cfg.settings.get("group_config_backup_dir") or cfg.root / "config_backups")}
        if what in targets:
            p = targets[what]
            if what == "backups":
                p.mkdir(parents=True, exist_ok=True)
            if what == "reports":
                reports.prepare_user_dir(cfg)
            if what in ("nmealogs", "logs"):
                p.mkdir(parents=True, exist_ok=True)
        elif what.startswith("config:"):
            name = what.split(":", 1)[1]
            if name not in ("species", "event_types", "observers", "behaviors", "shortcuts", "display"):
                raise ValueErrorMsg("Unknown config file")
            p = cfg.root / f"{name}.csv"
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

    async def tile_mb(self, request):
        m = request.match_info
        r = self.tiles.get_mbtile(m["name"], int(m["z"]), int(m["x"]), int(m["y"]))
        if r is None:
            raise web.HTTPNotFound()
        return web.Response(body=r[0], content_type=r[1],
                            headers={"Cache-Control": "max-age=86400"})

    async def tiles_info(self, request):
        return json_ok(cache=self.tiles.cache_stats(), prefetch=self.tiles.prefetch_state,
                       mbtiles=self.tiles.mbtiles_info())

    async def tiles_prefetch(self, request):
        b = await request.json()
        if b.get("cancel"):
            self.tiles.cancel_prefetch()
            return json_ok()
        n = self.tiles.start_prefetch(int(b["source"]), b["bounds"], int(b["zmin"]), int(b["zmax"]))
        return json_ok(total=n)

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

    # ---- reports (Survey → Reports; definitions in reports.py / report_defs/)
    async def reports_list(self, request):
        defs, errors = reports.load_definitions(self.rec.cfg)
        return json_ok(reports=[{k: d.get(k) for k in ("id", "title", "description", "order", "table", "source", "file")}
                                for d in defs], errors=errors, folder=str(reports.user_dir(self.rec.cfg)),
                       pdf=find_chrome() is not None)

    async def report_data(self, request):
        d = reports.get_definition(self.rec.cfg, request.match_info["id"])
        if d is None:
            raise ValueErrorMsg("There's no report with that name (check the reports folder).")
        return json_ok(report=reports.run(self.rec, d))

    async def report_save(self, request):
        """Save a report as HTML or PDF in the exports folder. The Summary's page comes from the window."""
        b = await request.json()
        rid, fmt = str(b.get("id", "")), b.get("format", "html")
        if fmt not in ("html", "pdf"):
            raise ValueErrorMsg("Save as html or pdf.")
        if rid == "summary":
            page = str(b.get("html") or "")
            if not page.startswith("<!DOCTYPE html>"):
                raise ValueErrorMsg("The summary page is missing.")
        else:
            d = reports.get_definition(self.rec.cfg, rid)
            if d is None:
                raise ValueErrorMsg("There's no report with that name.")
            page = reports.to_html(self.rec, reports.run(self.rec, d))
        prefix = safe_name((self.rec.survey or {}).get("prefix") or "no-survey")
        dest = self.rec.cfg.export_dir / f"{prefix}_{rid}_{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "pdf":
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, html_to_pdf, page, dest, 6000 if rid == "summary" else 3000)
            except PdfError as e:
                raise ValueErrorMsg(str(e))
        else:
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(page, encoding="utf-8")
            os.replace(tmp, dest)
        return json_ok(name=dest.name, path=str(dest), url=f"/api/download/{quote(dest.name)}")

    # ---- group config packs (Survey → File → Group config; configpack.py)
    async def groupconfig_check(self, request):
        b = await request.json() if request.can_read_body else {}
        url = str(b.get("url", "")).strip()
        cfg = self.rec.cfg
        cfg.save_settings({"group_config_url": url})

        def work():
            files, source = configpack.fetch(url)
            pack = configpack.read_pack(files)
            return source, pack, configpack.compare(cfg, pack)
        try:
            source, pack, plan = await asyncio.get_running_loop().run_in_executor(None, work)
        except configpack.PackError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(token=configpack.remember(url, pack), source=source, files=plan,
                       manifest=pack["manifest"][:8], ignored=pack["ignored"], problems=pack["problems"],
                       survey_active=self.rec.survey_active())

    async def groupconfig_pull(self, request):
        b = await request.json() if request.can_read_body else {}
        got = configpack.recall(b.get("token", ""))
        if not got:
            raise ValueErrorMsg("That check is too old. Press Check for new config again.")
        url, pack = got
        cfg = self.rec.cfg
        backup = bool(b.get("backup"))
        bdir = str(b.get("backup_dir", "") or "").strip()
        cfg.save_settings({"group_config_backup": backup, "group_config_backup_dir": bdir})

        def work():
            saved = configpack.save_backup(cfg, bdir) if backup else None
            return saved, configpack.apply(cfg, pack)
        try:
            saved, changed = await asyncio.get_running_loop().run_in_executor(None, work)
        except configpack.PackError as e:
            raise ValueErrorMsg(str(e))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cfg.save_settings({"group_config_last": {
            "url": url, "pulled": now, "latest": pack["manifest"][0] if pack["manifest"] else None, "changed": changed},
            "group_config_fingerprints": {"from": "pull", "when": now, "files": configpack.fingerprints(cfg)}})
        log.info("group config pulled from %s: %s", url, ", ".join(changed) or "no changes")
        self._broadcast_soon({"type": "reload"})
        return json_ok(changed=changed, backup=str(saved) if saved else None)

    async def groupconfig_backup(self, request):
        b = await request.json() if request.can_read_body else {}
        try:
            p = await asyncio.get_running_loop().run_in_executor(
                None, configpack.save_backup, self.rec.cfg, str(b.get("dir", "") or "").strip())
        except configpack.PackError as e:
            raise ValueErrorMsg(str(e))
        return json_ok(path=str(p), folder=str(p.parent))

    async def groupconfig_changes(self, request):
        """What "Make a pack" would put in the log's Files column: the files changed since the last pull or pack."""
        cfg = self.rec.cfg
        base = cfg.settings.get("group_config_fingerprints") or {}
        changed = configpack.changed_since(cfg, base.get("files"))
        return json_ok(files=changed, since=base.get("from"), when=base.get("when"),
                       by=cfg.settings.get("group_config_author", ""), name=cfg.settings.get("group_config_pack_name", ""))

    async def groupconfig_pack(self, request):
        b = await request.json() if request.can_read_body else {}
        by, notes, files = (str(b.get(k, "") or "").strip() for k in ("by", "notes", "files"))
        if not by or not notes:
            raise ValueErrorMsg("Give your name and what changed, for the pack's record of changes.")
        cfg = self.rec.cfg
        configpack.log_change(cfg, by, files or "all", notes)
        data = configpack.make_zip(cfg)
        name = configpack.safe_pack_name(b.get("name")) or f"spyhop-config-pack-{datetime.now().strftime('%Y%m%d')}.zip"
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        p = cfg.export_dir / name
        p.write_bytes(data)
        cfg.save_settings({"group_config_author": by, "group_config_pack_name": p.name, "group_config_fingerprints": {
            "from": "pack", "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": configpack.fingerprints(cfg)}})
        log.info("config pack made by %s: %s (%s)", by, notes, files or "all")
        return json_ok(name=p.name, path=str(p), url=f"/api/download/{quote(p.name)}")

    # ---- updates (Survey → About; updater.py)
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

    async def qc_fix(self, request):
        """Quality Control → Fix: mark a trackline jump or GPS gap with an ERROR Effort row."""
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
        app = web.Application(middlewares=[timing, errors, no_cache], client_max_size=50 * 1024 ** 2)
        r = app.router
        r.add_get("/", self.index)
        r.add_get("/ws", self.ws_handler)
        r.add_get("/api/bootstrap", self.bootstrap)
        r.add_post("/api/tab/{tab}/add", self.tab_add)
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
        r.add_get("/api/reports", self.reports_list)
        r.add_get("/api/reports/{id}", self.report_data)
        r.add_post("/api/reports/save", self.report_save)
        r.add_post("/api/survey/start", self.survey_start)
        r.add_post("/api/survey/end", self.survey_end)
        r.add_post("/api/survey/meta", self.survey_meta)
        r.add_post("/api/summary/save", self.save_summary)
        r.add_post("/api/survey/close", self.survey_close)
        r.add_post("/api/survey/open", self.survey_open)
        r.add_post("/api/survey/resume", self.survey_resume)
        r.add_post("/api/survey/clear", self.survey_clear)
        r.add_post("/api/data-dir", self.data_dir)
        r.add_post("/api/pick-folder", self.pick_folder)
        r.add_post("/api/export", self.export)
        r.add_get("/api/download/{name}", self.download)
        r.add_post("/api/settings", self.settings)
        r.add_post("/api/display", self.display)
        r.add_post("/api/config/reload", self.reload_config)
        r.add_post("/api/config/list", self.save_list)
        r.add_post("/api/config/shortcuts", self.save_shortcuts)
        r.add_post("/api/groupconfig/check", self.groupconfig_check)
        r.add_post("/api/groupconfig/pull", self.groupconfig_pull)
        r.add_post("/api/groupconfig/backup", self.groupconfig_backup)
        r.add_post("/api/groupconfig/pack", self.groupconfig_pack)
        r.add_get("/api/groupconfig/changes", self.groupconfig_changes)
        r.add_post("/api/open", self.open)
        r.add_get("/api/nmea", self.nmea)
        r.add_post("/api/nmea/sources", self.nmea_sources)
        r.add_post("/api/nmea/log", self.nmea_log)
        r.add_get("/tiles/s/{i}/{z}/{x}/{y}", self.tile_online)
        r.add_get("/tiles/mb/{name}/{z}/{x}/{y}", self.tile_mb)
        r.add_get("/api/tiles", self.tiles_info)
        r.add_post("/api/tiles/prefetch", self.tiles_prefetch)
        r.add_get("/overlays/{name}", self.overlay_get)
        r.add_post("/api/overlays", self.overlay_upload)
        r.add_delete("/api/overlays/{name}", self.overlay_delete)
        r.add_post("/api/plan/gpx", self.plan_gpx)
        r.add_post("/api/overlays/survey", self.overlay_from_survey)
        r.add_static("/static/", WEB)
        app.on_startup.append(self.on_startup)
        app.on_cleanup.append(self.on_cleanup)
        return app
