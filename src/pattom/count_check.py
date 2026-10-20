"""Check automated counts against manual counts from playback (PLAN validation, T17).

Manual counts file (CSV, typed while watching the prepared video):

    interval_start_s,interval_end_s,line_name,class,count
    0,60,N_arrival,car,14

The check matches it with interval_counts.csv on interval, line and class and
reports the error per line and class, and in total. The manual count is the
reference; nothing is adjusted.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

FIELDS = ["line_name", "class", "manual", "automatic", "difference", "error_pct"]


def _sum(rows, key_fields):
    out = defaultdict(int)
    for r in rows:
        out[tuple(r[k] for k in key_fields)] += int(float(r["count"]))
    return out


def compare(manual_csv: Path, counts_csv: Path, out_csv: Path | None = None) -> Path:
    with open(manual_csv, newline="", encoding="utf-8") as f:
        manual = list(csv.DictReader(f))
    with open(counts_csv, newline="", encoding="utf-8") as f:
        auto = list(csv.DictReader(f))
    windows = {(float(r["interval_start_s"]), float(r["interval_end_s"])) for r in manual}
    if not windows:
        raise ValueError(f"{manual_csv}: no manual counts")
    auto_in = [r for r in auto if any(a <= float(r["interval_start_s"]) and float(r["interval_end_s"]) <= b + 1e-6
                                      for a, b in windows)]
    m = _sum(manual, ("line_name", "class"))
    a = _sum(auto_in, ("line_name", "class"))
    rows = []
    for key in sorted(set(m) | set(a)):
        mv, av = m.get(key, 0), a.get(key, 0)
        rows.append({"line_name": key[0], "class": key[1], "manual": mv, "automatic": av, "difference": av - mv,
                     "error_pct": round(100 * (av - mv) / mv, 1) if mv else ""})
    tm, ta = sum(m.values()), sum(a.values())
    rows.append({"line_name": "ALL", "class": "ALL", "manual": tm, "automatic": ta, "difference": ta - tm,
                 "error_pct": round(100 * (ta - tm) / tm, 1) if tm else ""})
    out = out_csv or Path(counts_csv).with_name("count_check.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out
