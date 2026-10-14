"""SUMO set-up and runs on a small synthetic four-arm junction (made-up numbers, not site data).

Needs SUMO installed (netconvert and sumo); skipped otherwise.
"""

import json
import shutil
import os

import pytest
import yaml

from pattom import sumo
from pattom.tables import read_csv

from test_calculations import write

have_sumo = shutil.which("sumo") or os.environ.get("SUMO_HOME")
pytestmark = pytest.mark.skipif(not have_sumo, reason="SUMO not installed")

ARMS = {"north": [0, 120], "south": [0, -120], "east": [120, 0], "west": [-120, 0]}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


@pytest.fixture
def setup(tmp_path):
    net = {"centre_xy": [0, 0],
           "approaches": {a: {"end_xy": xy, "lanes_in": 2, "lanes_out": 2, "speed_kmh": 40} for a, xy in ARMS.items()},
           "vtypes": {"car": {"length_m": 4.5, "min_gap_m": 2.0, "max_speed_kmh": 50, "accel": 2.0, "decel": 4.0}}}
    (tmp_path / "net.yaml").write_text(yaml.safe_dump(net))
    lines = {"lines": [{"name": f"{a}_in", "type": "arrival", "approach": a, "endpoints_px": [[0, 0], [1, 1]],
                        "direction": "left"} for a in ARMS]
             + [{"name": f"{a}_out", "type": "exit", "approach": a, "endpoints_px": [[0, 0], [1, 1]],
                 "direction": "right"} for a in ARMS],
             "movements": [{"approach": a, "movement": "through", "entry_line": f"{a}_in",
                            "exit_line": f"{OPPOSITE[a]}_out"} for a in ARMS]}
    (tmp_path / "lines.yaml").write_text(yaml.safe_dump(lines))
    counts = write(tmp_path / "interval_counts.csv",
                   ["slot", "interval_start_s", "interval_end_s", "line_name", "line_type", "approach", "movement",
                    "class", "count", "value_type"],
                   [{"slot": "t", "interval_start_s": 0, "interval_end_s": 600, "line_name": f"{a}_in",
                     "line_type": "arrival", "approach": a, "movement": m, "class": "car", "count": n,
                     "value_type": "measured"} for a in ARMS for m, n in (("through", 60), ("unknown", 6))])
    plan = lambda ns, ew: {"cycle_s": ns + ew + 6, "groups": {"NS": {"green_s": ns, "amber_s": 3},
                                                              "EW": {"green_s": ew, "amber_s": 3}}}
    (tmp_path / "alternatives.json").write_text(json.dumps(
        {"existing": {"id": "existing", "control": "fixed", "plan": plan(40, 20)}, "alternatives": []}))
    (tmp_path / "selected.json").write_text(json.dumps(
        {"plan": {"id": "A1", "control": "fixed", "plan": plan(30, 30)}}))
    return tmp_path


PARAMS = {"approach_groups": {"north": "NS", "south": "NS", "east": "EW", "west": "EW"}, "phase_order": ["NS", "EW"],
          "all_red_s": 2, "demand_line_type": "arrival", "unknown_movement": "exclude"}


def test_build_inputs_and_run(setup):
    out = setup / "sumo"
    info = sumo.build_inputs(setup / "interval_counts.csv", setup / "alternatives.json", setup / "selected.json",
                             setup / "lines.yaml", setup / "net.yaml", "t", PARAMS, out)
    data = json.loads(info.read_text())
    assert data["demand"]["unrouted_vehicles"] == 24 and set(data["links"]) == set(ARMS)
    tls = (out / "tls_existing.add.xml").read_text()
    assert 'duration="40.0"' in tls and 'duration="2.0"' in tls
    with pytest.raises(ValueError, match="several random seeds"):
        sumo.run_cases(info, "t", {"seeds": [1], "warmup_s": 60}, out, log=lambda m: None)
    res = sumo.run_cases(info, "t", {"seeds": [11, 23], "warmup_s": 60}, out, log=lambda m: None)
    rows = read_csv(res)
    assert {(r["case"], r["seed"]) for r in rows} == {("existing", "11"), ("existing", "23"), ("selected", "11"),
                                                     ("selected", "23")}
    assert all(int(r["vehicles"]) > 50 for r in rows)
    sd = write(setup / "stopped_delay.csv", ["approach", "mean_stopped_delay_s"],
               [{"approach": "north", "mean_stopped_delay_s": 20}])
    q = write(setup / "queue.csv", ["approach", "queue_length_m"], [{"approach": "north", "queue_length_m": 30}])
    cmp_ = sumo.compare_cases(res, sd, q, "t", {"emission_method": "none", "calibration_tolerance": 0.5}, out)
    table = read_csv(cmp_)
    assert {r["case"] for r in table} == {"existing", "selected", "observed", "calibration"}
    assert all(r["value_type"].startswith(("simulated", "derived")) for r in table)


def test_vtype_parameters_are_required(setup):
    net = yaml.safe_load((setup / "net.yaml").read_text())
    del net["vtypes"]["car"]["accel"]
    (setup / "net.yaml").write_text(yaml.safe_dump(net))
    with pytest.raises(ValueError, match="accel"):
        sumo.build_inputs(setup / "interval_counts.csv", setup / "alternatives.json", setup / "selected.json",
                          setup / "lines.yaml", setup / "net.yaml", "t", PARAMS, setup / "sumo")
