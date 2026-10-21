"""Flow test of steps H to M (problems -> alternatives -> scoring -> MCE -> SUMO -> comparison).

Every number below is a SOFTWARE TEST FIXTURE, not project data: it only checks
that the stages connect and SUMO runs. Nothing here is a site value.
"""

import csv
import shutil

import pytest
import yaml

from pattom.graph import nodes

SLOT = "flowtest"


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "runs" / SLOT / "clip"
    d.mkdir(parents=True)
    idx = write_csv(d / "congestion_index.csv", [
        {"slot": SLOT, "approach": a, "interval_start_s": 0.0, "interval_end_s": 900.0, "volume_pcu_h": q,
         "capacity_pcu_h": 1200.0, "vc_ratio": round(q / 1200, 3), "mean_stopped_delay_s": 20.0,
         "max_queue_length_m": 30.0, "green_s": 40.0, "cycle_s": 100.0, "congestion_index": ci}
        for a, q, ci in (("north", 900.0, 0.8), ("east", 400.0, 0.2))])
    shutil.copy(idx, d / "approach_indicators.csv")
    write_csv(d / "emissions.csv", [{"slot": SLOT, "approach": "north", "interval_start_s": 0.0,
                                     "pollutant": "CO2", "value": 50.0}])
    write_csv(d / "stopped_delay.csv", [{"slot": SLOT, "approach": "north", "interval_start_s": 0.0,
                                         "mean_stopped_delay_s": 20.0}])
    write_csv(d / "interval_counts.csv", [
        {"slot": SLOT, "interval_start_s": 0.0, "interval_end_s": 300.0, "line_name": f"{a[0].upper()}_arr",
         "line_type": "arrival", "approach": a, "movement": "through", "class": "car", "count": n, "value_type": "measured"}
        for a, n in (("north", 40), ("east", 20))])
    sig = tmp_path / "signal_log.csv"
    sig.write_text("time_s,signal_head,state\n0,N,green\n40,N,amber\n43,N,red\n100,N,green\n140,N,amber\n143,N,red\n200,N,green\n"
                   "0,E,red\n43,E,green\n90,E,amber\n93,E,red\n143,E,green\n190,E,amber\n193,E,red\n", encoding="utf-8")
    lines = tmp_path / "lines.yaml"
    lines.write_text(yaml.safe_dump({"lines": [
        {"name": n, "type": t, "approach": a, "endpoints_px": [[0, 0], [1, 1]], "direction": "left"}
        for n, t, a in (("N_arr", "arrival", "north"), ("E_arr", "arrival", "east"),
                        ("S_exit", "exit", "south"), ("W_exit", "exit", "west"))],
        "movements": [{"approach": "north", "movement": "through", "entry_line": "N_arr", "exit_line": "S_exit"},
                      {"approach": "east", "movement": "through", "entry_line": "E_arr", "exit_line": "W_exit"}]}),
        encoding="utf-8")
    groups = {"NS": {"green_s": 40, "amber_s": 3}, "EW": {"green_s": 47, "amber_s": 3}}
    decision = tmp_path / "decision.yaml"
    decision.write_text(yaml.safe_dump({
        "test_values": True,
        "rules": [{"indicator": "vc_ratio", "op": ">", "value": 0.5, "problem": "north high V/C"}],
        "head_groups": {"N": "NS", "E": "EW"},
        "alternatives": [
            {"id": "A1", "description": "more NS green", "control": "fixed", "problem_addressed": "north high V/C",
             "plan": {"cycle_s": 100, "groups": {"NS": {"green_s": 55, "amber_s": 3}, "EW": {"green_s": 32, "amber_s": 3}}}},
            {"id": "A2", "description": "longer cycle", "control": "fixed", "problem_addressed": "north high V/C",
             "plan": {"cycle_s": 120, "groups": {"NS": {"green_s": 60, "amber_s": 3}, "EW": {"green_s": 47, "amber_s": 3}}}}],
        "pre_sumo": {"approach_groups": {"north": "NS", "east": "EW"}, "effective_green": "displayed_green",
                     "congestion_measure": "max_vc", "volume_stat": "max", "delay_method": "none"},
        "mce": {"weights": {"congestion": 0.4, "emission": 0.2, "safety": 0.2, "cost": 0.1, "land": 0.1},
                "directions": {"congestion": "higher_is_better", "emission": "higher_is_better",
                               "safety": "higher_is_better", "cost": "lower_is_better", "land": "lower_is_better"},
                "manual_scores": {"safety": {"A1": 3, "A2": 3}, "cost": {"A1": 1, "A2": 1}, "land": {"A1": 0, "A2": 0}},
                "scale": "1-5 test", "equal_criterion": "score_zero", "sensitivity_step": 0.1,
                "missing_criteria": "drop_and_reweight"},
    }), encoding="utf-8")
    sumo = tmp_path / "sumo.yaml"
    sumo.write_text(yaml.safe_dump({
        "test_values": True, "centre_xy": [0, 0],
        "approaches": {"north": {"end_xy": [0, 150], "lanes_in": 2, "lanes_out": 2, "speed_kmh": 40},
                       "south": {"end_xy": [0, -150], "lanes_in": 2, "lanes_out": 2, "speed_kmh": 40},
                       "east": {"end_xy": [150, 0], "lanes_in": 2, "lanes_out": 2, "speed_kmh": 40},
                       "west": {"end_xy": [-150, 0], "lanes_in": 2, "lanes_out": 2, "speed_kmh": 40}},
        "vtypes": {"car": {"length_m": 4.5, "min_gap_m": 2.0, "max_speed_kmh": 50, "accel": 2.0, "decel": 4.0}},
        "inputs": {"approach_groups": {"north": "NS", "south": "NS", "east": "EW", "west": "EW"},
                   "phase_order": ["NS", "EW"], "all_red_s": 0, "demand_line_type": "arrival",
                   "unknown_movement": "exclude"},
        "run": {"seeds": [1, 2], "warmup_s": 0},
        "comparison": {"emission_method": "none"},
    }), encoding="utf-8")
    return {"dir": d, "signal": sig, "lines": lines, "decision": decision, "sumo": sumo}


