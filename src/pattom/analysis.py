"""H Congestion-emission analysis: the problem list (PRD objective 3).

One row per approach and interval joins the indicators, the congestion index
and the CO2 estimate. A problem is a rule the user writes, e.g.
``{indicator: vc_ratio, op: '>', value: 0.9, problem: "north over capacity"}``.
The rules and their thresholds are the user's; none is built in.

Config (the ``rules`` key of configs/decision.yaml):

    rules:
      - {indicator: vc_ratio, op: '>', value: , problem: "..."}
"""

from __future__ import annotations

import operator
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from pattom.tables import num, read_csv, require, write_csv, write_meta

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
INDICATORS = ("vc_ratio", "mean_stopped_delay_s", "max_queue_length_m", "congestion_index", "co2_g")
ROW_FIELDS = ["slot", "approach", "interval_start_s", *INDICATORS]
PROBLEM_FIELDS = ["slot", "approach", "interval_start_s", "indicator", "value", "rule", "problem"]


def load_rules(path: Path) -> list[dict[str, Any]]:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    require(spec, "rules", why="problem rules are the user's: [{indicator, op, value, problem}]")
    for r in spec["rules"]:
        for k in ("indicator", "op", "value", "problem"):
            if r.get(k) in (None, ""):
                raise ValueError(f"rule {r}: missing {k}")
        if r["indicator"] not in INDICATORS:
            raise ValueError(f"rule indicator must be one of {INDICATORS}")
        if r["op"] not in OPS:
            raise ValueError(f"rule op must be one of {sorted(OPS)}")
    return spec["rules"]


def find_problems(index_csv: Path, emissions_csv: Path | None, rules_yaml: Path) -> Path:
    rules = load_rules(rules_yaml)
    rows: dict[tuple[str, float], dict[str, Any]] = {}
    slot = ""
    for r in read_csv(index_csv):
        slot = r.get("slot", slot)
        key = (r["approach"], float(r["interval_start_s"]))
        rows[key] = {c: num(r.get(c)) for c in INDICATORS if c != "co2_g"}
    if emissions_csv and Path(emissions_csv).is_file():
        co2 = defaultdict(float)
        for r in read_csv(emissions_csv):
            if r.get("pollutant") == "CO2" and num(r.get("value")) is not None:
                co2[(r["approach"], float(r["interval_start_s"]))] += float(r["value"])
        for key, v in co2.items():
            rows.setdefault(key, {})["co2_g"] = round(v, 3)
    table, hits = [], []
    for (approach, start), d in sorted(rows.items()):
        table.append({"slot": slot, "approach": approach, "interval_start_s": start, **d})
        for rule in rules:
            v = d.get(rule["indicator"])
            if v is not None and OPS[rule["op"]](v, float(rule["value"])):
                hits.append({"slot": slot, "approach": approach, "interval_start_s": start,
                             "indicator": rule["indicator"], "value": v,
                             "rule": f"{rule['indicator']} {rule['op']} {rule['value']}", "problem": rule["problem"]})
    out_dir = Path(index_csv).parent
    write_csv(out_dir / "analysis_table.csv", ROW_FIELDS, table)
    out = write_csv(out_dir / "problems.csv", PROBLEM_FIELDS, hits)
    inputs = {"congestion_index": Path(index_csv), "rules": Path(rules_yaml)}
    if emissions_csv and Path(emissions_csv).is_file():
        inputs["emissions"] = Path(emissions_csv)
    write_meta(out_dir / "problems.run.json", "H.analysis", slot, inputs, {"rules": rules},
               notes=f"{len(hits)} problem row(s) from {len(table)} approach-interval row(s)")
    return out
