"""Signal phases read from the footage (FR-10, T19, ARCHITECTURE 4.5).

The user plays the prepared video and writes one row each time a signal head
changes state:

    slot,time_s,signal_head,state,phase_group
    test,12.4,N_main,green,NS
    test,58.1,N_main,amber,NS
    test,61.0,N_main,red,NS

``time_s`` is the video time of the change (authoritative for CFR copies).
This module checks the log and turns it into cycles per head: a cycle runs
from one green onset to the next. Partial cycles at the start and end of the
log are left out, because their length is not observed. Durations are
measured values (read from the footage). The vehicle-start cross-check of
PLAN section 4 is a separate step and not done here.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from pattom.runmeta import RunMetadata, sha256_file
from pattom.values import ValueType

STATES = ("green", "amber", "red")
PHASE_FIELDS = ["slot", "time_s", "signal_head", "state", "phase_group"]
CYCLE_FIELDS = ["slot", "signal_head", "phase_group", "cycle_start_s", "cycle_end_s", "green_s", "amber_s",
                "red_s", "cycle_s", "sequence", "regular", "value_type"]


class PhaseLogError(ValueError):
    pass


def read_phase_log(path: Path, slot: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(PHASE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise PhaseLogError(f"{path}: missing columns {sorted(missing)}")
        rows = []
        for n, r in enumerate(reader, start=2):
            state = r["state"].strip().lower()
            if state not in STATES:
                raise PhaseLogError(f"{path} line {n}: state {r['state']!r} is not one of {STATES}")
            if r["slot"].strip() != slot:
                raise PhaseLogError(f"{path} line {n}: slot {r['slot']!r}, expected {slot!r}")
            try:
                t = float(r["time_s"])
            except ValueError:
                raise PhaseLogError(f"{path} line {n}: time_s {r['time_s']!r} is not a number") from None
            head = r["signal_head"].strip()
            if not head:
                raise PhaseLogError(f"{path} line {n}: empty signal_head")
            rows.append({"slot": slot, "time_s": t, "signal_head": head, "state": state,
                         "phase_group": r["phase_group"].strip()})
    by_head: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_head[r["signal_head"]].append(r)
    for head, seq in by_head.items():
        for a, b in zip(seq, seq[1:]):
            if b["time_s"] <= a["time_s"]:
                raise PhaseLogError(f"{path}: {head} times must increase ({a['time_s']} then {b['time_s']})")
            if b["state"] == a["state"]:
                raise PhaseLogError(f"{path}: {head} repeats state {a['state']!r} at {b['time_s']} s")
        groups = {r["phase_group"] for r in seq}
        if len(groups) > 1:
            raise PhaseLogError(f"{path}: {head} belongs to several phase groups {sorted(groups)}")
    return rows


def cycles(rows: list[dict]) -> list[dict]:
    """Complete cycles (green onset to next green onset) per signal head."""
    by_head: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_head[r["signal_head"]].append(r)
    out = []
    for head, seq in sorted(by_head.items()):
        starts = [i for i, r in enumerate(seq) if r["state"] == "green"]
        for i, j in zip(starts, starts[1:]):
            dur = dict.fromkeys(STATES, 0.0)
            for a, b in zip(seq[i:j], seq[i + 1:j + 1]):
                dur[a["state"]] += b["time_s"] - a["time_s"]
            sequence = "-".join(r["state"] for r in seq[i:j])
            out.append({
                "slot": seq[i]["slot"],
                "signal_head": head,
                "phase_group": seq[i]["phase_group"],
                "cycle_start_s": seq[i]["time_s"],
                "cycle_end_s": seq[j]["time_s"],
                "green_s": round(dur["green"], 3),
                "amber_s": round(dur["amber"], 3),
                "red_s": round(dur["red"], 3),
                "cycle_s": round(seq[j]["time_s"] - seq[i]["time_s"], 3),
                "sequence": sequence,
                "regular": sequence == "green-amber-red",
                "value_type": ValueType.MEASURED.value,
            })
    return out


def run_phases(phase_log: Path, slot: str, out_dir: Path) -> tuple[Path, Path]:
    rows = read_phase_log(phase_log, slot)
    cyc = cycles(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    phases_csv, cycles_csv = out_dir / "signal_phases.csv", out_dir / "signal_cycles.csv"
    with open(phases_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PHASE_FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["time_s"], r["signal_head"])))
    with open(cycles_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CYCLE_FIELDS)
        w.writeheader()
        w.writerows(cyc)
    RunMetadata(
        slot=slot,
        stage="F.signal_phases",
        video_file="",
        video_sha256="",
        parameters={"phase_log": str(phase_log), "phase_log_sha256": sha256_file(phase_log),
                    "changes": len(rows), "complete_cycles": len(cyc),
                    "irregular_cycles": sum(not c["regular"] for c in cyc),
                    "source": "read from the footage by the user (measured)"},
    ).write(out_dir / "signal_phases.run.json")
    return phases_csv, cycles_csv
