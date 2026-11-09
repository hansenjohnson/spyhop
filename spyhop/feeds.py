"""Online map feeds (Settings → Inputs → Online overlays): polygons, lines or points from the web,
drawn as map overlays. A feed is an ArcGIS FeatureServer or MapServer (a layer, or a whole
service: all its layers) or a GeoJSON file. Spyhop fetches it, keeps the last copy in
`<Spyhop folder>/feeds/<id>.geojson`, and shows that copy when there's no internet.

Feeds are listed in settings.json ("online_feeds"): [{id, name, url, color, refresh_min}].
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

PRESETS = [
    {"name": "Right whale Seasonal Management Areas (NOAA)", "color": "#d81b60", "refresh_min": 1440,
     "url": "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Seasonal_Management_Areas/FeatureServer/3",
     "about": "Mandatory 10-knot speed restriction areas for vessels 65 ft or longer, by season. NOAA Fisheries Office of Protected Resources; approximate, not the official boundaries."},
    {"name": "Right whale Slow Zones / DMAs (NOAA NEFSC)", "color": "#f57c00", "refresh_min": 60,
     "url": "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/ArcGIS/rest/services/NEFSC_Dynamic_Management_Areas/FeatureServer",
     "about": "Voluntary Right Whale Slow Zones (Dynamic Management Areas and acoustic Slow Zones) in effect now; each lasts about 15 days. NOAA Northeast Fisheries Science Center."},
]
MAX_FEATURES = 5000
MAX_BYTES = 20 * 1024 * 1024
_ARC = re.compile(r"^(?P<base>.*/(FeatureServer|MapServer))(?:/(?P<layer>\d+))?/?$", re.I)
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class FeedError(ValueError):
    pass


def feeds_dir(cfg) -> Path:
    d = cfg.root / "feeds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_url(url: str) -> str:
    u = str(url or "").strip()
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise FeedError("Give the feed's full web address, starting with https://")
    # drop a query (e.g. ?f=pjson) and trailing /query from a pasted ArcGIS address
    path = re.sub(r"/query/?$", "", parts.path, flags=re.I)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query if not _ARC.match(path) else "", ""))


def clean(feed: dict, existing: list[dict] | None = None) -> dict:
    name = str(feed.get("name") or "").strip()[:80]
    if not name:
        raise FeedError("Give the feed a name.")
    url = clean_url(feed.get("url", ""))
    color = str(feed.get("color") or "#1565c0").strip()
    if not _COLOR.match(color):
        raise FeedError("The color must be like #1565c0.")
    try:
        refresh = int(feed.get("refresh_min") or 60)
    except (TypeError, ValueError):
        raise FeedError("Refresh must be a number of minutes.")
    refresh = max(5, min(10080, refresh))
    fid = str(feed.get("id") or "")
    if not re.match(r"^[a-z0-9]{6,20}$", fid):
        fid = secrets.token_hex(4)
    others = [f for f in (existing or []) if f.get("id") != fid]
    if any(f.get("name", "").lower() == name.lower() for f in others):
        raise FeedError(f"There's already a feed called “{name}”.")
    return {"id": fid, "name": name, "url": url, "color": color, "refresh_min": refresh}


def requests_for(url: str) -> tuple[str, list[str]]:
    """("arcgis-service" | "arcgis-layer" | "geojson", [urls])."""
    m = _ARC.match(urlsplit(url).path)
    if m:
        base = url.split("?", 1)[0].rstrip("/")
        if m.group("layer") is not None:
            return "arcgis-layer", [base]
        return "arcgis-service", [base]
    return "geojson", [url]


def layer_query(layer_url: str) -> str:
    return layer_url.rstrip("/") + "/query?" + urlencode({
        "where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson", "resultRecordCount": str(MAX_FEATURES)})


def check_geojson(data) -> list[dict]:
    if not isinstance(data, dict):
        raise FeedError("The feed didn't send GeoJSON.")
    if data.get("error"):
        e = data["error"]
        raise FeedError(f"The server said: {e.get('message') if isinstance(e, dict) else e}")
    if data.get("type") == "Feature":
        return [data]
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise FeedError("The feed didn't send GeoJSON features.")
    return [f for f in data["features"] if isinstance(f, dict) and isinstance(f.get("geometry"), dict)][:MAX_FEATURES]


async def fetch(download, url: str) -> list[dict]:
    """The feed's features. download(url) -> (status, body, content type), as TileService._download."""
    kind, urls = requests_for(url)

    async def get_json(u):
        status, body, _ = await download(u)
        if status != 200:
            raise FeedError(f"{urlsplit(u).netloc} answered {status}" if status else "no internet connection")
        if len(body) > MAX_BYTES:
            raise FeedError("The feed is too big (over 20 MB).")
        try:
            return json.loads(body)
        except ValueError:
            raise FeedError("The feed didn't send JSON.")

    if kind == "arcgis-service":
        info = await get_json(urls[0] + "?f=json")
        if isinstance(info, dict) and info.get("error"):
            raise FeedError(f"The server said: {info['error'].get('message', info['error'])}")
        layers = [l for l in (info.get("layers") or []) if isinstance(l, dict) and "id" in l
                  and str(l.get("geometryType", "esri")).startswith("esri")]
        if not layers:
            raise FeedError("That service has no map layers.")
        feats = []
        for l in layers:
            for f in check_geojson(await get_json(layer_query(f"{urls[0]}/{l['id']}"))):
                f.setdefault("properties", {})["_layer"] = l.get("name", "")
                feats.append(f)
        return feats[:MAX_FEATURES]
    if kind == "arcgis-layer":
        return check_geojson(await get_json(layer_query(urls[0])))
    return check_geojson(await get_json(urls[0]))


def cache_path(cfg, fid: str) -> Path:
    return feeds_dir(cfg) / f"{fid}.geojson"


def save_cache(cfg, fid: str, features: list[dict]):
    p = cache_path(cfg, fid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"type": "FeatureCollection", "fetched": time.time(), "features": features}), encoding="utf-8")
    tmp.replace(p)


def load_cache(cfg, fid: str) -> dict | None:
    try:
        d = json.loads(cache_path(cfg, fid).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("features"), list) else None
    except (OSError, ValueError):
        return None


def drop_cache(cfg, fid: str):
    try:
        cache_path(cfg, fid).unlink()
    except OSError:
        pass
