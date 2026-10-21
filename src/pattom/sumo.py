"""L SUMO: network, demand and signal plans; seeded runs. M comparison (FR-20 to FR-22).

Everything is built on this PC from the site data; nothing is downloaded.

- Network: from configs/sumo_network.yaml, written from the site layout and
  measurements (junction centre, the end of each approach, lanes, speed limit).
  netconvert builds the .net.xml.
- Vehicle types: their parameters must be given (length, min gap, max speed,
  accel, decel per class). SUMO's own defaults are not a registered source
  (D15); any attribute left out falls back to SUMO's default, and the run notes
  list it so it can be calibrated (T33).
- Demand: flows per route and interval from the counts. Arrival-line counts
  are the better demand when the junction is oversaturated; the choice is the
  user's. Counts without a known movement are excluded or spread over the known
  movements of the approach, as the user chooses; the number is reported.
- Signal plans: the existing plan (observed) and the MCE-selected alternative
  only (D1). Fixed-time plans become static programmes; actuated ones use
  SUMO's gap-based actuated control with the alternative's min and max green.
  Adaptive control needs external control (TraCI) and is refused.
- Runs: the same pre-chosen seeds, warm-up and duration for both cases.
  Results are simulated values, kept apart from the video measurements.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import yaml

from pattom.tables import num, read_csv, require, write_csv, write_meta

VTYPE_REQUIRED = ("length_m", "min_gap_m", "max_speed_kmh", "accel", "decel")


def sumo_tool(name: str) -> str:
    exe = shutil.which(name)
    if not exe and os.environ.get("SUMO_HOME"):
        cand = Path(os.environ["SUMO_HOME"]) / "bin" / (name + (".exe" if os.name == "nt" else ""))
        exe = str(cand) if cand.exists() else None
    if not exe:
        raise FileNotFoundError(f"{name} not found: install SUMO and set SUMO_HOME")
    return exe


# --- network ----------------------------------------------------------------------

def write_network(spec: dict[str, Any], out_dir: Path) -> Path:
    for k in ("centre_xy", "approaches"):
        if k not in spec:
            raise ValueError(f"sumo network: missing {k}")
    nodes = ET.Element("nodes")
    cx, cy = spec["centre_xy"]
    ET.SubElement(nodes, "node", id="C", x=str(cx), y=str(cy), type="traffic_light", tl="C")
    edges = ET.Element("edges")
    for name, a in sorted(spec["approaches"].items()):
        for k in ("end_xy", "lanes_in", "lanes_out", "speed_kmh"):
            if k not in a:
                raise ValueError(f"sumo network, approach {name}: missing {k} (site measurement)")
        x, y = a["end_xy"]
        ET.SubElement(nodes, "node", id=f"end_{name}", x=str(x), y=str(y), type="priority")
        v = f"{float(a['speed_kmh']) / 3.6:.3f}"
        ET.SubElement(edges, "edge", id=f"in_{name}", **{"from": f"end_{name}"}, to="C",
                      numLanes=str(a["lanes_in"]), speed=v)
        ET.SubElement(edges, "edge", id=f"out_{name}", **{"from": "C"}, to=f"end_{name}",
                      numLanes=str(a["lanes_out"]), speed=v)
    out_dir.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(nodes).write(out_dir / "pattom.nod.xml", encoding="utf-8", xml_declaration=True)
    ET.ElementTree(edges).write(out_dir / "pattom.edg.xml", encoding="utf-8", xml_declaration=True)
    net = out_dir / "pattom.net.xml"
    subprocess.run([sumo_tool("netconvert"), "--node-files", str(out_dir / "pattom.nod.xml"),
                    "--edge-files", str(out_dir / "pattom.edg.xml"), "--no-turnarounds", "true",
                    "--output-file", str(net), "--no-warnings", "true"], check=True, capture_output=True, text=True)
    return net


def tl_links(net: Path) -> list[str]:
    """Approach name of the incoming edge for each link index of the junction's signal."""
    links: dict[int, str] = {}
    for c in ET.parse(net).getroot().iter("connection"):
        if c.get("tl") == "C":
            links[int(c.get("linkIndex"))] = c.get("from").removeprefix("in_")
    return [links[i] for i in range(len(links))]


