import csv
import os
import re
import shutil
import io
import json
import zipfile
from pathlib import Path

import pytest

from spyhop import geo, schema
from spyhop.nmea import NmeaDecoder, with_checksum, split_sentence
from spyhop.recorder import Recorder, ValueErrorMsg
from spyhop.sources import Simulator


# ---------------------------------------------------------------- geo
@pytest.mark.parametrize("text,is_lat,neg,expected", [
    ("41.5", True, False, 41.5),
    ("41 30", True, False, 41.5),
    ("41°30.000'N", True, False, 41.5),
    ("41 30 00 S", True, False, -41.5),
    ("N41 30.0", True, False, 41.5),
    ("4130.0N", True, False, 41.5),
    ("70 15W", False, False, -70.25),
    ("W070 15.0", False, False, -70.25),
    ("-70.25", False, False, -70.25),
    ("70 15", False, True, -70.25),        # hemisphere inferred
    ("70 15 E", False, True, 70.25),       # explicit beats inferred
    ("70°15'00\"W", False, False, -70.25),
])
def test_parse_coord(text, is_lat, neg, expected):
    assert geo.parse_coord(text, is_lat, neg) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("text,is_lat", [("95", True), ("41 75", True), ("41E", True), ("abc", False),
                                         ("-41 N", True), ("", True)])
def test_parse_coord_rejects(text, is_lat):
    with pytest.raises(ValueError):
        geo.parse_coord(text, is_lat)


def test_format_roundtrip():
    for fmt in ("DD", "DDM", "DMS"):
        for v, lat in ((41.512345, True), (-70.987654, False), (-0.5, True)):
            s = geo.format_coord(v, lat, fmt)
            assert geo.parse_coord(s, lat) == pytest.approx(v, abs=2e-5), (fmt, s)


def test_destination_and_bearing():
    lat, lon = geo.destination(41.0, -70.0, 90, 1852 * 10)
    assert geo.haversine_m(41.0, -70.0, lat, lon) == pytest.approx(18520, rel=1e-6)
    assert geo.initial_bearing(41.0, -70.0, lat, lon) == pytest.approx(90, abs=0.1)


def test_true_bearing():
    assert geo.to_true_bearing(45, "M", None, -14) == 31
    assert geo.to_true_bearing(10, "R", 350, None) == 0
    assert geo.to_true_bearing(10, "R", None, None) is None
    assert geo.to_true_bearing(10, "M", None, None) is None


