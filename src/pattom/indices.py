"""G Congestion index (FR-14) and baseline emission estimate (FR-15, FR-16); H problem list.

Congestion index: the formula is open (O4) and needs the guide's approval, so
the indicators, their normalisation, direction and weights are all passed in.
CI = sum(weight_i x n_i), with each indicator normalised to 0..1 where 1 is
the worst; the weights must add up to 1.

Emissions, phase 1 (D13): CO2 while stopped = stopped seconds x idle fuel rate x
fuel CO2 factor, from the source register. Fuel per class is an assumption
(the video shows the vehicle class, not its fuel), so it is passed in and every row is "estimated". The moving part needs per-km
factors (ARAI 2007 Table I); while those are not registered it is reported as
a gap, not filled. Stopped time is used as idle time: engines switched off at
the signal are not seen in the video, which is stated in each row.

Problems: indicators per approach and interval are compared with rules the
user writes (indicator, comparison, value); no threshold is built in.
"""

from __future__ import annotations

import operator
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from pattom.register import Register, SourceGap
from pattom.tables import num, read_csv, require, write_csv, write_meta
from pattom.values import ValueType

# --- congestion index -----------------------------------------------------------

INDICATOR_SOURCES = {"capacity_vc": "vc_ratio", "stopped_delay": "mean_stopped_delay_s", "queue": "queue_length_m"}
CI_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "congestion_index", "band", "indicators",
             "missing", "formula_version", "value_type"]