def tls_program(links: list[str], plan: dict[str, Any], control: str, approach_groups: dict[str, str],
                phase_order: list[str], all_red_s: float, program_id: str, actuated: dict[str, Any] | None = None) -> ET.Element:
    if control == "adaptive":
        raise ValueError("adaptive control needs external control (TraCI); not supported by the static SUMO set-up")
    kind = "actuated" if control == "actuated" else "static"
    root = ET.Element("additional")
    tl = ET.SubElement(root, "tlLogic", id="C", type=kind, programID=program_id, offset="0")
    for group in phase_order:
        on = {i for i, ap in enumerate(links) if approach_groups.get(ap) == group}
        state = lambda ch: "".join(ch if i in on else "r" for i in range(len(links)))
        if kind == "static":
            g = plan["groups"][group]
            ET.SubElement(tl, "phase", duration=f"{float(g['green_s']):.1f}", state=state("G"))
            ET.SubElement(tl, "phase", duration=f"{float(g['amber_s']):.1f}", state=state("y"))
        else:
            a = (actuated or {}).get(group) or {}
            for k in ("min_green_s", "max_green_s", "amber_s"):
                if k not in a:
                    raise ValueError(f"actuated plan, group {group}: missing {k}")
            ET.SubElement(tl, "phase", duration=f"{float(a['min_green_s']):.1f}", minDur=f"{float(a['min_green_s']):.1f}",
                          maxDur=f"{float(a['max_green_s']):.1f}", state=state("G"))
            ET.SubElement(tl, "phase", duration=f"{float(a['amber_s']):.1f}", state=state("y"))
        if all_red_s > 0:
            ET.SubElement(tl, "phase", duration=f"{all_red_s:.1f}", state="r" * len(links))
    return root


# --- demand -----------------------------------------------------------------------

def movement_exits(lines_yaml: Path) -> dict[tuple[str, str], str]:
    """(entry approach, movement) -> exit approach, from the movement definitions."""
    spec = yaml.safe_load(Path(lines_yaml).read_text(encoding="utf-8")) or {}
    approach_of = {l["name"]: l["approach"] for l in spec.get("lines") or []}
    return {(m["approach"], m["movement"]): approach_of[m["exit_line"]] for m in spec.get("movements") or []}


def demand(counts_csv: Path, exits: dict[tuple[str, str], str], line_type: str, unknown: str) -> tuple[list[dict], dict]:
    """Flows (veh/h) per interval, route and class; and what could not be routed."""
    if line_type not in ("arrival", "stop_line"):
        raise ValueError("demand_line_type must be arrival or stop_line")
    if unknown not in ("exclude", "proportional"):
        raise ValueError("unknown_movement must be exclude or proportional")
    known, unknown_n = defaultdict(float), defaultdict(float)
    for r in read_csv(counts_csv):
        if r["line_type"] != line_type:
            continue
        key = (float(r["interval_start_s"]), float(r["interval_end_s"]), r["approach"], r["class"])
        n = float(r["count"])
        dest = exits.get((r["approach"], r["movement"]))
        if dest:
            known[key + (dest,)] += n
        else:
            unknown_n[key] += n
    report = {"unrouted_vehicles": sum(unknown_n.values()), "policy": unknown}
    if unknown == "proportional":
        for (a, b, ap, cls), n in unknown_n.items():
            share = {k: v for k, v in known.items() if k[:4] == (a, b, ap, cls)}
            tot = sum(share.values())
            if not tot:
                continue
            for k, v in share.items():
                known[k] += n * v / tot
        report["spread_vehicles"] = sum(n for k, n in unknown_n.items()
                                        if any(kk[:4] == k for kk in known))
    flows = [{"begin": a, "end": b, "from": ap, "to": dest, "class": cls, "veh_per_h": n * 3600.0 / (b - a)}
             for (a, b, ap, cls, dest), n in sorted(known.items()) if n > 0]
    return flows, report


