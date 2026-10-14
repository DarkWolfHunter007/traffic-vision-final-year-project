"""Calculation stages on small synthetic tables (made-up values, not site data)."""

import csv

import numpy as np
import pytest
import yaml

from pattom import capacity, queue_delay, validation
from pattom.tables import read_csv


def write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path


TRACK_FIELDS = ["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2", "ground_x_m", "ground_y_m"]


@pytest.fixture
def scene(tmp_path):
    """Two cars approaching a stop line at y = 0 m from the south (y > 0):
    car 1 stops at y = 5 m from t = 2 s to t = 8 s, then crosses at t = 10 s;
    car 2 never stops and crosses at t = 4 s. Ground metres equal pixels / 100."""
    rows = []
    for t10 in range(0, 121):
        t = t10 / 10
        y1 = 10 - 2.5 * t if t < 2 else 5.0 if t < 8 else 5 - 2.5 * (t - 8)
        y2 = 20 - 5 * t
        for tid, y in ((1, y1), (2, y2)):
            rows.append({"frame": t10 * 3, "time_s": t, "track_id": tid, "class": "car", "confidence": 0.9,
                         "x1": 100, "y1": y * 100 - 50, "x2": 300, "y2": y * 100, "ground_x_m": 2.0, "ground_y_m": y})
    tracks = write(tmp_path / "tracks.csv", TRACK_FIELDS, rows)
    crossings = write(tmp_path / "crossings.csv",
                      ["time_s", "frame", "line_name", "line_type", "approach", "track_id", "class", "direction"],
                      [{"time_s": 4.0, "frame": 120, "line_name": "S_stop", "line_type": "stop_line", "approach": "south",
                        "track_id": 2, "class": "car", "direction": "left->right"},
                       {"time_s": 10.0, "frame": 300, "line_name": "S_stop", "line_type": "stop_line",
                        "approach": "south", "track_id": 1, "class": "car", "direction": "left->right"}])
    cycles = write(tmp_path / "signal_cycles.csv",
                   ["slot", "signal_head", "phase_group", "cycle_start_s", "cycle_end_s", "green_s", "amber_s", "red_s",
                    "cycle_s", "sequence", "regular", "value_type"],
                   [{"slot": "t", "signal_head": "S_main", "phase_group": "NS", "cycle_start_s": 0, "cycle_end_s": 9,
                     "green_s": 1, "amber_s": 1, "red_s": 7, "cycle_s": 9, "sequence": "green-amber-red",
                     "regular": True, "value_type": "measured"}])
    lines = tmp_path / "lines.yaml"
    lines.write_text(yaml.safe_dump({"lines": [{"name": "S_stop", "type": "stop_line", "approach": "south",
                                                "endpoints_px": [[0, 0], [1000, 0]], "direction": "left"}]}))
    ground = tmp_path / "ground.yaml"
    pts = [{"id": f"P{i}", "px": [u, v], "m": [u / 100, v / 100], "role": "fit"}
           for i, (u, v) in enumerate([(0, 0), (1000, 0), (1000, 2000), (0, 2000)])]
    pts.append({"id": "C", "px": [500, 1000], "m": [5, 10], "role": "check"})
    ground.write_text(yaml.safe_dump({"mappings": {"all": {"zone_px": [[-10, -10], [1010, -10], [1010, 2010], [-10, 2010]],
                                                           "points": pts}}}))
    return {"tracks": tracks, "crossings": crossings, "cycles": cycles, "lines": lines, "ground": ground,
            "out": tmp_path / "out"}


DEF = {"stopped_speed_kmh": 1.8, "speed_window_s": 1.0, "definition_version": "test-v1"}


def test_speeds_from_ground():
    t = np.arange(0, 3, 0.5)
    xy = np.column_stack([t * 4.0, np.zeros_like(t)])
    assert np.allclose(queue_delay.speeds(t, xy, 1.0)[1:-1], 4.0)


def test_stopped_delay_needs_the_definition(scene):
    with pytest.raises(ValueError, match="stopped_speed_kmh"):
        queue_delay.stopped_delay(scene["tracks"], scene["crossings"], "t", {}, scene["out"])


