"""Delay, queue, emissions, indicators and congestion index on a synthetic run."""

import csv
import json

import pytest
import yaml

from pattom import congestion, delay, emissions, indicators

APPROACH_ZONE = [[0, 0], [100, 0], [100, 400], [0, 400]]


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture
def run(tmp_path):
    """Two cars on the north approach. Pixel v = 10 * ground y; ground y is metres from the stop line.
    Car 1 stops 20 s at 10 m; car 2 never stops. Signal N: green at 0, 60 s cycle."""
    rows = []
    def add(tid, t, y):
        v = 10 * y
        rows.append([int(t * 10), t, tid, "car", 0.9, 40, v - 20, 60, v, 0.0, y])
    t = 0.0
    y = 30.0
    while t <= 60:  # car 1: drives 30 -> 10 m by t=10, stopped until t=30, then on to 0
        if t <= 10:
            y = 30 - 2 * t
        elif t <= 30:
            y = 10.0
        else:
            y = 10 - 2 * (t - 30)  # crosses the stop line at t=35 and leaves the zone
        add(1, round(t, 1), y)
        t += 0.5
    for i in range(30):  # car 2: constant 5 m/s
        add(2, i * 0.5, 39 - 2.5 * i * 0.5)
    _write_csv(tmp_path / "tracks.csv",
               ["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2", "ground_x_m", "ground_y_m"],
               rows)
    _write_csv(tmp_path / "track_summary.csv", ["track_id", "majority_class"], [[1, "car"], [2, "car"]])
    meta = {"slot": "peak", "video_file": "v", "video_sha256": "x", "fps": 10, "width": 100, "height": 400,
            "tracker": "bytetrack"}
    (tmp_path / "tracks.run.json").write_text(json.dumps(meta))
    (tmp_path / "counting.run.json").write_text(json.dumps(meta))
    defs = {"definition_version": "test-1", "approved": True, "stopped_speed_kmh": 2.0, "speed_window_s": 2.0,
            "max_gap_s": 1.0, "approaches": {"north": {"zone_px": APPROACH_ZONE, "stop_point_m": [0.0, 0.0],
                                                       "signal_head": "N"}}}
    (tmp_path / "definitions.yaml").write_text(yaml.safe_dump(defs))
    (tmp_path / "signals.csv").write_text("time_s,signal_head,state\n0,N,red\n25,N,green\n55,N,amber\n58,N,red\n"
                                          "85,N,green\n115,N,amber\n")
    return tmp_path


def test_unapproved_definitions_refused(run):
    d = yaml.safe_load((run / "definitions.yaml").read_text())
    d["approved"] = False
    (run / "definitions.yaml").write_text(yaml.safe_dump(d))
    with pytest.raises(PermissionError):
        delay.run_delay_queue(run / "tracks.csv", run / "definitions.yaml", 900)
    delay.run_delay_queue(run / "tracks.csv", run / "definitions.yaml", 900, allow_draft=True)
    rows = list(csv.DictReader(open(run / "stopped_delay.csv")))
    assert rows[0]["definition_status"] == "draft, not approved"


def test_unfilled_definitions_refused(run):
    d = yaml.safe_load((run / "definitions.yaml").read_text())
    d["stopped_speed_kmh"] = None
    (run / "definitions.yaml").write_text(yaml.safe_dump(d))
    with pytest.raises(ValueError, match="not filled in"):
        delay.Definitions.load(run / "definitions.yaml")