def write_routes(flows: list[dict], vtypes: dict[str, dict], path: Path) -> list[str]:
    root = ET.Element("routes")
    defaulted = []
    for cls, v in sorted(vtypes.items()):
        missing = [k for k in VTYPE_REQUIRED if k not in v]
        if missing:
            raise ValueError(f"vehicle type {cls}: missing {missing} (no SUMO default is used for these)")
        attrs = {"id": cls, "length": str(v["length_m"]), "minGap": str(v["min_gap_m"]),
                 "maxSpeed": f"{float(v['max_speed_kmh']) / 3.6:.3f}", "accel": str(v["accel"]), "decel": str(v["decel"])}
        for k, val in (v.get("extra") or {}).items():
            attrs[k] = str(val)
        defaulted.append(f"{cls}: SUMO default for {', '.join(a for a in ('sigma', 'tau', 'emergencyDecel', 'speedFactor') if a not in attrs)}")
        ET.SubElement(root, "vType", **attrs)
    for i, f in enumerate(sorted(flows, key=lambda f: (f["begin"], f["from"], f["to"], f["class"]))):
        if f["class"] not in vtypes:
            raise ValueError(f"no vehicle type for class {f['class']!r}")
        ET.SubElement(root, "flow", id=f"f{i}_{f['from']}_{f['to']}_{f['class']}", type=f["class"],
                      begin=f"{f['begin']:.1f}", end=f"{f['end']:.1f}", vehsPerHour=f"{f['veh_per_h']:.3f}",
                      **{"from": f"in_{f['from']}"}, to=f"out_{f['to']}", departLane="best", departSpeed="max")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return defaulted


def build_inputs(counts_csv: Path, alternatives_json: Path, selected_json: Path, lines_yaml: Path,
                 network_yaml: Path, slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "approach_groups", "phase_order", "all_red_s", "demand_line_type", "unknown_movement",
            why="phase groups and order, the measured all-red time, and the demand choices")
    spec = yaml.safe_load(Path(network_yaml).read_text(encoding="utf-8")) or {}
    require(spec, "vtypes", why="vehicle type parameters in the network file (no SUMO defaults, D15)")
    net = write_network(spec, out_dir)
    links = tl_links(net)
    flows, report = demand(counts_csv, movement_exits(lines_yaml), params["demand_line_type"],
                           params["unknown_movement"])
    if not flows:
        raise ValueError("no routable flows: check movements in the counting lines and demand_line_type")
    defaulted = write_routes(flows, spec["vtypes"], out_dir / "pattom.rou.xml")
    alts = json.loads(Path(alternatives_json).read_text(encoding="utf-8"))
    sel = json.loads(Path(selected_json).read_text(encoding="utf-8"))["plan"]
    cases = {"existing": alts["existing"], "selected": sel}
    begin, end = min(f["begin"] for f in flows), max(f["end"] for f in flows)
    for case, alt in cases.items():
        prog = tls_program(links, alt.get("plan") or {}, alt["control"], params["approach_groups"], params["phase_order"],
                           float(params["all_red_s"]), case, alt.get("actuated"))
        ET.ElementTree(prog).write(out_dir / f"tls_{case}.add.xml", encoding="utf-8", xml_declaration=True)
        cfg = ET.Element("configuration")
        inp = ET.SubElement(cfg, "input")
        ET.SubElement(inp, "net-file", value=net.name)
        ET.SubElement(inp, "route-files", value="pattom.rou.xml")
        ET.SubElement(inp, "additional-files", value=f"tls_{case}.add.xml")
        t = ET.SubElement(cfg, "time")
        ET.SubElement(t, "begin", value=f"{begin:.0f}")
        ET.SubElement(t, "end", value=f"{end:.0f}")
        ET.ElementTree(cfg).write(out_dir / f"{case}.sumocfg", encoding="utf-8", xml_declaration=True)
    manifest = {"slot": slot, "cases": {c: f"{c}.sumocfg" for c in cases}, "selected": sel["id"],
                "begin_s": begin, "end_s": end, "links": links, "demand": report, "vtype_defaults": defaulted,
                "flows": len(flows), "note": "Simulated set-up built from site data; nothing downloaded."}
    out = out_dir / "sumo_inputs.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_meta(out_dir / "sumo_inputs.run.json", "L.sumo_inputs", slot,
               {"interval_counts": counts_csv, "alternatives": alternatives_json, "selected": selected_json,
                "lines": lines_yaml, "network": network_yaml}, params)
    return out


