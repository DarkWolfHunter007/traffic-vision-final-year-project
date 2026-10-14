"""The whole chain, count to SUMO comparison, through the pipeline harness.

A synthetic 10-minute scene (made-up numbers, not site data): two approaches,
north (southbound) and east (westbound), crossing a signalised junction with a
60 s cycle. Vehicles stop at red and queue. Ground metres = pixels / 100.
Needs SUMO for the last blocks (skipped otherwise).
"""

import csv
import json
import os
import shutil

import pytest
import yaml

from pattom.harness import Pipeline
from pattom.tables import read_csv

have_sumo = shutil.which("sumo") or os.environ.get("SUMO_HOME")
pytestmark = pytest.mark.skipif(not have_sumo, reason="SUMO not installed")

CYCLE = 60.0
GREEN = {"N_main": (0.0, 25.0), "E_main": (30.0, 55.0)}   # green start, green end within the cycle
AMBER = 3.0


def is_green(head, t):
    a, b = GREEN[head]
    return a <= t % CYCLE < b


def next_green(head, t):
    a, _ = GREEN[head]
    k = (t - a) // CYCLE + 1
    return a + k * CYCLE


def scene_rows():
    """Each vehicle drives at 10 m/s, waits at the stop line (or behind the queue) during red."""
    rows, summary, tid = [], [], 0
    for head, approach in (("N_main", "north"), ("E_main", "east")):
        waiting_until, queue_at = {}, {}
        for i in range(55):
            tid += 1
            t0 = 2.0 + i * 10.0 + (0 if approach == "north" else 5.0)
            reach = t0 + 1.0                       # 10 m to the stop line
            stop_from = stop_until = None
            if not is_green(head, reach):
                g = next_green(head, reach)
                q = queue_at.get(g, 0)
                queue_at[g] = q + 1
                stop_from, stop_until = reach - 0.6 * q, g + 2.0 * q
            cls = "car" if i % 3 else "two_wheeler"
            t, samples = t0, []
            while True:
                if stop_from is None:
                    d = 10.0 * (t - t0)
                elif t < stop_from:
                    d = 10.0 * (t - t0)
                elif t < stop_until:
                    d = 10.0 * (stop_from - t0)
                else:
                    d = 10.0 * (stop_from - t0) + 10.0 * (t - stop_until)
                if d > 21.0 or t > 600:
                    break
                samples.append((round(t, 2), d))
                t += 0.2
            for t, d in samples:
                if approach == "north":
                    u, v = 300.0, d * 100.0                  # moving down the image
                else:
                    u, v = 2000.0 - d * 100.0, 500.0         # moving left
                gx, gy = u / 100.0, v / 100.0
                rows.append({"frame": int(round(t * 30)), "time_s": t, "track_id": tid, "class": cls, "confidence": 0.8,
                             "x1": u - 60, "y1": v - 40, "x2": u + 60, "y2": v, "ground_x_m": gx, "ground_y_m": gy})
            summary.append({"track_id": tid, "first_time_s": samples[0][0], "last_time_s": samples[-1][0],
                            "n_boxes": len(samples), "majority_class": cls, "class_changes": 0, "classes_seen": cls})
    rows.sort(key=lambda r: (r["frame"], r["track_id"]))
    return rows, summary


