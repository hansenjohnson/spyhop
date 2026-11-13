"""View-only sharing (0.53): other devices on the vessel's network follow Spyhop live in a browser.

The laptop keeps the full-access server on 127.0.0.1 (only it can reach that). When sharing is on, a second
listener on 0.0.0.0:<viewer_port> serves a *viewer* copy of the app (App.build(viewer=True)): the same
handlers and state, behind `gate`, which allows only the requests in ALLOWED (deny by default). A request is
a viewer request because of the listener (the aiohttp Application) it arrived on, never because of anything
the client sends. Viewers get the page, the data and the websocket, with private and machine details left
out (viewer_bootstrap, viewer_settings, viewer_message); a viewer never makes the laptop use the internet
(NO_NETWORK, read by tiles._download); messages a viewer sends on the websocket are ignored.

An optional PIN (setting viewer_pin, blank = none): the PIN page sets a cookie token; wrong PINs are slowed
down (per address). A recorder/editor role could later be another entry in ROLES with its own ALLOWED.
"""
from __future__ import annotations

import asyncio
import contextvars
import html
import ipaddress
import logging
import secrets
import socket
import time

from aiohttp import web

log = logging.getLogger("spyhop.sharing")

# set while a viewer request is handled: map tiles come from the cache and MBTiles files only
NO_NETWORK: contextvars.ContextVar[bool] = contextvars.ContextVar("spyhop_no_network", default=False)

DEFAULT_PORT = 8766
COOKIE = "spyhop_view"

# (method, route) a viewer may use; routes as registered (aiohttp's canonical form). Everything else: 403.
ALLOWED = {
    ("GET", "/"), ("GET", "/ws"), ("GET", "/static"),
    ("GET", "/api/bootstrap"), ("GET", "/api/changelog"), ("GET", "/api/guide"),
    ("GET", "/api/instruments/history"), ("GET", "/api/reports"), ("GET", "/api/externals"),
    ("GET", "/api/routes"), ("GET", "/api/routes/file"), ("GET", "/api/tiles"), ("GET", "/api/clock"),
    ("GET", "/overlays/{name}"),
    ("GET", "/tiles/s/{i}/{z}/{x}/{y}"), ("GET", "/tiles/mb/{name}/{z}/{x}/{y}"),
    ("GET", "/tiles/gl/{i}/style.json"), ("GET", "/tiles/gl/{i}/tilejson"), ("GET", "/tiles/gl/{i}/t/{z}/{x}/{y}"),
    ("GET", "/tiles/gl/{i}/glyphs/{fontstack}/{range}"), ("GET", "/tiles/gl/{i}/sprite/{rest}"),
    ("GET", "/tiles/off/{name}/style.json"), ("GET", "/tiles/off/{name}/t/{set}/{z}/{x}/{y}"),
    ("GET", "/tiles/off/{name}/glyphs/{fontstack}/{range}"),
    # read-only work: running a report, the Error check, testing a rule (nothing is saved or changed)
    ("POST", "/api/reports/run"), ("POST", "/api/qc"), ("POST", "/api/rules/test"),
}
PIN_ROUTES = {("GET", "/viewer/pin"), ("POST", "/viewer/pin")}

# settings a viewer never gets (names, emails, inputs, web addresses, the PIN itself, this computer's folders)
PRIVATE_SETTINGS = {"last_meta", "nmea_sources", "template_url", "template_last", "template_author", "template_current",
                    "template_fingerprints", "template_added", "viewer_pin", "online_feeds", "clock_zone_last",
                    "last_version", "check_updates_on_start"}
PRIVATE_CONFIG = {"root", "data_dir", "default_data_dir", "current_dir", "rule_problems"}


def route_key(request) -> tuple[str, str | None]:
    route = request.match_info.route
    res = getattr(route, "resource", None)
    method = "GET" if request.method == "HEAD" else request.method
    return method, (res.canonical if res is not None else None)


def viewer_settings(s: dict) -> dict:
    return {k: v for k, v in (s or {}).items() if k not in PRIVATE_SETTINGS}