# --- runs -------------------------------------------------------------------------

RESULT_FIELDS = ["case", "seed", "vehicles", "mean_waiting_s", "mean_travel_time_s", "mean_time_loss_s", "mean_stops",
                 "throughput", "max_queue_m", "mean_queue_m", "waiting_s_by_type", "value_type"]


def _tripinfo(path: Path, warmup: float) -> list[dict[str, Any]]:
    return [{k: t.get(k) for k in ("vType", "depart", "duration", "waitingTime", "waitingCount", "timeLoss", "routeLength")}
            for t in ET.parse(path).getroot().iter("tripinfo") if float(t.get("depart")) >= warmup]


def _queues(path: Path, warmup: float) -> tuple[float, float]:
    lengths = []
    for step in ET.parse(path).getroot().iter("data"):
        if float(step.get("timestep")) < warmup:
            continue
        total = defaultdict(float)
        for lane in step.iter("lane"):
            if lane.get("id", "").startswith("in_"):
                total[lane.get("id").rsplit("_", 1)[0]] = max(total[lane.get("id").rsplit("_", 1)[0]],
                                                              float(lane.get("queueing_length") or 0))
        lengths.extend(total.values())
    return (max(lengths), mean(lengths)) if lengths else (0.0, 0.0)


def run_cases(inputs_json: Path, slot: str, params: dict[str, Any], out_dir: Path, log=print) -> Path:
    require(params, "seeds", "warmup_s", why="pre-chosen seeds and warm-up, the same for both cases")
    seeds = [int(s) for s in params["seeds"]]
    if len(seeds) < 2:
        raise ValueError("use several random seeds (at least 2), chosen before the runs")
    info = json.loads(Path(inputs_json).read_text(encoding="utf-8"))
    sumo = sumo_tool("sumo")
    warm = float(params["warmup_s"])
    base = Path(inputs_json).parent
    rows = []
    for case, cfg in info["cases"].items():
        for seed in seeds:
            tag = f"{case}_seed{seed}"
            trip, queue = out_dir / f"{tag}.tripinfo.xml", out_dir / f"{tag}.queue.xml"
            log(f"sumo: {tag}")
            subprocess.run([sumo, "-c", str(base / cfg), "--seed", str(seed), "--tripinfo-output", str(trip),
                            "--queue-output", str(queue), "--no-step-log", "true", "--no-warnings", "true",
                            "--duration-log.disable", "true"], check=True, capture_output=True, text=True)
            trips = _tripinfo(trip, warm)
            by_type = defaultdict(float)
            for t in trips:
                by_type[t["vType"]] += float(t["waitingTime"])
            qmax, qmean = _queues(queue, warm)
            avg = lambda k: round(mean(float(t[k]) for t in trips), 3) if trips else ""
            rows.append({"case": case, "seed": seed, "vehicles": len(trips), "mean_waiting_s": avg("waitingTime"),
                         "mean_travel_time_s": avg("duration"), "mean_time_loss_s": avg("timeLoss"),
                         "mean_stops": avg("waitingCount"), "throughput": len(trips), "max_queue_m": round(qmax, 2),
                         "mean_queue_m": round(qmean, 2), "waiting_s_by_type": json.dumps(dict(by_type)),
                         "value_type": "simulated"})
    out = write_csv(out_dir / "sumo_results.csv", RESULT_FIELDS, rows)
    write_meta(out_dir / "sumo_results.run.json", "L.sumo_run", slot, {"sumo_inputs": inputs_json}, params,
               notes="Simulated values; not measurements and never used in the MCE (D1).")
    return out


# --- M comparison -----------------------------------------------------------------

COMPARE_FIELDS = ["case", "metric", "mean", "sd", "n_seeds", "unit", "value_type", "note"]
METRICS = {"mean_waiting_s": "s/veh", "mean_travel_time_s": "s/veh", "mean_time_loss_s": "s/veh",
           "mean_stops": "stops/veh", "throughput": "veh", "max_queue_m": "m", "mean_queue_m": "m"}