def test_stopped_delay(scene):
    queue_delay.stopped_delay(scene["tracks"], scene["crossings"], "t", DEF, scene["out"])
    veh = {int(r["track_id"]): float(r["stopped_s"]) for r in read_csv(scene["out"] / "stopped_delay_vehicles.csv")}
    # Stopped 2 s to 8 s; the 1 s speed window trims part of a window at each end (5.4 s here).
    assert veh[2] == 0.0 and 5.0 <= veh[1] <= 6.0
    [row] = read_csv(scene["out"] / "stopped_delay.csv")
    assert row["n_vehicles"] == "2" and row["definition_version"] == "test-v1" and row["value_type"] == "derived"


def test_queue_at_green_start(scene):
    params = {**DEF, "measure_at": "green_start", "approach_heads": {"south": "S_main"}}
    queue_delay.queue_lengths(scene["tracks"], scene["crossings"], scene["cycles"], scene["lines"], scene["ground"],
                              "t", params, scene["out"])
    [q] = read_csv(scene["out"] / "queue.csv")
    assert float(q["cycle_start"]) == 9 and q["n_queued"] == "0"  # car 1 is moving again at 9 s
    params["measure_at"] = "max_during_red"
    queue_delay.queue_lengths(scene["tracks"], scene["crossings"], scene["cycles"], scene["lines"], scene["ground"],
                              "t", params, scene["out"])
    [q] = read_csv(scene["out"] / "queue.csv")
    assert q["n_queued"] == "1" and abs(float(q["queue_length_m"]) - 5.0) < 0.05


def test_capacity_vc(scene, register):
    counts = write(scene["out"] / "interval_counts.csv",
                   ["slot", "interval_start_s", "interval_end_s", "line_name", "line_type", "approach", "movement",
                    "class", "count", "value_type"],
                   [{"slot": "t", "interval_start_s": 0, "interval_end_s": 900, "line_name": "S_stop",
                     "line_type": "stop_line", "approach": "south", "movement": "through", "class": "car",
                     "count": 100, "value_type": "measured"},
                    {"slot": "t", "interval_start_s": 0, "interval_end_s": 900, "line_name": "S_stop",
                     "line_type": "stop_line", "approach": "south", "movement": "through", "class": "two_wheeler",
                     "count": 200, "value_type": "measured"}])
    params = {"pcu_table": "table_3_1", "class_rows": {"car": "passenger_car", "two_wheeler": "motorcycle_scooter"},
              "approaches": {"south": {"width_m": 7.0, "gradient_pct": 0, "signal_head": "S_main",
                                       "volume_line": "S_stop"}}, "effective_green": "green"}
    with pytest.raises(ValueError, match="pcu_table"):
        capacity.run_capacity(counts, scene["cycles"], "t", {**params, "pcu_table": None}, scene["out"], register)
    capacity.run_capacity(counts, scene["cycles"], "t", params, scene["out"], register)
    [r] = read_csv(scene["out"] / "capacity_vc.csv")
    # volume = (100 x 1.0 + 200 x 0.5) PCU per 900 s = 800 PCU/h; s = 525 x 7; capacity = 1 x s / 9
    assert float(r["volume_pcu_h"]) == 800.0 and float(r["saturation_flow_pcu_h"]) == 3675.0
    assert abs(float(r["vc_ratio"]) - 800 / (3675 / 9)) < 0.01 and "p. 75" in r["source"]


def test_count_validation(scene):
    manual = write(scene["out"] / "manual_counts.csv", validation.MANUAL_FIELDS,
                   [{"slot": "t", "window_start_s": 0, "window_end_s": 20, "line_name": "S_stop", "class": "car",
                     "count": 3}])
    validation.compare(scene["crossings"], manual, "t", scene["out"])
    rows = read_csv(scene["out"] / "count_error.csv")
    window = rows[0]
    assert (window["manual"], window["automatic"], window["error"], window["error_pct"]) == ("3", "2", "-1", "-33.3")
    assert any(r["scope"] == "total" and r["line_name"] == "all" for r in rows)


# --- G and H ---------------------------------------------------------------