def write(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def repo(tmp_path):
    from pattom.paths import REPO_ROOT

    (tmp_path / "sources").mkdir()
    shutil.copy(REPO_ROOT / "sources/register.yaml", tmp_path / "sources/register.yaml")
    run = tmp_path / "runs/demo/scene"
    rows, summary = scene_rows()
    write(run / "tracks.csv", rows)
    write(run / "track_summary.csv", summary)
    (run / "tracks.run.json").write_text(json.dumps({"slot": "demo", "video_file": "", "video_sha256": "", "fps": 30,
                                                     "width": 2000, "height": 2000, "tracker": "synthetic"}))
    # Phase log for ten cycles (synthetic).
    log = []
    for c in range(10):
        base = c * CYCLE
        for head, grp in (("N_main", "NS"), ("E_main", "EW")):
            g0, g1 = GREEN[head]
            log += [{"slot": "demo", "time_s": base + g0, "signal_head": head, "state": "green", "phase_group": grp},
                    {"slot": "demo", "time_s": base + g1, "signal_head": head, "state": "amber", "phase_group": grp},
                    {"slot": "demo", "time_s": base + g1 + AMBER, "signal_head": head, "state": "red", "phase_group": grp}]
    log.sort(key=lambda r: r["time_s"])
    write(tmp_path / "runs/demo/phase_log.csv", log)
    write(run / "manual_counts.csv", [{"slot": "demo", "window_start_s": 0, "window_end_s": 300,
                                       "line_name": "N_stop", "class": "car", "count": 21}])
    cfg = tmp_path / "configs"
    cfg.mkdir()
    lines = {"lines": [{"name": "N_stop", "type": "stop_line", "approach": "north", "endpoints_px": [[0, 1000], [1000, 1000]], "direction": "left"},
                       {"name": "S_exit", "type": "exit", "approach": "south", "endpoints_px": [[0, 1900], [1000, 1900]], "direction": "left"},
                       {"name": "E_stop", "type": "stop_line", "approach": "east", "endpoints_px": [[1000, 0], [1000, 1000]], "direction": "left"},
                       {"name": "W_exit", "type": "exit", "approach": "west", "endpoints_px": [[100, 0], [100, 1000]], "direction": "left"}],
             "movements": [{"approach": "north", "movement": "through", "entry_line": "N_stop", "exit_line": "S_exit"},
                           {"approach": "east", "movement": "through", "entry_line": "E_stop", "exit_line": "W_exit"}]}
    (cfg / "lines.yaml").write_text(yaml.safe_dump(lines))
    pts = [{"id": f"P{i}", "px": [u, v], "m": [u / 100, v / 100], "role": "fit"}
           for i, (u, v) in enumerate([(0, 0), (2000, 0), (2000, 2000), (0, 2000)])]
    pts.append({"id": "C", "px": [700, 900], "m": [7, 9], "role": "check"})
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration/ground.yaml").write_text(yaml.safe_dump(
        {"mappings": {"all": {"zone_px": [[-5, -5], [2005, -5], [2005, 2005], [-5, 2005]], "points": pts}}}))
    (cfg / "alternatives.yaml").write_text(yaml.safe_dump({"alternatives": [
        {"id": "A1", "description": "shift 5 s to east", "control": "fixed", "problem_addressed": "east queue",
         "plan": {"cycle_s": 60, "groups": {"NS": {"green_s": 22, "amber_s": 3}, "EW": {"green_s": 28, "amber_s": 3}}}},
        {"id": "A2", "description": "longer cycle", "control": "fixed", "problem_addressed": "east queue",
         "plan": {"cycle_s": 80, "groups": {"NS": {"green_s": 34, "amber_s": 3}, "EW": {"green_s": 34, "amber_s": 3}}}}]}))
    (cfg / "sumo_network.yaml").write_text(yaml.safe_dump({
        "centre_xy": [0, 0], "approaches": {a: {"end_xy": xy, "lanes_in": 1, "lanes_out": 1, "speed_kmh": 36}
                                            for a, xy in {"north": [0, 100], "south": [0, -100], "east": [100, 0],
                                                          "west": [-100, 0]}.items()},
        "vtypes": {c: {"length_m": L, "min_gap_m": 2, "max_speed_kmh": 40, "accel": 2, "decel": 4}
                   for c, L in (("car", 4.5), ("two_wheeler", 2.0))}}))
    groups = {"north": "NS", "east": "EW"}
    fuel = {"car": {"idle_row": "car_petrol", "fuel": "petrol"}, "two_wheeler": {"idle_row": "motorcycle_petrol", "fuel": "petrol"}}
    definition = {"stopped_speed_kmh": 1.8, "speed_window_s": 1.0, "definition_version": "synthetic-test"}
    settings = {
        "review": {"low_confidence": 0.5, "edge_margin_px": 50, "random_frames": 3, "seed": 1, "min_gap_s": 2},
        "stopped-delay": {**definition, "interval_s": 300},
        "queue": {**definition, "measure_at": "max_during_red", "approach_heads": {"north": "N_main", "east": "E_main"}},
        "capacity-vc": {"pcu_table": "table_3_1", "class_rows": {"car": "passenger_car", "two_wheeler": "motorcycle_scooter"},
                        "approaches": {"north": {"width_m": 7, "gradient_pct": 0, "signal_head": "N_main", "volume_line": "N_stop"},
                                       "east": {"width_m": 7, "gradient_pct": 0, "signal_head": "E_main", "volume_line": "E_stop"}},
                        "effective_green": "green"},
        "congestion-index": {"formula_version": "synthetic", "interval_s": 300, "indicators": [
            {"source": "capacity_vc", "weight": 0.5, "direction": "higher_is_worse", "normalise": {"method": "minmax"}},
            {"source": "stopped_delay", "weight": 0.5, "direction": "higher_is_worse", "normalise": {"method": "minmax"}}]},
        "emissions": {"class_fuel": fuel, "interval_s": 300},
        "analysis": {"interval_s": 300, "rules": [{"indicator": "queue_length_m", "op": ">", "value": 3, "problem": "east queue"}]},
        "pre-sumo-scoring": {"approach_groups": groups, "effective_green": "green", "congestion_measure": "max_vc",
                             "volume_stat": "mean", "delay_method": "none"},
        "mce": {"weights": {"congestion": 0.4, "emission": 0.3, "safety": 0.1, "cost": 0.1, "land": 0.1},
                "directions": {"congestion": "higher_is_better", "emission": "higher_is_better", "safety": "higher_is_better",
                               "cost": "lower_is_better", "land": "lower_is_better"},
                "manual_scores": {"safety": {"A1": 3, "A2": 3}, "cost": {"A1": 1, "A2": 1}, "land": {"A1": 0, "A2": 0}},
                "scale": "1-5", "equal_criterion": "score_zero", "sensitivity_step": 0.1,
                "missing_criteria": "drop_and_reweight"},
        "sumo-inputs": {"approach_groups": {"north": "NS", "south": "NS", "east": "EW", "west": "EW"},
                        "phase_order": ["NS", "EW"], "all_red_s": 0, "demand_line_type": "stop_line",
                        "unknown_movement": "exclude"},
        "sumo-run": {"seeds": [11, 23], "warmup_s": 60},
        "comparison": {"emission_method": "registered_idle_factors", "class_fuel": fuel},
    }
    (cfg / "study_settings.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
    return tmp_path


def test_count_to_comparison(repo):
    s = {"settings_file": "configs/study_settings.yaml"}
    spec = {"slot": "demo",
            "inputs": {"tracks": "runs/demo/scene/tracks.csv", "tracks.ground": "runs/demo/scene/tracks.csv",
                       "track_summary": "runs/demo/scene/track_summary.csv", "phase_log": "runs/demo/phase_log.csv",
                       "manual_counts": "runs/demo/scene/manual_counts.csv"},
            "blocks": [{"use": "review", "params": s}, {"use": "count", "params": {"interval_s": 300}},
                       "signal-phases", "count-validation",
                       {"use": "stopped-delay", "params": s}, {"use": "queue", "params": s},
                       {"use": "capacity-vc", "params": s}, {"use": "congestion-index", "params": s},
                       {"use": "emissions", "params": s}, {"use": "analysis", "params": s}, "alternatives",
                       {"use": "pre-sumo-scoring", "params": s}, {"use": "mce", "params": s},
                       {"use": "sumo-inputs", "params": s}, {"use": "sumo-run", "params": s},
                       {"use": "comparison", "params": s}]}
    p = Pipeline.from_dict(spec)
    p.repo_root, p.runs_dir = repo, repo / "runs"
    assert p.check() == []
    manifest = p.run()
    assert all(step["status"] == "done" for step in manifest["steps"]), manifest["steps"]

    run = repo / "runs/demo/scene"
    counts = read_csv(run / "interval_counts.csv")
    assert {r["line_name"] for r in counts} == {"N_stop", "E_stop"}
    delay = {r["approach"]: float(r["mean_stopped_delay_s"]) for r in read_csv(run / "stopped_delay.csv")
             if r["interval_start_s"] == "0.0"}
    assert delay["north"] > 0 and delay["east"] > 0
    assert max(float(r["queue_length_m"]) for r in read_csv(run / "queue.csv")) > 0
    assert all(0 < float(r["vc_ratio"]) for r in read_csv(run / "capacity_vc.csv"))
    assert any(r["congestion_index"] for r in read_csv(run / "congestion_index.csv"))
    assert all(r["value_type"] == "estimated" for r in read_csv(run / "emissions.csv"))
    assert read_csv(run / "problems.csv")
    err = read_csv(run / "count_error.csv")[0]
    assert err["manual"] == "21" and err["automatic"] != ""
    sel = json.loads((repo / "runs/demo/decision/selected_alternative.json").read_text())
    assert sel["selected"] in ("A1", "A2") and "emission" in sel["criteria_dropped"]
    cmp_ = read_csv(repo / "sumo/demo/comparison.csv")
    assert {r["case"] for r in cmp_} >= {"existing", "selected", "observed"}
    assert any(r["metric"] == "idle_co2_kg" for r in cmp_)
    assert read_csv(run / "review_queue.csv")
