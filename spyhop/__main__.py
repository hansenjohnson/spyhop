"""Start Spyhop.

    python -m spyhop                 # opens in your browser
    python -m spyhop --window        # own app window (needs pywebview)
    python -m spyhop --sim           # add a simulated GPS for practice
    python -m spyhop --nmea serial:COM4:4800
    python -m spyhop --nmea udp:10110 --nmea tcp:192.168.1.5:10110
    python -m spyhop --install-shortcut   # make a double-clickable Spyhop shortcut
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from aiohttp import web

from . import __version__
from .browser import open_app_window
from .config import default_data_dir
from . import diag, instance
from .server import App


def parse_nmea_arg(s: str) -> dict:
    parts = s.split(":")
    kind = parts[0].lower()
    if kind == "serial":
        return {"type": "serial", "port": parts[1], "baud": int(parts[2]) if len(parts) > 2 else 4800}
    if kind == "udp":
        return {"type": "udp", "port": int(parts[1]) if len(parts) > 1 else 10110}
    if kind in ("tcp", "gpsd"):
        return {"type": kind, "host": parts[1],
                "port": int(parts[2]) if len(parts) > 2 else (10110 if kind == "tcp" else 2947)}
    if kind == "file":
        return {"type": "file", "path": ":".join(parts[1:]), "speed": 1}
    if kind == "sim":
        return {"type": "sim"}
    raise SystemExit(f"Don't understand --nmea {s}")


def port_free(host, port) -> bool:
    """True unless something is already listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1" if host in ("0.0.0.0", "") else host, port))
            return False
        except OSError:
            return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spyhop", description="Spyhop")
    ap.add_argument("--data-dir", type=Path, default=None, help="where data and config live")
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 to let other devices on the boat network connect")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--nmea", action="append", default=[],
                    help="extra NMEA source for this run, e.g. serial:COM4:4800, udp:10110, "
                         "tcp:host:port, gpsd:host, file:log.nmea, sim")
    ap.add_argument("--sim", action="store_true", help="add the GPS simulator")
    ap.add_argument("--sim-heading", type=float, default=0, help="simulator heading in degrees true (default 0)")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser")
    ap.add_argument("--browser", action="store_true", help="open a normal browser tab instead of an app window")
    ap.add_argument("--window", action="store_true", help="use a native window (pip install pywebview)")
    ap.add_argument("--install-shortcut", action="store_true",
                    help="make a double-clickable Spyhop icon (Desktop, Applications / Start menu)")
    ap.add_argument("--if-needed", action="store_true", help="with --install-shortcut: only if it isn't made yet")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.install_shortcut:
        from .shortcut import main as install_main
        raise SystemExit(install_main(args.if_needed))

    data_dir = args.data_dir or default_data_dir()
    log_folder = diag.setup(data_dir, args.verbose)
    extra = [parse_nmea_arg(s) for s in args.nmea]
    if args.sim:
        extra.append({"type": "sim", "heading": args.sim_heading})

    # 0.46: one Spyhop per computer (whatever program folder, data folder or port it was started with)
    restarted = bool(os.environ.pop("SPYHOP_RESTARTED", ""))
    if not instance.acquire(args.port, wait_s=15 if restarted else 2):
        other = instance.running() or {}
        url = f"http://127.0.0.1:{other.get('port') or args.port}/"
        print("Spyhop is already running on this computer"
              + (f" (from {other['program']})" if other.get("program") else "")
              + f". Only one Spyhop can run at a time, so every survey is recorded in one place. Opening {url}")
        if not args.no_browser:
            open_app_window(url)
        return
    if not port_free(args.host, args.port):
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Port {args.port} is in use by another program (or a Spyhop older than 0.46). Opening {url} in case it's Spyhop; "
              f"otherwise start Spyhop with another port, e.g. --port {args.port + 1}.")
        if not args.no_browser:
            open_app_window(url)
        return

    server = App(data_dir, extra)
    app = server.build()
    diag.log_startup(data_dir, server.rec.cfg.data_dir, server.rec.cfg.settings, sys.argv[1:])
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Spyhop {__version__}")
    print(f"  data folder: {data_dir}")
    print(f"  diagnostic logs: {log_folder}")
    print(f"  open {url} in a browser (Ctrl+C to stop)")

    if args.window:
        try:
            import webview  # type: ignore
        except ImportError:
            print("pywebview isn't installed (pip install pywebview); opening a browser instead.")
            args.window = False
    if args.window:
        def serve():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            loop.run_until_complete(web.TCPSite(runner, args.host, args.port).start())
            loop.run_forever()
        threading.Thread(target=serve, daemon=True).start()
        time.sleep(0.8)
        webview.create_window("Spyhop", url, width=1400, height=900)
        webview.start()
        return

    if not args.no_browser:
        threading.Timer(1.0, (webbrowser.open if args.browser else open_app_window), args=(url,)).start()

    try:
        web.run_app(app, host=args.host, port=args.port, print=None)
    finally:
        logging.getLogger("spyhop.diag").info("==== Spyhop %s stopped ====", __version__)
    print("Spyhop stopped.")


if __name__ == "__main__":
    main()
