"""Emission estimate, phase 1: CO2 from idle time (FR-15, FR-16, D13, ARCHITECTURE 4.8).

    idle CO2 (g) = idle seconds / 3600 x idle fuel rate (L/h) x fuel CO2 factor (kg/L) x 1000

- Idle seconds are each vehicle's stopped delay from the video (derived).
- Idle fuel rates and fuel CO2 factors come only from the source register.
  Both are "reported" (not yet checked against the papers, T50), so every row
  carries "source not checked".
- The fuel and emission category of each class is an assumption, because the
  video cannot show fuel type (AI_RULES 3.7). It is written in the config and
  copied into every row.
- Moving-vehicle CO2 (ARAI 2007 g/km) is not computed: the register holds no
  ARAI values yet (T49). It is reported as a gap, not filled.
- Results are estimates, never measurements, and are kept separate from any
  SUMO output.

Config file (configs/emissions.yaml):

    method_id: idle_co2_v1
    class_to_category:
      two_wheeler: {idle_fuel: motorcycle_petrol, fuel: petrol}
      car:         {idle_fuel: car_petrol, fuel: petrol}
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import yaml

from pattom.register import Register, SourceGap
from pattom.runmeta import RunMetadata, sha256_file

EMISSION_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "pollutant", "value", "unit",
                   "method_id", "factor_source", "factor_ref", "source_status", "vehicle_category",
                   "assumption", "n_vehicles", "idle_s", "definition_version", "value_type"]


def idle_co2_g(idle_s: float, idle_fuel_l_per_h: float, co2_kg_per_l: float) -> float:
    return idle_s / 3600.0 * idle_fuel_l_per_h * co2_kg_per_l * 1000.0


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if "method_id" not in cfg or not cfg.get("class_to_category"):
        raise ValueError(f"{path}: needs method_id and class_to_category")
    for cls, m in cfg["class_to_category"].items():
        if not {"idle_fuel", "fuel"} <= m.keys():
            raise ValueError(f"{path}: class {cls} needs idle_fuel and fuel")
    return cfg


def estimate(vehicles: list[dict], cfg: dict, register: Register, slot: str, interval_s: float,
             offset_s: float = 0.0) -> tuple[list[dict], list[str]]:
    """Idle CO2 per approach, interval and vehicle category. Returns (rows, gaps)."""
    gaps: list[str] = []
    groups: dict[tuple, list[float]] = defaultdict(list)
    for v in vehicles:
        mapping = cfg["class_to_category"].get(v["class"])
        if mapping is None:
            gap = f"class {v['class']!r} has no emission category in the config"
            if gap not in gaps:
                gaps.append(gap)
            continue
        start = float(int((float(v["zone_entry_s"]) + offset_s) // interval_s) * interval_s)
        key = (v["approach"], start, mapping["idle_fuel"], mapping["fuel"], v.get("definition_version", ""))
        groups[key].append(float(v["stopped_delay_s"]))

    rows = []
    for (approach, start, category, fuel, defv), idles in sorted(groups.items()):
        try:
            rate, fuel_entry = register.item("idle_fuel_l_per_h", category)
            factor, co2_entry = register.item("fuel_co2_kg_per_l", fuel)
        except SourceGap as e:
            if str(e) not in gaps:
                gaps.append(str(e))
            continue
        idle_s = sum(idles)
        status = "verified" if fuel_entry.status == co2_entry.status == "verified" else "reported (source not checked)"
        rows.append({
            "slot": slot, "approach": approach, "interval_start_s": start, "interval_end_s": start + float(interval_s),
            "pollutant": "CO2", "value": round(idle_co2_g(idle_s, rate, factor), 3), "unit": "g",
            "method_id": cfg["method_id"], "factor_source": f"{fuel_entry.source}; {co2_entry.source}",
            "factor_ref": f"{fuel_entry.ref}; {co2_entry.ref}", "source_status": status,
            "vehicle_category": category, "assumption": f"fuel assumed {fuel} for this class",
            "n_vehicles": len(idles), "idle_s": round(idle_s, 3), "definition_version": defv,
            "value_type": "estimated",
        })
    try:
        register.get("arai_2007.g_per_km.co2")
    except SourceGap:
        gaps.append("moving-vehicle CO2 not computed: no ARAI 2007 g/km values in the register yet (T49)")
    return rows, gaps


def run_emissions(vehicle_delay_csv: Path, config: Path, interval_s: float, offset_s: float = 0.0,
                  register: Register | None = None) -> Path:
    register = register or Register.load()
    cfg = load_config(config)
    out_dir = vehicle_delay_csv.parent
    meta = json.loads((out_dir / "delay_queue.run.json").read_text(encoding="utf-8"))
    with open(vehicle_delay_csv, newline="", encoding="utf-8") as f:
        vehicles = list(csv.DictReader(f))
    rows, gaps = estimate(vehicles, cfg, register, meta["slot"], interval_s, offset_s)
    out = out_dir / "emissions.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EMISSION_FIELDS)
        w.writeheader()
        w.writerows(rows)
    RunMetadata(
        slot=meta["slot"], stage="G.emissions", video_file=meta["video_file"],
        video_sha256=meta["video_sha256"], fps=meta["fps"], width=meta["width"], height=meta["height"],
        parameters={"config": str(config), "config_sha256": sha256_file(config), "method_id": cfg["method_id"],
                    "interval_s": interval_s, "offset_s": offset_s, "gaps": gaps,
                    "definition_status": meta["parameters"].get("definition_status"),
                    "vehicle_delay_sha256": sha256_file(vehicle_delay_csv)},
        notes="Estimates, not measurements. Phase 1 covers idle CO2 only (D13).",
    ).write(out_dir / "emissions.run.json")
    return out