def test_congestion_index_needs_weights_adding_to_one(tmp_path):
    from pattom.indices import congestion_index

    vc = write(tmp_path / "capacity_vc.csv", ["approach", "interval_start_s", "vc_ratio"],
               [{"approach": "north", "interval_start_s": 0, "vc_ratio": 0.5},
                {"approach": "south", "interval_start_s": 0, "vc_ratio": 1.1}])
    d = write(tmp_path / "stopped_delay.csv", ["approach", "interval_start_s", "mean_stopped_delay_s"],
              [{"approach": "north", "interval_start_s": 0, "mean_stopped_delay_s": 10},
               {"approach": "south", "interval_start_s": 0, "mean_stopped_delay_s": 40}])
    ind = [{"source": "capacity_vc", "weight": 0.5, "direction": "higher_is_worse", "normalise": {"method": "minmax"}},
           {"source": "stopped_delay", "weight": 0.4, "direction": "higher_is_worse", "normalise": {"method": "minmax"}}]
    with pytest.raises(ValueError, match="add up to"):
        congestion_index({"capacity_vc": vc, "stopped_delay": d}, "t", {"indicators": ind, "formula_version": "x"},
                         tmp_path)
    ind[1]["weight"] = 0.5
    congestion_index({"capacity_vc": vc, "stopped_delay": d}, "t", {"indicators": ind, "formula_version": "x"},
                     tmp_path)
    ci = {r["approach"]: float(r["congestion_index"]) for r in read_csv(tmp_path / "congestion_index.csv")}
    assert ci == {"north": 0.0, "south": 1.0}


def test_emissions_idle_co2_and_gaps(tmp_path, register):
    from pattom.indices import emissions

    veh = write(tmp_path / "stopped_delay_vehicles.csv", queue_delay.VEHICLE_FIELDS,
                [{"track_id": 1, "class": "car", "approach": "south", "stop_line": "S", "cross_time_s": 10,
                  "stopped_s": 3600, "speed_samples": 10, "value_type": "derived"},
                 {"track_id": 2, "class": "truck", "approach": "south", "stop_line": "S", "cross_time_s": 12,
                  "stopped_s": 60, "speed_samples": 10, "value_type": "derived"}])
    with pytest.raises(ValueError, match="class_fuel"):
        emissions(veh, "t", {}, tmp_path, register)
    emissions(veh, "t", {"class_fuel": {"car": {"idle_row": "car_petrol", "fuel": "petrol"},
                                        "truck": {"idle_row": "truck_diesel", "fuel": "diesel"}}}, tmp_path, register)
    [row] = read_csv(tmp_path / "emissions.csv")
    rate, _ = register.item("idle_fuel_l_per_h", "car_petrol")
    factor, _ = register.item("fuel_co2_kg_per_l", "petrol")
    assert abs(float(row["value"]) - rate * factor) < 1e-3 and row["value_type"] == "estimated"
    assert "not checked" in row["source_status"]
    gaps = read_csv(tmp_path / "emission_gaps.csv")
    assert any(g["vehicle_category"] == "truck" for g in gaps) and any(g["part"] == "moving" for g in gaps)


def test_problem_rules(tmp_path):
    from pattom.indices import problems

    vc = write(tmp_path / "capacity_vc.csv", ["approach", "interval_start_s", "vc_ratio"],
               [{"approach": "north", "interval_start_s": 0, "vc_ratio": 0.5},
                {"approach": "south", "interval_start_s": 0, "vc_ratio": 1.1}])
    problems({"capacity_vc": vc}, "t", {"rules": [{"indicator": "vc_ratio", "op": ">", "value": 1,
                                                   "problem": "over capacity"}]}, tmp_path)
    [hit] = read_csv(tmp_path / "problems.csv")
    assert hit["approach"] == "south" and hit["problem"] == "over capacity"


# --- I, J, K ---------------------------------------------------------------

@pytest.fixture
def decision(tmp_path):
    cycles = write(tmp_path / "signal_cycles.csv",
                   ["slot", "signal_head", "phase_group", "cycle_start_s", "cycle_end_s", "green_s", "amber_s", "red_s",
                    "cycle_s", "sequence", "regular", "value_type"],
                   [{"slot": "t", "signal_head": h, "phase_group": g, "cycle_start_s": 0, "cycle_end_s": 100,
                     "green_s": gr, "amber_s": 3, "red_s": 100 - gr - 3, "cycle_s": 100, "sequence": "green-amber-red",
                     "regular": True, "value_type": "measured"} for h, g, gr in (("N", "NS", 50), ("E", "EW", 30))])
    problems = write(tmp_path / "problems.csv", ["approach", "problem"], [{"approach": "east", "problem": "east V/C"}])
    cap = write(tmp_path / "capacity_vc.csv", ["approach", "volume_pcu_h", "saturation_flow_pcu_h"],
                [{"approach": "north", "volume_pcu_h": 1200, "saturation_flow_pcu_h": 3600},
                 {"approach": "east", "volume_pcu_h": 900, "saturation_flow_pcu_h": 3000}])
    alts = tmp_path / "alternatives.yaml"
    plan = lambda ns, ew: {"cycle_s": 100, "groups": {"NS": {"green_s": ns, "amber_s": 3}, "EW": {"green_s": ew, "amber_s": 3}}}
    alts.write_text(yaml.safe_dump({"alternatives": [
        {"id": "A1", "description": "more green east", "control": "fixed", "problem_addressed": "east V/C", "plan": plan(44, 36)},
        {"id": "A2", "description": "longer east", "control": "fixed", "problem_addressed": "east V/C", "plan": plan(42, 38)},
        {"id": "A3", "description": "actuated", "control": "actuated", "problem_addressed": "east V/C"}]}))
    return {"cycles": cycles, "problems": problems, "cap": cap, "alts": alts, "out": tmp_path}


