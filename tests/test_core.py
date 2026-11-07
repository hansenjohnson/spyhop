import csv
import os
import re
import shutil
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
    assert row["VesLat"] == "41.900000" and row["VesLon"] == "-70.333333"
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
    assert any(x.name.startswith(p.name + ".bak-") for x in tmp_path.joinpath("data").iterdir())
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
    rec = Recorder(tmp_path)
    for n in ("species", "event_types", "observers", "behaviors", "shortcuts", "display"):
        assert (tmp_path / f"{n}.csv").exists()
    # the online map layers come from the code, not a file (0.12.0)
    assert not (tmp_path / "tile_sources.csv").exists()
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
    assert (row["SigLat"], row["SigLon"]) == (row["VesLat"], row["VesLon"])
    rid = row["RowID"]
    r = rec.edit("sightings", rid, {"VesLat": "41 55.0"})["row"]           # vessel corrected -> follows
    assert r["SigLat"] == r["VesLat"] == "41.916667"
    r = rec.edit("sightings", rid, {"Bearing": "90", "Distance": "1"})["row"]
    assert r["SigLat"] != r["VesLat"]
    r = rec.edit("sightings", rid, {"Distance": ""})["row"]               # bearing/distance removed -> back to vessel
    assert (r["SigLat"], r["SigLon"]) == (r["VesLat"], r["VesLon"])
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


def test_old_timezone_and_surfacings_settings_cleaned(tmp_path):
    (tmp_path / "settings").mkdir(parents=True)
    (tmp_path / "settings" / "settings.json").write_text('{"timezone": "America/New_York", "surfacings_enabled": true}')
    (tmp_path / "shortcuts.csv").write_text("combo,action,prefill\nMod+Shift+L,cycle-latlon,\nMod+Shift+S,add:sightings,\n")
    r = Recorder(tmp_path)
    assert r.cfg.settings["timezone"] == "local" and "surfacings_enabled" not in r.cfg.settings
    actions = [s["action"] for s in r.cfg.shortcuts]
    assert "cycle-latlon" not in actions and "add:sightings" in actions and "toggle-log" in actions
    assert "surfacings" not in r.tables


def test_event_code_column_added_to_existing_list(tmp_path):
    (tmp_path / "event_types.csv").write_text("name,color\nCTD cast,blue\nMy own event,red\n")
    r = Recorder(tmp_path)
    rows = {e["name"]: e for e in r.cfg.lists["event_types"]}
    assert rows["CTD cast"]["event_code"] == "CTD"          # default filled in by name
    assert rows["My own event"]["event_code"] == ""          # user rows kept, code left blank
    assert rows["My own event"]["color"] == "red"
    assert read_csv(tmp_path / "event_types.csv")[0].keys() >= {"name", "color", "event_code"}


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


def test_old_data_folder_is_moved_to_spyhop(tmp_path, monkeypatch):
    from spyhop import config as cfgmod
    monkeypatch.delenv("SPYHOP_DATA_DIR", raising=False)
    monkeypatch.delenv("WSR_DATA_DIR", raising=False)
    monkeypatch.setattr(cfgmod, "_base_dir", lambda: tmp_path)
    old = tmp_path / "WhaleSurveyRecorder" / "data"
    old.mkdir(parents=True)
    (old / "Leg A_sightings.csv").write_text("x")
    d = cfgmod.default_data_dir()
    assert d == tmp_path / "Spyhop"
    assert (d / "data" / "Leg A_sightings.csv").read_text() == "x"
    assert not (tmp_path / "WhaleSurveyRecorder").exists()
    assert cfgmod.default_data_dir() == d          # second start: nothing to move


# ---------------------------------------------------------------- survey lifecycle
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
    assert start["Effort"] == "Start" and start["VesLat"] and rec.tracking_on()
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
    rec.open_survey(p, resume=False)
    assert rec.tables["sightings"].rows[0]["Species"] == "Fin whale" and not rec.tracking_on()
    rec.close_survey()
    rec.open_survey(p, resume=True)
    assert rec.tracking_on()


