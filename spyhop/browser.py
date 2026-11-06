"""Finding Chrome / Edge: for Spyhop's app window, and for saving reports as PDF
(Chrome's headless --print-to-pdf, so no PDF library is needed)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

log = logging.getLogger("spyhop.browser")


def chrome_candidates() -> list[Path]:
    env = os.environ.get("SPYHOP_CHROME")          # a browser of your choice (also used by the tests)
    out = [Path(env)] if env else []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                out += [Path(base) / "Google/Chrome/Application/chrome.exe",
                        Path(base) / "Microsoft/Edge/Application/msedge.exe"]
    elif sys.platform == "darwin":
        out += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    else:
        for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(n)
            if p:
                out.append(Path(p))
    return out


def find_chrome() -> Path | None:
    return next((c for c in chrome_candidates() if c.exists()), None)


def open_app_window(url: str):
    """Open the UI in a Chrome/Edge 'app' window (no tabs, so browser shortcuts
    don't clash), falling back to the default browser."""
    for c in chrome_candidates():
        if c.exists():
            try:
                subprocess.Popen([str(c), f"--app={url}", "--window-size=1400,900"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


class PdfError(Exception):
    pass


def html_to_pdf(html: str, dest: Path, wait_ms: int = 3000) -> Path:
    """Print an HTML page to a PDF file with headless Chrome / Edge. The page is given
    wait_ms to finish drawing (e.g. a map) before it is printed."""
    chrome = find_chrome()
    if chrome is None:
        raise PdfError("Saving as PDF needs Google Chrome or Microsoft Edge, and neither was found. "
                       "Save as HTML instead and print it to PDF from your browser.")
    with tempfile.TemporaryDirectory(prefix="spyhop_pdf_") as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(html, encoding="utf-8")
        out = Path(tmp) / "report.pdf"
        cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-extensions", "--disable-background-networking", "--disable-component-update",
               f"--user-data-dir={Path(tmp) / 'profile'}", "--no-pdf-header-footer", "--hide-scrollbars",
               f"--virtual-time-budget={int(wait_ms)}", f"--print-to-pdf={out}", page.as_uri()]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")            # Chrome refuses to run as root otherwise
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PdfError(f"Couldn't run {chrome.name} to make the PDF: {e}") from e
        if not out.exists() or out.stat().st_size == 0:
            log.warning("print-to-pdf failed (%s): %s", r.returncode, r.stderr.decode(errors="replace")[-800:])
            raise PdfError("The browser didn't make the PDF. Save as HTML instead and print it from your browser.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(out, tmp_dest)
        os.replace(tmp_dest, dest)
    return dest