SCORING = {"approach_groups": {"north": "NS", "east": "EW"}, "effective_green": "green", "congestion_measure": "max_vc",
           "volume_stat": "mean", "delay_method": "none"}


def test_alternatives_and_scores(decision, register):
    from pattom.alternatives import build_alternatives, pre_sumo_scores

    j = build_alternatives(decision["cycles"], decision["problems"], decision["alts"], "t", decision["out"])
    data = __import__("json").loads(j.read_text())
    assert data["existing"]["plan"]["groups"]["EW"]["green_s"] == 30 and data["warnings"] == []
    pre_sumo_scores(j, decision["cap"], "t", SCORING, decision["out"], register)
    rows = {(r["alternative"], r["criterion"]): r for r in read_csv(decision["out"] / "pre_sumo_scores.csv")}
    # existing: east V/C = 900 / (30 x 3000 / 100) = 1.0; A1: 900 / (36 x 3000 / 100) = 0.8333
    assert float(rows[("existing", "vc_east")]["raw_value"]) == 1.0 and float(rows[("A1", "vc_east")]["raw_value"]) == 0.8333
    # worst approach: A1 max(1200/1584, 0.8333) = 0.8333; A2 max(1200/1512, 900/1140) = 0.7937
    assert float(rows[("A2", "congestion")]["raw_value"]) == 0.7937
    assert "not scorable" in rows[("A3", "congestion")]["note"] and "gap" in rows[("A1", "delay")]["note"]


def test_mce_needs_an_explicit_missing_criteria_choice(decision, register):
    from pattom.alternatives import build_alternatives, mce, pre_sumo_scores

    j = build_alternatives(decision["cycles"], decision["problems"], decision["alts"], "t", decision["out"])
    data = __import__("json").loads(j.read_text())
    data["alternatives"] = data["alternatives"][:2]  # A1, A2 (fixed)
    j.write_text(__import__("json").dumps(data))
    scores = pre_sumo_scores(j, decision["cap"], "t", SCORING, decision["out"], register)
    params = {"weights": {"congestion": 0.4, "emission": 0.3, "safety": 0.1, "cost": 0.1, "land": 0.1},
              "directions": {"congestion": "higher_is_better", "emission": "higher_is_better",
                             "safety": "higher_is_better", "cost": "lower_is_better", "land": "lower_is_better"},
              "manual_scores": {"safety": {"A1": 3, "A2": 3}, "cost": {"A1": 1, "A2": 1}, "land": {"A1": 0, "A2": 0}},
              "scale": "1-5", "equal_criterion": "score_zero", "sensitivity_step": 0.1}
    with pytest.raises(ValueError, match="missing_criteria"):
        mce(j, scores, "t", params, decision["out"])
    sel = mce(j, scores, "t", {**params, "missing_criteria": "drop_and_reweight"}, decision["out"])
    s = __import__("json").loads(sel.read_text())
    assert s["selected"] == "A2" and "emission" in s["criteria_dropped"]
    assert read_csv(decision["out"] / "mce_sensitivity.csv")


def test_sp41_fixed_plan(decision, register):
    from pattom.alternatives import sp41_fixed_plan

    p = sp41_fixed_plan(decision["cap"], {"north": "NS", "east": "EW"}, all_red_s=4, register=register)
    # y: NS 1200/3600 = 0.3333, EW 900/3000 = 0.3; L = 2 x 2 + 4 = 8; Co = (1.5 x 8 + 5) / (1 - 0.6333) = 46.4
    assert p["lost_time_s"] == 8 and abs(p["cycle_s"] - 46.4) < 0.1