# ---------------------------------------------------------------- nmea
def test_nmea_rmc_hdt():
    d = NmeaDecoder()
    assert d.feed("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    s = d.state
    assert s.lat == pytest.approx(48.1173, abs=1e-4)
    assert s.lon == pytest.approx(11.516667, abs=1e-5)
    assert s.sog == 22.4 and s.cog == 84.4 and s.variation == -3.1
    assert d.feed(with_checksum("HEHDT,271.5,T"))
    assert s.heading == 271.5
    snap = s.snapshot()
    assert snap["has_fix"] and snap["best_heading"] == 271.5


def test_nmea_bad_checksum_and_void():
    d = NmeaDecoder()
    assert not d.feed("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*00")
    assert not d.feed(with_checksum("GPRMC,123519,V,,,,,,,230394,,"))
    assert d.state.lat is None
    assert d.errors == 1


def test_nmea_gga_and_hdg():
    d = NmeaDecoder()
    assert d.feed(with_checksum("GNGGA,092750.000,5321.6802,N,00630.3372,W,1,8,1.03,61.7,M,55.2,M,,"))
    assert d.state.lat == pytest.approx(53.36134, abs=1e-5) and d.state.sats == 8
    assert d.feed(with_checksum("HCHDG,100.0,,,14.0,W"))
    assert d.state.heading == pytest.approx(86.0)


def test_simulator_sentences_parse():
    sim = Simulator()
    d = NmeaDecoder()
    for _ in range(5):
        for s in sim.step(1):
            split_sentence(s)
            d.feed(s)
    assert d.state.lat == pytest.approx(41.9, abs=0.01)
    assert d.errors == 0


# ---------------------------------------------------------------- recorder / store
@pytest.fixture
def rec(tmp_path):
    r = Recorder(tmp_path)
    d = r.decoder
    d.feed(with_checksum("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))
    d.feed(with_checksum("HEHDT,045.0,T"))
    r.cfg.settings["mag_variation"] = "-14.5"
    r.start_survey("Test")
    return r


def read_csv(p: Path):
    with open(p, newline="") as fh:
        return list(csv.DictReader(fh))


def test_add_sighting_computes_position(rec):
    res = rec.new_row("sightings", {"Species": "huMPback WHALE", "Bearing": "59.5", "Distance": "1"})
    row = res["row"]
    assert row["Species"] == "Humpback whale"
    assert row["SightNo"] == "1"
    assert row["Lat"] == "41.900000" and row["Lon"] == "-70.333333"
    # 59.5 M with -14.5 variation = 45 T, 1 nm
    lat, lon = geo.destination(41.9, -70.333333, 45, 1852)
    assert float(row["SigLat"]) == pytest.approx(lat, abs=1e-6)
    assert float(row["SigLon"]) == pytest.approx(lon, abs=1e-6)
    rows = read_csv(rec.tables["sightings"].path)
    assert rows[0]["SigLat"] == row["SigLat"]          # written to disk immediately
    assert list(rows[0].keys()) == schema.headers("sightings")


def test_relative_bearing_uses_heading(rec):
    row = rec.new_row("sightings", {"BrgRef": "R", "Bearing": "0", "Distance": "1", "DistUnit": "km"})["row"]
    b = geo.initial_bearing(41.9, -70.333333, float(row["SigLat"]), float(row["SigLon"]))
    assert b == pytest.approx(45, abs=0.05)


def test_validation(rec):
    row = rec.new_row("sightings")["row"]
    with pytest.raises(ValueErrorMsg):
        rec.edit("sightings", row["RowID"], {"Count": "two"})
    with pytest.raises(ValueErrorMsg):
        rec.edit("sightings", row["RowID"], {"NumConf": "Maybe"})
    with pytest.raises(ValueErrorMsg):
        rec.edit("sightings", row["RowID"], {"Bearing": "400"})
    w = rec.edit("sightings", row["RowID"], {"Species": "Narwhal"})["warnings"]
    assert w and "species.csv" in w[0]
    r = rec.edit("sightings", row["RowID"], {"Behaviors": "feed, BREACH; Feed", "SigLon": "70 21.0"})["row"]
    assert r["Behaviors"] == "Feed; Breach"
    assert float(r["SigLon"]) == pytest.approx(-70.35)


def test_time_edit_keeps_date(rec):
    row = rec.new_row("events", {"EventType": "ctd cast"})["row"]
    assert row["EventType"] == "CTD cast" and row["EventNo"] == "1"
    r = rec.edit("events", row["RowID"], {"DateTime": "07:05"})["row"]
    assert r["DateTime"][:10] == row["DateTime"][:10]
    assert r["DateTime"][11:19] == "07:05:00"


def test_undo_redo_add_edit_delete(rec):
    t = rec.tables["sightings"]
    a = rec.new_row("sightings")["row"]
    rec.edit("sightings", a["RowID"], {"Count": "4"})
    rec.delete("sightings", a["RowID"])
    assert t.rows == []
    rec.undo("sightings")
    assert t.rows[0]["Count"] == "4"
    rec.undo("sightings")
    assert t.rows[0]["Count"] == ""
    rec.undo("sightings")
    assert t.rows == []
    assert read_csv(t.path) == []
    rec.redo("sightings")
    rec.redo("sightings")
    assert t.rows[0]["Count"] == "4"
    assert read_csv(t.path)[0]["Count"] == "4"


def test_effort_copy_forward_after_start(rec):
    t = rec.tables["effort"]
    assert [r["Effort"] for r in t.rows] == ["Start"] and rec.cfg.settings["tracking_enabled"]
    first = rec.new_row("effort", {"SeaState": "3", "Port": "OBS1", "Notes": "start"})["row"]
    assert first["Effort"] == ""                            # after Start: choose ON/OFF yourself
    rec.edit("effort", first["RowID"], {"Effort": "ON"})
    second = rec.toggle_effort()["row"]
    assert second["Effort"] == "OFF"
    assert second["SeaState"] == "3" and second["Port"] == "OBS1"
    assert second["Notes"] == ""                           # notes are not copied
    assert second["DateTime"] >= first["DateTime"]


def test_schema_mismatch_backs_up(tmp_path):
    r = Recorder(tmp_path)
    r.start_survey("S")
    p = r.tables["sightings"].path
    p.write_text("Old,Columns\n1,2\n")
    r2 = Recorder(tmp_path)
    assert r2.tables["sightings"].rows == []
    assert any(x.name.startswith(p.name + ".bak-") for x in p.parent.iterdir())
    assert r2.notices


def test_new_survey_keeps_old_files(rec):
    rec.new_row("sightings", {"Species": "Fin whale"})
    old = rec.tables["sightings"].path
    old_prefix = rec.survey["prefix"]
    with pytest.raises(ValueErrorMsg):
        rec.start_survey("NEAQ 2026-11 Leg 2")             # current one still active
    rec.close_survey()
    rec.start_survey("NEAQ 2026-11 Leg 2")                    # the team's own naming, no date added
    assert rec.survey["prefix"] == "NEAQ 2026-11 Leg 2"
    assert rec.tables["sightings"].path.name == "NEAQ 2026-11 Leg 2_sightings.csv"
    assert old.exists() and rec.tables["sightings"].rows == []
    rec.new_row("events")
    rec.end_survey()
    with pytest.raises(ValueErrorMsg):
        rec.start_survey("NEAQ 2026-11 Leg 2")                # name already used -> clear error
    listed = {s["prefix"]: s for s in rec.list_surveys()}
    assert listed[old_prefix]["sightings"] == 1 and listed["NEAQ 2026-11 Leg 2"]["current"]
    rec.open_survey(old_prefix)
    assert rec.tables["sightings"].rows[0]["Species"] == "Fin whale"


def test_survey_names_with_odd_characters(rec):
    rec.close_survey()
    rec.start_survey('Leg [2] a/b: "test"?')
    p = rec.survey["prefix"]
    assert p == "Leg [2] a_b_ _test__"
    rec.new_row("sightings")
    rec.close_survey()
    rec.start_survey("Other")
    rec.open_survey(p)                                    # glob characters in the name still work
    assert len(rec.tables["sightings"].rows) == 1


def zread(z, suffix):
    zf = zipfile.ZipFile(z)
    return zf.read(next(n for n in zf.namelist() if n.endswith(suffix))).decode("utf-8")


def zcsv(z, suffix):
    import csv as _csv, io as _io
    return list(_csv.DictReader(_io.StringIO(zread(z, suffix))))


def test_track_and_export(rec, tmp_path):
    rec.cfg.settings["tracking_enabled"] = True
    rec.cfg.settings["tracking_interval"] = 1
    rec.new_row("effort", {"Effort": "ON"})
    rec.new_row("sightings", {"Species": "Fin whale", "Bearing": "10", "Distance": "0.5"})
    rec.new_row("marks", {"Name": "Buoy"}, lat=41.95, lon=-70.3)
    for i in range(3):
        rec._last_track_t = 0
        rec.tick_tracker()
    assert len(rec.track.points) == 4                               # Start point + 3
    assert [p["Effort"] for p in rec.track.points] == ["Start", "ON", "ON", "ON"]
    z = rec.export()
    names = zipfile.ZipFile(z).namelist()
    assert any(n.endswith("_track.csv") for n in names)
    assert any(n.endswith(".geojson") for n in names)
    assert any(n.endswith(".gpx") for n in names)
    gj = json.loads(zread(z, ".geojson"))
    layers = {f["properties"]["layer"] for f in gj["features"]}
    assert {"sightings", "marks"} <= layers


def test_clear_survey(rec):
    rec.new_row("sightings")
    p = rec.tables["sightings"].path
    rec.clear_survey()
    assert rec.survey is None and rec.tables["sightings"].rows == []
    assert not p.exists()


def test_config_files_created(tmp_path):
    """A new Spyhop folder: the setup in use in templates/current, and nothing at the top but folders
    (spyhop-local.json appears with the first setting saved)."""
    rec = Recorder(tmp_path)
    cur = tmp_path / "templates" / "current"
    for n in ("species", "event_types", "observers", "behaviors", "shortcuts"):
        assert (cur / f"{n}.csv").exists() and not (tmp_path / f"{n}.csv").exists()
    doc = json.loads((cur / "spyhop-config.json").read_text())
    assert sorted(doc["reports"]) == ["blue_whales.json", "dead_birds.json", "gear.json", "right_whales.json"]
    assert (tmp_path / "templates" / "saved").is_dir() and (tmp_path / "templates" / "backups").is_dir()
    for gone in ("settings", "reports", "display.csv"):
        assert not (tmp_path / gone).exists()
    rec.cfg.save_settings({"latlon_format": "DD", "follow_vessel": False})
    assert json.loads((cur / "spyhop-config.json").read_text())["settings"]["latlon_format"] == "DD"
    loc = json.loads((tmp_path / "spyhop-local.json").read_text())
    assert loc["settings"]["follow_vessel"] is False and "latlon_format" not in loc["settings"]
    names = [s["name"] for s in rec.cfg.tile_sources]
    assert names[:2] == ["Seascape depths (feet)", "Esri Ocean"] and rec.cfg.tile_sources[0]["kind"] == "style"
    assert not any("OpenSeaMap" in n or "tiled" in n for n in names)


def test_source_priority():
    d = NmeaDecoder()
    d.priority = {"GPS A": 0, "GPS B": 1}
    a = with_checksum("GPRMC,120000,A,4200.000,N,07000.000,W,5.0,180.0,041126,,")
    b = with_checksum("GPRMC,120000,A,4100.000,N,07000.000,W,5.0,180.0,041126,,")
    d.feed(a, "GPS A")
    d.feed(b, "GPS B")
    assert d.state.lat == pytest.approx(42.0)       # B ignored while A is fresh
    d.state.updated -= 10                            # A goes quiet
    d.feed(b, "GPS B")
    assert d.state.lat == pytest.approx(41.0)
    d.feed(a, "GPS A")                               # A back: higher priority takes over
    assert d.state.lat == pytest.approx(42.0)


def test_mbtiles_and_bbox(tmp_path):
    import sqlite3
    from spyhop.config import Config
    from spyhop.tiles import TileService, tile_bbox_3857, lonlat_to_tile
    cfg = Config(tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
    db = sqlite3.connect(cfg.charts_dir / "test.mbtiles")
    db.execute("CREATE TABLE metadata (name text, value text)")
    db.execute("CREATE TABLE tiles (zoom_level int, tile_column int, tile_row int, tile_data blob)")
    db.executemany("INSERT INTO metadata VALUES (?,?)", [("name", "Test chart"), ("format", "png"),
                   ("minzoom", "5"), ("maxzoom", "12"), ("bounds", "-71,41,-69,43")])
    x, y = lonlat_to_tile(-70.3, 41.9, 10)
    db.execute("INSERT INTO tiles VALUES (10, ?, ?, ?)", (x, (2 ** 10 - 1) - y, png))   # TMS row
    db.commit(); db.close()
    cfg.reload()
    ts = TileService(cfg)
    info = ts.mbtiles_info()[0]
    assert info["name"] == "Test chart" and info["maxzoom"] == 12 and info["bounds"][0] == -71
    data, ctype = ts.get_mbtile("test.mbtiles", 10, x, y)
    assert ctype == "image/png" and data == png
    assert ts.get_mbtile("test.mbtiles", 10, x + 1, y) is None
    assert tile_bbox_3857(0, 0, 0).startswith("-20037508")


def test_sighting_placed_on_map_gets_bearing_distance(rec):
    slat, slon = geo.destination(41.9, -70.333333, 120, 1852 * 0.7)
    row = rec.new_row("sightings", {"SigLat": f"{slat:.6f}", "SigLon": f"{slon:.6f}"})["row"]
    assert row["BrgRef"] == "M"
    assert float(row["Bearing"]) == pytest.approx(120 + 14.5, abs=1)      # true 120 -> magnetic with 14.5W var
    assert float(row["Distance"]) == pytest.approx(0.7, abs=0.01)
    assert float(row["SigLat"]) == pytest.approx(slat, abs=1e-6)          # the picked point is kept
    assert float(row["SigLon"]) == pytest.approx(slon, abs=1e-6)


@pytest.mark.parametrize("heading", [0, 45, 135, 270])
def test_simulator_fixed_heading(heading):
    sim = Simulator(lat=41.9, lon=-70.3, speed_kn=10, heading=heading)
    lat0, lon0 = sim.lat, sim.lon
    d = NmeaDecoder()
    for _ in range(600):
        for line in sim.step(1):
            d.feed(line)
    b = geo.initial_bearing(lat0, lon0, sim.lat, sim.lon)
    assert (b - heading + 540) % 360 - 180 == pytest.approx(0, abs=0.2)
    assert geo.haversine_m(lat0, lon0, sim.lat, sim.lon) / 1852 == pytest.approx(10 * 600 / 3600, rel=0.001)
    assert d.state.cog == pytest.approx(heading) and d.state.heading == pytest.approx(heading)


def test_simulator_heading_change_is_immediate_and_keeps_position():
    sim = Simulator(heading=0)
    for _ in range(60):
        sim.step(1)
    pos = (sim.lat, sim.lon)
    sim.heading = 90
    assert (sim.lat, sim.lon) == pos
    sim.step(1)
    assert geo.initial_bearing(*pos, sim.lat, sim.lon) == pytest.approx(90, abs=0.01)


def test_old_columns_migrated_with_backup(tmp_path):
    r = Recorder(tmp_path)
    r.start_survey("S")
    p = r.tables["sightings"].path
    # a file from the previous version: no FieldID, VesHdg visible
    old_hdr = [h for h in schema.headers("sightings") if h != "FieldID"] + ["SurfStuff"]
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(old_hdr)
        w.writerow(["abc123" if h == "RowID" else "7" if h == "SightNo" else "Fin whale" if h == "Species"
                    else "x" if h == "SurfStuff" else "" for h in old_hdr])
    r2 = Recorder(tmp_path)
    rows = r2.tables["sightings"].rows
    assert len(rows) == 1 and rows[0]["Species"] == "Fin whale" and rows[0]["SightNo"] == "7"
    assert rows[0]["FieldID"] == "" and rows[0]["RowID"] == "abc123"
    assert read_csv(p)[0]["Species"] == "Fin whale"                     # rewritten in the new layout
    assert list(read_csv(p)[0].keys()) == schema.headers("sightings")
    baks = [x for x in p.parent.iterdir() if x.name.startswith(p.name + ".bak-")]
    assert len(baks) == 1 and "SurfStuff" in baks[0].read_text()
    assert any("SurfStuff" in n and "backup" in n for n in r2.notices)


def test_siglatlon_follow_vessel_without_bearing(rec):
    row = rec.new_row("sightings", {"Species": "Fin whale"})["row"]
    assert (row["SigLat"], row["SigLon"]) == (row["Lat"], row["Lon"])
    rid = row["RowID"]
    r = rec.edit("sightings", rid, {"Lat": "41 55.0"})["row"]           # vessel corrected -> follows
    assert r["SigLat"] == r["Lat"] == "41.916667"
    r = rec.edit("sightings", rid, {"Bearing": "90", "Distance": "1"})["row"]
    assert r["SigLat"] != r["Lat"]
    r = rec.edit("sightings", rid, {"Distance": ""})["row"]               # bearing/distance removed -> back to vessel
    assert (r["SigLat"], r["SigLon"]) == (r["Lat"], r["Lon"])
    r = rec.edit("sightings", rid, {"SigLat": "41 56.0"})["row"]           # typed animal position is kept
    assert r["SigLat"] == "41.933333"
    r = rec.edit("sightings", rid, {"Notes": "x"})["row"]
    assert r["SigLat"] == "41.933333"


def test_utc_clock(rec):
    rec.cfg.settings["timezone"] = "UTC"
    row = rec.new_row("events")["row"]
    assert row["DateTime"].endswith("+00:00")
    r = rec.edit("events", row["RowID"], {"DateTime": "07:05"})["row"]
    assert r["DateTime"][11:] == "07:05:00+00:00"


def test_column_order_and_help():
    sk = schema.headers("sightings")
    assert sk.index("FieldID") == sk.index("Images") + 1
    assert "Observer" not in schema.headers("events")
    for tab, spec in schema.TABS.items():
        for c in spec["columns"]:
            if not c["hidden"]:
                assert c["help"], (tab, c["key"])


def test_reordered_columns_migrate(tmp_path):
    r = Recorder(tmp_path)
    r.start_survey("S")
    p = r.tables["events"].path
    old = ["RowID", "EventNo", "DateTime", "Lat", "Lon", "EventType", "ID", "Observer", "Notes", "Map"]
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(old)
        w.writerow(["e1", "1", "2026-11-04T10:00:00-05:00", "41.9", "-70.3", "CTD cast", "C-1", "OBS1", "n", "1"])
    r2 = Recorder(tmp_path)
    row = r2.tables["events"].rows[0]
    assert row["ID"] == "C-1" and row["EventType"] == "CTD cast" and "Observer" not in row
    assert any("Observer" in n for n in r2.notices)            # dropped data is called out


def test_no_survey_open_blocks_survey_tabs_but_not_marks(tmp_path):
    r = Recorder(tmp_path)
    assert r.survey is None and r.survey_info() is None
    for tab in ("sightings", "effort", "events"):
        with pytest.raises(ValueErrorMsg):
            r.new_row(tab)
    r.new_row("marks", {"Name": "Buoy"}, lat=41.9, lon=-70.3)       # marks belong to no survey
    r.cfg.settings["tracking_enabled"] = True
    r.tick_tracker()
    assert r.track.points == []
    with pytest.raises(ValueErrorMsg):
        r.export()


def test_start_row_rules(rec):
    t = rec.tables["effort"]
    start = t.rows[0]
    assert start["Effort"] == "Start" and start["Lat"] and rec.tracking_on()
    assert not t.undo_stack                                        # Start can't be undone
    with pytest.raises(ValueErrorMsg):
        rec.edit("effort", start["RowID"], {"Effort": "ON"})       # first row stays Start
    with pytest.raises(ValueErrorMsg):
        rec.delete("effort", start["RowID"])
    with pytest.raises(ValueErrorMsg):
        rec.new_row("effort", {"Effort": "Start"})                 # Start only on the first row
    row = rec.new_row("effort", {"Effort": "ON"})["row"]
    rec.new_row("effort", {"Effort": "OFF"})
    with pytest.raises(ValueErrorMsg):
        rec.edit("effort", row["RowID"], {"Effort": "End"})        # End only on the last row
    rec.edit("effort", row["RowID"], {"Effort": "OFF"})
    rec.undo("effort"); rec.undo("effort"); rec.undo("effort")    # back to just Start
    assert [r["Effort"] for r in t.rows] == ["Start"]
    assert rec.undo("effort") is False                             # the Start row itself can't be undone
    assert [r["Effort"] for r in t.rows] == ["Start"]


def test_end_survey_and_reopen_by_deleting_end(rec):
    rec.new_row("effort", {"Effort": "ON"})
    rec.end_survey()
    info = rec.survey_info()
    assert info["ended"] and not info["active"] and not rec.tracking_on() and info["end_time"]
    assert rec.tables["effort"].rows[-1]["Effort"] == "End"
    for tab in ("sightings", "effort", "events"):
        with pytest.raises(ValueErrorMsg):
            rec.new_row(tab)                                       # ended: no new rows
    s = rec.tables["sightings"]
    rec.new_row("marks")
    end = rec.tables["effort"].rows[-1]
    rec.delete("effort", end["RowID"])                             # continue it
    assert rec.survey_active()
    rec.new_row("sightings")
    assert len(s.rows) == 1


def test_close_and_open_with_resume(rec):
    rec.new_row("sightings", {"Species": "Fin whale"})
    p = rec.survey["prefix"]
    rec.close_survey()
    assert rec.survey is None and not rec.tracking_on() and rec.tables["sightings"].rows == []
    assert rec.cfg.current_survey() is None
    listed = {s["prefix"]: s for s in rec.list_surveys()}
    assert listed[p]["active"] and not listed[p]["current"]
    rec.open_survey(p, resume=False)          # 0.45: an active survey always records its track once open
    assert rec.tables["sightings"].rows[0]["Species"] == "Fin whale" and rec.tracking_on()
    rec.end_survey()
    assert not rec.tracking_on()
    rec.delete("effort", rec.tables["effort"].rows[-1]["RowID"])     # End deleted: active again
    assert rec.tracking_on()


def test_crash_recovery_asks_to_continue(tmp_path):
    r = Recorder(tmp_path)
    r.start_survey("Leg A")
    r.new_row("sightings", {"Species": "Fin whale"})
    assert r.tracking_on()
    # Spyhop is killed here; next start:
    r2 = Recorder(tmp_path)
    assert r2.survey["prefix"] == "Leg A" and r2.pending_resume == "Leg A"
    assert r2.tracking_on()                                        # 0.45: carries on recording; the window says so
    assert r2.bootstrap()["resume_prompt"] == "Leg A"
    r2.answer_resume("continue")
    assert r2.tracking_on() and r2.pending_resume is None
    r2.end_survey()
    r3 = Recorder(tmp_path)
    assert r3.survey["prefix"] == "Leg A" and r3.pending_resume is None   # ended: nothing to ask
    r3.answer_resume("close")
    assert r3.survey is None


def test_data_folder_is_always_inside_spyhops_folder(tmp_path):
    """0.45: the survey data folder can't be changed: always <Spyhop folder>/data (an old data_dir is ignored)."""
    (tmp_path / "app").mkdir()
    r = Recorder(tmp_path / "app")
    assert r.cfg.data_dir == tmp_path / "app" / "data" and not hasattr(r, "set_data_dir")
    r.cfg.save_settings({"data_dir": str(tmp_path / "usb")})
    assert Recorder(tmp_path / "app").cfg.data_dir == tmp_path / "app" / "data"


def test_survey_details_saved_remembered_and_exported(rec):
    m = rec.set_meta({"platform_name": "R/V Example", "platform_type": "shipboard", "organization": "NEAQ",
                      "chief_scientist": "A. Person", "bogus": "x"})
    assert m["platform_type"] == "Shipboard" and "bogus" not in m
    with pytest.raises(ValueErrorMsg):
        rec.set_meta({"platform_type": "Boat"})
    assert rec.survey_info()["meta"]["platform_name"] == "R/V Example"
    z = rec.export()
    assert any(n.endswith("Test_metadata.csv") for n in zipfile.ZipFile(z).namelist())
    rec.end_survey()
    rec.start_survey("Next leg")                                    # details carried over
    assert rec.read_meta()["organization"] == "NEAQ"
    rec.end_survey()
    rec.start_survey("Plane day", meta={"platform_type": "Aerial", "platform_name": "N123"})
    m2 = rec.read_meta()
    assert m2["platform_type"] == "Aerial" and m2["platform_name"] == "N123" and m2["organization"] == "NEAQ"
    assert rec.read_meta("Test")["platform_name"] == "R/V Example"   # older survey unchanged


def test_marks_shape_and_colour_per_row(rec):
    m = rec.new_row("marks", {"Name": "Buoy"}, lat=41.9, lon=-70.3)["row"]
    assert m["Shape"] == "Circle" and m["Color"] == "purple"
    r = rec.edit("marks", m["RowID"], {"Shape": "star", "Color": "ORANGE"})["row"]
    assert r["Shape"] == "Star" and r["Color"] == "orange"
    r = rec.edit("marks", m["RowID"], {"Color": "#FF8800"})["row"]
    assert r["Color"] == "#ff8800"
    with pytest.raises(ValueErrorMsg):
        rec.edit("marks", m["RowID"], {"Shape": "Hexagon"})
    with pytest.raises(ValueErrorMsg):
        rec.edit("marks", m["RowID"], {"Color": "chartreuse-ish"})


def test_chief_scientist_email(rec):
    m = rec.set_meta({"chief_scientist_email": " person@example.org "})
    assert m["chief_scientist_email"] == "person@example.org"
    with pytest.raises(ValueErrorMsg):
        rec.set_meta({"chief_scientist_email": "not an email"})
    assert rec.read_meta()["chief_scientist_email"] == "person@example.org"
    rec.end_survey()
    with pytest.raises(ValueErrorMsg):
        rec.start_survey("Bad email", meta={"chief_scientist_email": "nope"})
    assert not rec._survey_exists("Bad email")                       # nothing created
    rec.start_survey("Good", meta={"chief_scientist_email": ""})
    assert rec.read_meta()["chief_scientist_email"] == ""



def test_track_marks_start_and_end(rec):
    """Track points carry the effort state in force: Start until the first ON/OFF,
    then ON/OFF, and the last point (written at End survey) is End."""
    t = rec.track
    assert [p["Effort"] for p in t.points] == ["Start"]               # recorded the moment the survey starts
    rec._last_track_t = 0; rec.tick_tracker()
    assert t.points[-1]["Effort"] == "Start"                          # no ON/OFF row yet
    rec.new_row("effort", {"Effort": "ON"})
    rec._last_track_t = 0; rec.tick_tracker()
    rec.new_row("effort", {"Effort": "OFF"})
    rec._last_track_t = 0; rec.tick_tracker()
    rec.end_survey()
    assert [p["Effort"] for p in t.points] == ["Start", "Start", "ON", "OFF", "End"]
    rec._last_track_t = 0; rec.tick_tracker()                        # ended: no more points
    assert len(t.points) == 5
    on_disk = [r["Effort"] for r in read_csv(t.path)]
    assert on_disk == ["Start", "Start", "ON", "OFF", "End"]
    exported = zcsv(rec.export(["csv"]), "_track.csv")
    assert [r["Effort"] for r in exported] == on_disk               # same after recomputing from the Effort table


def test_export_leaves_out_rowid(rec):
    rec.new_row("sightings", {"Species": "Fin whale"})
    rec.new_row("events", {"EventType": "CTD cast"})
    rec.new_row("marks", {"Name": "Buoy"}, lat=41.9, lon=-70.3)
    z = rec.export(["csv", "merged"])
    for name in ("Test_sightings.csv", "Test_effort.csv", "Test_events.csv", "waypoints.csv", "Test_merged.csv"):
        rows = zcsv(z, "/" + name)
        assert rows and "RowID" not in rows[0], name
    assert zcsv(z, "/Test_sightings.csv")[0]["Species"] == "Fin whale"
    assert "RowID" in read_csv(rec.tables["sightings"].path)[0]     # Spyhop's own working file keeps it


def test_export_choices(rec):
    rec.new_row("effort", {"Effort": "ON", "SeaState": "2", "Port": "AB"})
    rec.new_row("sightings", {"Species": "Fin whale", "Count": "2"})
    rec.new_row("events", {"EventType": "CTD cast", "ID": "C-1"})
    one = rec.export(["gpx"])                                       # one format: the file itself
    assert one.suffix == ".gpx" and one.exists() and one.read_text().startswith("<?xml")
    gj = rec.export(["geojson"])
    assert gj.suffix == ".geojson" and json.loads(gj.read_text())["type"] == "FeatureCollection"
    merged = rec.export(["merged"])
    assert merged.name.startswith("Test_merged_") and merged.suffix == ".csv"
    rows = read_csv(merged)
    track = [r for r in rows if r["Record"] == "Track"]
    assert [r["Record"] for r in rows if r["Record"] != "Track"] == ["Effort", "Effort", "Sighting", "Event"]
    assert track and track[0]["Effort"] == "Start" and track[0]["Lat"] and "SOG" in rows[0] and "COG" in rows[0]
    rows = [r for r in rows if r["Record"] != "Track"]
    s = rows[2]
    assert s["Species"] == "Fin whale" and s["Count"] == "2"
    assert s["Effort"] == "ON" and s["SeaState"] == "2" and s["Port"] == "AB"   # conditions carried to the sighting
    assert rows[3]["EventID"] == "C-1" and rows[3]["Effort"] == "ON" and rows[3]["Survey"] == "Test"
    rec._last_track_t = 0
    rec.tick_tracker()                                               # a point while ON: carries the conditions
    on = [r for r in read_csv(rec.export(["merged"])) if r["Record"] == "Track"][-1]
    assert on["Effort"] == "ON" and on["SeaState"] == "2" and on["Port"] == "AB" and on["SOG"] != ""
    html = "<!DOCTYPE html><html><body>summary</body></html>"
    z = rec.export(["gpx", "html"], html=html)                      # several: one zip
    assert z.suffix == ".zip" and zread(z, "_summary.html") == html
    with pytest.raises(ValueErrorMsg):
        rec.export([])
    with pytest.raises(ValueErrorMsg):
        rec.export(["pdf"])
    with pytest.raises(ValueErrorMsg):
        rec.export(["html"])                                        # the summary page must be supplied


def test_instruments_decoded():
    from spyhop.nmea import NmeaDecoder, with_checksum as w
    d = NmeaDecoder()
    for s in ["SDDPT,42.5,0.5,", "WIMWV,32.0,R,12.4,N,A", "WIMWV,40.0,T,10,M,A", "YXMTW,12.4,C",
              "WIMDA,29.92,I,1.0132,B,14.2,C,12.6,C,78.0,,10.3,C,220,T,235,M,11.2,N,5.8,M",
              "VWVHW,10,T,24.5,M,9.6,N,17.8,K", "ERRPM,E,2,1450,,A", "IIXDR,C,15.1,C,AIRTEMP,P,1.013,B,Barometer",
              "SDDBT,98.4,f,30.0,M,16.4,F", "IIMMB,29.9,I,1.012,B", "IIMHU,81,,,"]:
        d.feed(w(s), "udp")
    i = {k: v["value"] for k, v in d.instruments().items()}
    assert i["depth"] == 43.0 and i["depth_transducer"] == 30.0
    assert i["wind_app_angle"] == 32 and i["wind_app_speed"] == 12.4
    assert abs(i["wind_true_speed"] - 11.2) < 0.01 and i["wind_true_dir"] == 220
    assert i["stw"] == 9.6 and i["rpm_engine_2"] == 1450
    assert i["water_temp"] == 12.6 and i["air_temp"] == 15.1 and i["humidity"] == 81
    assert i["pressure"] == 1012.0
    assert d.instruments()["rpm_engine_2"]["group"] == "Engine"


def test_raw_nmea_log(rec):
    from spyhop.nmea import with_checksum as w
    st = rec.set_raw_logging(True, True)
    assert st["on"]
    rec.decoder.feed(w("GPRMC,120000,A,4154.0,N,07020.0,W,10.0,90.0,051126,14.5,W"), "udp:10110")
    rec.decoder.feed(w("SDDPT,42.5,0.5,"), "udp:10110")
    st = rec.raw_log_status()
    assert st["lines"] == 2 and st["name"].startswith("Test_nmea_")
    lines = open(st["path"]).read().splitlines()
    t, src, sentence = lines[0].split("\t")
    assert t.endswith("Z") and src == "udp:10110" and sentence.startswith("$GPRMC")
    rec.set_raw_logging(timestamps=False)                       # new file, plain NMEA
    rec.decoder.feed(w("SDDPT,40.0,0.5,"), "udp")
    st2 = rec.raw_log_status()
    assert open(st2["path"]).read().startswith("$SDDPT")
    rec.close_survey()                                         # follows the survey: no-survey file next
    assert rec.raw_log_status()["name"].startswith("no-survey_nmea_")
    rec.set_raw_logging(False)
    assert not rec.raw_log_status()["on"] and rec.decoder.raw_logger is None


def _qc(rec):
    from spyhop.qc import run_qc
    return run_qc(rec)


def _complete_meta(rec):
    rec.set_meta({"platform_name": "R/V Test", "platform_type": "Shipboard", "organization": "NEAQ",
                  "chief_scientist": "A. Person", "chief_scientist_email": "a@example.org"})


GOOD_EFFORT = {"Effort": "ON", "Visibility": ">10 nm", "SeaState": "2", "Weather": "Clear", "Glare": "None",
               "Port": "OBS1", "Recorder": "OBS2", "Starboard": "OBS3"}
GOOD_SIGHTING = {"Species": "Fin whale", "Count": "2", "Calves": "0", "NumConf": "Definite", "IDrel": "Definite",
                 "Observer": "OBS1", "Images": "None"}


def test_qc_clean_survey(rec):
    _complete_meta(rec)
    rec.new_row("effort", GOOD_EFFORT)
    rec.new_row("sightings", GOOD_SIGHTING)
    rec.new_row("events", {"EventType": "CTD cast"})
    rec.end_survey()
    r = _qc(rec)
    assert r["counts"]["error"] == 0 and r["counts"]["warning"] == 0, r["issues"]


def test_qc_finds_problems(rec):
    rec.new_row("effort", {**GOOD_EFFORT, "Starboard": "OBS1", "SeaState": ""})          # OBS1 twice, sea state blank
    s = rec.new_row("sightings", {**GOOD_SIGHTING, "Count": "2", "Calves": "3", "Bearing": "45",
                                  "Distance": "40", "DistUnit": "nm", "Observer": "OBS4"})["row"]
    rec.new_row("sightings", {"Species": "Fin whale"})                                  # most fields blank
    rec.edit("sightings", s["RowID"], {"Lat": "42.5"})                               # typo, far from the track
    rec.new_row("events", {"EventType": "Mooring deployed"})
    r = _qc(rec)
    got = {(x["check"], x["column"]) for x in r["issues"]}
    msgs = " | ".join(x["message"] for x in r["issues"])
    assert ("Survey details complete", "platform_name") in got
    assert ("Survey ended", "") in got
    assert ("Required fields filled", "SeaState") in got
    assert ("Required fields filled", "Count") in got and ("Required fields filled", "Observer") in got
    assert ("Observers in one position at a time", "Port") in got
    assert ("Plausible numbers", "Calves") in got
    assert ("Plausible bearings and distances", "Distance") in got and "40.0 nm" in msgs
    assert ("Positions match the trackline", "Lat") in got
    assert ("Sighting observer on watch", "Observer") in got
    assert not any(x["column"] in ("Behaviors", "FieldID", "Notes", "ID") for x in r["issues"] if x["check"] == "Required fields filled")
    assert r["counts"]["error"] >= 5 and r["issues"][0]["level"] == "error"
    first = next(x for x in r["issues"] if x["check"] == "Plausible numbers")
    assert first["tab"] == "sightings" and first["row_id"] == s["RowID"] and first["label"] == "Sighting 1"


def test_qc_land_and_track():
    from spyhop import qc
    assert qc.on_land(42.35, -71.06)            # Boston
    assert not qc.on_land(41.9, -70.33)         # Cape Cod Bay
    assert not qc.on_land(42.0, -40.0)          # mid-Atlantic


def test_merged_effort_with_odd_times(rec):
    from datetime import datetime, timezone
    # times typed or saved by Excel in other forms still line up with their effort rows
    e = rec.new_row("effort", {"Effort": "ON", "SeaState": "3", "Port": "AB"})["row"]
    s = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1"})["row"]
    t = datetime.fromisoformat(e["DateTime"]).astimezone(timezone.utc)
    rec.tables["effort"].rows[-1]["DateTime"] = t.strftime("%Y-%m-%d %H:%M:%SZ")      # space + Z
    hdr, rows = rec.merged_rows()
    sight = next(r for r in rows if r["Record"] == "Sighting")
    assert sight["Effort"] == "ON" and sight["SeaState"] == "3" and sight["Port"] == "AB"
    # a sighting before any effort row says so
    rec.tables["sightings"].rows.insert(0, {**s, "RowID": "x", "DateTime": "2020-01-01T00:00:00+00:00"})
    hdr, rows = rec.merged_rows()
    assert rows[0]["Record"] == "Sighting" and rows[0]["Effort"] == "no effort row yet"


def test_instrument_history(rec):
    import time as _t
    from spyhop.nmea import with_checksum as w
    rec.decoder.feed(w("SDDPT,42.5,0.5,"), "udp")
    rec.decoder.feed(w("WIMWV,350.0,T,10,N,A"), "udp")
    rec.decoder.feed(w("GPGGA,120000,4154.0,N,07020.0,W,1,09,0.9,5.0,M,-33.0,M,,"), "udp")   # gps fix text isn't plotted
    rec.sample_instruments()
    rec.decoder.feed(w("SDDPT,44.0,0.5,"), "udp")
    rec.sample_instruments()
    h = rec.instrument_history("depth")
    assert [v for _, v in h["points"]] == [43.0, 44.5] and h["unit"] == "m" and h["start"]
    assert rec.instrument_history("wind_true_angle")["angle"] is True
    assert rec.instrument_history("gps_quality")["points"] == []
    # saved with the survey and read back when it's opened again
    p = rec._inst_path()
    assert p.exists() and "depth" in p.read_text()
    prefix = rec.survey["prefix"]
    rec.close_survey()
    rec.open_survey(prefix)
    assert len(rec.instrument_history("depth")["points"]) == 2
    # stale readings aren't saved
    rec.decoder.inst["depth"]["t"] = _t.time() - 60
    rec.sample_instruments()
    assert len(rec.instrument_history("depth")["points"]) == 2
    assert "Test_nmea.csv" in {n.split("/")[-1] for n in zipfile.ZipFile(rec.export(["csv"])).namelist()}


def test_negative_bearings(rec):
    row = rec.new_row("sightings", {"BrgRef": "R", "Bearing": "-10", "Distance": "1", "DistUnit": "km"})["row"]
    assert row["Bearing"] == "350"                                       # 10° to port
    b = geo.initial_bearing(41.9, -70.333333, float(row["SigLat"]), float(row["SigLon"]))
    assert b == pytest.approx(35, abs=0.05)                              # heading 045 − 10
    assert rec.edit("sightings", row["RowID"], {"Bearing": "-360"})["row"]["Bearing"] == "0"
    assert rec.edit("sightings", row["RowID"], {"Bearing": "-0.5"})["row"]["Bearing"] == "359.5"
    with pytest.raises(ValueErrorMsg):
        rec.edit("sightings", row["RowID"], {"Bearing": "-400"})


def test_past_survey_as_overlay(rec):
    rec.cfg.settings["tracking_enabled"] = True
    rec.new_row("effort", {"Effort": "ON"})
    rec.new_row("sightings", {"Species": "North Atlantic right whale", "Count": "3", "Calves": "1", "FieldID": "Eg-1", "Bearing": "10", "Distance": "0.5"})
    rec.new_row("events", {"EventType": "Other", "ID": "X1"})
    for _ in range(3):
        rec._last_track_t = 0
        rec.tick_tracker()
    rec.new_row("effort", {"Effort": "OFF"})
    rec._last_track_t = 0
    rec.tick_tracker()
    rec.end_survey()
    rec.close_survey()
    name, gj = rec.survey_overlay("Test")
    assert name == "Survey - Test.geojson"
    kinds = [f["geometry"]["type"] for f in gj["features"]]
    assert "LineString" in kinds and kinds.count("Point") == 2
    sight = next(f for f in gj["features"] if f["properties"]["name"].startswith("S1"))
    assert sight["properties"]["number"] == "3 + 1 calves" and sight["properties"]["FieldID"] == "Eg-1"
    ev = next(f for f in gj["features"] if f["properties"]["name"].startswith("E1"))
    assert ev["properties"]["ID"] == "X1"
    on = [f for f in gj["features"] if f["geometry"]["type"] == "LineString" and f["properties"]["Effort"] == "ON"]
    assert on and on[0]["properties"]["dash"] is None
    json.dumps(gj)                                         # writable as a file
    with pytest.raises(ValueError):
        rec.survey_overlay("Nope")


def test_qc_duplicates_fieldids_and_visibility(rec):
    _complete_meta(rec)
    rec.new_row("effort", {**GOOD_EFFORT, "Visibility": "1-2 nm"})
    a = rec.new_row("sightings", {**GOOD_SIGHTING, "FieldID": "A", "Bearing": "10", "Distance": "0.5", "DistUnit": "nm"})["row"]
    rec.new_row("sightings", {**GOOD_SIGHTING, "FieldID": "B", "Bearing": "12", "Distance": "0.6", "DistUnit": "nm"})   # same species, seconds apart
    rec.new_row("sightings", {**GOOD_SIGHTING, "Species": "North Atlantic right whale", "FieldID": "A",
                              "Bearing": "200", "Distance": "3", "DistUnit": "nm"})                    # FieldID A reused; beyond 2 nm
    r = _qc(rec)
    checks = [x["check"] for x in r["issues"]]
    assert "FieldIDs consistent" not in checks
    assert "No duplicate records" not in checks
    far = [x for x in r["issues"] if x["check"] == "Distance within visibility"]
    assert len(far) == 1 and "3.00 nm" in far[0]["message"] and "1-2 nm" in far[0]["message"]
    # the very same record entered twice is still caught
    rec.tables["sightings"].add({**a, "RowID": "", "SightNo": "9"})
    r = _qc(rec)
    assert [x["label"] for x in r["issues"] if x["check"] == "No duplicate records"] == ["Sighting 9"]


def test_track_break_fix(rec):
    from datetime import datetime, timedelta
    e = rec.new_row("effort", {**GOOD_EFFORT})["row"]
    t0 = datetime.fromisoformat(e["DateTime"])

    def pt(sec, lat, lon):
        rec.track.append({"DateTime": (t0 + timedelta(seconds=sec)).isoformat(), "Lat": f"{lat:.6f}", "Lon": f"{lon:.6f}",
                          "SOG": "10", "COG": "0", "Effort": "ON"})
    pt(10, 41.90, -70.333333); pt(20, 41.9005, -70.333333)
    pt(30, 42.20, -70.333333)                     # an 18 nm jump in 10 s
    pt(40, 42.2005, -70.333333); pt(400, 42.21, -70.333333)   # then 6 min with no points
    r = _qc(rec)
    tr = [x for x in r["issues"] if x["check"] == "Trackline plausible"]
    assert len(tr) == 2 and all(x["fix"] and x["fix"]["kind"] == "track_break" for x in tr), tr
    res = rec.insert_track_break(tr[0]["fix"]["t0"], tr[0]["fix"]["t1"])
    assert res["added"] == 2
    effs = [r_["Effort"] for r_ in rec.tables["effort"].rows]
    assert effs == ["Start", "ON", "ERROR", "ON"]
    err = rec.tables["effort"].rows[2]
    assert err["Lat"] == "41.900500" and err["Visibility"] == ">10 nm"
    # one second after the last good track point (t0 + 20 s), so it sorts after it in the merged export
    assert datetime.fromisoformat(err["DateTime"]) == t0 + timedelta(seconds=21)
    merged = [m for m in rec.merged_rows()[1] if m.get("Record") in ("Effort", "Track")]
    i_err = next(i for i, m in enumerate(merged) if m.get("Effort") == "ERROR" and m.get("Record") == "Effort")
    assert any(m.get("Record") == "Track" and datetime.fromisoformat(m["DateTime"]) == t0 + timedelta(seconds=20) for m in merged[:i_err])
    with pytest.raises(ValueErrorMsg):
        rec.insert_track_break(tr[0]["fix"]["t0"], tr[0]["fix"]["t1"])      # already marked
    r = _qc(rec)
    tr2 = [x for x in r["issues"] if x["check"] == "Trackline plausible"]
    assert len(tr2) == 1 and "No track points" in tr2[0]["message"]
    # 0.45: the limits are the Error check's own (120 s; 30 kn, 200 kn for aerial)
    from spyhop.qc import run_qc, track_limit_defaults
    assert r["track_limits"]["gap_s"] == 120 and r["track_limits"]["speed_kn"] == 30
    with pytest.raises(TypeError):                 # 0.46: the limits are fixed (no override)
        run_qc(rec, {"gap_s": 600})
    rec.set_meta({"platform_type": "Aerial"})
    assert track_limit_defaults(rec)["speed_kn"] == 200
    assert "track_break_kn" not in rec.cfg.settings and "track_break_kn" not in __import__("spyhop.config", fromlist=["x"]).LOCKED_SETTINGS
    assert rec._track_state(datetime.fromisoformat(err["DateTime"]) + timedelta(seconds=5)) == "ERROR"


def test_clock_settings_and_zone_guess(rec):
    from spyhop.config import clean_timezone
    from spyhop import tzguess
    assert clean_timezone("UTC-3:30") == "UTC-03:30" and clean_timezone("utc+5") == "UTC+05:00"
    assert clean_timezone("auto") == "auto" and clean_timezone("GMT") == "UTC" and clean_timezone("Europe/Paris") == "local"
    rec.cfg.save_settings({"timezone": "UTC-03:30"})
    assert rec.now().utcoffset().total_seconds() == -3.5 * 3600
    assert tzguess.nautical_zone(-70.3) == "Etc/GMT+5" and tzguess.nautical_zone(100) == "Etc/GMT-7"
    if tzguess.tzfpy is None:
        pytest.skip("tzfpy not installed")
    assert tzguess.zone_at(41.9, -70.33) == ("America/New_York", "position")
    assert tzguess.zone_at(41.3, -69.0)[0] == "America/New_York"            # at sea, 40 nm off: the coast's zone
    assert tzguess.zone_at(38.0, -50.0) == ("Etc/GMT+3", "nautical zone")   # mid-ocean
    rec.cfg.save_settings({"timezone": "auto"})
    assert rec.clock_info()["zone"] == "America/New_York"                   # the fixture's GPS is in Cape Cod Bay


def test_track_glitch_away_and_back_is_one_break(rec):
    from datetime import datetime, timedelta
    e = rec.new_row("effort", {**GOOD_EFFORT})["row"]
    t0 = datetime.fromisoformat(e["DateTime"])
    for sec, lat in [(10, 41.9), (20, 41.9005), (30, 42.3), (40, 42.3), (50, 41.901), (60, 41.9015)]:
        rec.track.append({"DateTime": (t0 + timedelta(seconds=sec)).isoformat(), "Lat": f"{lat:.6f}", "Lon": "-70.333333",
                          "SOG": "10", "COG": "0", "Effort": "ON"})
    tr = [x for x in _qc(rec)["issues"] if x["check"] == "Trackline plausible"]
    assert len(tr) == 1 and "and back" in tr[0]["message"]
    rec.insert_track_break(tr[0]["fix"]["t0"], tr[0]["fix"]["t1"])
    assert [r["Effort"] for r in rec.tables["effort"].rows] == ["Start", "ON", "ERROR", "ON"]
    assert not [x for x in _qc(rec)["issues"] if x["check"] == "Trackline plausible"]


# ---------------------------------------------------------------- 0.9.0
def test_na_observer_in_several_positions(rec):
    _complete_meta(rec)
    rec.new_row("effort", {**GOOD_EFFORT, "Port": "NA", "Recorder": "NA", "Starboard": "OBS1"})
    issues = [x for x in _qc(rec)["issues"] if x["check"] == "Observers in one position at a time"]
    assert not issues
    rec.new_row("effort", {**GOOD_EFFORT, "Port": "OBS1", "Recorder": "NA", "Starboard": "OBS1"})
    issues = [x for x in _qc(rec)["issues"] if x["check"] == "Observers in one position at a time"]
    assert len(issues) == 1 and "OBS1" in issues[0]["message"]
    assert any(o["name"] == "NA" for o in rec.cfg.lists["observers"])


def test_report_pdf_when_a_browser_is_available(rec, tmp_path):
    from spyhop import browser, reports
    import os
    if not os.environ.get("SPYHOP_CHROME") or browser.find_chrome() is None:
        pytest.skip("set SPYHOP_CHROME to a Chrome / Edge / headless-shell binary to test PDFs")
    gear = next(f for f in reports.load(rec.cfg)[0] if f["name"] == "Gear")
    page = reports.to_html(rec, reports.run(rec, gear))
    p = browser.html_to_pdf(page, tmp_path / "gear.pdf", 300)
    assert p.read_bytes()[:5] == b"%PDF-"


# ---------------------------------------------------------------- 0.9.2: updates
def _fake_github(tmp_path, version="9.9.0", releases=True, drop="spyhop/geo.py"):
    """A local stand-in for the GitHub API: a release (or only the main branch) of a newer Spyhop."""
    import http.server, threading, io as _io, base64 as _b64
    from spyhop import updater
    src = Path(updater.__file__).resolve().parent.parent
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = "hansenjohnson-spyhop-abc1234/"
        for rel in updater._program_files(src):
            data = (src / rel).read_bytes()
            if rel.as_posix() == "spyhop/__init__.py":
                data = re.sub(rb'__version__ = "[^"]+"', f'__version__ = "{version}"'.encode(), data)
            if rel.as_posix() == drop:
                continue                                   # pretend the new version dropped a file
            zi = zipfile.ZipInfo(top + rel.as_posix())
            zi.external_attr = ((0o755 if rel.suffix in (".command", ".sh") else 0o644) << 16)
            z.writestr(zi, data)
        z.writestr(top + "NEWFILE.md", b"new")
    zbytes = buf.getvalue()
    init = f'__version__ = "{version}"\n'.encode()
    changelog = f"# Changelog\n\n## {version} — 2026-12-01\n\n- Something new.\n\n## 0.1.0 — 2026-01-01\n\n- Old.\n".encode()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            port = self.server.server_address[1]
            if self.path.endswith("/releases/latest"):
                if not releases:
                    self.send_error(404); return
                body = json.dumps({"tag_name": f"v{version}", "body": "- Release notes", "html_url": "https://example/rel",
                                   "zipball_url": f"http://127.0.0.1:{port}/repo/zipball/v{version}",
                                   "published_at": "2026-12-01T00:00:00Z"}).encode()
            elif "/contents/spyhop/__init__.py" in self.path:
                body = json.dumps({"content": _b64.b64encode(init).decode()}).encode()
            elif "/contents/CHANGELOG.md" in self.path:
                body = json.dumps({"content": _b64.b64encode(changelog).decode()}).encode()
            elif "/zipball/" in self.path:
                body = zbytes
            else:
                self.send_error(404); return
            self.send_response(200); self.end_headers(); self.wfile.write(body)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/repo"


def test_update_check_and_install(tmp_path, monkeypatch, rec):
    from spyhop import updater
    assert updater.is_newer("v0.10.0", "0.9.1") and not updater.is_newer("0.9.1", "0.9.1") and not updater.is_newer("x", "0.9.1")
    srv, api_url = _fake_github(tmp_path)
    try:
        monkeypatch.setattr(updater, "API", api_url)
        info = updater.check()
        assert info["newer"] and info["latest"] == "9.9.0" and info["source"] == "release" and "Release notes" in info["notes"]
        # install into a copy of the program folder, never into the real one
        prog = tmp_path / "prog"
        shutil.copytree(updater.PROGRAM_DIR, prog, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache"))
        (prog / ".venv").mkdir()
        (prog / ".venv" / "keep.txt").write_text("mine")
        monkeypatch.setattr(updater, "PROGRAM_DIR", prog)
        monkeypatch.setattr(updater, "_install_packages", lambda: "stubbed")
        res = updater.install(rec.cfg, info)
        assert res["installed"] == "9.9.0" and Path(res["backup"]).exists()
        assert '__version__ = "9.9.0"' in (prog / "spyhop" / "__init__.py").read_text()
        assert (prog / "NEWFILE.md").read_text() == "new"
        assert not (prog / "spyhop" / "geo.py").exists()                 # dropped by the new version
        assert (prog / ".venv" / "keep.txt").read_text() == "mine"         # the environment is left alone
        assert os.access(prog / "Start Spyhop (Mac).command", os.X_OK)
        with zipfile.ZipFile(res["backup"]) as z:
            assert "spyhop/spyhop/geo.py" in z.namelist()                  # the old version is in the backup
        with pytest.raises(updater.UpdateError):
            updater.install(rec.cfg, {**info, "newer": False})
    finally:
        srv.shutdown()


def test_update_check_without_releases_uses_main(monkeypatch):
    from spyhop import updater
    srv, api_url = _fake_github(None, version="9.9.1", releases=False)
    try:
        monkeypatch.setattr(updater, "API", api_url)
        info = updater.check()
        assert info["source"] == "main" and info["latest"] == "9.9.1" and info["newer"]
        assert "Something new" in info["notes"] and "Old." not in info["notes"]
    finally:
        srv.shutdown()
    monkeypatch.setattr(updater, "API", "http://127.0.0.1:9")            # nothing listening
    with pytest.raises(updater.UpdateError):
        updater.check()


def test_keep_awake(tmp_path, monkeypatch):
    """The keep-awake request follows the setting and the survey, and a failure doesn't retry every tick."""
    from spyhop import awake
    from spyhop.server import App

    calls = []
    monkeypatch.setattr(awake.KeepAwake, "_start", lambda self, mode: calls.append(("start", mode)))
    monkeypatch.setattr(awake.KeepAwake, "_stop", lambda self: calls.append(("stop",)))
    monkeypatch.setattr(awake.KeepAwake, "method", lambda self: "test")

    app = App(tmp_path)
    rec, s = app.rec, app.rec.cfg.settings
    assert s["keep_awake"] == "survey" and s["keep_screen_on"] is False
    app.sync_awake()
    assert app.awake.mode is None and not any(c[0] == "start" for c in calls)   # no survey yet

    rec.start_survey("Awake test")
    app.sync_awake()
    assert app.awake.mode == "system" and ("start", "system") in calls
    n = len(calls)
    app.sync_awake()
    assert len(calls) == n                                  # nothing changes: nothing is redone

    rec.cfg.save_settings({"keep_screen_on": True})
    app.sync_awake()
    assert app.awake.mode == "display"

    rec.end_survey()
    app.sync_awake()
    assert app.awake.mode is None                           # ended: normal sleep again

    rec.cfg.save_settings({"keep_awake": "always"})
    app.sync_awake()
    assert app.awake.mode == "display"
    rec.cfg.save_settings({"keep_awake": "nonsense"})
    assert s["keep_awake"] == "survey"                      # unknown values fall back to the default
    rec.cfg.save_settings({"keep_awake": "off"})
    app.sync_awake()
    assert app.awake.mode is None
    app.awake.release()

    # a helper that fails: reported once, then not retried until RETRY_S has passed
    def boom(self, mode):
        calls.append(("try", mode))
        raise RuntimeError("no power manager here")
    monkeypatch.setattr(awake.KeepAwake, "_start", boom)
    k = awake.KeepAwake()
    k.set("system")
    assert k.mode is None and "no power manager" in k.status()["error"]
    tries = sum(c[0] == "try" for c in calls)
    k.set("system")
    assert sum(c[0] == "try" for c in calls) == tries
    k.set(None)
    assert k.status()["error"] == ""


def test_summary_pdf_uses_printed_page(tmp_path, monkeypatch):
    """Export: the summary's PDF is printed from the page made for printing, its HTML stays the interactive one."""
    import zipfile
    from spyhop import recorder as recmod
    printed = []
    monkeypatch.setattr(recmod, "_pdf_bytes", lambda page, wait_ms=3000: printed.append((page, wait_ms)) or b"%PDF-1.4 fake")
    rec = Recorder(tmp_path)
    rec.start_survey("PdfPage")
    html, html_pdf = "<!DOCTYPE html><p>interactive</p>", "<!DOCTYPE html><p>printed</p>"
    z = rec.export(["html"], html, ["html", "pdf"], html_pdf)
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
        page = f.read(next(n for n in names if n.endswith("_summary.html"))).decode()
    assert page == html and any(n.endswith("_summary.pdf") for n in names)
    assert printed == [(html_pdf, 6000)]
    printed.clear()
    rec.export(["html"], html, ["pdf"])          # an older window that sends no printed page
    assert printed == [(html, 6000)]


def _template_zip(files: dict, top: str = "") -> bytes:
    import io as _io, zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        for n, text in files.items():
            z.writestr(top + n, text)
    return buf.getvalue()


def _serve(routes: dict):
    """A local web server: {path: (status, content-type, bytes)}. Returns (base url, stop)."""
    import http.server, threading as _th

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            st, ct, body = routes.get(self.path.split("?")[0], (404, "text/plain", b"nope"))
            self.send_response(st)
            self.send_header("Content-Type", ct)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}", srv.shutdown




def test_save_lists_and_shortcuts(tmp_path):
    from spyhop.config import Config, clean_combo
    cfg = Config(tmp_path)
    rows = [{"name": "Fin whale", "color": "royalblue", "species_code": "FIWH"},
            {"name": "", "color": "", "species_code": ""},                       # blank: dropped
            {"name": "Sei whale", "color": "#00aa88", "species_code": "SEWH", "extra": "x"}]
    cfg.save_list("species", rows)
    assert [s["name"] for s in cfg.lists["species"]] == ["Fin whale", "Sei whale", "Other"]
    for bad, words in (([{"name": "A", "species_code": "X"}, {"name": "a", "species_code": "Y"}], "already used"),
                       ([{"name": "A", "species_code": "X"}, {"name": "B", "species_code": "x"}], "Code “x” is already used"),
                       ([{"name": "A", "color": "not a color!"}], "isn't a color"),
                       ([{"name": "", "species_code": "X"}], "Name is empty"),
                       ([], "can't be empty")):
        with pytest.raises(ValueError, match=words):
            cfg.save_list("species", bad)
    assert [s["name"] for s in cfg.lists["species"]] == ["Fin whale", "Sei whale", "Other"]   # unchanged
    cfg.save_list("observers", [{"name": "HJ", "full_name": "Hansen Johnson"}, {"name": "NA", "full_name": "None"}])
    assert cfg.lists["observers"][0]["full_name"] == "Hansen Johnson"
    with pytest.raises(ValueError):
        cfg.save_list("nonsense", [{"name": "A"}])

    assert clean_combo("shift+mod+r") == "Mod+Shift+R" and clean_combo("alt+ArrowLeft") == "Alt+ArrowLeft"
    assert clean_combo("f2") == "F2" and clean_combo("Ctrl+Shift++") == "Mod+Shift++"
    for bad in ("R", "Shift+R", "Hyper+R", ""):
        with pytest.raises(ValueError):
            clean_combo(bad)
    tabs = {"sightings": {"Species", "Obs"}, "effort": set(), "events": {"EventType"}, "marks": set()}
    cfg.save_shortcuts([{"combo": "shift+mod+b", "action": "add:sightings", "prefill": "Species=Fin whale;Obs=HJ"},
                        {"combo": "Mod+1", "action": "tab:sightings"}, {"combo": "", "action": "", "prefill": ""}], tabs)
    assert cfg.shortcuts == [{"combo": "Mod+Shift+B", "action": "add:sightings", "prefill": "Species=Fin whale;Obs=HJ"},
                             {"combo": "Mod+1", "action": "tab:sightings", "prefill": ""}]
    for bad, words in (([{"combo": "Mod+1", "action": "undo"}, {"combo": "mod+1", "action": "redo"}], "already used"),
                       ([{"combo": "Mod+1", "action": "fly"}], "isn't an action"),
                       ([{"combo": "Mod+1", "action": "add:surfacings"}], "no surfacings table"),
                       ([{"combo": "Mod+1", "action": "add:sightings", "prefill": "Color=red"}], "no column “Color”"),
                       ([{"combo": "Mod+1", "action": "undo", "prefill": "Species=X"}], "only shortcuts that add"),
                       ([{"combo": "Q", "action": "undo"}], "needs Mod or Alt")):
        with pytest.raises(ValueError, match=words):
            cfg.save_shortcuts(bad, tabs)
    assert len(cfg.shortcuts) == 2


def test_lists_locked_during_survey(tmp_path):
    import asyncio
    from spyhop.server import App
    app = App(tmp_path)
    app.rec.start_survey("Locked")

    class Req:
        def __init__(self, body): self.body = body
        async def json(self): return self.body
    with pytest.raises(ValueErrorMsg, match="survey is under way"):
        asyncio.run(app.save_list(Req({"list": "species", "rows": [{"name": "X"}]})))
    asyncio.run(app.save_shortcuts(Req({"rows": [{"combo": "Mod+1", "action": "undo"}]})))   # shortcuts aren't locked
    assert app.rec.cfg.shortcuts[0]["action"] == "undo"
    app.rec.end_survey()
    asyncio.run(app.save_list(Req({"list": "species", "rows": [{"name": "X"}]})))
    assert [s["name"] for s in app.rec.cfg.lists["species"]] == ["X", "Other"]



def _png_bytes():
    import struct, zlib as _z
    raw = b"\x00" + bytes([10, 120, 200]) * 4
    raw = raw * 4
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", _z.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) + ch(b"IDAT", _z.compress(raw)) + ch(b"IEND", b"")


def test_style_layer_proxy_cache_and_download(tmp_path):
    """A MapLibre style (like Seascape) goes through the tile cache, downloads for offline use, and works offline."""
    import asyncio
    from spyhop.config import Config
    from spyhop.tiles import TileService
    png, pbf = _png_bytes(), b"\x1a\x05fake-mvt"
    routes = {}
    base, stop = None, None

    def build(b):
        style = {"version": 8, "glyphs": b + "/fonts/{fontstack}/{range}.pbf",
                 "sources": {"bathy": {"type": "vector", "url": b + "/vector.json"},
                             "dem": {"type": "raster-dem", "url": b + "/raster.json"},
                             "osm": {"type": "raster", "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]}},
                 "layers": [{"id": "bg", "type": "background"}, {"id": "osm-base", "type": "raster", "source": "osm"},
                            {"id": "lbl", "type": "symbol", "source": "bathy", "layout": {"text-font": ["Noto Sans Regular"]}},
                            {"id": "depth-points", "type": "symbol", "source": "bathy", "source-layer": "soundings"},
                            {"id": "contour-labels", "type": "symbol", "source": "bathy", "source-layer": "contours",
                             "layout": {"text-padding": 50}},
                            {"id": "soundings-shallow", "type": "symbol", "source": "bathy", "source-layer": "spot"}]}
        routes["/style.json"] = (200, "application/json", json.dumps(style).encode())
        routes["/vector.json"] = (200, "application/json", json.dumps({"tiles": [b + "/v/{z}/{x}/{y}.pbf"], "minzoom": 0, "maxzoom": 3}).encode())
        routes["/raster.json"] = (200, "application/json", json.dumps({"tiles": [b + "/r/{z}/{x}/{y}.webp"], "maxzoom": 2}).encode())
        for z in range(4):
            for x in range(2 ** z):
                for y in range(2 ** z):
                    routes[f"/v/{z}/{x}/{y}.pbf"] = (200, "application/x-protobuf", pbf)
                    if z <= 2:
                        routes[f"/r/{z}/{x}/{y}.webp"] = (200, "image/png", png)
        for r in ("0-255", "256-511", "8192-8447"):
            routes[f"/fonts/Noto%20Sans%20Regular/{r}.pbf"] = (200, "application/x-protobuf", b"glyphs")
    base, stop = _serve(routes)
    build(base)
    cfg = Config(tmp_path)
    cfg.settings["tile_cache_enabled"] = False         # downloads are kept anyway
    cfg.tile_sources = [{"name": "Test style", "url": base + "/style.json", "kind": "style", "max_zoom": "22"},
                        {"name": "Test raster", "url": base + "/r/{z}/{x}/{y}.webp", "kind": "raster", "max_zoom": "2"}]
    ts = TileService(cfg)

    async def go():
        local = "http://127.0.0.1:8765"
        st = await ts.gl_style(0, local)
        assert [l["id"] for l in st["layers"]] == ["bg", "lbl", "contour-labels"]   # depth soundings dropped
        assert st["layers"][2]["layout"]["text-padding"] == 2                     # more contour labels
        assert st["sources"]["bathy"]["url"].startswith(local + "/tiles/gl/0/tilejson?u=")
        assert "osm" not in st["sources"]                                          # no OpenStreetMap background (0.26)
        assert st["glyphs"].startswith(local + "/tiles/gl/0/glyphs/{fontstack}/{range}?u=")
        from urllib.parse import parse_qs, urlsplit
        up = lambda u: parse_qs(urlsplit(u).query)["u"][0]        # noqa: E731
        tj = await ts.gl_tilejson(0, up(st["sources"]["bathy"]["url"]), local)
        assert tj["tiles"][0].startswith(local + "/tiles/gl/0/t/{z}/{x}/{y}?u=")
        data, ctype, status = await ts.gl_tile(0, up(tj["tiles"][0]), 1, 0, 1)
        assert data == pbf and status == 200
        assert (await ts.gl_tile(0, "https://evil.example/{z}/{x}/{y}", 1, 0, 0))[2] == 403   # not an open proxy
        g = await ts.gl_file(0, ts.fill_glyphs(up(st["glyphs"]), "Noto Sans Regular", "0-255"), "_glyphs")
        assert g == b"glyphs"

        world = [-85, -180, 85, 180]
        plan = await ts.plan_prefetch(0, world, 0, 5)
        # vector z0–3 (85 tiles) + DEM z0–2 (21) + 3 font ranges; the OpenStreetMap background isn't in the style any more
        assert plan["total"] == 85 + 21 + 3 and not any("openstreetmap" in x for x in plan["skipped"])
        r = await ts.start_prefetch(0, world, 0, 5, name="Cape Cod Bay")
        assert r["total"] == 109 and r["file"] == "Cape Cod Bay.mbtiles"
        await ts._prefetch_task
        s = ts.prefetch_state
        assert s["done"] == 109 and s["failed"] == 0 and not s["running"] and s["saved"] == 85 + 21

        # the download is a file in the charts folder, listed with what's in it
        import sqlite3 as _sq
        chart = cfg.charts_dir / "Cape Cod Bay.mbtiles"
        con = _sq.connect(chart)
        meta = dict(con.execute("SELECT name, value FROM metadata"))
        assert meta["spyhop_kind"] == "style" and meta["spyhop_source"] == "Test style" and meta["maxzoom"] == "5"
        assert con.execute("SELECT COUNT(*) FROM spyhop_tiles").fetchone()[0] == 106
        keys = {k for (k,) in con.execute("SELECT key FROM spyhop_files")}
        assert "style" in keys and sum(k.startswith("tilejson:") for k in keys) == 2 and sum(k.startswith("file:") for k in keys) == 3
        con.close()
        assert "Cape Cod Bay.mbtiles" in cfg.mbtiles
        info = {m["file"]: m for m in ts.mbtiles_info()}["Cape Cod Bay.mbtiles"]
        assert info["kind"] == "style" and info["source"] == "Test style" and info["tiles"] == 106 and info["mb"] is not None

        # again: nothing new to download; another layer can't add to this file
        await ts.start_prefetch(0, world, 0, 5, name="Cape Cod Bay")
        await ts._prefetch_task
        assert ts.prefetch_state["saved"] == 0 and ts.prefetch_state["cached"] == 106
        with pytest.raises(ValueError, match="already a chart"):
            await ts.start_prefetch(1, world, 0, 2, name="Cape Cod Bay")
        with pytest.raises(ValueError, match="name"):
            await ts.start_prefetch(1, world, 0, 2, name="   ")

        rp = await ts.plan_prefetch(1, world, 0, 6)
        assert rp["zmax"] == 2 and "only goes up to zoom 2" in rp["note"] and rp["total"] == 21
        await ts.start_prefetch(1, world, 0, 6, name="Raster test")
        await ts._prefetch_task
        assert ts.prefetch_state["failed"] == 0 and ts.prefetch_state["saved"] == 21
        con = _sq.connect(cfg.charts_dir / "Raster test.mbtiles")     # a plain MBTiles file
        assert con.execute("SELECT COUNT(*) FROM tiles").fetchone()[0] == 21
        assert dict(con.execute("SELECT name, value FROM metadata"))["format"] == "png"
        con.close()
        with pytest.raises(ValueError, match="lowest zoom"):
            await ts.plan_prefetch(1, world, 4, 2)
        with pytest.raises(ValueError, match="limit"):
            await ts.start_prefetch(1, world, 0, 2, limit=10)

    asyncio.run(go())
    asyncio.run(ts.close())
    stop()                                            # the internet is gone, and so is the browsing cache:
    import shutil as _sh                              # everything comes from the chart files
    _sh.rmtree(cfg.tile_cache_dir, ignore_errors=True)
    ts = TileService(cfg)                             # as after a restart
    import time as _t
    ts._offline_until = _t.monotonic() + 3600          # known to be offline (the stopped test server would only time out)

    async def offline():
        local = "http://127.0.0.1:8765"
        st = await ts.gl_style(0, local)
        assert st and st["sources"]["dem"]["url"].startswith(local)
        from urllib.parse import parse_qs, urlsplit
        up = lambda u: parse_qs(urlsplit(u).query)["u"][0]        # noqa: E731
        tj = await ts.gl_tilejson(0, up(st["sources"]["dem"]["url"]), local)
        data, ctype, status = await ts.gl_tile(0, up(tj["tiles"][0]), 2, 3, 1)
        assert status == 200 and ctype == "image/png"
        assert (await ts.get_online(1, 2, 1, 1))[1] == "image/png"
        assert (await ts.gl_tile(0, up(tj["tiles"][0]), 2, 9, 9))[0] is None   # not saved, and no internet
        g = await ts.gl_file(0, ts.fill_glyphs(up(st["glyphs"]), "Noto Sans Regular", "0-255"), "_glyphs")
        assert g == b"glyphs"

        # the downloaded area on its own (preview): only the file's tiles and fonts
        off = ts.offline_style("Cape Cod Bay.mbtiles", local)
        here = local + "/tiles/off/Cape%20Cod%20Bay.mbtiles"
        assert [l["id"] for l in off["layers"]] == ["bg", "lbl", "contour-labels"]
        assert off["sources"]["dem"]["tiles"][0].startswith(here + "/t/") and off["sources"]["dem"]["maxzoom"] == 2
        assert "url" not in off["sources"]["bathy"] and off["glyphs"] == here + "/glyphs/{fontstack}/{range}"
        assert "osm" not in off["sources"]                                         # no OpenStreetMap background (0.26)
        dem_set = off["sources"]["dem"]["tiles"][0].split("/t/")[1].split("/")[0]
        assert ts.offline_style_tile("Cape Cod Bay.mbtiles", dem_set, 2, 3, 1) == png
        assert ts.offline_style_tile("Cape Cod Bay.mbtiles", dem_set, 5, 0, 0) is None
        assert ts.offline_glyphs("Cape Cod Bay.mbtiles", "Noto Sans Regular", "0-255") == b"glyphs"
        assert ts.offline_style("Raster test.mbtiles", local) is None
        ts.delete_chart("Raster test.mbtiles")                       # Settings → Basemap → Delete
        assert not (cfg.charts_dir / "Raster test.mbtiles").exists() and "Raster test.mbtiles" not in cfg.mbtiles
        assert await ts.get_online(1, 2, 1, 1) is None                # gone, and no internet
        with pytest.raises(ValueError, match="no chart file"):
            ts.delete_chart("../settings.json")
        await ts.close()
    asyncio.run(offline())
    assert ts.cache_stats()["tiles"] == 0


def test_offline_backoff_is_per_server(tmp_path):
    """A map server that can't be reached is skipped for a while, without blocking the others."""
    import asyncio, socket
    from spyhop.config import Config
    from spyhop.tiles import TileService, OFFLINE_AFTER
    png = _png_bytes()
    base, stop = _serve({"/t/1/0/0.png": (200, "image/png", png)})
    s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()   # nothing listens here
    ts = TileService(Config(tmp_path))

    async def go():
        for _ in range(OFFLINE_AFTER):
            assert (await ts._download(f"http://127.0.0.1:{dead}/x"))[0] == 0
        assert (await ts._download(f"http://127.0.0.1:{dead}/x"))[2] == "no internet connection"   # skipped now
        st, body, _ = await ts._download(base + "/t/1/0/0.png")                                     # others still work
        assert st == 200 and body == png
        await ts.close()
    try:
        asyncio.run(go())
    finally:
        stop()


def test_reports_presets_run_and_export(rec):
    from spyhop import reports as filters
    saved, errors = filters.load(rec.cfg)                     # first use: the starting presets
    assert not errors
    assert [f["name"] for f in saved] == ["Blue whales", "Dead birds", "Gear", "Right whales"]
    rec.new_row("sightings", {"Species": "North Atlantic right whale", "Count": "3", "Calves": "1", "Notes": "mom & calf"})
    rec.new_row("sightings", {"Species": "Humpback whale", "Count": "2"})
    rec.new_row("sightings", {"Species": "RIWH", "Count": "2"})            # typed as the code
    rec.new_row("sightings", {"Species": "Spyhop mystery whale", "Count": "1"})   # not in the list
    rec.new_row("events", {"EventType": "CTD cast"})
    by = {f["name"]: f for f in saved}
    r = filters.run(rec, by["Right whales"])
    assert r["count"] == 2 and r["total"] == 4
    assert [c["label"] for c in r["columns"]] == ["Time", "Position", "Num", "Calves", "Notes"]
    assert r["totals"] == ["", "", "5", "1", ""] and "°" in r["rows"][0][1] and len(r["row_ids"]) == 2
    rec.new_row("sightings", {"Species": "Fishing gear - reported", "Count": "1", "Notes": "buoy line"})   # 0.34: a sighting
    g = filters.run(rec, by["Gear"])
    assert g["count"] == 1 and g["rows"][0][1] == "Fishing gear - reported"
    # codes in this survey, with counts; a name with no code counts by its name
    c = {x["code"]: x["n"] for x in filters.counts(rec, "sightings")}
    assert c == {"RIWH": 2, "HUWH": 1, "Spyhop mystery whale": 1, "GRPT": 1}
    spec = {"name": "Big groups", "table": "sightings", "codes": [], "columns": ["code", "Count"],
            "rules": [{"column": "Count", "op": "gt", "value": "1"}, {"column": "Notes", "op": "not_contains", "value": "calf"}]}
    r = filters.run(rec, spec)
    assert r["rows"] == [["HUWH", "2"], ["RIWH", "2"]]
    assert filters.run(rec, {**spec, "rules": [], "codes": ["Spyhop mystery whale"]})["count"] == 1
    # on effort only: rows made while effort was ON
    before = filters.run(rec, {**spec, "rules": [], "on_effort": True})["count"]
    import time as _t
    _t.sleep(1.05)                                          # times are to the second
    if rec.tables["effort"].rows[-1].get("Effort") != "ON":
        rec.toggle_effort()
    rec.new_row("sightings", {"Species": "Humpback whale", "Count": "1"})
    _t.sleep(1.05)
    rec.toggle_effort()
    rec.new_row("sightings", {"Species": "Humpback whale", "Count": "1"})
    assert filters.run(rec, {**spec, "rules": [], "on_effort": True})["count"] == before + 1
    rec.delete("sightings", rec.tables["sightings"].rows[-1]["RowID"])
    rec.delete("sightings", rec.tables["sightings"].rows[-1]["RowID"])
    # time range in the survey clock
    later = filters.run(rec, {**spec, "rules": [], "time_from": "2999-01-01T00:00"})
    assert later["count"] == 0
    with pytest.raises(filters.ReportError):
        filters.clean({**spec, "columns": ["Nope"]})
    with pytest.raises(filters.ReportError):
        filters.clean({**spec, "rules": [{"column": "Count", "op": "gt", "value": "lots"}]})
    page = filters.to_html(rec, filters.run(rec, spec))
    assert "Big groups" in page and "Sightings:" not in page
    import datetime as _dt
    assert f"<th>Date</th><td>{_dt.date.today().isoformat()}</td>" in page        # one day: one date, no range
    rec.set_meta({"chief_scientist_email": "chief@example.org"})
    assert 'href="mailto:chief@example.org"' in filters.to_html(rec, filters.run(rec, spec))
    tf = filters.run(rec, {**spec, "rules": [], "columns": ["time_fmt"]})
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d [A-Z+\-0-9]+", tf["rows"][0][0]), tf["rows"][0][0]
    csv_text = filters.to_csv(filters.run(rec, spec))
    assert csv_text.startswith("﻿Species code,Num\r\n")
    # save, rename (replace), delete
    f = filters.save(rec.cfg, spec)
    assert f["file"] == "big_groups.json" and "big_groups.json" in rec.cfg.reports
    g = filters.save(rec.cfg, {**spec, "name": "Groups"}, replace=f["file"])
    assert g["file"] == "groups.json" and "big_groups.json" not in rec.cfg.reports
    filters.delete(rec.cfg, "groups.json")
    with pytest.raises(filters.ReportError):
        filters.delete(rec.cfg, "../species.csv")
    # deleting every preset doesn't bring them back
    for x in filters.load(rec.cfg)[0]:
        filters.delete(rec.cfg, x["file"])
    assert filters.load(rec.cfg)[0] == []
    filters.save(rec.cfg, {**spec, "name": "Right whales", "codes": ["RIWH"]})
    with pytest.raises(ValueErrorMsg, match="during a survey"):         # 0.40: reports wait for the end
        rec.export(["report:right_whales.json"])
    rec.end_survey()
    out = rec.export(["report:right_whales.json"])
    assert out.name.startswith("Test_report_right_whales") and out.suffix == ".csv"
    with pytest.raises(ValueErrorMsg):
        rec.export(["report:nope.json"])



def test_saved_routes_folder(tmp_path):
    import json as _json
    from spyhop import routes
    from spyhop.config import Config
    cfg = Config(tmp_path / "app")
    assert cfg.routes_dir.is_dir() and routes.list_routes(cfg) == []
    design = {"spyhop": 1, "mode": "systematic", "speed": 9, "name": "Leg plan", "style": {"color": "#ff0000"},
              "sys": {"start": [41.9, -70.3], "bearing": 0, "legs": 2, "legNm": 5, "spacingNm": 1}}
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
           'xmlns:spyhop="https://github.com/spyhop/route/1"><metadata><name>Leg plan</name><extensions><spyhop:route>'
           + _json.dumps(design).replace("&", "&amp;").replace("<", "&lt;") + '</spyhop:route></extensions></metadata>'
           '<rte><name>Leg plan</name><rtept lat="41.9" lon="-70.3"/><rtept lat="42.0" lon="-70.3"/>'
           '<rtept lat="42.0" lon="-70.28"/></rte></gpx>')
    r = routes.save(cfg, "Leg plan", gpx)
    assert r["file"] == "Leg plan.gpx" and r["mode"] == "systematic" and r["points"] == 3 and r["color"] == "#ff0000"
    assert 6.8 < r["nm"] < 7.0 and r["spyhop"]
    with pytest.raises(routes.RouteError, match="exists"):
        routes.save(cfg, "Leg plan", gpx)                         # a new route with a name in use
    routes.save(cfg, "Leg plan", gpx, overwrite=True)
    routes.save(cfg, "Leg plan", gpx, replace="Leg plan.gpx")     # saving the open one again
    r2 = routes.save(cfg, "Renamed/plan", gpx, replace="Leg plan.gpx")
    assert r2["file"] == "Renamed_plan.gpx" and [x["file"] for x in routes.list_routes(cfg)] == ["Renamed_plan.gpx"]
    # a GPX copied into the folder from elsewhere, and one that isn't GPX
    (cfg.routes_dir / "other.gpx").write_text('<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">'
                                              '<wpt lat="41" lon="-70"/><wpt lat="41.1" lon="-70"/></gpx>')
    (cfg.routes_dir / "broken.gpx").write_text("nope")
    by = {x["file"]: x for x in routes.list_routes(cfg)}
    assert by["other.gpx"]["mode"] == "imported" and by["other.gpx"]["points"] == 2 and not by["other.gpx"]["spyhop"]
    assert by["broken.gpx"]["error"]
    assert "spyhop:route" in routes.read(cfg, "Renamed_plan.gpx")
    for bad in ("../x.gpx", "x.txt", ".hidden.gpx", "missing.gpx"):
        with pytest.raises(routes.RouteError):
            routes.read(cfg, bad)
    with pytest.raises(routes.RouteError):
        routes.save(cfg, "x", "not gpx")
    routes.delete(cfg, "other.gpx")
    assert "other.gpx" not in {x["file"] for x in routes.list_routes(cfg)}


def test_status_bar_font_size_default(tmp_path):
    from spyhop.config import Config
    cfg = Config(tmp_path)
    assert cfg.display["status_font_size"] == "13"


def test_online_feeds_fetch_and_cache(tmp_path):
    import asyncio, json as _json
    from spyhop import feeds
    from spyhop.config import Config
    cfg = Config(tmp_path)
    poly = {"type": "Feature", "properties": {"zone_name": "Cape Cod Bay", "st_mo": 1, "st_day": 1, "end_mo": 5, "end_day": 15},
            "geometry": {"type": "Polygon", "coordinates": [[[-70.5, 41.8], [-70.1, 41.8], [-70.1, 42.1], [-70.5, 41.8]]]}}
    calls = []

    async def download(url):
        calls.append(url)
        if url.endswith("/FeatureServer?f=json"):
            return 200, _json.dumps({"layers": [{"id": 0, "name": "Slow Zones", "geometryType": "esriGeometryPolygon"},
                                                 {"id": 2, "name": "Labels", "geometryType": "esriGeometryPoint"}]}).encode(), ""
        if "broken" in url:
            return 200, b'{"error": {"code": 400, "message": "Invalid URL"}}', ""
        if "/query?" in url:
            assert "f=geojson" in url and "outSR=4326" in url
            return 200, _json.dumps({"type": "FeatureCollection", "features": [poly]}).encode(), ""
        if url.endswith(".geojson"):
            return 200, _json.dumps({"type": "FeatureCollection", "features": [poly, {"type": "Feature", "geometry": None}]}).encode(), ""
        if "broken" in url:
            return 200, b'{"error": {"code": 400, "message": "Invalid URL"}}', ""
        return 0, b"", "no internet connection"

    run = lambda u: asyncio.run(feeds.fetch(download, u))   # noqa: E731
    assert len(run("https://x.example/arcgis/rest/services/SMA/FeatureServer/3")) == 1
    both = run("https://x.example/arcgis/rest/services/DMA/FeatureServer")
    assert len(both) == 2 and {f["properties"]["_layer"] for f in both} == {"Slow Zones", "Labels"}
    assert len(run("https://x.example/data/zones.geojson")) == 1               # a feature with no geometry is dropped
    with pytest.raises(feeds.FeedError, match="Invalid URL"):
        run("https://x.example/broken/FeatureServer/0")
    with pytest.raises(feeds.FeedError, match="no internet"):
        run("https://offline.example/zones.json")
    # pasted addresses are tidied; bad ones refused
    assert feeds.clean_url("https://x.example/a/FeatureServer/3/query?where=1=1&f=pjson") == "https://x.example/a/FeatureServer/3"
    for bad in ("", "ftp://x/y", "zones.geojson"):
        with pytest.raises(feeds.FeedError):
            feeds.clean_url(bad)
    f = feeds.clean({"name": "SMA", "url": "https://x.example/a/FeatureServer/3", "color": "#d81b60", "refresh_min": 2})
    assert f["refresh_min"] == 5 and len(f["id"]) == 8
    with pytest.raises(feeds.FeedError, match="already"):
        feeds.clean({"name": "sma", "url": "https://x.example/b.geojson"}, [f])
    with pytest.raises(feeds.FeedError):
        feeds.clean({"name": "x", "url": "https://x.example/b.geojson", "color": "red"})
    feeds.save_cache(cfg, f["id"], [poly])
    c = feeds.load_cache(cfg, f["id"])
    assert c["features"][0]["properties"]["zone_name"] == "Cape Cod Bay" and c["fetched"] > 0
    feeds.drop_cache(cfg, f["id"])
    assert feeds.load_cache(cfg, f["id"]) is None
    assert all(p["url"].startswith("https://services2.arcgis.com/") for p in feeds.PRESETS)




# ---------------------------------------------------------------- templates (Settings → Templates)
class _Req:
    def __init__(self, body=None, query=None, match=None):
        self.body, self.query, self.match_info = body or {}, query or {}, match or {}
    can_read_body = True

    async def json(self):
        return self.body


def _run(coro):
    import asyncio
    return json.loads(asyncio.run(coro).text)


def test_template_resolve():
    from spyhop.templates import resolve, TemplateError
    assert resolve("https://github.com/team/spyhop-config") == ("url", "https://api.github.com/repos/team/spyhop-config/zipball")
    assert resolve("https://github.com/team/cfg/tree/main/aerial/pack") == \
        ("url", "https://api.github.com/repos/team/cfg/zipball/main#aerial/pack")
    assert resolve("https://github.com/team/spyhop/blob/main/configs/neaq-aerial.zip") == \
        ("url", "https://raw.githubusercontent.com/team/spyhop/main/configs/neaq-aerial.zip")
    assert resolve("https://github.com/team/spyhop/raw/v0.12.0/configs/neaq.zip")[1] == \
        "https://raw.githubusercontent.com/team/spyhop/v0.12.0/configs/neaq.zip"
    raw = "https://raw.githubusercontent.com/team/spyhop/main/configs/neaq.zip"
    assert resolve(raw) == ("url", raw)
    rel = "https://github.com/team/spyhop/releases/download/v0.12.0/neaq-config.zip"
    assert resolve(rel) == ("url", rel)
    k, u = resolve("https://www.dropbox.com/scl/fo/abc/xyz?rlkey=k&dl=0")
    assert "dl=1" in u and "rlkey=k" in u
    assert resolve("https://drive.google.com/file/d/FILEID/view?usp=sharing") == \
        ("url", "https://drive.google.com/uc?export=download&id=FILEID")
    for bad in ("https://drive.google.com/drive/folders/abc", "", "not a link"):
        with pytest.raises(TemplateError):
            resolve(bad)


def test_template_check_use_backup(tmp_path):
    """A template from the web: read, compared, used; a backup puts things back; problems stop it;
    a folder on disk works."""
    import json as _json, zipfile as _zf
    from spyhop import templates
    from spyhop.config import Config
    cfg = Config(tmp_path / "app")
    cfg.save_reports({"mine.json": {"name": "Mine", "table": "events", "columns": ["time"]}})
    cur = cfg.current_dir
    species = "name,color,species_code\r\nNorth Atlantic right whale,red,RIWH\r\nHumpback whale,orange,HUWH\r\nSpyhop test whale,pink,SPTW\r\n"
    observers = "name,full_name\r\nHJ,Hansen Johnson\r\n"
    gear = {"name": "Gear (team)", "table": "events", "codes": ["GRPT"], "columns": ["time"]}
    conf = _json.dumps({"spyhop_template": 3, "history": [
        {"date": "2026-10-01", "by": "HJ", "changed": "all", "notes": "First version"},
        {"date": "2026-11-06", "by": "HJ", "changed": "species.csv", "notes": "Added test whale"}],
        "map_display": {"marker_radius": "11"}, "reports": {"team_gear.json": gear}})
    good = _template_zip({"spyhop-config.json": conf, "species.csv": species, "observers.csv": observers,
                          "notes.txt": "hello"}, top="team-cfg-abc123/")
    bad = _template_zip({"species.csv": "color\r\nred\r\n", "spyhop-config.json": "{nope"})
    base, stop = _serve({"/good.zip": (200, "application/zip", good), "/bad.zip": (200, "application/zip", bad),
                         "/page": (200, "text/html", b"<!DOCTYPE html><html>sign in</html>"),
                         "/private": (403, "text/plain", b"no")})
    try:
        files, src = templates.fetch(base + "/good.zip")
        t = templates.read_template(files)
        assert not t["problems"] and t["ignored"] == ["notes.txt"]
        assert [m["notes"] for m in t["history"]] == ["Added test whale", "First version"]    # newest first
        assert t["history"][0]["changed"] == "species.csv" and t["display"] == {"marker_radius": "11"}
        plan = {r["file"]: r for r in templates.compare(cfg, t)}
        assert plan["species.csv"]["status"] == "changed" and plan["species.csv"]["in_template"] == 4   # with Other (0.40)
        assert plan["observers.csv"]["status"] == "changed"
        assert plan["Map display"]["status"] == "changed" and "marker_radius: 8 → 11" in plan["Map display"]["detail"]
        assert plan["Saved report: Gear (team)"]["status"] == "new" and plan["Saved report: Mine"]["status"] == "removed"

        backup = templates.save_backup(cfg)
        assert backup.parent == cfg.backups_dir and backup.name.startswith("spyhop-backup-") and backup.name.endswith(".spyhop-template.zip")
        with _zf.ZipFile(backup) as z:
            names = set(z.namelist())
            old_species = z.read("species.csv").decode()
            doc = _json.loads(z.read("spyhop-config.json"))
        assert {"species.csv", "shortcuts.csv", "spyhop-config.json", "waypoints.csv"} <= names
        assert not any(n.startswith(("reports/", "feeds/")) or n in ("display.csv", "spyhop-config.csv") for n in names)
        assert "mine.json" in doc["reports"] and doc["map_display"]["marker_radius"] == "8"
        assert "Backup" in doc["history"][-1]["notes"] and doc["includes"] == ["waypoints", "routes", "overlays"]

        changed = templates.apply(cfg, t)
        assert "species.csv" in changed and "Saved report: Mine" in changed and "Map display" in changed
        assert [s["name"] for s in cfg.lists["species"]] == ["North Atlantic right whale", "Humpback whale", "Spyhop test whale", "Other"]
        assert sorted(cfg.reports) == ["team_gear.json"]                     # replaced as a set
        assert cfg.display["marker_radius"] == "11" and cfg.display["label_size"] == "12"      # missing keys come back
        assert [e["notes"] for e in templates.local_history(cfg)] == ["First version", "Added test whale"]
        assert cfg.shortcuts                                    # tables not in the template are untouched
        assert all(r["status"] == "same" for r in templates.compare(cfg, templates.read_template(files)))

        # a computer with no saved reports: its templates leave reports alone, its backups remove them
        cfg2 = Config(tmp_path / "app2")
        cfg2.save_reports({})
        assert templates.read_template(templates.unzip(templates.make_zip(cfg2)))["reports"] is None
        empty = templates.read_template(templates.unzip(templates.make_zip(cfg2, "none", backup=True)))
        assert empty["reports"] == {}
        templates.apply(cfg2, t)
        assert "team_gear.json" in cfg2.reports
        assert "team_gear.json" in json.loads(cfg2.config_path.read_text())["reports"]
        templates.apply(cfg2, empty)
        assert not cfg2.reports

        # the backup is itself a template: using it puts things back
        restore = templates.read_template(templates.fetch(str(backup))[0])
        assert not restore["problems"]
        templates.apply(cfg, restore)
        assert (cur / "species.csv").read_text(encoding="utf-8-sig").replace("\r\n", "\n") == old_species.replace("\r\n", "\n").lstrip("﻿")
        assert sorted(cfg.reports) == ["mine.json"]
        assert cfg.display["marker_radius"] == "8"

        badt = templates.read_template(templates.fetch(base + "/bad.zip")[0])
        assert any("species.csv needs the column name" in p for p in badt["problems"])
        assert any("spyhop-config.json isn't valid JSON" in p for p in badt["problems"])
        before = (cur / "species.csv").read_text()
        with pytest.raises(templates.TemplateError):
            templates.apply(cfg, badt)
        assert (cur / "species.csv").read_text() == before              # nothing changed

        for path, words in (("/page", "web page"), ("/private", "refused"), ("/missing.zip", "404")):
            with pytest.raises(templates.TemplateError, match=words):
                templates.fetch(base + path)
        with pytest.raises(templates.TemplateError, match="doesn't look like"):
            templates.read_template({"readme.txt": b"hi"})

        # a template as a folder on disk (e.g. a USB stick), with an Excel-saved CSV
        d = tmp_path / "usb"
        d.mkdir()
        (d / "observers.csv").write_bytes("name,full_name\r\nJM,José Martínez\r\n".encode("cp1252"))
        p2 = templates.read_template(templates.fetch(str(d))[0])
        assert not p2["problems"] and "José" in p2["csv"]["observers.csv"] and p2["reports"] is None
        assert templates.compare(cfg, p2)[0]["file"] == "observers.csv"
        z = templates.make_zip(cfg, "made here")
        assert "made here" in templates.read_template(templates.unzip(z))["history"][0]["notes"]

        # a bad spyhop-config.json is a problem, not a crash
        bj = templates.read_template({"spyhop-config.json": b"{not json", "species.csv": species.encode()})
        assert any("spyhop-config.json isn't valid JSON" in p for p in bj["problems"])
        br = templates.read_template({"spyhop-config.json": _json.dumps({"reports": {"x.json": {"table": "boats"}}}).encode()})
        assert any("the saved report x.json" in p for p in br["problems"])
    finally:
        stop()


def test_templates_folder(tmp_path):
    import asyncio, zipfile as _zf
    from spyhop import templates
    from spyhop.server import App
    app = App(tmp_path)
    cfg = app.rec.cfg
    folder = tmp_path / "templates" / "saved"
    assert _run(app.templates_list(_Req()))["templates"] == []
    assert _run(app.templates_status(_Req()))["status"] == {"name": "", "saved": False, "changed": []}
    assert _run(app.templates_changes(_Req()))["files"] is None     # nothing to compare with yet
    with pytest.raises(ValueErrorMsg, match="your name"):
        asyncio.run(app.templates_save(_Req({"by": "", "notes": "x", "name": "a"})))

    # save a new template: <name>.spyhop-template.zip in templates/saved, with the change logged
    r = _run(app.templates_save(_Req({"by": "H. Johnson", "notes": "First version", "name": "2026-NEA-CCB"})))
    assert r["name"] == "2026-NEA-CCB.spyhop-template.zip" and (folder / r["name"]).is_file()
    with _zf.ZipFile(folder / r["name"]) as z:
        doc = json.loads(z.read("spyhop-config.json"))
    assert doc["history"][-1] == {**doc["history"][-1], "by": "H. Johnson", "notes": "First version", "changed": "all"}
    with pytest.raises(ValueErrorMsg, match="already a template"):
        asyncio.run(app.templates_save(_Req({"by": "H", "notes": "again", "name": "2026-NEA-CCB.zip"})))
    L = _run(app.templates_list(_Req()))
    assert [p["name"] for p in L["templates"]] == ["2026-NEA-CCB.spyhop-template.zip"] and L["templates"][0]["matches"]
    assert L["current"]["name"] == "2026-NEA-CCB.spyhop-template.zip" and L["current"]["how"] == "saved"
    assert L["backups_folder"] == str(tmp_path / "templates" / "backups")
    assert L["status"] == {"name": "2026-NEA-CCB.spyhop-template.zip", "saved": True, "changed": []}
    assert _run(app.templates_changes(_Req()))["files"] == []

    # change a list: the template now differs; updating it continues the template's own record
    cfg.save_list("observers", [{"name": "JM", "full_name": "J. M."}])
    L = _run(app.templates_list(_Req()))
    assert L["templates"][0]["differs"] == ["observers.csv"] and not L["templates"][0]["matches"]
    assert L["status"] == {"name": "2026-NEA-CCB.spyhop-template.zip", "saved": False, "changed": ["observers.csv"]}
    assert _run(app.templates_changes(_Req(query={"name": "2026-NEA-CCB.spyhop-template.zip"})))["files"] == ["observers.csv"]
    assert _run(app.templates_changes(_Req()))["files"] == ["observers.csv"]
    templates.save_local_history(cfg, [{"date": "2020-01-01", "by": "X", "changed": "all", "notes": "unrelated"}])
    _run(app.templates_save(_Req({"by": "H. Johnson", "notes": "New observer JM", "changed": "observers.csv",
                                  "name": "2026-NEA-CCB.spyhop-template.zip", "overwrite": True})))
    t = templates.read_template_file(cfg, "2026-NEA-CCB.spyhop-template.zip")
    assert [x["notes"] for x in t["history"]] == ["New observer JM", "First version"] and "JM" in t["csv"]["observers.csv"]
    with pytest.raises(ValueErrorMsg, match="no template called"):
        asyncio.run(app.templates_save(_Req({"by": "H", "notes": "x", "name": "nope.spyhop-template.zip", "overwrite": True})))

    # use a template from the folder: a backup goes to templates/backups, no copy is made
    _run(app.templates_save(_Req({"by": "H", "notes": "with JM", "name": "with-jm"})))
    cfg.save_list("observers", [{"name": "ZZ", "full_name": "Z. Z."}])
    chk = _run(app.templates_check(_Req({"template": "with-jm.spyhop-template.zip"})))
    assert chk["kind"] == "folder" and [f["file"] for f in chk["files"] if f["status"] != "same"] == ["observers.csv"]
    assert chk["history"][0]["notes"] == "with JM" and chk["info"]["min_spyhop"] == "0.28.0"
    res = _run(app.templates_use(_Req({"token": chk["token"], "backup": True})))
    assert res["changed"] == ["observers.csv"] and res["copy"] is None
    assert Path(res["backup"]).parent == tmp_path / "templates" / "backups" and res["backup"].endswith(".spyhop-template.zip")
    assert cfg.lists["observers"][0]["name"] == "JM"
    L = _run(app.templates_list(_Req()))
    assert L["current"] == {**L["current"], "name": "with-jm.spyhop-template.zip", "how": "loaded"}
    assert [b["name"] for b in L["backups"]] == [Path(res["backup"]).name]
    assert sorted(p["name"] for p in L["templates"]) == ["2026-NEA-CCB.spyhop-template.zip", "with-jm.spyhop-template.zip"]

    # restore the backup: ZZ again
    chk = _run(app.templates_check(_Req({"backup": Path(res["backup"]).name})))
    assert chk["kind"] == "backup"
    _run(app.templates_use(_Req({"token": chk["token"], "backup": False})))
    assert cfg.lists["observers"][0]["name"] == "ZZ"
    with pytest.raises(ValueErrorMsg, match="name of a"):
        asyncio.run(app.templates_check(_Req({"template": "../settings.json"})))

    # a template from elsewhere (a web address, or here a file outside the folder) is kept as a copy
    outside = tmp_path / "team pack.zip"
    outside.write_bytes((folder / "with-jm.spyhop-template.zip").read_bytes())
    chk = _run(app.templates_check(_Req({"url": str(outside)})))
    assert chk["kind"] == "file"
    res = _run(app.templates_use(_Req({"token": chk["token"], "backup": False})))
    assert res["copy"] == "team pack.spyhop-template.zip" and (folder / "team pack.spyhop-template.zip").is_file()
    assert _run(app.templates_list(_Req()))["current"]["name"] == "team pack.spyhop-template.zip"

    # download from the folder; names outside it refused
    resp = asyncio.run(app.templates_file(_Req(match={"name": "with-jm.spyhop-template.zip"})))
    assert resp.status == 200
    from aiohttp import web as _web
    with pytest.raises(_web.HTTPNotFound):
        asyncio.run(app.templates_file(_Req(match={"name": "../x.zip"})))
    assert templates.safe_template_name('a/b:c') == "a_b_c.spyhop-template.zip" and templates.safe_template_name("  ") == ""
    assert templates.safe_template_name("x.zip") == "x.spyhop-template.zip"
    assert templates.template_stem("t.spyhop-template.zip") == "t" and templates.template_stem("t.zip") == "t"
    assert templates._download_name("https://drive.google.com/uc?export=download&id=1",
                                    {"Content-Disposition": 'attachment; filename="2026-NEA-CCB-spyhop_config.zip"'}) == "2026-NEA-CCB-spyhop_config.zip"
    assert templates._download_name("https://api.github.com/repos/team/spyhop-config/zipball", {}) == "spyhop-config"


def test_reports_travel_in_templates(tmp_path):
    import json as _json, zipfile as _zf, io as _io
    from spyhop import templates, reports
    from spyhop.config import Config
    cfg = Config(tmp_path / "app")
    with _zf.ZipFile(_io.BytesIO(templates.make_zip(cfg))) as z:
        files = {n: z.read(n) for n in z.namelist()}
    doc = _json.loads(files["spyhop-config.json"])
    assert "right_whales.json" in doc["reports"]                 # the starting reports are in a template
    doc["reports"]["sea_state.json"] = {"name": "Rough", "table": "effort", "columns": ["time", "SeaState"],
                                        "rules": [{"column": "SeaState", "op": "gt", "value": "3"}]}
    del doc["reports"]["gear.json"]
    files["spyhop-config.json"] = _json.dumps(doc).encode()
    t = templates.read_template(files)
    assert not t["problems"]
    plan = {r["file"]: r["status"] for r in templates.compare(cfg, t)}
    assert plan["Saved report: Rough"] == "new" and plan["Saved report: Gear"] == "removed"
    templates.apply(cfg, t)
    assert sorted(f["name"] for f in reports.load(cfg)[0]) == ["Blue whales", "Dead birds", "Right whales", "Rough"]
    assert sorted(_json.loads(cfg.config_path.read_text())["reports"]) == ["blue_whales.json", "dead_birds.json",
                                                                         "right_whales.json", "sea_state.json"]
    # a template without reports leaves the saved reports alone
    no_reps = {k: v for k, v in files.items() if k != "spyhop-config.json"}
    assert templates.read_template(no_reps)["reports"] is None


def test_template_carries_settings_feeds_waypoints_routes_overlays(tmp_path):
    """Shared settings are replaced; feeds, waypoints, routes and overlays are only added; serial inputs and
    the data folder stay; feeds travel as addresses only; a minimum Spyhop version is checked; restoring the
    backup takes away what the template added."""
    import asyncio, zipfile as _zf
    from spyhop import templates, feeds, __version__
    from spyhop.server import App

    a, b = App(tmp_path / "a"), App(tmp_path / "b")
    ca, cb = a.rec.cfg, b.rec.cfg
    ca.save_settings({"timezone": "UTC", "effort_reminder_min": 20,
                      "nmea_sources": [{"type": "serial", "port": "COM4", "baud": 4800}, {"type": "udp", "port": 2000}],
                      "online_feeds": [{"id": "abc12345", "name": "SMAs", "url": "https://example.org/FeatureServer/3",
                                        "color": "#ff0000", "refresh_min": 60}]})
    feeds.save_cache(ca, "abc12345", [{"type": "Feature", "properties": {"big": "x" * 1000}, "geometry": None}])
    for n, lat in (("Buoy A", "41.5"), ("Harbor", "41.9")):
        a.rec.tables["marks"].add({"Name": n, "Lat": lat, "Lon": "-70.1", "Shape": "Circle", "Color": "red"})
    (ca.routes_dir / "Line 1.gpx").write_text('<?xml version="1.0"?><gpx><rte><rtept lat="41" lon="-70"/></rte></gpx>')
    (ca.overlays_dir / "zones.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (ca.overlays_dir / "Survey - old.geojson").write_text('{"type":"FeatureCollection","features":[]}')

    info = _run(a.templates_changes(_Req()))
    assert (info["waypoints"], info["routes"], info["overlays"]) == (2, 1, 1) and info["min_default"] == "0.28.0"
    with pytest.raises(ValueErrorMsg, match="can't be newer"):
        asyncio.run(a.templates_save(_Req({"by": "H", "notes": "x", "name": "t", "min_spyhop": "99.0.0"})))
    r = _run(a.templates_save(_Req({"by": "H", "notes": "Team setup", "name": "team", "include": ["waypoints", "routes", "overlays"],
                                    "online": {"ais": True, "radar_us": False, "feeds": ["https://example.org/FeatureServer/3"]}})))
    tf = ca.saved_dir / r["name"]
    with _zf.ZipFile(tf) as z:
        names = set(z.namelist())
        doc = json.loads(z.read("spyhop-config.json"))
    assert names == {"spyhop-config.json", "species.csv", "event_types.csv", "observers.csv", "behaviors.csv", "shortcuts.csv",
                     "visibility.csv", "weather.csv", "reticles.csv", "effort.csv",
                     "waypoints.csv", "routes/Line 1.gpx", "overlays/zones.geojson"}      # no feed data, no display.csv
    assert doc["min_spyhop"] == "0.28.0" and doc["includes"] == ["waypoints", "routes", "overlays"] and doc["made_with"] == __version__
    # 0.41: serial inputs are in templates too, named; which are in use stays with each computer
    assert doc["nmea_inputs"] == [{"type": "serial", "port": "COM4", "baud": 4800, "name": "Serial COM4 @ 4800"},
                                  {"type": "udp", "port": 2000, "name": "UDP port 2000"}] and "data_dir" not in doc["settings"]
    assert doc["settings"]["timezone"] == "UTC" and doc["online_overlays"]["ais"] is True
    assert doc["map_feeds"] == [{"id": "abc12345", "name": "SMAs", "url": "https://example.org/FeatureServer/3",
                                 "color": "#ff0000", "refresh_min": 60}]
    assert set(doc) >= {"history", "map_display", "reports"}
    assert _run(a.templates_changes(_Req(query={"name": r["name"]})))["includes"] == ["waypoints", "routes", "overlays"]
    _run(a.templates_save(_Req({"by": "H", "notes": "lists only", "name": "lists"})))
    with _zf.ZipFile(ca.saved_dir / "lists.spyhop-template.zip") as z:
        assert "waypoints.csv" not in z.namelist() and not any(n.startswith("routes/") for n in z.namelist())

    # computer B: its own serial port, a waypoint called Harbor somewhere else, its own route of the same name
    cb.save_settings({"nmea_sources": [{"type": "serial", "port": "/dev/ttyUSB0"}, {"type": "udp", "port": 10110}]})
    b.rec.tables["marks"].add({"Name": "Harbor", "Lat": "42.0", "Lon": "-70.5"})
    (cb.routes_dir / "Line 1.gpx").write_text('<?xml version="1.0"?><gpx><rte/></gpx>')
    chk = _run(b.templates_check(_Req({"url": str(tf)})))
    st = {f["file"]: f for f in chk["files"]}
    assert st["waypoints.csv"]["status"] == "new" and st["waypoints.csv"]["add"] == 1 and "kept" in st["waypoints.csv"]["detail"]
    assert st["routes/Line 1.gpx"]["status"] == "kept" and st["overlays/zones.geojson"]["status"] == "new"
    assert st["Map feed: SMAs"]["status"] == "new" and "UTC" in st[templates.SETTINGS_LABEL]["detail"]
    assert chk["info"]["min_spyhop"] == "0.28.0" and chk["online"]["ais"] is True and chk["online"]["feed_names"] == ["SMAs"]
    res = _run(b.templates_use(_Req({"token": chk["token"], "backup": True})))
    assert res["added"] == {"waypoints": 1, "routes": 0, "overlays": 1, "feeds": 1}
    assert cb.settings["timezone"] == "UTC" and cb.settings["effort_reminder_min"] == 20
    pick = lambda L: [(x["name"], x["enabled"], x["role"] == "primary") for x in L]  # noqa: E731
    # none of B's inputs has those names, so the first is put in use, as the primary
    assert pick(cb.settings["nmea_sources"]) == [("Serial COM4 @ 4800", True, True), ("UDP port 2000", False, False)]
    assert cb.settings["online_feeds"][0]["name"] == "SMAs" and not feeds.cache_path(cb, "abc12345").exists()
    assert cb.settings["online_display"]["stamp"] and cb.settings["online_display"]["ais"] is True
    assert {(m["Name"], m["Lat"]) for m in b.rec.tables["marks"].rows} == {("Harbor", "42.0"), ("Buoy A", "41.5")}
    assert "<rte/>" in (cb.routes_dir / "Line 1.gpx").read_text() and (cb.overlays_dir / "zones.geojson").is_file()
    chk2 = _run(b.templates_check(_Req({"template": r["name"]})))
    assert all(f["status"] in ("same", "kept") for f in chk2["files"])
    # restoring the backup takes away what the template added, and the settings go back
    bk = Path(res["backup"]).name
    chk3 = _run(b.templates_check(_Req({"backup": bk})))
    removed = {f["file"] for f in chk3["files"] if f["status"] == "removed"}
    assert {"waypoints.csv", "overlays/zones.geojson", "Map feed: SMAs"} <= removed
    _run(b.templates_use(_Req({"token": chk3["token"], "backup": False})))
    assert cb.settings["timezone"] == "local" and cb.settings["online_feeds"] == []
    assert {m["Name"] for m in b.rec.tables["marks"].rows} == {"Harbor"} and not (cb.overlays_dir / "zones.geojson").exists()
    assert [x["name"] for x in cb.settings["nmea_sources"]] == ["Serial /dev/ttyUSB0 @ 4800", "UDP port 10110"]

    # a template that needs a newer Spyhop can't be used
    with _zf.ZipFile(tf) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files["spyhop-config.json"] = json.dumps({**doc, "min_spyhop": "9.0.0"}).encode()
    t = templates.read_template(files)
    assert any("needs Spyhop 9.0.0" in x and __version__ in x for x in t["problems"])
    with pytest.raises(templates.TemplateError):
        templates.apply(cb, t)
    assert templates.clean_min_version("") == "0.28.0"
    with pytest.raises(templates.TemplateError):
        templates.clean_min_version("0.27.0")

    # the inputs are part of the setup in use: in templates/current/spyhop-config.json (without this
    # computer's choices), and in spyhop-local.json with them
    cur = json.loads(cb.config_path.read_text())
    loc = json.loads(cb.local_path.read_text())
    assert cur["nmea_inputs"] == [{"type": "serial", "port": "/dev/ttyUSB0", "name": "Serial /dev/ttyUSB0 @ 4800"},
                                  {"type": "udp", "port": 10110, "name": "UDP port 10110"}]
    assert loc["settings"]["nmea_sources"][0]["role"] == "primary"
    assert "timezone" not in loc["settings"] and "online_feeds" not in loc["settings"]


def test_prefetch_estimate_counts_without_listing(tmp_path):
    """0.27: the download estimate counts tiles arithmetically: a huge area at high zooms is instant
    (listing every tile held up the server for minutes), and a download that big is refused at once."""
    import asyncio, time as _t
    from spyhop.config import Config
    from spyhop.tiles import TileService
    cfg = Config(tmp_path)
    cfg.tile_sources = [{"name": "Esri test", "url": "https://example.org/{z}/{y}/{x}", "kind": "raster", "max_zoom": "19"}]
    ts = TileService(cfg)
    bounds = [30, -80, 50, -60]

    async def go():
        t0 = _t.monotonic()
        plan = await ts.plan_prefetch(0, bounds, 0, 18)
        assert _t.monotonic() - t0 < 0.5 and plan["total"] > 10_000_000 and plan["jobs"] == []
        small = await ts.plan_prefetch(0, bounds, 0, 4, jobs_limit=50000)
        assert small["total"] == len(small["jobs"]) == sum(ts._count_in(bounds, z) for z in range(5))
        assert small["jobs"][0][0] == "raster"
        t0 = _t.monotonic()
        with pytest.raises(ValueError, match="limit"):
            await ts.start_prefetch(0, bounds, 0, 18, name="Too big")
        assert _t.monotonic() - t0 < 0.5
    asyncio.run(go())


def test_file_replay_reads_spyhop_logs_and_plain_nmea(tmp_path):
    """FILE input: a Spyhop raw log (time stamp, input, sentence) is paced by its time stamps;
    a plain NMEA file by the RMC times; a quoted path (Windows' Copy as path) still works."""
    import asyncio, time as _t
    from spyhop.sources import SourceManager, Simulator, clean_path
    from spyhop.nmea import NmeaDecoder, with_checksum
    sim = Simulator(lat=42.5, lon=-69.0)
    stamped, plain = [], []
    for k in range(6):
        for ln in sim.step(1.0):
            body = ln.split("*")[0][1:].split(",")
            if body[0][2:] in ("RMC", "GGA"):
                body[1] = f"1200{k:02d}.00"          # a log 6 s long
            ln = with_checksum(",".join(body))
            stamped.append(f"2026-07-01T12:00:{k:02d}.000Z\tGPS 1\t{ln}")
            plain.append(ln)
    (tmp_path / "a.nmea").write_text("\n".join(stamped) + "\n")
    (tmp_path / "b.nmea").write_text("\r\n".join(plain) + "\r\n")
    assert clean_path(f' "{tmp_path / "a.nmea"}" ') == str(tmp_path / "a.nmea")

    async def run(name, speed):
        dec = NmeaDecoder()
        sm = SourceManager(dec)
        t0 = _t.time()
        await sm.start([{"type": "file", "path": f'"{tmp_path / name}"', "speed": speed, "loop": False}])
        await asyncio.wait_for(asyncio.gather(*sm.tasks), 10)
        took = _t.time() - t0
        st = sm.status[0]
        await sm.stop()
        return dec, st, took

    dec, st, took = asyncio.run(run("a.nmea", 10))
    assert st["state"] == "finished" and st["at"] == len(stamped)
    assert dec.state.lat and abs(dec.state.lat - 42.5) < 0.01
    assert 0.4 < took < 3            # 5 s of log at ×10
    dec, st, took = asyncio.run(run("b.nmea", 10))
    assert st["state"] == "finished" and dec.state.lat and abs(dec.state.lat - 42.5) < 0.01
    assert 0.4 < took < 3


def test_diagnostics_bundle_lists_folders_without_data(tmp_path):
    import zipfile, json as _json
    from spyhop import diag
    from spyhop.config import Config
    cfg = Config(tmp_path / "spy")
    (cfg.routes_dir / "Leg A.gpx").write_text("<gpx/>")
    (cfg.data_dir / "SecretSurvey").mkdir()
    (cfg.data_dir / "SecretSurvey" / "SecretSurvey_sightings.csv").write_text("a,b\n1,2\n")
    (cfg.saved_dir / "Ship.spyhop-template.zip").write_bytes(b"PK")
    cfg.save_settings({"online_feeds": [{"url": "https://x.org/f.json?key=SECRET"}],
                       "last_meta": {"chief_scientist": "Dr Secret"}})
    z = diag.make_bundle(cfg, {"survey": "none"}, tmp_path / "out")
    zz = zipfile.ZipFile(z)
    names = zz.namelist()
    assert {"folders.txt", "spyhop-local.json", "current/spyhop-config.json", "current/behaviors.csv"} <= set(names)
    assert "current/observers.csv" not in names
    f = zz.read("folders.txt").decode()
    assert "Leg A.gpx" in f and "Ship.spyhop-template.zip" in f and "routes/" in f and "current/" in f
    assert "SecretSurvey" not in f and "survey folders: 1, 1 files" in f
    s = zz.read("current/spyhop-config.json").decode()
    assert "SECRET" not in s and "https://x.org/f.json?…" in s
    assert "Dr Secret" not in zz.read("spyhop-local.json").decode()
    assert not any("SecretSurvey" in n for n in names)


def _fake_program(tmp_path):
    prog = tmp_path / "prog"
    (prog / "spyhop").mkdir(parents=True)
    (prog / "spyhop" / "__init__.py").write_text('__version__ = "0.1"\n')
    (prog / "pyproject.toml").write_text("")
    (prog / ".venv" / "bin").mkdir(parents=True)
    (prog / ".venv" / "bin" / "python").write_text("")
    return prog


def _wait_helper(log_path, secs=20):
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < secs:
        if Path(log_path).exists() and "done" in Path(log_path).read_text():
            return Path(log_path).read_text()
        _t.sleep(0.2)
    raise AssertionError("helper didn't finish: " + (Path(log_path).read_text() if Path(log_path).exists() else "no log"))


def test_uninstall_plan_and_run(tmp_path, monkeypatch):
    import subprocess as _sp, sys as _sys
    from spyhop import uninstall, updater, shortcut
    from spyhop.config import Config
    prog = _fake_program(tmp_path)
    monkeypatch.setattr(updater, "PROGRAM_DIR", prog)
    monkeypatch.setattr(shortcut, "ROOT", prog)
    cfg = Config(tmp_path / "spy")
    (cfg.data_dir / "S1_sightings.csv").write_text("x\n")
    # nothing is deleted beyond the program unless ticked; a chosen data folder is never deleted
    p = uninstall.plan(cfg, "uninstall")
    assert not p["problems"] and [d["path"] for d in p["delete"]] == [str(prog)]
    assert {k["path"] for k in p["keep"]} == {str(cfg.root), str(cfg.data_dir)}
    # survey data needs DELETE typed
    with pytest.raises(uninstall.UninstallError):
        uninstall.start(cfg, "uninstall", True, True, confirm="")
    # a git checkout is never deleted
    (prog / ".git").mkdir()
    assert uninstall.plan(cfg, "uninstall")["problems"]
    (prog / ".git").rmdir()
    # run it: settings deleted, the default data folder inside Spyhop's folder kept
    dead = _sp.Popen([_sys.executable, "-c", "pass"]); dead.wait()
    monkeypatch.setattr(uninstall.os, "getpid", lambda: dead.pid)
    r = uninstall.start(cfg, "uninstall", delete_settings=True, delete_data=False)
    _wait_helper(r["helper_log"])
    assert not prog.exists()
    assert (cfg.data_dir / "S1_sightings.csv").exists()
    assert not (cfg.root / "templates").exists() and not (cfg.root / "routes").exists()


def test_uninstall_refuses_unsafe_folders(tmp_path, monkeypatch):
    from spyhop import uninstall, updater
    from spyhop.config import Config
    cfg = Config(tmp_path / "spy")
    monkeypatch.setattr(updater, "PROGRAM_DIR", Path.home())
    assert uninstall.plan(cfg, "uninstall")["problems"]
    prog = _fake_program(tmp_path)
    monkeypatch.setattr(updater, "PROGRAM_DIR", prog)
    cfg2 = Config(prog / "inside")                     # Spyhop's folder inside the program folder
    assert any("inside the program folder" in x for x in uninstall.plan(cfg2, "uninstall")["problems"])


def test_reinstall_replaces_program_keeps_data(tmp_path, monkeypatch):
    import io as _io, zipfile as _zf, subprocess as _sp, sys as _sys
    from spyhop import uninstall, updater, shortcut
    from spyhop.config import Config
    prog = _fake_program(tmp_path)
    (prog / "old_only.txt").write_text("stale")
    monkeypatch.setattr(updater, "PROGRAM_DIR", prog)
    monkeypatch.setattr(shortcut, "ROOT", prog)
    cfg = Config(tmp_path / "spy")
    (cfg.data_dir / "S1_sightings.csv").write_text("x\n")
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("org-spyhop-abc/spyhop/__init__.py", '__version__ = "9.9.9"\n')
        z.writestr("org-spyhop-abc/pyproject.toml", "")
        z.writestr("org-spyhop-abc/start-spyhop.sh", "")
    monkeypatch.setattr(updater, "_get", lambda url, accept=None: buf.getvalue())
    dead = _sp.Popen([_sys.executable, "-c", "pass"]); dead.wait()
    monkeypatch.setattr(uninstall.os, "getpid", lambda: dead.pid)
    r = uninstall.start(cfg, "reinstall", info={"zip": "x", "latest": "9.9.9"}, launch=False)
    _wait_helper(r["helper_log"])
    assert '9.9.9' in (prog / "spyhop" / "__init__.py").read_text()
    assert not (prog / "old_only.txt").exists() and not (prog / ".venv").exists()
    assert (cfg.data_dir / "S1_sightings.csv").exists() and (cfg.current_dir / "species.csv").exists()
    assert not (cfg.root / "updates").exists()                # no copy of the old program is kept
    assert not list(tmp_path.glob(".spyhop-reinstall-*"))


def test_old_layout_moved_once(tmp_path):
    """0.28: a 0.27 Spyhop folder (lists at the top, settings/, reports/, templates in the data folder) is moved
    into templates/current, templates/saved, templates/backups and spyhop-local.json, and the old files go."""
    from spyhop.config import Config
    root = tmp_path / "Spyhop"
    (root / "settings").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "data" / "templates" / "backups").mkdir(parents=True)
    (root / "species.csv").write_text("name,color,species_code\nTest whale,red,TEWH\n")
    (root / "shortcuts.csv").write_text("combo,action,prefill\nMod+Shift+T,add:sightings,Species=Test whale\n")
    (root / "display.csv").write_text("key,value\nmarker_radius,11\n")
    (root / "settings" / "settings.json").write_text(json.dumps({
        "timezone": "UTC", "follow_vessel": False, "last_meta": {"organization": "NEAq"},
        "nmea_sources": [{"type": "serial", "port": "COM4"}, {"type": "udp", "port": 2000}],
        "online_feeds": [{"id": "abc12345", "name": "SMAs", "url": "https://example.org/x", "color": "#ff0000", "refresh_min": 60}],
        "template_current": {"name": "Team.spyhop-template.zip", "how": "saved"}}))
    (root / "settings" / "template_history.json").write_text(json.dumps([{"date": "2026-11-01", "by": "H", "changed": "all", "notes": "v1"}]))
    (root / "settings" / "current_survey.txt").write_text(json.dumps({"prefix": "S1", "data_dir": str(root / "data")}))
    for marker in ("list_rows_added.txt", "reports_started.txt"):
        (root / "settings" / marker).write_text("x")
    (root / "reports" / "mine.json").write_text(json.dumps({"name": "Mine", "table": "events", "columns": ["time"]}))
    (root / "data" / "templates" / "Team.spyhop-template.zip").write_bytes(b"PK")
    (root / "data" / "templates" / "backups" / "spyhop-backup-1.spyhop-template.zip").write_bytes(b"PK")
    (root / "data" / "S1_effort.csv").write_text("x\n")

    cfg = Config(root)
    assert any("new layout" in n for n in cfg.notices)
    assert sorted(p.name for p in root.iterdir()) == ["charts", "data", "overlays", "routes", "spyhop-local.json", "templates"]
    assert [r["name"] for r in cfg.lists["species"]] == ["Test whale", "Other"] and cfg.shortcuts[0]["combo"] == "Mod+Shift+T"
    assert cfg.display["marker_radius"] == "11" and sorted(cfg.reports) == ["mine.json"]
    assert cfg.settings["timezone"] == "UTC" and cfg.settings["follow_vessel"] is False
    assert [(x["name"], x["enabled"], x["role"] == "primary") for x in cfg.settings["nmea_sources"]] == [
        ("Serial COM4 @ 4800", True, True), ("UDP port 2000", True, False)]
    assert cfg.settings["online_feeds"][0]["name"] == "SMAs" and cfg.history[0]["notes"] == "v1"
    assert cfg.current_survey()["prefix"] == "S1"
    assert (cfg.saved_dir / "Team.spyhop-template.zip").is_file() and (cfg.backups_dir / "spyhop-backup-1.spyhop-template.zip").is_file()
    assert sorted(p.name for p in (root / "data").iterdir()) == ["S1"] and (root / "data" / "S1" / "S1_effort.csv").is_file()   # 0.36: a folder per survey
    # a second start changes nothing
    again = Config(root)
    assert not again.notices and again.settings["timezone"] == "UTC"


def test_survey_records_template_and_version(tmp_path):
    """0.28: a survey's details silently record the Spyhop version and the template the setup came from,
    and whether the setup still matched it."""
    import csv as _csv
    from spyhop import templates, __version__
    rec = Recorder(tmp_path)
    cfg = rec.cfg

    def meta(prefix):
        with open(cfg.data_dir / prefix / f"{prefix}_metadata.csv", newline="", encoding="utf-8-sig") as fh:
            return {r["field"]: r["value"] for r in _csv.DictReader(fh)}
    rec.start_survey("A")
    m = meta("A")
    assert m["spyhop_version_created"] == __version__ and m["template_created"] == ""
    assert m["template_created_matches"] == "no — not saved as a template"
    rec.end_survey()
    p = templates.save_template(cfg, "Team", "H", "all", "v1")
    cfg.save_settings({"template_current": {"name": p.name, "how": "saved"}})
    rec.start_survey("B")
    assert (meta("B")["template_created"], meta("B")["template_created_matches"]) == ("Team.spyhop-template.zip", "yes")
    rec.set_meta({"organization": "NEAq"})                         # editing the details keeps what was recorded
    assert meta("B")["template_created"] == "Team.spyhop-template.zip" and meta("B")["organization"] == "NEAq"
    rec.end_survey()
    cfg.save_list("observers", [{"name": "JM", "full_name": "J. M."}])
    rec.start_survey("C")
    assert meta("C")["template_created_matches"] == "no — changed since: observers.csv"
    # waypoints don't count as a change of setup
    from spyhop.config import DEFAULT_LISTS
    rec.tables["marks"].add({"Name": "W", "Lat": "41", "Lon": "-70"})
    cfg.save_list("observers", [dict(zip(DEFAULT_LISTS["observers"][0], r)) for r in DEFAULT_LISTS["observers"][1]])
    assert templates.current_status(cfg) == {"name": "Team.spyhop-template.zip", "saved": True, "changed": []}


def test_reticle_distances():
    """0.29: Lerczak & Hobbs (1998) distances from angles below the horizon/horizontal."""
    import math
    from spyhop import reticle as rt
    b = {"reticle_method": "binoculars", "reticle_deg_per_division": 0.573}
    h_ft = 10 / rt.FT                                                   # 10 m eye height
    assert abs(rt.distance_m(0, h_ft, b) - 11290) < 60                  # 0 reticles: the horizon, ~3.57 √h km
    near = rt.distance_m(10, h_ft, b)
    assert abs(near - 10 / math.tan(rt.dip(10) + math.radians(5.73))) < 1   # close in, the flat formula agrees
    d = rt.distance_m(1.3, 33, b)
    assert abs(rt.reading_for(d, 33, b) - 1.3) < 1e-6                   # map pick → reading, and back
    inc = {"reticle_method": "inclinometer"}
    assert abs(rt.distance_m(30, 750, inc) - 750 * rt.FT / math.tan(math.radians(30))) < 1
    # 0.38: evenly spaced marks, counted from the horizontal: mark 2 at 22.5° apart = 45° down
    marks = {"reticle_method": "marks", "reticle_deg_per_division": 22.5}
    assert abs(rt.distance_m(2, 1000, marks) - 1000 * rt.FT) < 1
    assert abs(rt.reading_for(rt.distance_m(1.5, 1000, marks), 1000, marks) - 1.5) < 1e-6
    with pytest.raises(rt.ReticleError, match="degrees between marks"):
        rt.distance_m(3, 1000, {"reticle_method": "marks"})
    with pytest.raises(rt.ReticleError, match="above the horizon"):
        rt.distance_m(-1, 33, b)


def test_reticle_sighting_altitude_and_platforms(tmp_path):
    """0.29: Unit = reticle places the animal from the bearing, the reading and the altitude; Alt is filled
    from the survey's Platform altitude; a Stationary platform records no trackline in the background."""
    from spyhop import reticle as rt, geo
    rec = Recorder(tmp_path)
    rec.decoder.feed(with_checksum("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))
    rec.cfg.save_settings({"distance_unit": "reticles-binos", "tracking_interval": 1})      # 0.37: the reticles list
    rec.start_survey("R", meta={"platform_type": "Shipboard", "platform_altitude_ft": "33"})
    r = rec.new_row("sightings", {"Bearing": "90", "BrgRef": "T", "Distance": "1"}, lat=41.0, lon=-70.0)["row"]
    row = next(x for x in rec.tables["sightings"].rows if x["RowID"] == r["RowID"])
    assert row["Altitude"] == "33" and row["DistUnit"] == "reticles-binos"
    got = geo.haversine_m(41.0, -70.0, float(row["SigLat"]), float(row["SigLon"]))
    assert abs(got - rt.distance_m(1, 33, {"reticle_method": "binoculars", "reticle_deg_per_division": 0.573})) < 2
    rec.edit("sightings", r["RowID"], {"Altitude": "66"})                      # a higher eye: further away
    row = next(x for x in rec.tables["sightings"].rows if x["RowID"] == r["RowID"])
    assert geo.haversine_m(41.0, -70.0, float(row["SigLat"]), float(row["SigLon"])) > got * 1.2
    with pytest.raises(ValueErrorMsg, match="Platform altitude must be a number"):
        rec.set_meta({"platform_altitude_ft": "high"})
    with pytest.raises(ValueErrorMsg, match="Shipboard, Aerial, Stationary or Other"):
        rec.set_meta({"platform_type": "Vessel"})
    rec.end_survey()
    # a stationary platform: no background track points
    rec.start_survey("S", meta={"platform_type": "Stationary", "platform_altitude_ft": "60"})
    n = len(rec.track.points)
    rec._last_track_t = 0
    rec.tick_tracker()
    assert len(rec.track.points) == n
    rec.decoder.feed(with_checksum("GPRMC,120001,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))
    rec._last_track_t = 0
    rec.tick_tracker()
    assert len(rec.track.points) == n                                         # still nothing
    rec.set_meta({"platform_type": "Other"})                                  # a moving platform again
    rec._last_track_t = 0
    rec.tick_tracker()
    assert len(rec.track.points) == n + 1


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_uninstall_reinstall_git_checkout(tmp_path, monkeypatch):
    """0.29: a git checkout can be reinstalled (reset to GitHub's branch, .venv removed) or uninstalled only
    when nothing would be lost; otherwise the plan says why."""
    import subprocess as _sp, sys as _sys
    from spyhop import uninstall, updater, shortcut
    from spyhop.config import Config
    g = lambda *a, cwd=None: _sp.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)  # noqa: E731
    remote = tmp_path / "remote.git"
    g("init", "--bare", "-b", "main", str(remote))
    prog = _fake_program(tmp_path)
    (prog / ".gitignore").write_text(".venv/\n")
    g("init", "-b", "main", cwd=prog)
    g("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=prog)
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "v1", cwd=prog)
    g("remote", "add", "origin", str(remote), cwd=prog)
    g("push", "-u", "origin", "main", cwd=prog)
    monkeypatch.setattr(updater, "PROGRAM_DIR", prog)
    monkeypatch.setattr(shortcut, "ROOT", prog)
    cfg = Config(tmp_path / "spy")
    assert uninstall.plan(cfg, "reinstall")["problems"] == []
    (prog / "spyhop" / "__init__.py").write_text('__version__ = "local edit"\n')
    p = uninstall.plan(cfg, "reinstall")
    assert p["problems"] and "uncommitted changes" in p["problems"][0]
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-am", "local", cwd=prog)
    assert "not pushed" in uninstall.plan(cfg, "uninstall")["problems"][0]
    g("reset", "--hard", "HEAD~1", cwd=prog)
    # reinstall: reset to the remote's branch, the Python set-up removed, the folder and .git kept
    dead = _sp.Popen([_sys.executable, "-c", "pass"]); dead.wait()
    monkeypatch.setattr(uninstall.os, "getpid", lambda: dead.pid)
    (prog / "stray.txt").write_text("x")
    assert "uncommitted" in uninstall.plan(cfg, "reinstall")["problems"][0]      # untracked files count too
    (prog / "stray.txt").unlink()
    r = uninstall.start(cfg, "reinstall", launch=False)
    log = _wait_helper(r["helper_log"])
    assert "git reset" in log and not (prog / ".venv").exists() and (prog / ".git").is_dir()
    assert (prog / "spyhop" / "__init__.py").read_text() == '__version__ = "0.1"\n'


def test_templates_left_in_data_folder_are_tidied(tmp_path):
    """0.29: a templates folder left in the data folder (e.g. kept by a .DS_Store) is emptied into
    templates/saved and backups, and removed; files Spyhop doesn't know are left, with a notice."""
    from spyhop.config import Config
    Config(tmp_path / "S")                                         # a 0.28 folder
    d = tmp_path / "S" / "data" / "templates"
    (d / "backups").mkdir(parents=True)
    (d / ".DS_Store").write_bytes(b"x")
    (d / "Old.spyhop-template.zip").write_bytes(b"PK1")
    (d / "backups" / "b1.spyhop-template.zip").write_bytes(b"PK2")
    cfg = Config(tmp_path / "S")
    assert not d.exists()
    assert (cfg.saved_dir / "Old.spyhop-template.zip").read_bytes() == b"PK1"
    assert (cfg.backups_dir / "b1.spyhop-template.zip").is_file()
    d.mkdir()
    (d / "notes.txt").write_text("mine")
    cfg = Config(tmp_path / "S")
    assert (d / "notes.txt").exists() and any("doesn't know" in n for n in cfg.notices)


def test_resights(tmp_path):
    """0.30: Add resight copies the species, numbers, confidences and FieldID and links to the first
    sighting; ResightOf is checked; QC, the merged CSV and the grouping helpers know about resights."""
    from spyhop import resights, qc
    rec = Recorder(tmp_path)
    rec.decoder.feed(with_checksum("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))
    rec.start_survey("RS", meta={"platform_type": "Shipboard"})
    a = rec.new_row("sightings", {"Species": "Humpback whale", "Count": "2", "Calves": "0", "NumConf": "Probable",
                                  "IDrel": "Definite", "FieldID": "HW-7", "Notes": "first"})["row"]
    b = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1"})["row"]
    r1 = rec.add_resight(a["RowID"])["row"]
    assert r1["ResightOf"] == a["SightNo"] and r1["Species"] == "Humpback whale" and r1["Count"] == "2"
    assert r1["NumConf"] == "Probable" and r1["IDrel"] == "Definite" and r1["FieldID"] == "HW-7" and r1["Notes"] == ""
    rec.edit("sightings", r1["RowID"], {"Count": "3", "Calves": "1"})
    r2 = rec.add_resight(r1["RowID"])["row"]                    # a resight of a resight → the first sighting
    assert r2["ResightOf"] == a["SightNo"] and r2["Count"] == "3" and r2["Calves"] == "1"
    # typed by hand: checked, and chains flattened
    with pytest.raises(ValueErrorMsg, match="no sighting 99"):
        rec.edit("sightings", b["RowID"], {"ResightOf": "99"})
    with pytest.raises(ValueErrorMsg, match="itself"):
        rec.edit("sightings", b["RowID"], {"ResightOf": b["SightNo"]})
    w = rec.edit("sightings", b["RowID"], {"ResightOf": r1["SightNo"]})
    row_b = next(x for x in rec.tables["sightings"].rows if x["RowID"] == b["RowID"])
    assert row_b["ResightOf"] == a["SightNo"] and "first sighting" in w["warnings"][0]
    with pytest.raises(ValueErrorMsg, match="resight of this sighting"):
        rec.edit("sightings", a["RowID"], {"ResightOf": r1["SightNo"]})
    rows = rec.tables["sightings"].rows
    gs = resights.groups(rows)
    assert len(gs) == 1 and gs[0][0]["RowID"] == a["RowID"] and len(gs[0]) == 4
    # QC: b is a fin whale linked to a humpback → warning; a dangling link → warning
    issues = qc.run_qc(rec)["issues"]
    assert any(i["check"] == "Resights linked" and "Species" in i["message"] for i in issues)
    rec.edit("sightings", b["RowID"], {"ResightOf": ""})
    rec.delete("sightings", a["RowID"])
    issues = qc.run_qc(rec)["issues"]
    assert sum(1 for i in issues if i["check"] == "Resights linked" and "no such sighting" in i["message"]) == 2
    head, merged = rec.merged_rows()
    assert "ResightOf" in head and any(m.get("ResightOf") == a["SightNo"] for m in merged)
    with pytest.raises(ValueErrorMsg, match="no longer exists"):
        rec.add_resight(a["RowID"])


def test_effort_kinds_segments_and_insert(rec):
    """0.31: LINE/FOLLOW/PHOTO count as on effort; Toggle effort returns to the last kind; effort segments
    number status changes; Insert row averages or copies the time and position, with a note."""
    from spyhop import qc
    from spyhop.recorder import parse_time
    from datetime import datetime, timedelta, timezone
    e = rec.tables["effort"]
    a = rec.new_row("effort", {"Effort": "TRANSECT"})["row"]
    rec.edit("effort", a["RowID"], {"DateTime": "2026-11-04T12:10:00+00:00"})
    rec.new_row("effort", {"Effort": "TRANSECT", "SeaState": "3"})
    rec.toggle_effort()                                           # TRANSECT → OFF
    assert e.rows[-1]["Effort"] == "OFF"
    rec.toggle_effort()                                           # OFF → TRANSECT (the last kind), not ON
    assert e.rows[-1]["Effort"] == "TRANSECT"
    rec.new_row("effort", {"Effort": "FOLLOW"})
    assert [r["Segment"] for r in e.rows] == ["1", "2", "2", "3", "4", "5"]
    assert rec._track_state(datetime.now(timezone.utc) + timedelta(seconds=5)) == "FOLLOW"
    with pytest.raises(ValueErrorMsg, match="filled in by Spyhop"):
        rec.edit("effort", e.rows[1]["RowID"], {"Segment": "9"})
    rec.delete("effort", e.rows[3]["RowID"])                      # OFF gone: TRANSECT ×3 merge
    assert [r["Segment"] for r in e.rows] == ["1", "2", "2", "2", "3"]
    rec.undo("effort")
    assert [r["Segment"] for r in e.rows] == ["1", "2", "2", "3", "4", "5"]
    # Insert row: average of the rows either side, with a note; copies; refusals
    s1 = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1"})["row"]
    s2 = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1"})["row"]
    rec.edit("sightings", s1["RowID"], {"DateTime": "2026-11-04T12:00:00+00:00", "Lat": "41.9", "Lon": "-70.3"})
    rec.edit("sightings", s2["RowID"], {"DateTime": "2026-11-04T12:10:00+00:00", "Lat": "42.1", "Lon": "-70.5"})
    mid = rec.insert_row("sightings", s1["RowID"], "average")["row"]
    S = rec.tables["sightings"].rows
    assert [r["RowID"] for r in S].index(mid["RowID"]) == 1
    assert parse_time(mid["DateTime"]) == parse_time("2026-11-04T12:05:00+00:00")
    assert abs(float(mid["Lat"]) - 42.0) < 1e-6 and abs(float(mid["Lon"]) + 70.4) < 1e-6
    assert mid["Notes"].startswith("Inserted: time and position averaged from the rows before and after")
    nxt = rec.insert_row("sightings", s2["RowID"], "previous", where="before")["row"]
    assert parse_time(nxt["DateTime"]) == parse_time(mid["DateTime"]) and "copied from the row before" in nxt["Notes"]
    with pytest.raises(ValueErrorMsg, match="no row after"):
        rec.insert_row("sightings", s2["RowID"], "next")
    with pytest.raises(ValueErrorMsg, match="before the Start row"):
        rec.insert_row("effort", e.rows[0]["RowID"], "next", where="before")
    rec.end_survey()
    with pytest.raises(ValueErrorMsg, match="after the End row"):
        rec.insert_row("effort", e.rows[-1]["RowID"], "previous")
    ins = rec.insert_row("effort", e.rows[-2]["RowID"], "previous")["row"]       # fixing an ended survey is allowed
    assert e.rows[-2]["RowID"] == ins["RowID"] and e.rows[-1]["Effort"] == "End"
    head, merged = rec.merged_rows()
    assert "Segment" in head


def test_survey_notes_and_column_layout(rec):
    rec.set_meta({"survey_notes": "Calm morning.\nFog after 14:00", "organization": "NEAq"})
    assert rec.read_meta()["survey_notes"] == "Calm morning.\nFog after 14:00"
    assert "survey_notes" not in rec.cfg.settings["last_meta"] and rec.cfg.settings["last_meta"]["organization"] == "NEAq"
    from spyhop.server import clean_column_layout
    got = clean_column_layout({"sightings": {"order": ["Species", "Nope", "Species", "DateTime"], "widths": {"Notes": "2000", "Count": 10, "X": 50}},
                               "bogus": {"order": ["a"]}})
    assert got == {"sightings": {"order": ["Species", "DateTime"], "widths": {"Notes": 800, "Count": 30}}}
    rec.cfg.save_settings({"column_layout": got})
    import json
    assert "column_layout" in rec.cfg.local_path.read_text() and "column_layout" not in rec.cfg.config_path.read_text()


def test_clock_bearings_and_insert_at_time(rec):
    """0.32: Ref C clock bearings (each hour 30° from the heading); Insert row at a typed time takes the
    position from the trackline; First surfacing in the default behaviors; fade in minutes."""
    from spyhop import geo, qc
    from spyhop.config import DEFAULT_DISPLAY, DEFAULT_LISTS
    from datetime import timedelta
    assert geo.to_true_bearing(3, "C", 45.0, None) == 135.0 and geo.to_true_bearing(12, "C", 45.0, None) == 45.0
    assert geo.to_true_bearing(13, "C", 45.0, None) is None
    s = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1", "Bearing": "3", "BrgRef": "C",
                                  "Distance": "1", "DistUnit": "nm"})["row"]
    assert s["VesHdg"] == "45"
    want = geo.destination(float(s["Lat"]), float(s["Lon"]), 135.0, 1852.0)
    assert abs(float(s["SigLat"]) - want[0]) < 1e-5 and abs(float(s["SigLon"]) - want[1]) < 1e-5
    w = rec.edit("sightings", s["RowID"], {"Bearing": "20"})["warnings"]
    assert any("clock bearing" in x for x in w)
    assert any(i["check"] == "Plausible bearings and distances" and "clock bearing" in i["message"] for i in qc.run_qc(rec)["issues"])
    # a map-picked position back to the nearest hour
    row = {"Lat": s["Lat"], "Lon": s["Lon"], "SigLat": f"{want[0]:.6f}", "SigLon": f"{want[1]:.6f}", "BrgRef": "C", "VesHdg": "45", "DistUnit": "nm"}
    rec._fill_bearing_distance(row)
    assert row["Bearing"] == "3" and row["BrgRef"] == "C"
    # insert at a typed time: the trackline position then
    from spyhop.recorder import parse_time
    t0 = parse_time(s["DateTime"])
    rec.track.points[:] = [{"DateTime": (t0 - timedelta(minutes=10)).isoformat(), "Lat": "41.0", "Lon": "-70.0", "SOG": "", "COG": "", "Effort": "ON"},
                           {"DateTime": (t0 + timedelta(minutes=10)).isoformat(), "Lat": "41.2", "Lon": "-70.4", "SOG": "", "COG": "", "Effort": "ON"}]
    hhmm = (t0 - timedelta(minutes=5)).astimezone(rec.tz()).strftime("%H:%M:%S")
    r = rec.insert_row("sightings", s["RowID"], "time", time_text=hhmm)["row"]
    assert abs(float(r["Lat"]) - 41.05) < 1e-6 and abs(float(r["Lon"]) + 70.1) < 1e-6
    assert rec.tables["sightings"].rows[0]["RowID"] == r["RowID"]           # in time order, before the sighting
    assert r["Notes"].startswith("Inserted: time typed in") and "trackline" in r["Notes"]
    with pytest.raises(ValueErrorMsg, match="Type the time"):
        rec.insert_row("sightings", s["RowID"], "time", time_text="")
    assert any(b[0] == "First surfacing" for b in DEFAULT_LISTS["behaviors"][1])
    assert DEFAULT_DISPLAY["fade_min"] == "30" and "fade_hours" not in DEFAULT_DISPLAY


def test_pane_layout_is_kept_on_this_computer(tmp_path):
    """0.33: the three panes' sizes and states are a local setting, cleaned by the server."""
    from spyhop.server import clean_pane_layout
    from spyhop.config import Config, DEFAULT_SETTINGS
    assert "view" not in DEFAULT_SETTINGS and "split_ratio" not in DEFAULT_SETTINGS
    got = clean_pane_layout({"fx": 0.05, "fy": "0.7", "min": {"map": 1, "data": 0, "x": True}, "max": "bogus"})
    assert got == {"fx": 0.15, "fy": 0.7, "min": {"map": True, "util": False, "data": False}, "max": None}
    assert clean_pane_layout({"max": "data"})["max"] == "data" and clean_pane_layout(None) == {"min": {"map": False, "util": False, "data": False}, "max": None}
    cfg = Config(tmp_path)
    cfg.save_settings({"pane_layout": got})
    assert "pane_layout" in cfg.local_path.read_text() and "pane_layout" not in cfg.config_path.read_text()


def test_resight_swim_speed_check_and_default_lists(tmp_path):
    """0.34: the Error check warns when animals would have swum faster than 30 kn between one
    sighting of them and the next; vessels, debris and fishing gear are sightings, moorings events."""
    from datetime import datetime, timedelta
    from spyhop import qc
    from spyhop.config import DEFAULT_LISTS
    rec = Recorder(tmp_path)
    rec.decoder.feed(with_checksum("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))
    rec.start_survey("SP", meta={"platform_type": "Shipboard"})
    a = rec.new_row("sightings", {"Species": "Fin whale", "Count": "1", "SigLat": "41.9", "SigLon": "-70.3"})["row"]
    b = rec.add_resight(a["RowID"])["row"]
    c = rec.add_resight(a["RowID"])["row"]
    t0 = datetime.fromisoformat(a["DateTime"])
    rec.edit("sightings", b["RowID"], {"DateTime": (t0 + timedelta(minutes=10)).isoformat(), "SigLat": "41.91", "SigLon": "-70.3"})  # 0.6 nm in 10 min
    rec.edit("sightings", c["RowID"], {"DateTime": (t0 + timedelta(minutes=12)).isoformat(), "SigLat": "42.0", "SigLon": "-70.3"})   # 5.4 nm in 2 min
    fast = [i for i in qc.run_qc(rec)["issues"] if i["check"] == "Resight swim speeds"]
    assert len(fast) == 1 and fast[0]["row_id"] == c["RowID"] and fast[0]["level"] == "warning" and fast[0]["column"] == "SigLat"
    assert "162 kn" in fast[0]["message"] and f"sighting {b['SightNo']}" in fast[0]["message"]
    species = {r[0]: r[2] for r in DEFAULT_LISTS["species"][1]}
    events = {r[0] for r in DEFAULT_LISTS["event_types"][1]}
    assert species["Vessel sighted"] == "VESL" and species["Fishing gear - reported"] == "GRPT" and "Marine debris" in species
    assert {"Mooring deployed", "Mooring recovered"} <= events
    assert not events & {"Vessel sighted", "Marine debris", "Gear Reported", "Photo-ID session start", "Fishing gear sighted", "Acoustic recorder deployed"}


def test_smooth_vessel_is_a_setting_of_this_computer(tmp_path):
    """0.35: Smooth vessel movement (drawing only) is on by default and kept in spyhop-local.json."""
    from spyhop.config import Config, DEFAULT_SETTINGS, SHARED_SETTINGS
    assert DEFAULT_SETTINGS["smooth_vessel"] is True and "smooth_vessel" not in SHARED_SETTINGS
    cfg = Config(tmp_path)
    cfg.save_settings({"smooth_vessel": False})
    assert '"smooth_vessel": false' in cfg.local_path.read_text() and "smooth_vessel" not in cfg.config_path.read_text()
    assert Config(tmp_path).settings["smooth_vessel"] is False


def _sim_fix(rec):
    rec.decoder.feed(with_checksum("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,045.0,041126,14.5,W"))


def test_one_folder_per_survey_with_its_template(tmp_path):
    """0.36: each survey has its own folder with its tables, details, the template copy, raw logs and
    exports; reserved names are refused; Delete Survey Data removes the folder."""
    rec = Recorder(tmp_path)
    _sim_fix(rec)
    rec.cfg.save_settings({"nmea_log_enabled": True})
    rec.start_survey("Leg 1", meta={"platform_type": "Shipboard"})
    d = rec.cfg.data_dir / "Leg 1"
    rec.new_row("sightings", {"Species": "Fin whale", "Count": "1"})
    _sim_fix(rec)
    for t in rec.tables.values():
        t.save()
    names = {p.name for p in d.iterdir()}
    assert {"Leg 1_sightings.csv", "Leg 1_effort.csv", "Leg 1_metadata.csv", "Leg 1_template.zip", "Leg 1_track.csv"} <= names
    assert not any(p.suffix == ".csv" for p in rec.cfg.data_dir.iterdir() if p.is_file() and p.name != "waypoints.csv")
    assert rec.raw_log_status()["folder"] == str(d / "nmea_logs") and any((d / "nmea_logs").iterdir())
    assert rec.cfg.export_dir == d / "exports"
    st = rec.template_status()
    assert st["saved"] and st["differs"] == []
    with zipfile.ZipFile(d / "Leg 1_template.zip") as z:
        assert "spyhop-config.json" in z.namelist() and "species.csv" in z.namelist()
    assert [s["prefix"] for s in rec.list_surveys()] == ["Leg 1"] and rec.list_surveys()[0]["has_template"]
    # the survey keeps its template when the computer's lists change later
    rec.end_survey()
    rows = rec.cfg.lists["species"] + [{"name": "Spyhop test whale", "color": "pink", "species_code": "SPTW"}]
    rec.cfg.save_list("species", rows)
    assert "species.csv" in rec.template_status()["differs"]
    with pytest.raises(ValueErrorMsg, match="Spyhop's own folders"):
        rec.start_survey("exports")
    rec.clear_survey()
    assert not d.exists() and rec.list_surveys() == []
    rec.close_survey()
    assert rec.cfg.export_dir == rec.cfg.data_dir / "exports"


def test_old_survey_files_moved_into_folders(tmp_path):
    """0.36: survey files at the top of the data folder (and their logs and exports) move into a folder each, once."""
    data = tmp_path / "data"
    (data / "nmea_logs").mkdir(parents=True)
    (data / "exports").mkdir()
    hdr = "RowID,DateTime,Effort\n"
    for f in ("A_sightings.csv", "A_metadata.csv", "A_B_track.csv", "A_effort.csv.bak-20261101"):
        (data / f).write_text("x\n")
    (data / "A_effort.csv").write_text(hdr + "r1,2026-11-01T10:00:00-05:00,Start\n")
    (data / "A_B_effort.csv").write_text(hdr + "r2,2026-11-02T10:00:00-05:00,Start\n")
    (data / "waypoints.csv").write_text("RowID,Name\n")
    for f in ("A_nmea_20261101-1000.nmea", "A_B_nmea_20261102-1000.nmea", "no-survey_nmea_1.nmea"):
        (data / "nmea_logs" / f).write_text("$GPRMC\n")
    for f in ("A_export_20261101.zip", "A_B_summary_20261102.html", "plan_1.gpx"):
        (data / "exports" / f).write_text("x")
    (data / "Orphan_metadata.csv").write_text("x")              # no tables: not a survey, left alone
    rec = Recorder(tmp_path)
    assert sorted((data / "A").iterdir()) == sorted(data / "A" / n for n in
                                                    ("A_sightings.csv", "A_metadata.csv", "A_effort.csv", "A_effort.csv.bak-20261101", "nmea_logs", "exports"))
    assert (data / "A" / "nmea_logs" / "A_nmea_20261101-1000.nmea").is_file() and (data / "A" / "exports" / "A_export_20261101.zip").is_file()
    assert (data / "A_B" / "A_B_effort.csv").is_file() and (data / "A_B" / "nmea_logs" / "A_B_nmea_20261102-1000.nmea").is_file()
    assert (data / "A_B" / "exports" / "A_B_summary_20261102.html").is_file()
    assert [p.name for p in (data / "nmea_logs").iterdir()] == ["no-survey_nmea_1.nmea"]
    assert [p.name for p in (data / "exports").iterdir()] == ["plan_1.gpx"]
    assert (data / "waypoints.csv").is_file() and (data / "Orphan_metadata.csv").is_file()
    assert sorted(s["prefix"] for s in rec.list_surveys()) == ["A", "A_B"]
    assert any("folder of its own" in n for n in rec.notices)
    Recorder(tmp_path)                                           # nothing left to move the second time
    rec.open_survey("A")
    assert rec.tables["effort"].rows[0]["Effort"] == "Start" and not rec.template_status()["saved"]


def test_survey_package_save_and_open(tmp_path):
    """0.36: <survey>.spyhop-survey.zip holds the survey's files (RowIDs kept) and its template copy, with
    checksums; another computer opens it as it was, under a new name if the name is taken."""
    rec = Recorder(tmp_path / "a")
    _sim_fix(rec)
    rec.start_survey("Leg 2", meta={"platform_type": "Shipboard"})
    s = rec.new_row("sightings", {"Species": "Humpback whale", "Count": "2"})["row"]
    rec.cfg.save_settings({"nmea_log_enabled": True})
    rec.set_raw_logging()
    _sim_fix(rec)
    rec.save_package()                                          # makes exports/; it isn't packaged
    p = rec.save_package()
    assert p.name == "Leg 2.spyhop-survey.zip" and p.parent == rec.cfg.survey_dir("Leg 2") / "exports"
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        man = json.loads(z.read("Leg 2/spyhop-survey.json"))
    assert "Leg 2/Leg 2_sightings.csv" in names and "Leg 2/Leg 2_template.zip" in names
    assert not any("/exports/" in n or "/nmea_logs/" in n for n in names)
    assert man["survey"] == "Leg 2" and man["status"] == "active" and man["has_template"] and len(man["files"]["Leg 2_sightings.csv"]["sha256"]) == 64
    with zipfile.ZipFile(rec.save_package(logs=True)) as z:
        assert any("/nmea_logs/" in n for n in z.namelist())
    data = p.read_bytes()
    # another computer
    other = Recorder(tmp_path / "b")
    got = other.open_package(data)
    assert got["opened"] == "Leg 2" and other.survey["prefix"] == "Leg 2" and other.tracking_on() == other.survey_active()
    assert [r["RowID"] for r in other.tables["sightings"].rows] == [s["RowID"]]
    assert got["template"]["saved"] and got["template"]["differs"] == []
    # the name is taken: nothing overwritten, a new name suggested; with it the files are renamed
    again = other.open_package(data)
    assert again["exists"] and again["suggest"] == "Leg 2 (2)"
    got2 = other.open_package(data, "Leg 2 (2)")
    d2 = other.cfg.survey_dir("Leg 2 (2)")
    assert got2["opened"] == "Leg 2 (2)" and (d2 / "Leg 2 (2)_sightings.csv").is_file() and (d2 / "Leg 2 (2)_template.zip").is_file()
    assert other.tables["sightings"].rows[0]["Species"] == "Humpback whale"
    assert sorted(x["prefix"] for x in other.list_surveys()) == ["Leg 2", "Leg 2 (2)"]

    def repack(edit):
        src = zipfile.ZipFile(io.BytesIO(data))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                b = src.read(n)
                z.writestr(n, edit(n, b))
        return buf.getvalue()
    with pytest.raises(ValueErrorMsg, match="checksum"):
        other.open_package(repack(lambda n, b: b + b"x" if n.endswith("_sightings.csv") else b), "X")
    with pytest.raises(ValueErrorMsg, match="needs Spyhop 9.0.0"):
        other.open_package(repack(lambda n, b: json.dumps({**json.loads(b), "min_spyhop": "9.0.0"}).encode() if n.endswith(".json") else b), "X")
    with pytest.raises(ValueErrorMsg, match="unsafe"):
        other.open_package(repack(lambda n, b: json.dumps({**json.loads(b), "files": {"../evil.csv": {"sha256": ""}}}).encode() if n.endswith(".json") else b), "X")
    with pytest.raises(ValueErrorMsg, match="no spyhop-survey.json"):
        other.open_package(zipfile.ZipFile(p).read("Leg 2/Leg 2_template.zip"), "X")
    with pytest.raises(ValueErrorMsg, match="isn't a zip"):
        other.open_package(b"hello", "X")
    assert not other.cfg.survey_dir("X").exists() and not any(q.name.startswith(".") for q in other.cfg.data_dir.iterdir())


def test_reticles_visibility_weather_lists_and_glare(tmp_path):
    """0.37: reticles, visibility and weather are drop-down lists in the template; each reticle is a Unit
    reticles-<name>; glare start/end/ref in Effort are checked; no UNK observer by default."""
    from spyhop import reticle as rt, geo, qc
    from spyhop.config import DEFAULT_LISTS
    rec = Recorder(tmp_path)
    cfg = rec.cfg
    assert {"visibility", "weather", "reticles"} <= set(cfg.lists) and (cfg.current_dir / "reticles.csv").is_file()
    assert "UNK" not in [r[0] for r in DEFAULT_LISTS["observers"][1]]
    assert rec.list_values("distunit") == ["m", "km", "nm", "mi", "yd", "reticles-binos", "reticles-big-eyes", "reticles-incl", "reticles-Other"]
    assert "reticle_method" not in cfg.settings
    # checked when saved
    for bad, msg in [({"name": "big eyes", "method": "binoculars", "deg_per_division": "0.1"}, "no spaces"),
                     ({"name": "x", "method": "laser"}, "how readings are taken"),
                     ({"name": "x", "method": "binoculars", "deg_per_division": ""}, "degrees per reticle division"),
                     ({"name": "x", "method": "marks", "deg_per_division": ""}, "degrees between marks"),
                     ({"name": "x", "method": "marks", "deg_per_division": "50"}, "at most 45")]:
        with pytest.raises(ValueError, match=msg):
            cfg.save_list("reticles", [bad])
    cfg.save_list("reticles", [{"name": "big-eyes", "method": "Binoculars", "magnification": "25", "deg_per_division": "0.0771"},
                               {"name": "strut", "method": "marks", "magnification": "7", "deg_per_division": "10"},
                               {"name": "incl", "method": "inclinometer", "magnification": "7"}])
    by = {r["name"]: r for r in cfg.lists["reticles"]}
    assert by["strut"]["deg_per_division"] == "10" and by["strut"]["magnification"] == "" and by["incl"]["magnification"] == ""
    assert "marks" not in cfg.list_header("reticles")
    assert by["big-eyes"]["method"] == "binoculars"
    _sim_fix(rec)
    rec.start_survey("R", meta={"platform_type": "Aerial", "platform_altitude_ft": "750"})
    def place(unit, dist):
        r = rec.new_row("sightings", {"Bearing": "90", "BrgRef": "T", "Distance": dist, "DistUnit": unit}, lat=41.0, lon=-70.0)
        row = next(x for x in rec.tables["sightings"].rows if x["RowID"] == r["row"]["RowID"])
        return row, r.get("warnings", [])
    row, _ = place("reticles-strut", "2")
    got = geo.haversine_m(41.0, -70.0, float(row["SigLat"]), float(row["SigLon"]))
    assert abs(got - rt.distance_m(2, 750, rt.settings_for(by["strut"]))) < 2 and 600 < got < 700   # 20° down from 750 ft
    row, _ = place("reticles-incl", "20")
    assert abs(geo.haversine_m(41.0, -70.0, float(row["SigLat"]), float(row["SigLon"])) - got) < 2   # the same angle, read directly
    row, _ = place("reticles-strut", "1")                        # 10° down: further than mark 2
    assert geo.haversine_m(41.0, -70.0, float(row["SigLat"]), float(row["SigLon"])) > got * 1.9
    with pytest.raises(ValueErrorMsg, match="choose one of"):
        place("reticles-nope", "1")
    # glare
    e = rec.new_row("effort", {"Effort": "ON", "Glare": "Moderate", "GlareStart": "100", "GlareEnd": "140", "GlareRef": "T"})["row"]
    assert rec.list_values("visibility")[0] == "<0.5 nm" and rec.list_values("weather")[0] == "Clear"
    rec.new_row("effort", {"Effort": "ON", "GlareStart": "2", "GlareEnd": "", "GlareRef": "C"})     # GlareEnd would be copied forward
    rec.new_row("effort", {"Effort": "ON", "GlareStart": "13", "GlareEnd": "3", "GlareRef": "C"})
    issues = [i for i in qc.run_qc(rec)["issues"] if i["check"] == "Glare bearings"]
    msgs = " | ".join(i["message"] for i in issues)
    assert "Glare is Moderate: give Gstart and Gend" in msgs and "Gstart 13 is outside 1–12" in msgs
    assert not any(i["row_id"] == e["RowID"] for i in issues)
    # 0.45: Glare None → Gstart / Gend NA; other glare → bearings (NA refused); Gref defaults to M
    n = rec.new_row("effort", {"Effort": "ON", "Glare": "None", "GlareStart": "", "GlareEnd": ""})["row"]
    assert (n["GlareStart"], n["GlareEnd"]) == ("NA", "NA")
    with pytest.raises(ValueErrorMsg, match="set Glare first"):
        rec.edit("effort", n["RowID"], {"GlareStart": "90"})
    n = rec.edit("effort", n["RowID"], {"Glare": "Slight"})["row"]
    assert (n["GlareStart"], n["GlareEnd"]) == ("", "")
    with pytest.raises(ValueErrorMsg, match="NA only when Glare is None"):
        rec.edit("effort", n["RowID"], {"GlareStart": "NA"})
    assert schema.column("effort", "GlareRef")["default"] == "M"
    head, merged = rec.merged_rows()
    assert {"GlareStart", "GlareEnd", "GlareRef"} <= set(head)


def test_data_settings_are_locked_during_a_survey(tmp_path):
    """0.37: during an active survey the lists (reticles, visibility and weather too), magnetic variation and
    the tracking settings can't change, by Settings, by reading the files again, or by using a template."""
    import asyncio
    from spyhop.server import App
    from spyhop import templates
    app = App(tmp_path)
    cfg = app.rec.cfg
    _run(app.templates_save(_Req({"by": "HJ", "notes": "first", "name": "Team"})))
    cfg.save_list("weather", [{"name": "Sunny"}, {"name": "Murky"}])            # differs from the saved template now
    other_shortcuts = (cfg.current_dir / "shortcuts.csv").read_text()
    _sim_fix(app.rec)
    app.rec.start_survey("L", meta={"platform_type": "Shipboard"})
    for list_name in ("weather", "reticles", "visibility"):
        with pytest.raises(ValueErrorMsg, match="survey is under way"):
            asyncio.run(app.save_list(_Req({"list": list_name, "rows": [{"name": "x", "method": "inclinometer"}]})))
    with pytest.raises(ValueErrorMsg, match="Magnetic variation can't be changed"):
        asyncio.run(app.settings(_Req({"updates": {"mag_variation": "-14"}})))
    with pytest.raises(ValueErrorMsg, match="Track point every"):
        asyncio.run(app.settings(_Req({"updates": {"tracking_interval": 99}})))
    _run(app.settings(_Req({"updates": {"latlon_format": "DD", "tracking_interval": cfg.settings["tracking_interval"]}})))  # display: fine
    # reading the files again puts a hand-edited locked list back, but takes the shortcuts
    (cfg.current_dir / "weather.csv").write_text("name\nHail\n")
    (cfg.current_dir / "shortcuts.csv").write_text(other_shortcuts.replace("Mod+Shift+K", "Mod+Shift+J"))
    r = _run(app.reload_config(_Req()))
    assert r["kept"] == ["weather.csv"] and [x["name"] for x in cfg.lists["weather"]] == ["Sunny", "Murky", "Other"]
    assert "Sunny" in (cfg.current_dir / "weather.csv").read_text()
    assert any(s["combo"] == "Mod+Shift+J" for s in cfg.shortcuts)
    # 0.40: a template used during a survey changes only the preferences: the locked lists stay
    chk = _run(app.templates_check(_Req({"template": "Team.spyhop-template.zip"})))
    r = _run(app.templates_use(_Req({"token": chk["token"]})))
    assert r["data_kept"] == ["weather.csv"] and [x["name"] for x in cfg.lists["weather"]] == ["Sunny", "Murky", "Other"]
    assert not any(s["combo"] == "Mod+Shift+J" for s in cfg.shortcuts)                 # the template's shortcuts
    app.rec.end_survey()
    _run(app.templates_use(_Req({"token": _run(app.templates_check(_Req({"template": "Team.spyhop-template.zip"})))["token"]})))
    assert [x["name"] for x in cfg.lists["weather"]][0] == "Clear"
    app.rec.start_survey("M", meta={"platform_type": "Shipboard"})
    cfg.save_shortcuts([{"combo": "Alt+9", "action": "undo", "prefill": ""}])           # an interface part
    chk = _run(app.templates_check(_Req({"template": "Team.spyhop-template.zip"})))
    _run(app.templates_use(_Req({"token": chk["token"]})))
    assert not any(s["combo"] == "Alt+9" for s in cfg.shortcuts) and any(s["combo"] == "Mod+Shift+K" for s in cfg.shortcuts)


def test_calves_na_reports_without_resights_and_undo_keys(tmp_path):
    """0.38: Calves takes NA; reports read only the first sighting of each group (no resights);
    undo / redo are Mod+Z / Mod+Shift+Z by default."""
    from spyhop import qc, reports
    from spyhop.config import DEFAULT_SHORTCUTS
    rec = Recorder(tmp_path)
    _sim_fix(rec)
    rec.start_survey("N", meta={"platform_type": "Shipboard"})
    g = rec.new_row("sightings", {"Species": "Fishing gear - reported", "Count": "1", "Calves": "na"})["row"]
    assert next(r for r in rec.tables["sightings"].rows if r["RowID"] == g["RowID"])["Calves"] == "NA"
    with pytest.raises(ValueErrorMsg, match=r"whole number \(or NA\)"):
        rec.new_row("sightings", {"Species": "Fin whale", "Count": "1", "Calves": "some"})
    with pytest.raises(ValueErrorMsg, match="whole number"):
        rec.new_row("sightings", {"Species": "Fin whale", "Count": "NA"})              # only Calves takes NA
    issues = [i for i in qc.run_qc(rec)["issues"] if i["row_id"] == g["RowID"] and i["column"] == "Calves"]
    assert issues == []
    # reports: resights are left out
    a = rec.new_row("sightings", {"Species": "North Atlantic right whale", "Count": "2", "Calves": "1"})["row"]
    rec.add_resight(a["RowID"])
    rec.add_resight(a["RowID"])
    saved, _ = reports.load(rec.cfg)
    rw = reports.run(rec, {f["name"]: f for f in saved}["Right whales"])
    assert rw["count"] == 1 and rw["total"] == 2 and rw["row_ids"] == [a["RowID"]] and rw["totals"][2] == "2"
    assert {c["code"]: c["n"] for c in reports.counts(rec, "sightings")}["RIWH"] == 1
    keys = {r[1]: r[0] for r in DEFAULT_SHORTCUTS[1]}
    assert keys["undo"] == "Mod+Z" and keys["redo"] == "Mod+Shift+Z"


def test_effort_list_status_definition_color(tmp_path):
    from datetime import datetime, timedelta, timezone
    """0.39: Effort values come from the effort list; status decides on effort; Start/End/ERROR required."""
    from spyhop import schema, qc
    from spyhop.config import LOCKED_LISTS
    rec = Recorder(tmp_path)
    _sim_fix(rec)
    cfg = rec.cfg
    assert [r["name"] for r in cfg.lists["effort"]] == ["Start", "ON", "TRANSECT", "DIRECTED", "PHOTO-ID", "FOLLOW", "OFF", "Other", "End", "ERROR"]
    assert schema.ON_EFFORT == ("ON", "TRANSECT", "DIRECTED", "PHOTO-ID", "FOLLOW") and "effort" in LOCKED_LISTS
    with pytest.raises(ValueError, match="must include End, ERROR"):
        cfg.save_list("effort", [{"name": "Start", "status": "off"}, {"name": "ON", "status": "on"}])
    with pytest.raises(ValueError, match="Status must be on or off"):
        cfg.save_list("effort", [*cfg.lists["effort"], {"name": "X", "status": "maybe"}])
    rows = [dict(r) for r in cfg.lists["effort"] if r["name"] != "FOLLOW"]
    rows.insert(1, {"name": "AERIAL", "status": "on", "definition": "Aerial leg.", "color": "#123456"})
    rows[0]["status"] = "on"                                      # Start is always off effort
    cfg.save_list("effort", rows)
    assert cfg.lists["effort"][0]["status"] == "off" and "AERIAL" in schema.ON_EFFORT and "FOLLOW" not in schema.EFFORT_NAMES
    rec.start_survey("E", meta={"platform_type": "Shipboard"})
    rec.new_row("effort", {"Effort": "aerial"})                  # matched case-insensitively
    assert rec.tables["effort"].rows[-1]["Effort"] == "AERIAL"
    with pytest.raises(ValueErrorMsg, match="choose one of"):
        rec.new_row("effort", {"Effort": "LINE"})
    rec.toggle_effort()
    assert rec.tables["effort"].rows[-1]["Effort"] == "OFF"
    rec.toggle_effort()
    assert rec.tables["effort"].rows[-1]["Effort"] == "AERIAL"    # back as it was last on
    assert schema.is_on(rec._track_state(datetime.now(timezone.utc) + timedelta(seconds=5)))
    rep = qc.run_qc(rec)
    assert not any(i["check"] == "Values from the lists" and i["column"] == "Effort" for i in rep["issues"])
    cfg.lists["effort"] = []
    schema.set_effort_list(None)                                  # back to the defaults for the other tests
    assert schema.ON_EFFORT == schema.DEFAULT_ON_EFFORT


def test_template_parts_colors_and_other(tmp_path):
    """0.40: a template's data part waits during a survey, its preferences don't; colors may change during a
    survey; every list has Other, flagged by the Error check."""
    import asyncio
    from spyhop.server import App
    from spyhop import templates, qc
    from spyhop.config import DEFAULT_LISTS
    app = App(tmp_path)
    cfg, rec = app.rec.cfg, app.rec
    assert all(any(r[0] == "Other" for r in rows) for _, rows in DEFAULT_LISTS.values())
    cfg.save_list("weather", [{"name": "Sunny"}])                         # Other comes back at the end
    assert [x["name"] for x in cfg.lists["weather"]] == ["Sunny", "Other"]
    _run(app.templates_save(_Req({"by": "HJ", "notes": "first", "name": "Team"})))
    cfg.save_list("weather", [{"name": "Sunny"}, {"name": "Fog"}, {"name": "other"}])
    cfg.save_shortcuts([{"combo": "Alt+9", "action": "undo", "prefill": ""}])
    _run(app.settings(_Req({"updates": {"bearing_reference": "M", "distance_unit": "km"}})))
    _sim_fix(rec)
    rec.start_survey("P", meta={"platform_type": "Shipboard"})
    t = templates.read_template_file(cfg, "Team.spyhop-template.zip")
    plan = {r["file"]: r for r in templates.compare(cfg, t)}
    assert plan["weather.csv"]["part"] == "data" and plan["shortcuts.csv"]["part"] == "prefs"
    assert plan[templates.SETTINGS_LABEL]["status"] == "changed" and plan[templates.SETTINGS_LABEL]["part"] == "prefs"
    assert templates.data_differs(cfg, t) == ["weather.csv"]
    # colors only: allowed during a survey; anything else isn't
    rows = [dict(r) for r in cfg.lists["species"]]
    rows[0]["color"] = "#010203"
    _run(app.save_list(_Req({"list": "species", "rows": rows})))
    assert cfg.lists["species"][0]["color"] == "#010203"
    rows[0]["species_code"] = "ZZZZ"
    with pytest.raises(ValueErrorMsg, match="only the colors"):
        asyncio.run(app.save_list(_Req({"list": "species", "rows": rows})))
    assert rec.template_status()["differs"] == []                         # colors don't count
    # using the template now takes the preferences only
    r = _run(app.templates_use(_Req({"token": _run(app.templates_check(_Req({"template": "Team.spyhop-template.zip"})))["token"]})))
    assert r["data_kept"] == ["weather.csv"] and [x["name"] for x in cfg.lists["weather"]] == ["Sunny", "Fog", "Other"]
    assert not any(s["combo"] == "Alt+9" for s in cfg.shortcuts) and cfg.settings["distance_unit"] != "km"
    # Other is a placeholder the Error check lists
    rec.new_row("effort", {"Effort": "ON", "Weather": "Other", "Port": "Other", "Starboard": "Other"})
    rec.new_row("sightings", {"Species": "Other", "Count": "1", "Bearing": "10", "BrgRef": "T", "Distance": "3", "DistUnit": "reticles-Other"})
    issues = [i for i in qc.run_qc(rec)["issues"] if i["check"] == "Other placeholders"]
    assert {i["column"] for i in issues} >= {"Weather", "Port", "Starboard", "Species", "DistUnit"}
    assert not any(i["check"] == "Observers in one position at a time" and "Other" in i["message"] for i in qc.run_qc(rec)["issues"])


def test_reports_are_data_and_wait_for_the_end(tmp_path):
    """0.40: saved reports are in the data part; no report can be run, saved or deleted during a survey."""
    import asyncio
    from spyhop.server import App
    from spyhop import templates, reports
    app = App(tmp_path)
    cfg, rec = app.rec.cfg, app.rec
    _run(app.templates_save(_Req({"by": "HJ", "notes": "first", "name": "Team"})))
    spec = {"name": "Mine", "table": "sightings", "columns": ["Species"]}
    reports.save(cfg, spec)
    _sim_fix(rec)
    rec.start_survey("R", meta={"platform_type": "Shipboard"})
    for call, body in ((app.report_run, {"spec": spec}), (app.report_save, {"spec": spec}),
                       (app.report_delete, {"file": "mine.json"}), (app.reports_batch, {"files": ["mine.json"], "formats": ["csv"]})):
        with pytest.raises(ValueErrorMsg, match="during a survey"):
            asyncio.run(call(_Req(body)))
    t = templates.read_template_file(cfg, "Team.spyhop-template.zip")
    plan = templates.compare(cfg, t)
    assert all(r["part"] == "data" for r in plan if r["file"].startswith("Saved report: "))
    assert "Saved report: Mine" in templates.data_differs(cfg, t, plan)
    r = _run(app.templates_use(_Req({"token": _run(app.templates_check(_Req({"template": "Team.spyhop-template.zip"})))["token"]})))
    assert "mine.json" in cfg.reports and "Saved report: Mine" in r["data_kept"]          # kept until the end
    snap = cfg.locked_snapshot()
    cfg.save_reports({})                                                            # a hand edit
    assert "saved reports" in cfg.restore_locked(snap) and "mine.json" in cfg.reports
    rec.end_survey()
    assert _run(app.report_run(_Req({"spec": spec})))["result"] is not None


def test_named_inputs_primary_secondary_and_nmea_csv(rec, tmp_path):
    """0.41: named inputs; the primary gives the position, secondaries keep their own; failover;
    <survey>_nmea.csv has every input's readings with lat/lon; _instruments.csv is renamed."""
    import time as _t
    from spyhop.nmea import with_checksum as w
    from spyhop.config import clean_inputs, merge_inputs
    from spyhop.layout import rename_instrument_files
    d = rec.decoder
    d.primary, d.failover = "Tablet GPS", False
    d.priority = {"Tablet GPS": 0, "External GPS": 1}
    d.feed(w("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,90.0,111126,,"), "Tablet GPS")
    d.feed(w("GPRMC,120000,A,4200.000,N,07000.000,W,5.0,180.0,111126,,"), "External GPS")
    d.feed(w("SDDPT,12.5,0.5,"), "External GPS")
    assert abs(d.state.lat - 41.9) < 1e-6 and d.state.source == "Tablet GPS" and d.state.sog == 10.0
    assert d.others["External GPS"].lat == 42.0
    assert d.inst["sog"]["source"] == "Tablet GPS" and d.inst["depth"]["source"] == "External GPS"   # filled in
    assert [o["name"] for o in d.secondaries({"External GPS"})] == ["External GPS"]
    rec.sample_instruments()
    text = rec._inst_path().read_text()
    assert rec._inst_path().name.endswith("_nmea.csv") and text.startswith("DateTime,Source,Role,Key,Label,Unit,Value")
    assert ",Tablet GPS,primary,lat,Latitude,°,41.9" in text and ",External GPS,secondary,lat,Latitude,°,42.0" in text
    assert ",External GPS,secondary,depth," in text and "lat" not in rec.inst_hist
    # failover: the primary quiet for over 5 s → the first secondary with a fix stands in
    d.heard["Tablet GPS"] = _t.time() - 10
    d.feed(w("GPRMC,120001,A,4200.000,N,07000.000,W,5.0,180.0,111126,,"), "External GPS")
    assert d.state.source == "Tablet GPS"                                  # failover off
    d.failover = True
    d.feed(w("GPRMC,120002,A,4200.000,N,07000.000,W,5.0,180.0,111126,,"), "External GPS")
    assert d.state.source == "External GPS" and d.state.lat == 42.0
    d.primary = None                                                       # don't leak into other tests
    # names, one primary; a template's inputs keep this computer's choices by name
    c = clean_inputs([{"type": "udp", "port": 1}, {"type": "udp", "port": 1, "name": "UDP port 1"}, {"type": "serial", "port": "COM3", "enabled": False, "primary": True}])
    assert [x["name"] for x in c] == ["UDP port 1", "UDP port 1 (2)", "Serial COM3 @ 4800"]
    assert [x["role"] for x in c] == ["primary", "secondary", "secondary"]
    mine = [{"name": "Tablet GPS", "type": "serial", "port": "COM3", "enabled": False},
            {"name": "External GPS", "type": "serial", "port": "COM5", "enabled": True, "primary": True, "show_on_map": False},
            {"type": "sim"}]
    tpl = [{"name": "Tablet GPS", "type": "serial", "port": "COM3"}, {"name": "External GPS", "type": "serial", "port": "COM9"},
           {"name": "Ship", "type": "udp", "port": 10110}]
    m = merge_inputs(mine, tpl)
    assert [(x["name"], x.get("port"), x["enabled"], x["role"] == "primary") for x in m] == [
        ("Tablet GPS", "COM3", False, False), ("External GPS", "COM9", True, True), ("Ship", 10110, False, False), ("Simulator", None, True, False)]
    # the 0.36–0.40 file is renamed and converted
    sd = tmp_path / "old" / "S"
    sd.mkdir(parents=True)
    (sd / "S_instruments.csv").write_text("DateTime,Key,Label,Unit,Value\n2026-11-01T12:00:00+00:00,depth,Depth,m,40\n")
    assert rename_instrument_files(tmp_path / "old") == 1
    assert (sd / "S_nmea.csv").read_text().splitlines()[1] == "2026-11-01T12:00:00+00:00,,primary,depth,Depth,m,40"
    assert not (sd / "S_instruments.csv").exists()



def test_external_inputs_and_failover_notice(rec, tmp_path):
    """0.42: roles primary / secondary / external; externals never give the platform's position, readings
    or failover; failover_state while a secondary stands in; a 0.41 _nmea.csv gets the Role column."""
    import time as _t
    from spyhop.nmea import with_checksum as w
    from spyhop.config import clean_inputs, input_definition, merge_inputs
    from spyhop.layout import rename_instrument_files
    d = rec.decoder
    d.primary, d.failover, d.externals = "Ship GPS", True, {"Drone"}
    d.priority = {"Ship GPS": 0, "Backup GPS": 1, "Drone": 2}
    d.feed(w("GPRMC,120000,A,4154.000,N,07020.000,W,10.0,90.0,111126,,"), "Ship GPS")
    d.heard["Ship GPS"] = _t.time() - 30                          # the primary has gone quiet
    d.feed(w("GPRMC,120000,A,4300.000,N,06900.000,W,30.0,10.0,111126,,"), "Drone")
    d.feed(w("SDDPT,99.0,0.5,"), "Drone")
    assert abs(d.state.lat - 41.9) < 1e-6 and d.failover_state() is None     # a drone never stands in
    assert "depth" not in d.inst and d.inst_src["Drone"]["depth"]["value"] == 99.5
    assert [o["other"] for o in d.secondaries({"Drone"})] == [True]
    d.feed(w("GPRMC,120001,A,4200.000,N,07000.000,W,5.0,180.0,111126,,"), "Backup GPS")
    f = d.failover_state()
    assert d.state.lat == 42.0 and f["from"] == "Backup GPS" and f["primary"] == "Ship GPS" and f["quiet_s"] >= 29
    rec.sample_instruments()
    assert ",Drone,other,depth," in rec._inst_path().read_text()
    d.primary, d.externals = None, set()
    # roles: one primary among platform inputs; externals stay external, also through a template
    c = clean_inputs([{"type": "udp", "port": 1, "role": "other"}, {"type": "udp", "port": 2, "role": "primary"},
                      {"type": "udp", "port": 3, "role": "primary"}])
    assert [x["role"] for x in c] == ["other", "primary", "secondary"] and c[0]["show_on_map"] is True
    assert input_definition(c[0])["role"] == "other" and "role" not in input_definition(c[1])
    m = merge_inputs([{"name": "Ship", "type": "udp", "port": 2, "role": "primary"}],
                     [{"name": "Ship", "type": "udp", "port": 2}, {"name": "Drone", "type": "udp", "port": 9, "role": "other"}])
    assert [(x["name"], x["enabled"], x["role"]) for x in m] == [("Ship", True, "primary"), ("Drone", False, "other")]
    sd = tmp_path / "v041" / "S"
    sd.mkdir(parents=True)
    (sd / "S_nmea.csv").write_text("DateTime,Source,Primary,Key,Label,Unit,Value\nt,A,yes,lat,Latitude,°,41\nt,B,no,lat,Latitude,°,42\n")
    assert rename_instrument_files(tmp_path / "v041") == 1
    assert (sd / "S_nmea.csv").read_text().splitlines()[1:] == ["t,A,primary,lat,Latitude,°,41", "t,B,secondary,lat,Latitude,°,42"]


def test_external_tracks_recorded_and_styled(rec):
    """0.43: each external's fixes go to <survey>_<name>_gps.csv (0.44) while a survey is active (if recording is
    on), and into a trail for the map, read back when the survey is opened again; styles are cleaned."""
    from spyhop.nmea import with_checksum as w
    from spyhop.config import clean_inputs, input_definition
    d = rec.decoder
    d.primary, d.externals = "Ship", {"Drone 1", "Buoy"}
    inputs = clean_inputs([{"name": "Ship", "type": "udp", "port": 1, "role": "primary"},
                           {"name": "Drone 1", "type": "udp", "port": 2, "role": "other", "color": "nope", "line": "zigzag", "trail": "30"},
                           {"name": "Buoy", "type": "udp", "port": 3, "role": "other", "record": False, "label": False}])
    drone, buoy = inputs[1], inputs[2]
    assert (drone["color"], drone["line"], drone["width"], drone["trail"], drone["label"], drone["record"]) == ("#e07000", "solid", 2.0, 30, True, True)
    assert clean_inputs([{"type": "udp", "port": 9, "role": "external"}])[0]["role"] == "other"   # 0.43's name
    assert buoy["color"] == "#0097a7" and buoy["record"] is False and buoy["label"] is False
    assert input_definition(drone)["color"] == "#e07000" and "color" not in inputs[0]        # styles travel in templates
    for i, (lat, lon) in enumerate([(4200.0, 7000.0), (4200.5, 7000.5)]):
        d.feed(w(f"GPRMC,12000{i},A,{lat:.3f},N,0{lon:.3f},W,8.0,45.0,111126,,"), "Drone 1")
        d.feed(w(f"GPRMC,12000{i},A,4100.000,N,06900.000,W,1.0,0.0,111126,,"), "Buoy")
        d.others["Drone 1"].updated += i             # a new fix each second
        rec.tick_externals(d, inputs)
        rec.tick_externals(d, inputs)                # no new fix: nothing added
    p = rec._ext_path("Drone 1")
    assert p.name == "Test_Drone_1_gps.csv"
    lines = p.read_text().splitlines()
    assert lines[0] == "DateTime,Lat,Lon,SOG,COG,Heading,GPSTime" and len(lines) == 3 and ",42.000000,-70.000000,8.0,45.0," in lines[1]
    assert rec._ext_path("Buoy").exists() is False                                 # not recorded
    tr = rec.external_tracks(inputs)
    assert len(tr["Drone 1"]) == 2 and len(tr["Buoy"]) == 2
    assert "Test_Drone_1_gps.csv" in {n.split("/")[-1] for n in zipfile.ZipFile(rec.export(["csv"])).namelist()}
    prefix = rec.survey["prefix"]
    rec.close_survey()
    assert rec.external_tracks(inputs) == {}
    rec.open_survey(prefix)
    assert len(rec.external_tracks(inputs)["Drone 1"]) == 2                          # read back from the file
    d.primary, d.externals = None, set()


def test_only_one_spyhop_per_computer(tmp_path, monkeypatch):
    """0.46: a second Spyhop can't take the lock while one runs (any port); it's free again once that ends."""
    import subprocess, sys, textwrap, time
    from spyhop import instance
    monkeypatch.setenv("SPYHOP_LOCK_DIR", str(tmp_path))
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
        import sys, time
        from spyhop import instance
        print(instance.acquire(8765), flush=True)
        time.sleep(30)""")], stdout=subprocess.PIPE, text=True, env={**__import__("os").environ, "SPYHOP_LOCK_DIR": str(tmp_path)})
    try:
        assert holder.stdout.readline().strip() == "True"
        assert instance.running()["port"] == 8765 and instance.running()["pid"] == holder.pid
        assert instance.acquire(9999) is False                     # another port doesn't help
    finally:
        holder.kill(); holder.wait()
    assert instance.acquire(9999, wait_s=2) is True                 # released when the process ends (no stale lock)
    assert instance.running()["port"] == 9999