def _interval_rows(tables: dict[str, list[dict]], interval_s: float) -> dict[tuple[str, float], dict[str, list[float]]]:
    """(approach, interval start) -> indicator source -> values."""
    out: dict[tuple[str, float], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for source, rows in tables.items():
        col = INDICATOR_SOURCES[source]
        for r in rows:
            v = num(r.get(col))
            if v is None:
                continue
            start = num(r.get("interval_start_s"))
            if start is None:  # queue rows are per cycle
                start = float(int(float(r["cycle_start"]) // interval_s) * interval_s)
            out[(r["approach"], start)][source].append(v)
    return out


def congestion_index(tables: dict[str, Path], slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "indicators", "formula_version",
            why="the congestion-index formula is open (O4); give indicators, normalisation, directions and weights")
    spec = params["indicators"]
    total_w = sum(float(i["weight"]) for i in spec)
    if abs(total_w - 1.0) > 1e-6:
        raise ValueError(f"indicator weights add up to {total_w}, not 1")
    for i in spec:
        if i["source"] not in INDICATOR_SOURCES:
            raise ValueError(f"indicator source must be one of {sorted(INDICATOR_SOURCES)}")
        if i.get("direction") not in ("higher_is_worse", "lower_is_worse"):
            raise ValueError(f"indicator {i['source']}: direction must be higher_is_worse or lower_is_worse")
        if (i.get("normalise") or {}).get("method") not in ("minmax", "reference"):
            raise ValueError(f"indicator {i['source']}: normalise.method must be minmax or reference")
    interval = float(params.get("interval_s", 900.0))
    grouped = _interval_rows({s: read_csv(p) for s, p in tables.items()}, interval)
    agg = {k: {s: (max(v) if s == "queue" and params.get("queue_aggregate") == "max" else mean(v))
               for s, v in d.items()} for k, d in grouped.items()}
    ranges = {}
    for i in spec:
        vals = [a[i["source"]] for a in agg.values() if i["source"] in a]
        n = i["normalise"]
        ranges[i["source"]] = (float(n["min"]), float(n["max"])) if n["method"] == "reference" else \
            ((min(vals), max(vals)) if vals else (0.0, 0.0))
    bands = params.get("bands") or []
    rows = []
    for (approach, start), a in sorted(agg.items()):
        missing = [i["source"] for i in spec if i["source"] not in a]
        parts = {}
        for i in spec:
            if i["source"] in missing:
                continue
            lo, hi = ranges[i["source"]]
            x = 0.0 if hi == lo else float(np.clip((a[i["source"]] - lo) / (hi - lo), 0, 1))
            parts[i["source"]] = x if i["direction"] == "higher_is_worse" else 1 - x
        ci = None if missing else round(sum(float(i["weight"]) * parts[i["source"]] for i in spec), 4)
        band = next((b["label"] for b in bands if ci is not None and ci <= float(b["max"])), "") if bands else ""
        rows.append({"slot": slot, "approach": approach, "interval_start_s": start, "interval_end_s": start + interval,
                     "congestion_index": "" if ci is None else ci, "band": band,
                     "indicators": "; ".join(f"{k}={v:.3f}" for k, v in parts.items()), "missing": ", ".join(missing),
                     "formula_version": params["formula_version"], "value_type": ValueType.DERIVED.value})
    out = write_csv(out_dir / "congestion_index.csv", CI_FIELDS, rows)
    write_meta(out_dir / "congestion_index.run.json", "G.congestion_index", slot, tables,
               {**params, "normalisation_ranges": ranges})
    return out


# --- emissions, phase 1 ---------------------------------------------------------

EMISSION_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "pollutant", "value", "unit", "method_id",
                   "activity", "factor_source", "factor_ref", "source_status", "vehicle_category", "n_vehicles",
                   "assumptions", "value_type"]
GAP_FIELDS = ["part", "vehicle_category", "needed", "reason"]


def emissions(vehicles_csv: Path, slot: str, params: dict[str, Any], out_dir: Path,
              register: Register | None = None) -> Path:
    require(params, "class_fuel",
            why="fuel per class is an assumption (video cannot tell fuel): {car: {idle_row: car_petrol, fuel: petrol}}")
    register = register or Register.load()
    interval = float(params.get("interval_s", 900.0))
    offset = float(params.get("offset_s", 0.0))
    idle = register.get("idle_fuel_l_per_h")
    co2 = register.get("fuel_co2_kg_per_l")
    gaps, sums = [], defaultdict(lambda: [0.0, 0])
    for v in read_csv(vehicles_csv):
        stopped = num(v.get("stopped_s"))
        if stopped is None:
            continue
        cls = v["class"]
        spec = params["class_fuel"].get(cls)
        if not spec:
            gaps.append({"part": "idle", "vehicle_category": cls, "needed": "class_fuel entry",
                         "reason": "no fuel assumption given for this class"})
            continue
        try:
            rate, _ = register.item("idle_fuel_l_per_h", spec["idle_row"])
            factor, _ = register.item("fuel_co2_kg_per_l", spec["fuel"])
        except SourceGap as e:
            gaps.append({"part": "idle", "vehicle_category": cls, "needed": f"{spec}", "reason": str(e)})
            continue
        start = float(int((float(v["cross_time_s"]) + offset) // interval) * interval)
        key = (v["approach"], start, cls, spec["idle_row"], spec["fuel"])
        sums[key][0] += stopped / 3600.0 * float(rate) * float(factor)
        sums[key][1] += 1
    try:
        register.get(params.get("moving_factor_key") or "arai.co2_g_per_km")
        moving_note = "per-km factors registered but the moving part is not implemented for phase 1 yet"
    except SourceGap as e:
        moving_note = str(e)
    gaps.append({"part": "moving", "vehicle_category": "all", "needed": "ARAI 2007 Table I CO2 g/km (T49)",
                 "reason": moving_note})
    status = "reported" if "reported" in (idle.status, co2.status) else "verified"
    rows = []
    for (approach, start, cls, row, fuel), (kg, n) in sorted(sums.items()):
        rows.append({"slot": slot, "approach": approach, "interval_start_s": start, "interval_end_s": start + interval,
                     "pollutant": "CO2", "value": round(kg, 4), "unit": "kg", "method_id": "phase1_idle_co2",
                     "activity": "stopped time before the stop line, used as idle time",
                     "factor_source": f"{idle.citation}; {co2.citation}", "factor_ref": f"{row}; {fuel}",
                     "source_status": status if status == "verified" else "reported (source not checked)",
                     "vehicle_category": cls, "n_vehicles": n,
                     "assumptions": f"fuel assumed {fuel} for {cls}; engines off at the signal not seen",
                     "value_type": ValueType.ESTIMATED.value})
    write_csv(out_dir / "emission_gaps.csv", GAP_FIELDS, gaps)
    out = write_csv(out_dir / "emissions.csv", EMISSION_FIELDS, rows)
    write_meta(out_dir / "emissions.run.json", "G.emissions", slot, {"stopped_delay_vehicles": vehicles_csv},
               {**params, "gaps": len(gaps)}, notes="Estimates, not measurements (FR-16).")
    return out


# --- problems -------------------------------------------------------------------

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
INDICATOR_FIELDS = ["slot", "approach", "interval_start_s", "vc_ratio", "mean_stopped_delay_s", "queue_length_m",
                    "congestion_index", "co2_kg"]
PROBLEM_FIELDS = ["slot", "approach", "interval_start_s", "indicator", "value", "rule", "problem"]


def problems(tables: dict[str, Path], slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "rules", why="problem rules are the user's: [{indicator, op, value, problem}]")
    interval = float(params.get("interval_s", 900.0))
    data: dict[tuple[str, float], dict[str, float]] = defaultdict(dict)
    cols = {"capacity_vc": ("vc_ratio", max), "stopped_delay": ("mean_stopped_delay_s", max),
            "queue": ("queue_length_m", max), "congestion_index": ("congestion_index", max), "emissions": ("co2_kg", sum)}
    for source, path in tables.items():
        col, how = cols[source]
        vals = defaultdict(list)
        for r in read_csv(path):
            v = num(r.get("value") if source == "emissions" else r.get(col))
            if v is None:
                continue
            start = num(r.get("interval_start_s"))
            if start is None:
                start = float(int(float(r["cycle_start"]) // interval) * interval)
            vals[(r["approach"], start)].append(v)
        for k, vs in vals.items():
            data[k][col] = round(how(vs), 4)
    rows, hits = [], []
    for (approach, start), d in sorted(data.items()):
        rows.append({"slot": slot, "approach": approach, "interval_start_s": start, **d})
        for rule in params["rules"]:
            ind, op = rule["indicator"], rule["op"]
            if op not in OPS:
                raise ValueError(f"rule op must be one of {sorted(OPS)}")
            if ind in d and OPS[op](d[ind], float(rule["value"])):
                hits.append({"slot": slot, "approach": approach, "interval_start_s": start, "indicator": ind,
                             "value": d[ind], "rule": f"{ind} {op} {rule['value']}", "problem": rule["problem"]})
    write_csv(out_dir / "indicators.csv", INDICATOR_FIELDS, rows)
    out = write_csv(out_dir / "problems.csv", PROBLEM_FIELDS, hits)
    write_meta(out_dir / "problems.run.json", "H.analysis", slot, tables, params)
    return out