def test_crash_recovery_asks_to_continue(tmp_path):
    r = Recorder(tmp_path)
    r.start_survey("Leg A")
    r.new_row("sightings", {"Species": "Fin whale"})
    assert r.tracking_on()
    # Spyhop is killed here; next start:
    r2 = Recorder(tmp_path)
    assert r2.survey["prefix"] == "Leg A" and r2.pending_resume == "Leg A"
    assert not r2.tracking_on()                                    # waits for an answer
    assert r2.bootstrap()["resume_prompt"] == "Leg A"
    r2.answer_resume("continue")
    assert r2.tracking_on() and r2.pending_resume is None
    r2.end_survey()
    r3 = Recorder(tmp_path)
    assert r3.survey["prefix"] == "Leg A" and r3.pending_resume is None   # ended: nothing to ask
    r3.answer_resume("close")
    assert r3.survey is None


def test_older_survey_gets_a_start_row(tmp_path):
    r = Recorder(tmp_path)
    d = r.cfg.data_dir
    hdr = schema.headers("effort")
    with open(d / "Old_effort.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(hdr)
        w.writerow(["a1", "2026-11-03T10:05:00-05:00", "41.9", "-70.3", "ON"] + [""] * (len(hdr) - 5))
    with open(d / "Old_sightings.csv", "w", newline="") as fh:
        w = csv.writer(fh); h = schema.headers("sightings"); w.writerow(h)
        w.writerow(["s1", "1", "2026-11-03T10:00:00-05:00"] + [""] * (len(h) - 3))
    r.open_survey("Old")
    rows = r.tables["effort"].rows
    assert rows[0]["Effort"] == "Start" and rows[0]["DateTime"] == "2026-11-03T10:00:00-05:00"
    assert rows[1]["Effort"] == "ON" and any("Start row" in n for n in r.notices)


def test_choose_data_folder(tmp_path):
    r = Recorder(tmp_path / "app")
    r.start_survey("Leg A")
    r.new_row("marks", {"Name": "Home"}, lat=41, lon=-70)
    new = tmp_path / "Shared drive" / "Spyhop data"
    r.set_data_dir(str(new))
    assert r.survey is None and r.cfg.data_dir == new               # switching closes the survey
    assert r.tables["marks"].rows == [] and r.list_surveys() == []
    r.start_survey("Leg B")
    assert (new / "Leg B_effort.csv").exists()
    r2 = Recorder(tmp_path / "app")                                # remembered between sessions
    assert r2.cfg.data_dir == new and r2.survey["prefix"] == "Leg B"
    with pytest.raises(ValueError):
        r2.cfg.set_data_dir("relative/path")
    r2.close_survey()
    r2.set_data_dir("")                                             # back to the default folder
    assert r2.cfg.data_dir == tmp_path / "app" / "data"
    assert [s["prefix"] for s in r2.list_surveys()] == ["Leg A"]


def test_missing_data_folder_falls_back_with_notice(tmp_path):
    r = Recorder(tmp_path / "app")
    r.set_data_dir(str(tmp_path / "usb"))
    (tmp_path / "usb").rmdir()                                      # drive unplugged
    r2 = Recorder(tmp_path / "app")
    assert r2.cfg.data_dir == tmp_path / "app" / "data"
    assert any("wasn't found" in n for n in r2.notices)
    assert r2.cfg.settings["data_dir"] == str(tmp_path / "usb")    # still remembered for next time


def test_survey_details_saved_remembered_and_exported(rec):
    m = rec.set_meta({"platform_name": "R/V Example", "platform_type": "vessel", "organization": "NEAQ",
                      "chief_scientist": "A. Person", "bogus": "x"})
    assert m["platform_type"] == "Vessel" and "bogus" not in m
    with pytest.raises(ValueErrorMsg):
        rec.set_meta({"platform_type": "Boat"})
    assert rec.survey_info()["meta"]["platform_name"] == "R/V Example"
    z = rec.export()
    assert any(n.endswith("Test_metadata.csv") for n in zipfile.ZipFile(z).namelist())
    rec.end_survey()
    rec.start_survey("Next leg")                                    # details carried over
    assert rec.read_meta()["organization"] == "NEAQ"
    rec.end_survey()
    rec.start_survey("Plane day", meta={"platform_type": "Plane", "platform_name": "N123"})
    m2 = rec.read_meta()
    assert m2["platform_type"] == "Plane" and m2["platform_name"] == "N123" and m2["organization"] == "NEAQ"
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


def test_new_event_types_added_once(tmp_path):
    from spyhop.config import Config
    root = tmp_path / "app"
    root.mkdir()
    (root / "event_types.csv").write_text("name,color,event_code\nCTD cast,blue,CTD\nOther,black,OTH\nMy event,red,MINE\n")
    cfg = Config(root)
    names = [r["name"] for r in cfg.lists["event_types"]]
    assert names == ["CTD cast", "Gear Reported", "Gear Recovered", "Other", "My event"]
    gr = next(r for r in cfg.lists["event_types"] if r["name"] == "Gear Reported")
    assert gr["event_code"] == "GRPT"
    # a user who deletes one keeps it deleted
    (root / "event_types.csv").write_text("name,color,event_code\nCTD cast,blue,CTD\nGear Recovered,x,GRCV\n")
    cfg = Config(root)
    assert [r["name"] for r in cfg.lists["event_types"]] == ["CTD cast", "Gear Recovered"]
    fresh = Config(tmp_path / "fresh")
    assert {"Gear Reported", "Gear Recovered", "Other"} <= {r["name"] for r in fresh.lists["event_types"]}


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
    rec.set_meta({"platform_name": "R/V Test", "platform_type": "Vessel", "organization": "NEAQ",
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
    rec.edit("sightings", s["RowID"], {"VesLat": "42.5"})                               # typo, far from the track
    rec.new_row("events", {"EventType": "Gear Reported"})
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
    assert ("Positions match the trackline", "VesLat") in got
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
    assert "Test_instruments.csv" in {n.split("/")[-1] for n in zipfile.ZipFile(rec.export(["csv"])).namelist()}


def test_negative_bearings(rec):
    row = rec.new_row("sightings", {"BrgRef": "R", "Bearing": "-10", "Distance": "1", "DistUnit": "km"})["row"]
    assert row["Bearing"] == "350"                                       # 10° to port
    b = geo.initial_bearing(41.9, -70.333333, float(row["SigLat"]), float(row["SigLon"]))
    assert b == pytest.approx(35, abs=0.05)                              # heading 045 − 10
    assert rec.edit("sightings", row["RowID"], {"Bearing": "-360"})["row"]["Bearing"] == "0"
    assert rec.edit("sightings", row["RowID"], {"Bearing": "-0.5"})["row"]["Bearing"] == "359.5"
    with pytest.raises(ValueErrorMsg):
        rec.edit("sightings", row["RowID"], {"Bearing": "-400"})


def test_marks_renamed_to_waypoints(tmp_path):
    from spyhop.recorder import Recorder
    d = tmp_path / "app" / "data"
    d.mkdir(parents=True)
    (d / "marks.csv").write_text("RowID,Name,DateTime,Lat,Lon,Shape,Color,Notes,Map\nr1,Buoy,,42,-70,Circle,red,,1\n")
    r = Recorder(tmp_path / "app")
    assert (d / "waypoints.csv").exists() and not (d / "marks.csv").exists()
    assert [x["Name"] for x in r.tables["marks"].rows] == ["Buoy"]
    from spyhop import schema
    assert schema.TABS["marks"]["title"] == "Waypoints"


# ---------------------------------------------------------------- 0.7.0
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


def test_renamed_tab_shortcuts_migrated(tmp_path):
    from spyhop.config import Config
    Config(tmp_path)
    p = tmp_path / "shortcuts.csv"
    rows = read_csv(p)
    assert any(r["action"] == "tab:reports" for r in rows)
    with open(p, "a", newline="") as fh:
        fh.write("Mod+9,tab:summary,\nMod+8,tab:planning,\n")
    Config(tmp_path)
    acts = [r["action"] for r in read_csv(p)]
    assert "tab:summary" not in acts and "tab:planning" not in acts
    assert acts.count("tab:reports") == 2 and "tab:route" in acts


# ---------------------------------------------------------------- 0.8.0
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
    rec.cfg.settings["track_break_gap_s"] = 120
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
    assert err["VesLat"] == "41.900500" and err["Visibility"] == ">10 nm"
    with pytest.raises(ValueErrorMsg):
        rec.insert_track_break(tr[0]["fix"]["t0"], tr[0]["fix"]["t1"])      # already marked
    r = _qc(rec)
    tr2 = [x for x in r["issues"] if x["check"] == "Trackline plausible"]
    assert len(tr2) == 1 and "No track points" in tr2[0]["message"]
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


def test_reports_builtin(rec):
    from spyhop import reports
    defs, errors = reports.load_definitions(rec.cfg)
    assert not errors
    assert [d["id"] for d in defs] == ["gear", "dead_birds", "right_whales", "blue_whales"]
    assert any(s["name"] == "Dead bird" and s["species_code"] == "DEBI" for s in rec.cfg.lists["species"])
    rec.new_row("sightings", {"Species": "North Atlantic right whale", "Count": "3", "Calves": "1", "Notes": "mom & calf"})
    rec.new_row("sightings", {"Species": "North Atlantic right whale", "Count": "2"})
    rec.new_row("sightings", {"Species": "Blue whale", "Count": "1"})
    rec.new_row("sightings", {"Species": "Dead bird", "Count": "1", "Notes": "shearwater"})
    rec.new_row("events", {"EventType": "Gear Reported", "Notes": "buoy line"})
    rec.new_row("events", {"EventType": "CTD cast"})
    res = {d["id"]: reports.run(rec, d) for d in defs}
    assert res["right_whales"]["count"] == 2 and res["right_whales"]["totals"] == ["", "", "5", "1", ""]
    assert res["right_whales"]["rows"][0][4] == "mom & calf" and "°" in res["right_whales"]["rows"][0][1]
    assert res["blue_whales"]["count"] == 1 and res["dead_birds"]["rows"][0][2] == "shearwater"
    assert res["gear"]["count"] == 1 and res["gear"]["rows"][0][1] == "Gear Reported"
    page = reports.to_html(rec, res["right_whales"])
    assert page.startswith("<!DOCTYPE html>") and "mom &amp; calf" in page and "Total (2)" in page
    # chosen in Export Data
    f = rec.export(["report:right_whales", "report:gear"], report_as=["html"])
    with zipfile.ZipFile(f) as z:
        names = [n.split("/")[-1] for n in z.namelist()]
    assert names == ["Test_report_gear.html", "Test_report_right_whales.html"]
    with pytest.raises(ValueErrorMsg):
        rec.export(["report:nope"])


def test_reports_custom_folder(rec):
    from spyhop import reports
    d = reports.prepare_user_dir(rec.cfg)
    assert (d / "README.md").exists() and (d / "examples" / "gear.json").exists()
    (d / "hide.json").write_text('{"id": "blue_whales", "enabled": false}')
    (d / "fins.json").write_text(json.dumps({"id": "fins", "title": "Fin whales", "order": 1, "table": "sightings",
        "where": [{"column": "Species", "equals": "fin whale"}],
        "columns": [{"label": "When", "value": "clock"}, {"label": "N", "column": "Count", "align": "right"}],
        "totals": {"N": "sum"}}))
    (d / "bad.json").write_text('{"id": "bad", "title": "Bad", "table": "sightings", "columns": [{"label": "X", "column": "Nope"}]}')
    defs, errors = reports.load_definitions(rec.cfg)
    ids = [x["id"] for x in defs]
    assert ids[0] == "fins" and "blue_whales" not in ids and "bad" not in ids
    assert len(errors) == 1 and "bad.json" in errors[0] and "Nope" in errors[0]
    rec.new_row("sightings", {"Species": "Fin whale", "Count": "4"})
    r = reports.run(rec, defs[0])
    assert r["count"] == 1 and r["totals"] == ["", "4"]


def test_report_pdf_when_a_browser_is_available(rec, tmp_path):
    from spyhop import browser, reports
    import os
    if not os.environ.get("SPYHOP_CHROME") or browser.find_chrome() is None:
        pytest.skip("set SPYHOP_CHROME to a Chrome / Edge / headless-shell binary to test PDFs")
    page = reports.to_html(rec, reports.run(rec, reports.get_definition(rec.cfg, "gear")))
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


def _pack_zip(files: dict, top: str = "") -> bytes:
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


def test_config_pack_resolve():
    from spyhop.configpack import resolve, PackError
    assert resolve("https://github.com/team/spyhop-config") == ("url", "https://api.github.com/repos/team/spyhop-config/zipball")
    assert resolve("https://github.com/team/cfg/tree/main/aerial/pack") == \
        ("url", "https://api.github.com/repos/team/cfg/zipball/main#aerial/pack")
    # a zip committed to a repository, by its page or raw link, or a release download: the zip itself
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
    with pytest.raises(PackError):
        resolve("https://drive.google.com/drive/folders/abc")
    with pytest.raises(PackError):
        resolve("")
    with pytest.raises(PackError):
        resolve("not a link")


def test_config_pack_check_pull_backup(tmp_path):
    import json as _json, zipfile as _zf
    from spyhop import configpack
    from spyhop.config import Config
    cfg = Config(tmp_path / "app")
    (cfg.root / "reports").mkdir(exist_ok=True)
    (cfg.root / "reports" / "mine.json").write_text(_json.dumps(
        {"id": "mine", "title": "Mine", "table": "events", "columns": [{"label": "Time", "value": "time"}]}))
    species = "name,color,species_code\r\nNorth Atlantic right whale,red,RIWH\r\nHumpback whale,orange,HUWH\r\nSpyhop test whale,pink,SPTW\r\n"
    observers = "name,full_name\r\nHJ,Hansen Johnson\r\n"
    gear = _json.dumps({"id": "gear", "title": "Gear (team)", "table": "events",
                        "where": [{"event_code": ["GRPT"]}], "columns": [{"label": "Time", "value": "time"}]})
    manifest = "Date,Changed by,Files,Notes\r\n2026-10-01,HJ,all,First version\r\n2026-11-06,HJ,species.csv,Added test whale\r\n"
    good = _pack_zip({"spyhop-config.csv": manifest, "species.csv": species, "observers.csv": observers,
                      "reports/gear.json": gear, "notes.txt": "hello"}, top="team-cfg-abc123/")
    bad = _pack_zip({"species.csv": "colour\r\nred\r\n", "reports/x.json": "{nope"})
    base, stop = _serve({"/good.zip": (200, "application/zip", good), "/bad.zip": (200, "application/zip", bad),
                         "/page": (200, "text/html", b"<!DOCTYPE html><html>sign in</html>"),
                         "/private": (403, "text/plain", b"no")})
    try:
        files, src = configpack.fetch(base + "/good.zip")
        pack = configpack.read_pack(files)
        assert not pack["problems"] and pack["ignored"] == ["notes.txt"]
        assert [m["notes"] for m in pack["manifest"]] == ["Added test whale", "First version"]   # newest first
        plan = {r["file"]: r for r in configpack.compare(cfg, pack)}
        assert plan["species.csv"]["status"] == "changed" and plan["species.csv"]["pack"] == 3
        assert plan["observers.csv"]["status"] == "changed"
        assert plan["reports/gear.json"]["status"] == "new" and plan["reports/mine.json"]["status"] == "removed"

        backup = configpack.save_backup(cfg, tmp_path / "bk")
        with _zf.ZipFile(backup) as z:
            names = set(z.namelist())
            old_species = z.read("species.csv").decode()
            assert "Backup" in z.read("spyhop-config.csv").decode("utf-8-sig")
        assert {"species.csv", "shortcuts.csv", "reports/mine.json", "spyhop-config.csv"} <= names

        changed = configpack.apply(cfg, pack)
        assert "species.csv" in changed and "reports/mine.json" in changed
        assert [s["name"] for s in cfg.lists["species"]] == ["North Atlantic right whale", "Humpback whale", "Spyhop test whale"]
        assert not (cfg.root / "reports" / "mine.json").exists() and (cfg.root / "reports" / "gear.json").exists()
        assert (cfg.root / "spyhop-config.csv").read_bytes().decode() == manifest
        assert cfg.shortcuts                                    # files not in the pack are untouched
        assert all(r["status"] == "same" for r in configpack.compare(cfg, configpack.read_pack(files)))

        # a backup made with no templates removes templates added since
        cfg2 = Config(tmp_path / "app2")
        assert configpack.read_pack(configpack._unzip(configpack.make_zip(cfg2, "pack"), ""))["reports"] is None
        empty = configpack.read_pack(configpack._unzip(configpack.make_zip(cfg2, "none", backup=True), ""))
        assert empty["reports"] == {}
        configpack.apply(cfg2, pack)
        assert (cfg2.root / "reports" / "gear.json").exists()
        configpack.apply(cfg2, empty)
        assert not (cfg2.root / "reports" / "gear.json").exists()

        # the backup is itself a pack: pulling it puts things back
        restore = configpack.read_pack(configpack.fetch(str(backup))[0])
        configpack.apply(cfg, restore)
        assert (cfg.root / "species.csv").read_text(encoding="utf-8-sig").replace("\r\n", "\n") == old_species.replace("\r\n", "\n").lstrip("﻿")
        assert (cfg.root / "reports" / "mine.json").exists() and not (cfg.root / "reports" / "gear.json").exists()

        badpack = configpack.read_pack(configpack.fetch(base + "/bad.zip")[0])
        assert any("species.csv needs the column name" in p for p in badpack["problems"])
        assert any("x.json isn't valid JSON" in p for p in badpack["problems"])
        before = (cfg.root / "species.csv").read_text()
        with pytest.raises(configpack.PackError):
            configpack.apply(cfg, badpack)
        assert (cfg.root / "species.csv").read_text() == before          # nothing changed

        for path, words in (("/page", "web page"), ("/private", "refused"), ("/missing.zip", "404")):
            with pytest.raises(configpack.PackError, match=words):
                configpack.fetch(base + path)
        with pytest.raises(configpack.PackError, match="doesn't look like"):
            configpack.read_pack({"readme.txt": b"hi"})

        # a pack made on this computer, as a folder on disk (e.g. a USB stick), with an Excel-saved CSV
        d = tmp_path / "usb"
        (d / "reports").mkdir(parents=True)
        (d / "observers.csv").write_bytes("name,full_name\r\nJM,José Martínez\r\n".encode("cp1252"))
        p2 = configpack.read_pack(configpack.fetch(str(d))[0])
        assert not p2["problems"] and "José" in p2["csv"]["observers.csv"] and p2["reports"] is None   # an empty reports folder leaves templates alone
        assert configpack.compare(cfg, p2)[0]["file"] == "observers.csv"
        z = configpack.make_zip(cfg, "made here")
        assert "made here" in configpack.read_pack(configpack._unzip(z, ""))["manifest"][0]["notes"]
    finally:
        stop()


def test_tile_sources_from_code_keep_extras(tmp_path):
    from spyhop.config import Config
    (tmp_path / "tile_sources.csv").write_text(
        "name,url,attribution,overlay,max_zoom\nEsri Ocean,https://old.example/{z}/{x}/{y},,0,10\n"
        "Team charts,https://charts.example/{z}/{x}/{y}.png,Team,0,14\n"
        "NOAA charts (tiled),https://gis.charttools.noaa.gov/x/{z}/{y}/{x},NOAA,0,18\n"
        "OpenSeaMap seamarks,https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png,OSM,1,18\n")
    cfg = Config(tmp_path)
    names = [s["name"] for s in cfg.tile_sources]
    assert names.count("Esri Ocean") == 1 and names[-1] == "Team charts"
    assert "old.example" not in next(s for s in cfg.tile_sources if s["name"] == "Esri Ocean")["url"]


def test_save_lists_and_shortcuts(tmp_path):
    from spyhop.config import Config, clean_combo
    cfg = Config(tmp_path)
    rows = [{"name": "Fin whale", "color": "royalblue", "species_code": "FIWH"},
            {"name": "", "color": "", "species_code": ""},                       # blank: dropped
            {"name": "Sei whale", "color": "#00aa88", "species_code": "SEWH", "extra": "x"}]
    cfg.save_list("species", rows)
    assert [s["name"] for s in cfg.lists["species"]] == ["Fin whale", "Sei whale"]
    for bad, words in (([{"name": "A", "species_code": "X"}, {"name": "a", "species_code": "Y"}], "already used"),
                       ([{"name": "A", "species_code": "X"}, {"name": "B", "species_code": "x"}], "Code “x” is already used"),
                       ([{"name": "A", "color": "not a colour!"}], "isn't a colour"),
                       ([{"name": "", "species_code": "X"}], "Name is empty"),
                       ([], "can't be empty")):
        with pytest.raises(ValueError, match=words):
            cfg.save_list("species", bad)
    assert [s["name"] for s in cfg.lists["species"]] == ["Fin whale", "Sei whale"]   # unchanged
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
                       ([{"combo": "Mod+1", "action": "add:sightings", "prefill": "Colour=red"}], "no column “Colour”"),
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
    assert [s["name"] for s in app.rec.cfg.lists["species"]] == ["X"]


def test_make_pack_logs_the_change(tmp_path):
    import asyncio, zipfile as _zf
    from spyhop import configpack
    from spyhop.server import App
    app = App(tmp_path)
    cfg = app.rec.cfg

    class Req:
        def __init__(self, body): self.body = body
        can_read_body = True
        async def json(self): return self.body
        match_info = {}
    run = lambda coro: json.loads(asyncio.run(coro).text)          # noqa: E731
    assert run(app.groupconfig_changes(Req({})))["files"] is None    # nothing to compare with yet
    with pytest.raises(ValueErrorMsg, match="your name"):
        asyncio.run(app.groupconfig_pack(Req({"by": "", "notes": "x"})))
    r = run(app.groupconfig_pack(Req({"by": "H. Johnson", "notes": "First version", "name": "2026-NEA-CCB-spyhop_config"})))
    assert r["name"] == "2026-NEA-CCB-spyhop_config.zip"
    with _zf.ZipFile(cfg.export_dir / r["name"]) as z:
        log = configpack.read_manifest(z.read("spyhop-config.csv").decode("utf-8-sig"))
    assert log[0]["by"] == "H. Johnson" and log[0]["notes"] == "First version" and log[0]["files"] == "all"
    # the local record of changes has the row too, and the next pack lists only what changed
    assert configpack.read_manifest((cfg.root / "spyhop-config.csv").read_text(encoding="utf-8-sig"))[0]["notes"] == "First version"
    ch = run(app.groupconfig_changes(Req({})))
    assert ch["files"] == [] and ch["since"] == "pack" and ch["by"] == "H. Johnson"
    assert ch["name"] == "2026-NEA-CCB-spyhop_config.zip"
    cfg.save_list("observers", [{"name": "JM", "full_name": "J. M."}])
    assert run(app.groupconfig_changes(Req({})))["files"] == ["observers.csv"]
    run(app.groupconfig_pack(Req({"by": "H. Johnson", "notes": "New observer JM", "files": "observers.csv",
                                  "name": "2026-NEA-CCB-spyhop_config.zip"})))
    with _zf.ZipFile(cfg.export_dir / "2026-NEA-CCB-spyhop_config.zip") as z:
        log = configpack.read_manifest(z.read("spyhop-config.csv").decode("utf-8-sig"))
        assert "JM" in z.read("observers.csv").decode()
    assert [x["notes"] for x in log] == ["New observer JM", "First version"] and log[0]["files"] == "observers.csv"
    assert configpack.safe_pack_name('a/b:c') == "a_b_c.zip" and configpack.safe_pack_name("  ") == ""


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
                 "layers": [{"id": "bg", "type": "background"},
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
        assert st["sources"]["osm"]["tiles"][0].startswith(local + "/tiles/gl/0/t/{z}/{x}/{y}?u=")
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
        # vector z0–3 (85 tiles) + DEM z0–2 (21) + 3 font ranges; OpenStreetMap left out
        assert plan["total"] == 85 + 21 + 3 and plan["skipped"] and "tile.openstreetmap.org" in plan["skipped"][0]
        r = await ts.start_prefetch(0, world, 0, 5)
        assert r["total"] == 109
        await ts._prefetch_task
        s = ts.prefetch_state
        assert s["done"] == 109 and s["failed"] == 0 and not s["running"]

        rp = await ts.plan_prefetch(1, world, 0, 6)
        assert rp["zmax"] == 2 and "only goes up to zoom 2" in rp["note"] and rp["total"] == 21
        await ts.start_prefetch(1, world, 0, 6)
        await ts._prefetch_task
        assert ts.prefetch_state["failed"] == 0
        with pytest.raises(ValueError, match="lowest zoom"):
            await ts.plan_prefetch(1, world, 4, 2)
        with pytest.raises(ValueError, match="limit"):
            await ts.start_prefetch(1, world, 0, 2, limit=10)

    asyncio.run(go())
    stop()                                            # the internet is gone: everything comes from the cache

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
        await ts.close()
    asyncio.run(offline())
    assert ts.cache_stats()["tiles"] >= 85 + 21 + 21