def test_full_chain(run):
    delay.run_delay_queue(run / "tracks.csv", run / "definitions.yaml", 900, signal_log=run / "signals.csv")
    veh = {r["track_id"]: float(r["stopped_delay_s"]) for r in csv.DictReader(open(run / "vehicle_delay.csv"))}
    assert veh["1"] == pytest.approx(20.0, abs=1.5)
    assert veh["2"] == 0.0
    d = list(csv.DictReader(open(run / "stopped_delay.csv")))[0]
    assert (d["n_vehicles"], d["n_stopped"]) == ("2", "1")
    q = list(csv.DictReader(open(run / "queue.csv")))
    assert float(q[0]["queue_length_m"]) == pytest.approx(10.0)  # green at 25 s: car 1 waiting at 10 m
    assert q[0]["queued_vehicles"] == "1"

    em_cfg = run / "emissions.yaml"
    em_cfg.write_text(yaml.safe_dump({"method_id": "idle_co2_v1",
                                      "class_to_category": {"car": {"idle_fuel": "car_petrol", "fuel": "petrol"}}}))
    emissions.run_emissions(run / "vehicle_delay.csv", em_cfg, 900)
    e = list(csv.DictReader(open(run / "emissions.csv")))[0]
    expected = veh["1"] / 3600 * 0.60 * 2.27193 * 1000
    assert float(e["value"]) == pytest.approx(expected, rel=1e-3)
    assert e["value_type"] == "estimated" and "source not checked" in e["source_status"]
    gaps = json.loads((run / "emissions.run.json").read_text())["parameters"]["gaps"]
    assert any("ARAI" in g for g in gaps)

    _write_csv(run / "interval_counts.csv",
               ["slot", "interval_start_s", "interval_end_s", "line_name", "line_type", "approach", "movement",
                "class", "count", "value_type"],
               [["peak", 0.0, 900.0, "N_arr", "arrival", "north", "through", "car", 150, "measured"],
                ["peak", 0.0, 900.0, "N_arr", "arrival", "north", "through", "two_wheeler", 100, "measured"]])
    ind_cfg = run / "indicators.yaml"
    ind_cfg.write_text(yaml.safe_dump({
        "pcu_table": "table_3_1", "class_to_pcu_row": {"car": "passenger_car", "two_wheeler": "motorcycle_scooter"},
        "volume_line_type": "arrival", "effective_green": "displayed_green",
        "approaches": {"north": {"width_m": 7.0, "signal_head": "N"}}}))
    indicators.run_indicators(run, ind_cfg, run / "signals.csv")
    ind = list(csv.DictReader(open(run / "approach_indicators.csv")))[0]
    # volume = (150 + 0.5*100) PCU in 15 min = 800 PCU/h; capacity = 30/60 * 525*7 = 1837.5
    assert float(ind["volume_pcu_h"]) == pytest.approx(800.0)
    assert float(ind["capacity_pcu_h"]) == pytest.approx(1837.5)
    assert float(ind["vc_ratio"]) == pytest.approx(800 / 1837.5, abs=1e-3)
    assert float(ind["max_queue_length_m"]) == pytest.approx(10.0)

    f = run / "congestion.yaml"
    f.write_text(yaml.safe_dump({"formula_version": "t", "approved": False, "indicators": [
        {"column": "vc_ratio", "normalisation": "reference", "reference": 1.0, "weight": 1.0}]}))
    congestion.run_congestion(run / "approach_indicators.csv", f)
    ci = list(csv.DictReader(open(run / "congestion_index.csv")))[0]
    assert float(ci["congestion_index"]) == pytest.approx(800 / 1837.5, abs=1e-3)
    assert ci["formula_status"] == "draft, not approved"


def test_congestion_weights_required(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump({"formula_version": "t", "approved": False, "indicators": [
        {"column": "vc_ratio", "normalisation": "reference", "reference": 1.0, "weight": None}]}))
    with pytest.raises(ValueError, match="weight not set"):
        congestion.load_formula(f)
    f.write_text(yaml.safe_dump({"formula_version": "t", "approved": False, "indicators": [
        {"column": "a", "normalisation": "minmax", "weight": 0.5}]}))
    with pytest.raises(ValueError, match="sum to"):
        congestion.load_formula(f)


def test_congestion_minmax_and_missing():
    rows = [{"d": "10"}, {"d": "30"}, {"d": ""}]
    out, notes = congestion.compute(rows, {"formula_version": "t", "approved": True, "indicators": [
        {"column": "d", "normalisation": "minmax", "weight": 1.0, "direction": "higher_is_worse"}]})
    assert [r["congestion_index"] for r in out] == [0.0, 1.0, ""]
    assert notes


def test_emission_class_without_category_is_a_gap():
    rows, gaps = emissions.estimate(
        [{"class": "tractor", "approach": "n", "zone_entry_s": "0", "stopped_delay_s": "5"}],
        {"method_id": "m", "class_to_category": {}}, __import__("pattom.register").register.Register.load(),
        "s", 900)
    assert rows == [] and any("tractor" in g for g in gaps)