def test_decision_chain(run):
    d, cfg = run["dir"], str(run["decision"])
    prob = nodes._problems({"index": d / "congestion_index.csv", "emissions": d / "emissions.csv"}, {"config": cfg})
    assert "north high V/C" in open(prob["problems"]).read()
    alts = nodes._alternatives({"problems": prob["problems"]}, {"config": cfg, "signal_log": str(run["signal"])})
    pre = nodes._pre_sumo({"alternatives": alts["alternatives"], "indicators": d / "approach_indicators.csv"}, {"config": cfg})
    sel = nodes._mce({"alternatives": alts["alternatives"], "scores": pre["scores"]}, {"config": cfg})
    import json
    assert json.loads(open(sel["selected"]).read())["selected"] in ("A1", "A2")
    for n in ("problems", "alternatives", "pre_sumo", "mce"):
        assert nodes.NODE_TYPES[n].gate_checker({**nodes.NODE_TYPES[n].params, "config": cfg})["locked"] is False


def test_sumo_chain(run):
    pytest.importorskip("yaml")
    from pattom.sumo import sumo_tool

    try:
        sumo_tool("sumo"), sumo_tool("netconvert")
    except FileNotFoundError:
        pytest.skip("SUMO not installed")
    d, cfg = run["dir"], str(run["decision"])
    prob = nodes._problems({"index": d / "congestion_index.csv", "emissions": d / "emissions.csv"}, {"config": cfg})
    alts = nodes._alternatives({"problems": prob["problems"]}, {"config": cfg, "signal_log": str(run["signal"])})
    pre = nodes._pre_sumo({"alternatives": alts["alternatives"], "indicators": d / "approach_indicators.csv"}, {"config": cfg})
    sel = nodes._mce({"alternatives": alts["alternatives"], "scores": pre["scores"]}, {"config": cfg})
    inp = nodes._sumo_inputs({"counts": d / "interval_counts.csv", "selected": sel["selected"]},
                             {"config": str(run["sumo"]), "lines": str(run["lines"])})
    res = nodes._sumo_run({"sumo_inputs": inp["sumo_inputs"]}, {"config": str(run["sumo"])})
    rows = list(csv.DictReader(open(res["results"])))
    assert {r["case"] for r in rows} == {"existing", "selected"} and all(int(r["vehicles"]) > 0 for r in rows)
    cmp_ = nodes._comparison({"results": res["results"], "delays": d / "stopped_delay.csv"}, {"config": str(run["sumo"])})
    assert "mean_waiting_s" in open(cmp_["comparison"]).read()