def compare_cases(results_csv: Path, stopped_delay_csv: Path, queue_csv: Path, slot: str, params: dict[str, Any],
                  out_dir: Path, register=None) -> Path:
    require(params, "emission_method", why="how SUMO-case emissions are computed is open (O18): none or registered_idle_factors")
    rows = read_csv(results_csv)
    out = []
    for case in sorted({r["case"] for r in rows}):
        mine = [r for r in rows if r["case"] == case]
        for m, unit in METRICS.items():
            vals = [float(r[m]) for r in mine if r[m] != ""]
            out.append({"case": case, "metric": m, "mean": round(mean(vals), 3) if vals else "",
                        "sd": round(stdev(vals), 3) if len(vals) > 1 else "", "n_seeds": len(vals), "unit": unit,
                        "value_type": "simulated", "note": ""})
        if params["emission_method"] == "registered_idle_factors":
            from pattom.register import Register

            register = register or Register.load()
            require(params, "class_fuel", why="fuel per vehicle type, as for the video estimate")
            per_seed = []
            for r in mine:
                kg = 0.0
                for vtype, wait in json.loads(r["waiting_s_by_type"]).items():
                    spec = params["class_fuel"].get(vtype)
                    if not spec:
                        raise ValueError(f"class_fuel has no entry for vehicle type {vtype}")
                    rate, _ = register.item("idle_fuel_l_per_h", spec["idle_row"])
                    factor, _ = register.item("fuel_co2_kg_per_l", spec["fuel"])
                    kg += wait / 3600 * float(rate) * float(factor)
                per_seed.append(kg)
            out.append({"case": case, "metric": "idle_co2_kg", "mean": round(mean(per_seed), 3),
                        "sd": round(stdev(per_seed), 3) if len(per_seed) > 1 else "", "n_seeds": len(per_seed),
                        "unit": "kg", "value_type": "simulated (estimated)",
                        "note": "registered idle factors x SUMO waiting time; relative comparison only, source not checked"})
    observed = []
    d = [num(r["mean_stopped_delay_s"]) for r in read_csv(stopped_delay_csv)]
    d = [x for x in d if x is not None]
    q = [num(r["queue_length_m"]) for r in read_csv(queue_csv)] if queue_csv and Path(queue_csv).is_file() else []
    q = [x for x in q if x is not None]
    if d:
        observed.append({"case": "observed", "metric": "mean_stopped_delay_s", "mean": round(mean(d), 3), "sd": "",
                         "n_seeds": "", "unit": "s/veh", "value_type": "derived (video)",
                         "note": "compare with SUMO mean_waiting_s of the existing case"})
    if q:
        observed.append({"case": "observed", "metric": "queue_length_m", "mean": round(mean(q), 3),
                         "sd": round(stdev(q), 3) if len(q) > 1 else "", "n_seeds": "", "unit": "m",
                         "value_type": "derived (video)", "note": "compare with SUMO mean_queue_m of the existing case"})
    tol = params.get("calibration_tolerance")  # O14; checked only when given
    if tol and d:
        ex = next((r for r in out if r["case"] == "existing" and r["metric"] == "mean_waiting_s"), None)
        if ex and ex["mean"] != "":
            diff = abs(ex["mean"] - mean(d)) / mean(d)
            observed.append({"case": "calibration", "metric": "waiting_vs_stopped_delay", "mean": round(diff, 4),
                             "sd": "", "n_seeds": "", "unit": "relative difference",
                             "value_type": "derived", "note": f"tolerance {tol}: {'within' if diff <= float(tol) else 'outside'}"})
    path = write_csv(out_dir / "comparison.csv", COMPARE_FIELDS, out + observed)
    write_meta(out_dir / "comparison.run.json", "M.comparison", slot,
               {"sumo_results": results_csv, "stopped_delay": stopped_delay_csv,
                **({"queue": queue_csv} if queue_csv and Path(queue_csv).is_file() else {})}, params,
               notes="Simulated and video values are labelled and kept in separate rows (D7).")
    return path
