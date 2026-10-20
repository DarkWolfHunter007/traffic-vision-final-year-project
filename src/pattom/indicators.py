"""Per-approach indicator table: volume, capacity, V/C, stopped delay, queue (FR-13, T22).

Joins the video outputs for one recording into one row per approach and
interval, which is the input to the congestion index.

- Volume: interval counts at the chosen line type, converted to PCU/h with
  the named SP 41 PCU table (O3 is open, so the table has no default).
- Capacity: SP 41 section 7.6, g x s / c. s from the approach width and
  gradient measured on site; g and c from the signal log (measured). How
  effective green is taken from the logged times is a stated choice:
    displayed_green               g = green
    green_plus_amber_minus_lost   g = green + amber - lost time per phase (SP 41 p. 78, about 2 s)
- Stopped delay and queue come from the delay stage with its definition version.

Config file (configs/indicators.yaml):

    pcu_table: table_3_1            # or table_III_1 (O3)
    class_to_pcu_row: {two_wheeler: motorcycle_scooter, auto_rickshaw: auto_rickshaw,
                       car: passenger_car, bus: truck_bus, truck: truck_bus}
    volume_line_type: arrival       # or stop_line
    effective_green: displayed_green
    approaches:
      north: {width_m: 7.0, gradient_pct: 0.0, signal_head: N}
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import yaml

from pattom import capacity as cap
from pattom.register import Register
from pattom.runmeta import RunMetadata, sha256_file
from pattom.signals import load_log, summary

FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "volume_pcu_h", "capacity_pcu_h",
          "vc_ratio", "mean_stopped_delay_s", "max_queue_length_m", "green_s", "cycle_s", "pcu_table",
          "capacity_source", "definition_version", "value_type"]
GREEN_METHODS = ("displayed_green", "green_plus_amber_minus_lost")


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for k in ("pcu_table", "class_to_pcu_row", "volume_line_type", "effective_green", "approaches"):
        if k not in cfg:
            raise ValueError(f"{path}: missing {k}")
    if cfg["pcu_table"] not in ("table_3_1", "table_III_1"):
        raise ValueError("pcu_table must be table_3_1 or table_III_1 (O3 is open; choose one)")
    active_approaches = {}
    for name, a in (cfg.get("approaches") or {}).items():
        if not isinstance(a, dict):
            continue
        if a.get("enabled") is False:
            continue
        if a.get("enabled") is True:
            if a.get("width_m") is None or a.get("signal_head") is None:
                raise ValueError(f"approach {name}: width_m (measured on site) and signal_head are required when enabled")
            active_approaches[name] = a
        else:
            # When enabled is not explicitly set, include if complete
            if a.get("width_m") is not None and a.get("signal_head") is not None:
                active_approaches[name] = a

    if not active_approaches:
        raise ValueError("No approach has complete data (both width_m and signal_head). Enable or configure at least one approach.")

    cfg["approaches"] = active_approaches
    if cfg["effective_green"] not in GREEN_METHODS:
        raise ValueError(f"effective_green must be one of {GREEN_METHODS}")
    if cfg["volume_line_type"] not in ("arrival", "stop_line"):
        raise ValueError("volume_line_type must be arrival or stop_line")
    return cfg


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def effective_green(sig: dict, method: str, register: Register) -> float:
    if method == "displayed_green":
        return sig["mean_green_s"]
    lost = register.get("sp41.lost_time_per_phase_s").value
    return sig["mean_green_s"] + sig["mean_amber_s"] - lost


def build(run_dir: Path, cfg: dict, signal_log: Path, register: Register) -> list[dict]:
    counts = _read(run_dir / "interval_counts.csv")
    delays = {(r["approach"], float(r["interval_start_s"])): r for r in _read(run_dir / "stopped_delay.csv")}
    queues = _read(run_dir / "queue.csv")
    sig = summary(load_log(signal_log))
    by_key: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    meta_key: dict[tuple, dict] = {}
    for r in counts:
        if r["line_type"] != cfg["volume_line_type"] or r["approach"] not in cfg["approaches"]:
            continue
        key = (r["approach"], float(r["interval_start_s"]), float(r["interval_end_s"]))
        row_name = cfg["class_to_pcu_row"].get(r["class"])
        if row_name is None:
            raise ValueError(f"class {r['class']!r} has no PCU row in the config")
        by_key[key][row_name] += int(r["count"])
        meta_key[key] = r
    rows = []
    for (approach, start, end), veh in sorted(by_key.items()):
        a = cfg["approaches"][approach]
        s_head = sig.get(a["signal_head"])
        if not s_head or not s_head["cycles"]:
            raise ValueError(f"approach {approach}: no complete signal cycles for head {a['signal_head']!r}")
        g = effective_green(s_head, cfg["effective_green"], register)
        c = s_head["mean_cycle_s"]
        volume = cap.pcu_flow(veh, end - start, cfg["pcu_table"], register)
        capacity = cap.capacity(g, c, cap.saturation_flow(a["width_m"], register, a.get("gradient_pct", 0.0)))
        vc = cap.vc_ratio(volume, capacity)
        d = delays.get((approach, start))
        qs = [float(q["queue_length_m"]) for q in queues
              if q["approach"] == approach and start <= float(q["cycle_start_s"]) < end]
        rows.append({
            "slot": meta_key[(approach, start, end)]["slot"], "approach": approach, "interval_start_s": start,
            "interval_end_s": end, "volume_pcu_h": round(volume.value, 1),
            "capacity_pcu_h": round(capacity.value, 1), "vc_ratio": round(vc.value, 3),
            "mean_stopped_delay_s": d["mean_stopped_delay_s"] if d else "",
            "max_queue_length_m": max(qs) if qs else "", "green_s": round(g, 2), "cycle_s": round(c, 2),
            "pcu_table": cfg["pcu_table"], "capacity_source": "; ".join(capacity.sources),
            "definition_version": d["definition_version"] if d else "", "value_type": "derived",
        })
    return rows


def run_indicators(run_dir: Path, config: Path, signal_log: Path, register: Register | None = None) -> Path:
    register = register or Register.load()
    cfg = load_config(config)
    rows = build(run_dir, cfg, signal_log, register)
    out = run_dir / "approach_indicators.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    meta = json.loads((run_dir / "counting.run.json").read_text(encoding="utf-8"))
    RunMetadata(
        slot=meta["slot"], stage="F.indicators", video_file=meta["video_file"],
        video_sha256=meta["video_sha256"], fps=meta["fps"], width=meta["width"], height=meta["height"],
        parameters={"config": str(config), "config_sha256": sha256_file(config),
                    "signal_log": str(signal_log), "signal_log_sha256": sha256_file(signal_log),
                    "signal_summary": summary(load_log(signal_log)), "rows": len(rows)},
    ).write(run_dir / "indicators.run.json")
    return out
