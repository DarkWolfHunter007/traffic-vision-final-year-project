"""Automatic counts against manual counts from playback (FR-08, T17).

Manual counts are made by the user on sampled clips of the same prepared video:
one row per window, line and class (``manual_counts.csv``: slot,
window_start_s, window_end_s, line_name, class, count). Times are video time,
the same clock as ``crossings.csv``. The automatic count for a window is the
number of counted crossings of that line, by class, inside the window, so a
manual window does not need to match the 15-minute intervals.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pattom.tables import read_csv, write_csv, write_meta
from pattom.values import ValueType

MANUAL_FIELDS = ["slot", "window_start_s", "window_end_s", "line_name", "class", "count"]
ERROR_FIELDS = ["slot", "scope", "line_name", "approach", "class", "window_start_s", "window_end_s", "manual",
                "automatic", "error", "error_pct", "value_type"]


def compare(crossings_csv: Path, manual_csv: Path, slot: str, out_dir: Path) -> Path:
    crossings = read_csv(crossings_csv)
    manual = [m for m in read_csv(manual_csv) if m.get("slot", slot) == slot]
    if not manual:
        raise ValueError(f"{manual_csv} has no manual counts for slot {slot!r}")
    approach_of = {c["line_name"]: c["approach"] for c in crossings}
    rows, totals = [], defaultdict(lambda: [0, 0])
    for m in manual:
        a, b, line, cls = float(m["window_start_s"]), float(m["window_end_s"]), m["line_name"], m["class"]
        auto = sum(1 for c in crossings
                   if c["line_name"] == line and c["class"] == cls and a <= float(c["time_s"]) < b)
        man = int(m["count"])
        approach = approach_of.get(line, "")
        rows.append(_row(slot, "window", line, approach, cls, a, b, man, auto))
        for key in ((line, approach, cls), (line, approach, "all"), ("all", approach, "all")):
            totals[key][0] += man
            totals[key][1] += auto
    for (line, approach, cls), (man, auto) in sorted(totals.items()):
        rows.append(_row(slot, "total", line, approach, cls, "", "", man, auto))
    out = write_csv(out_dir / "count_error.csv", ERROR_FIELDS, rows)
    write_meta(out_dir / "count_error.run.json", "F.count_validation", slot,
               {"crossings": crossings_csv, "manual_counts": manual_csv}, {"windows": len(manual)})
    return out


def _row(slot, scope, line, approach, cls, a, b, man, auto):
    return {"slot": slot, "scope": scope, "line_name": line, "approach": approach, "class": cls,
            "window_start_s": a, "window_end_s": b, "manual": man, "automatic": auto, "error": auto - man,
            "error_pct": round(100.0 * (auto - man) / man, 1) if man else "",
            "value_type": ValueType.DERIVED.value}