def viewer_bootstrap(data: dict) -> dict:
    """The bootstrap for a viewer: no private or machine details."""
    out = dict(data)
    cfg = dict(out.get("config") or {})
    for k in PRIVATE_CONFIG:
        cfg.pop(k, None)
    cfg["settings"] = viewer_settings(cfg.get("settings"))
    out["config"] = cfg
    about = out.get("about") or {}
    out["about"] = {k: about.get(k) for k in ("spyhop", "spyhop_date")} | {"updated_from": ""}
    out["nmea"] = {"sources": [], "counts": {}, "errors": {}, "log": {}, "position_source": ""}
    out["notices"] = []
    out["resume_prompt"] = None
    out["startup_update"] = None
    out["surveys"] = [{k: s.get(k) for k in ("prefix", "sightings", "start_time", "end_time")} for s in out.get("surveys") or []]
    sv = out.get("survey")
    if sv:
        out["survey"] = {k: v for k, v in sv.items() if k not in ("data_dir", "template")}
    out["viewer"] = True
    out["viewer_allowed"] = sorted(f"{m} {p}" for m, p in ALLOWED)
    return out


def viewer_message(msg: dict) -> dict | None:
    """A websocket message as a viewer gets it (None: not sent to viewers)."""
    t = msg.get("type")
    if t in ("update", "prefetch", "sharing", "closing_laptop"):
        return None
    if t == "settings":
        return {**msg, "settings": viewer_settings(msg.get("settings"))}
    if t == "vessel" and "nmea" in msg:
        return {k: v for k, v in msg.items() if k not in ("nmea", "prefetch")}
    if t == "notice":
        return None
    return msg


def addresses() -> list[str]:
    """This computer's IPv4 addresses that other devices can use (not loopback or link-local)."""
    found: list[str] = []

    def add(a):
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            return
        if ip.version == 4 and not ip.is_loopback and not ip.is_link_local and not ip.is_unspecified and a not in found:
            found.append(a)
    try:
        import psutil  # type: ignore  # optional: every interface
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET:
                    add(a.address)
    except Exception:  # noqa: BLE001
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):   # the address used for that network (nothing is sent)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                add(s.getsockname()[0])
        except OSError:
            pass
    return found


PIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spyhop — view only</title><style>
body{{font:16px system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:90vh;background:#eef1f4;margin:0}}
form{{background:#fff;padding:1.6em 2em;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.12);max-width:20em}}
input{{font-size:1.4em;width:100%;box-sizing:border-box;padding:.3em;letter-spacing:.2em;margin:.6em 0}}
button{{font-size:1.1em;padding:.4em 1.2em;background:#0b5c8a;color:#fff;border:0;border-radius:5px}}
.err{{color:#a1271c}}</style></head><body><form method="post" action="/viewer/pin">
<h2>Spyhop</h2><p>View only. Type the PIN shown on the laptop under Settings → Sharing.</p>
{error}<input name="pin" type="password" inputmode="numeric" autocomplete="off" autofocus aria-label="PIN">
<button type="submit">Watch</button></form></body></html>"""


class Sharing:
    """The viewer listener and its state, owned by server.App."""

    def __init__(self, app_obj):
        self.owner = app_obj                   # server.App
        self.runner: web.AppRunner | None = None
        self.port: int | None = None
        self.error = ""
        self.viewers: dict = {}                # ws → {address, browser, since}
        self.tokens: set[str] = set()
        self.failures: dict[str, tuple[int, float]] = {}
        self.session_port: int | None = None   # --viewers PORT: on for this session

    # -- settings
    def settings(self) -> dict:
        s = self.owner.rec.cfg.settings
        return {"enabled": bool(s.get("sharing_enabled")) or self.session_port is not None,
                "port": self.session_port or int(s.get("viewer_port") or DEFAULT_PORT),
                "pin": str(s.get("viewer_pin") or "")}

    def status(self) -> dict:
        st = self.settings()
        return {"enabled": st["enabled"], "port": st["port"], "listening": self.runner is not None, "listening_port": self.port,
                "error": self.error, "pin_set": bool(st["pin"]), "session": self.session_port is not None,
                "addresses": [f"http://{a}:{self.port or st['port']}/" for a in addresses()],
                "viewers": [{"address": v["address"], "browser": v["browser"], "since": v["since"]} for v in self.viewers.values()]}

    # -- the listener
    async def sync(self):
        """Open or close the viewer port to match the settings (no restart needed)."""
        st = self.settings()
        if st["enabled"] and self.runner is not None and self.port == st["port"]:
            return
        await self.stop()
        if not st["enabled"]:
            return
        app = self.owner.build(viewer=True)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", st["port"]).start()
        except OSError as e:
            await runner.cleanup()
            self.error = f"Port {st['port']} can't be used ({e.strerror or e}). Choose another port."
            log.warning("sharing: %s", self.error)
            return
        self.runner, self.port, self.error = runner, st["port"], ""
        log.info("sharing on: viewers can connect on port %s (%s)", self.port, ", ".join(addresses()) or "no network address")
        self.changed()

    async def stop(self):
        if self.runner is None:
            return
        await self.disconnect_all(rotate=False)
        runner, self.runner, self.port = self.runner, None, None
        await runner.cleanup()
        log.info("sharing off")
        self.changed()

    async def disconnect_all(self, rotate=True):
        if rotate:
            self.tokens.clear()            # with a PIN, viewers have to type it again
        for ws in list(self.viewers):
            try:
                await ws.close(code=4001, message=b"disconnected by the laptop")
            except Exception:  # noqa: BLE001
                pass
        self.viewers.clear()
        self.changed()

    def pin_changed(self):
        self.tokens.clear()

    def changed(self):
        """Tell the laptop's windows (not viewers) how many viewers there are."""
        self.owner._broadcast_soon({"type": "sharing", "sharing": self.status()})

    # -- the websocket
    def add_viewer(self, ws, request):
        self.viewers[ws] = {"address": request.remote or "?", "browser": browser_name(request.headers.get("User-Agent", "")),
                            "since": time.strftime("%H:%M:%S")}
        log.info("viewer connected: %s (%s); %d watching", self.viewers[ws]["address"], self.viewers[ws]["browser"], len(self.viewers))
        self.changed()

    def remove_viewer(self, ws):
        v = self.viewers.pop(ws, None)
        if v:
            log.info("viewer left: %s; %d watching", v["address"], len(self.viewers))
            self.changed()

    # -- the gate (middleware of the viewer app)
    def gate(self):
        @web.middleware
        async def gate(request, handler):
            key = route_key(request)
            pin = self.settings()["pin"]
            if key in PIN_ROUTES:
                return await handler(request)
            if pin and request.cookies.get(COOKIE) not in self.tokens:
                if key == ("GET", "/"):
                    raise web.HTTPFound("/viewer/pin")
                return web.json_response({"ok": False, "error": "View only: type the PIN first.", "pin": True}, status=401)
            if key not in ALLOWED:
                log.info("viewer request refused: %s %s", request.method, key[1] or request.path)
                return web.json_response({"ok": False, "error": "View only: this can only be done on the laptop running Spyhop.",
                                          "viewer": True}, status=403)
            tok = NO_NETWORK.set(True)
            try:
                return await handler(request)
            finally:
                NO_NETWORK.reset(tok)
        return gate

    async def pin_page(self, request):
        if not self.settings()["pin"]:
            raise web.HTTPFound("/")
        return web.Response(text=PIN_PAGE.format(error=""), content_type="text/html")

    async def pin_post(self, request):
        pin = self.settings()["pin"]
        if not pin:
            raise web.HTTPFound("/")
        who = request.remote or "?"
        n, _ = self.failures.get(who, (0, 0.0))
        form = await request.post()
        given = str(form.get("pin", "")).strip()
        if n:
            await asyncio.sleep(min(2 ** (n - 1), 30))          # slower after each wrong PIN
        if not secrets.compare_digest(given, pin):
            self.failures[who] = (n + 1, time.time())
            log.info("viewer PIN wrong from %s (%d)", who, n + 1)
            return web.Response(text=PIN_PAGE.format(error='<p class="err">That PIN isn’t right.</p>'),
                                content_type="text/html", status=401)
        self.failures.pop(who, None)
        token = secrets.token_urlsafe(24)
        self.tokens.add(token)
        resp = web.HTTPFound("/")
        resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", max_age=30 * 86400)
        raise resp


def browser_name(ua: str) -> str:
    u = ua or ""
    dev = ("iPhone" if "iPhone" in u else "iPad" if "iPad" in u else "Android" if "Android" in u
           else "Mac" if "Macintosh" in u else "Windows" if "Windows" in u else "Linux" if "Linux" in u else "")
    br = ("Edge" if "Edg/" in u else "Chrome" if "Chrome/" in u or "CriOS" in u else "Firefox" if "Firefox/" in u
          else "Safari" if "Safari/" in u else "browser")
    return f"{br} on {dev}" if dev else br


def escape(s) -> str:
    return html.escape(str(s))
