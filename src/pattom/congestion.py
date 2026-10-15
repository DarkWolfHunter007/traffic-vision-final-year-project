"""Congestion index (FR-14, D9, open decision O4).

The formula is not decided: indicators, normalisation, weights and scale need
the guide's approval. So nothing here has a default. The formula lives in a
versioned config, every row carries the formula version and whether it is
approved, and the index is computed as

    CI = sum_i  w_i x n_i(x_i)

where x_i is an indicator from approach_indicators.csv, n_i its normalised
value in [0, 1] (1 = most congested), and the weights w_i sum to 1.

Normalisations offered:
    minmax     (x - min) / (max - min) over the rows of this table
    reference  x / reference, capped at 1 (e.g. V/C against 1.0)
direction: higher_is_worse (default for delay, queue, V/C) or higher_is_better
(e.g. speed), which flips n to 1 - n.

Config file (configs/congestion.yaml):

    formula_version: draft-1
    approved: false
    indicators:
      - {column: vc_ratio, normalisation: reference, reference: 1.0, weight: ..., direction: higher_is_worse}
      - {column: mean_stopped_delay_s, normalisation: minmax, weight: ...}
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import yaml

from pattom.runmeta import RunMetadata, sha256_file

NORMALISATIONS = ("minmax", "reference")
DIRECTIONS = ("higher_is_worse", "higher_is_better")


def load_formula(path: Path) -> dict:
    f = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for k in ("formula_version", "approved", "indicators"):
        if k not in f:
            raise ValueError(f"{path}: missing {k}")
    inds = f["indicators"]
    if not inds:
        raise ValueError(f"{path}: no indicators")
    for i in inds:
        if i.get("weight") is None:
            raise ValueError(f"indicator {i.get('column')}: weight not set (O4 is open; the weights need approval)")
        if i.get("normalisation") not in NORMALISATIONS:
            raise ValueError(f"indicator {i.get('column')}: normalisation must be one of {NORMALISATIONS}")
        if i["normalisation"] == "reference" and not i.get("reference"):
            raise ValueError(f"indicator {i['column']}: reference normalisation needs a reference value")
        i.setdefault("direction", "higher_is_worse")
        if i["direction"] not in DIRECTIONS:
            raise ValueError(f"indicator {i['column']}: direction must be one of {DIRECTIONS}")
    total = sum(float(i["weight"]) for i in inds)
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError(f"weights sum to {total}, not 1")
    return f


def compute(rows: list[dict], formula: dict) -> tuple[list[dict], list[str]]:
    """Adds congestion_index and n_<column> to each row. Rows missing an
    indicator get no index (reported, not filled)."""
    notes: list[str] = []
    cols = [i["column"] for i in formula["indicators"]]
    usable = [r for r in rows if all(r.get(c) not in ("", None) for c in cols)]
    skipped = len(rows) - len(usable)
    if skipped:
        notes.append(f"{skipped} row(s) lack one of {cols} and have no index")
    ranges = {}
    for i in formula["indicators"]:
        if i["normalisation"] == "minmax":
            vals = [float(r[i["column"]]) for r in usable]
            ranges[i["column"]] = (min(vals), max(vals)) if vals else (0.0, 0.0)
            if vals and ranges[i["column"]][0] == ranges[i["column"]][1]:
                notes.append(f"{i['column']} is equal in every row; min-max gives it no spread (set to 0)")
    status = "approved" if formula["approved"] else "draft, not approved"
    out = []
    for r in rows:
        r = dict(r)
        if any(r.get(c) in ("", None) for c in cols):
            r.update({"congestion_index": "", "formula_version": formula["formula_version"],
                      "formula_status": status})
            out.append(r)
            continue
        ci = 0.0
        for i in formula["indicators"]:
            x = float(r[i["column"]])
            if i["normalisation"] == "minmax":
                lo, hi = ranges[i["column"]]
                n = (x - lo) / (hi - lo) if hi > lo else 0.0
            else:
                n = min(x / float(i["reference"]), 1.0)
            if i["direction"] == "higher_is_better":
                n = 1.0 - n
            r[f"n_{i['column']}"] = round(n, 4)
            ci += float(i["weight"]) * n
        r.update({"congestion_index": round(ci, 4), "formula_version": formula["formula_version"],
                  "formula_status": status})
        out.append(r)
    return out, notes


def run_congestion(indicators_csv: Path, formula_path: Path) -> Path:
    formula = load_formula(formula_path)
    with open(indicators_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out_rows, notes = compute(rows, formula)
    out = indicators_csv.parent / "congestion_index.csv"
    fields = list(rows[0].keys()) if rows else []
    extra = [k for r in out_rows for k in r if k not in fields]
    fields += list(dict.fromkeys(extra))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    meta = json.loads((indicators_csv.parent / "indicators.run.json").read_text(encoding="utf-8"))
    RunMetadata(
        slot=meta["slot"], stage="G.congestion_index", video_file=meta["video_file"],
        video_sha256=meta["video_sha256"], fps=meta["fps"], width=meta["width"], height=meta["height"],
        parameters={"formula": str(formula_path), "formula_sha256": sha256_file(formula_path),
                    "formula_version": formula["formula_version"], "approved": formula["approved"],
                    "notes": notes, "indicators_sha256": sha256_file(indicators_csv)},
    ).write(indicators_csv.parent / "congestion.run.json")
    return out
