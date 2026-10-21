"""I Alternatives, J pre-SUMO scoring, K multi-criteria evaluation (FR-17 to FR-19).

Order (D4): problems -> alternatives -> scoring -> MCE -> selection; SUMO
results never feed back (D1). The existing plan is taken from the observed
cycles; the alternatives are written by the user in configs/alternatives.yaml.

Pre-SUMO scoring uses only registered formulas: capacity g x s / c (SP 41 p. 75)
under each fixed-time plan gives V/C per approach. SP 41 has no delay formula,
so delay and the emission change are gaps until a source is registered (T28).
Actuated and adaptive plans cannot be scored by a fixed-time formula; that
limit is written out, not hidden (ARCHITECTURE section 8).

The MCE weights, directions, scales, the treatment of a criterion that is
equal for every alternative, and the sensitivity step are the user's (O13).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from pattom.capacity import fixed_time_cycle, green_split
from pattom.register import Register, SourceGap
from pattom.tables import num, read_csv, require, write_csv, write_meta
from pattom.values import ValueType

CONTROLS = ("fixed", "actuated", "adaptive")
NOTE_FIELDS = ("problem_addressed", "expected_effect", "safety_note", "cost_note", "land_note", "feasibility_note")
CRITERIA = ("congestion", "emission", "safety", "cost", "land")


# --- I: alternatives ------------------------------------------------------------

CYCLE_FIELDS = ["signal_head", "phase_group", "cycle_start_s", "cycle_s", "green_s", "amber_s", "red_s", "value_type"]


def write_cycles(signal_log: Path, head_groups: dict[str, str], out_dir: Path) -> Path:
    """Complete signal cycles from the logged signal changes (measured from the footage)."""
    from pattom.signals import cycles, load_log

    log = load_log(signal_log)
    missing = sorted(set(log) - set(head_groups))
    if missing:
        raise ValueError(f"head_groups has no phase group for signal head(s) {missing}")
    rows = [{"signal_head": h, "phase_group": head_groups[h], "cycle_start_s": c.start_s, "cycle_s": round(c.length_s, 2),
             "green_s": c.green_s, "amber_s": c.amber_s, "red_s": c.red_s, "value_type": ValueType.MEASURED.value}
            for h, changes in sorted(log.items()) for c in cycles(changes, h)]
    return write_csv(Path(out_dir) / "signal_cycles.csv", CYCLE_FIELDS, rows)


def _saturation(row: dict[str, str]) -> float:
    """Saturation flow of an approach row: the stored value, or s = capacity x c / g (SP 41 p. 75)."""
    if row.get("saturation_flow_pcu_h"):
        return float(row["saturation_flow_pcu_h"])
    return float(row["capacity_pcu_h"]) * float(row["cycle_s"]) / float(row["green_s"])


def existing_plan(cycles_csv: Path) -> dict[str, Any]:
    """The observed plan: mean cycle and mean green and amber per phase group (derived)."""
    cycles = read_csv(cycles_csv)
    if not cycles:
        raise ValueError("no complete signal cycles; read the phases first (signal-phases)")
    groups = defaultdict(list)
    for c in cycles:
        groups[c["phase_group"] or c["signal_head"]].append(c)
    return {
        "id": "existing", "description": "Existing plan as observed in the footage", "control": "fixed",
        "plan": {"cycle_s": round(mean(float(c["cycle_s"]) for c in cycles), 2),
                 "groups": {g: {"green_s": round(mean(float(c["green_s"]) for c in cs), 2),
                                "amber_s": round(mean(float(c["amber_s"]) for c in cs), 2),
                                "n_cycles": len(cs)} for g, cs in sorted(groups.items())}},
        "value_type": ValueType.DERIVED.value,
    }


def load_alternatives(path: Path) -> list[dict[str, Any]]:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    alts = spec.get("alternatives") or []
    seen = set()
    for a in alts:
        for k in ("id", "description", "control", "problem_addressed"):
            if not a.get(k):
                raise ValueError(f"alternative {a.get('id', '?')}: missing {k}")
        if a["id"] in seen or a["id"] == "existing":
            raise ValueError(f"alternative id {a['id']!r} is used twice or reserved")
        seen.add(a["id"])
        if a["control"] not in CONTROLS:
            raise ValueError(f"alternative {a['id']}: control must be one of {CONTROLS}")
        if a["control"] == "fixed":
            plan = a.get("plan") or {}
            if not plan.get("cycle_s") or not plan.get("groups"):
                raise ValueError(f"alternative {a['id']}: a fixed plan needs cycle_s and groups with green_s, amber_s")
            for g, v in plan["groups"].items():
                if "green_s" not in v or "amber_s" not in v:
                    raise ValueError(f"alternative {a['id']}, group {g}: green_s and amber_s are needed")
    return alts


def build_alternatives(cycles_csv: Path, problems_csv: Path, alternatives_yaml: Path, slot: str, out_dir: Path) -> Path:
    alts = load_alternatives(alternatives_yaml)
    known = {p["problem"] for p in read_csv(problems_csv)}
    warnings = []
    if len(alts) < 2:
        warnings.append("fewer than two alternatives besides the existing plan (PLAN P6 asks for at least two)")
    for a in alts:
        if known and a["problem_addressed"] not in known:
            warnings.append(f"{a['id']}: problem_addressed {a['problem_addressed']!r} is not in problems.csv")
    out = Path(out_dir) / "alternatives.json"
    out.write_text(json.dumps({"slot": slot, "existing": existing_plan(cycles_csv), "alternatives": alts,
                               "warnings": warnings}, indent=2) + "\n", encoding="utf-8")
    write_meta(Path(out_dir) / "alternatives.run.json", "I.alternatives", slot,
               {"signal_cycles": cycles_csv, "problems": problems_csv, "alternatives": alternatives_yaml},
               {"n_alternatives": len(alts), "warnings": warnings})
    return out


def sp41_fixed_plan(capacity_csv: Path, approach_groups: dict[str, str], all_red_s: float,
                    register: Register | None = None) -> dict[str, Any]:
    """A re-optimised fixed-time plan from observed flows: Co = (1.5 L + 5) / (1 - Y), greens split by y
    (SP 41 p. 78). y = q / s per approach; the critical y of a group is its largest. L = n x l + R with
    l from the register and R the all-red time per cycle (measured, passed in). Returns a derived suggestion."""
    register = register or Register.load()
    l = float(register.get("sp41.lost_time_per_phase_s").value)
    rows = read_csv(capacity_csv)
    y_by_group: dict[str, float] = defaultdict(float)
    for approach, group in approach_groups.items():
        rs = [r for r in rows if r["approach"] == approach]
        if not rs:
            raise ValueError(f"no capacity rows for approach {approach}")
        q = max(float(r["volume_pcu_h"]) for r in rs)
        s = _saturation(rs[0])
        y_by_group[group] = max(y_by_group[group], q / s)
    groups = sorted(y_by_group)
    lost = len(groups) * l + float(all_red_s)
    co = fixed_time_cycle(lost, [y_by_group[g] for g in groups])
    greens = green_split(co.value - lost, [y_by_group[g] for g in groups])
    return {"cycle_s": round(co.value, 1), "lost_time_s": lost, "y": {g: round(y_by_group[g], 4) for g in groups},
            "effective_green_s": {g: round(gr.value, 1) for g, gr in zip(groups, greens)},
            "sources": list(co.sources), "value_type": ValueType.DERIVED.value,
            "note": "effective greens; convert to displayed green and amber before using as a plan"}


# --- J: pre-SUMO scoring --------------------------------------------------------

SCORE_FIELDS = ["alternative", "criterion", "raw_value", "unit", "method", "note", "value_type"]


def _plan_green(plan: dict[str, Any], group: str, definition: str, lost_s: float) -> float:
    g = plan["groups"][group]
    green = float(g["green_s"])
    return green + float(g["amber_s"]) - lost_s if definition == "green_plus_amber_minus_lost" else green


def pre_sumo_scores(alternatives_json: Path, capacity_csv: Path, slot: str, params: dict[str, Any], out_dir: Path,
                    register: Register | None = None) -> Path:
    require(params, "approach_groups", "effective_green", "congestion_measure", "volume_stat", "delay_method",
            why="how scores are formed is open (O13): approach groups, effective green, congestion measure, "
                "volume statistic and the delay method")
    if params["congestion_measure"] not in ("max_vc", "flow_weighted_vc"):
        raise ValueError("congestion_measure must be max_vc or flow_weighted_vc")
    if params["volume_stat"] not in ("mean", "max"):
        raise ValueError("volume_stat must be mean or max")
    register = register or Register.load()
    lost = float(register.get("sp41.lost_time_per_phase_s").value)
    delay_gap = None
    if params["delay_method"] != "none":
        try:
            register.get(params["delay_method"])
            delay_gap = "a registered delay formula is named but not implemented yet"
        except SourceGap as e:
            delay_gap = str(e)
    data = json.loads(Path(alternatives_json).read_text(encoding="utf-8"))
    rows_cap = read_csv(capacity_csv)
    per_approach = {}
    for approach in params["approach_groups"]:
        rs = [r for r in rows_cap if r["approach"] == approach]
        if not rs:
            raise ValueError(f"no capacity rows for approach {approach}")
        vols = [float(r["volume_pcu_h"]) for r in rs]
        per_approach[approach] = {"q": mean(vols) if params["volume_stat"] == "mean" else max(vols),
                                  "s": _saturation(rs[0])}
    out = []
    for alt in [data["existing"], *data["alternatives"]]:
        aid = alt["id"]
        if alt["control"] != "fixed":
            out.append({"alternative": aid, "criterion": "congestion", "raw_value": "", "unit": "",
                        "method": "fixed-time capacity", "note": f"not scorable: {alt['control']} control cannot be "
                        "scored by a fixed-time formula (limit recorded, ARCHITECTURE 8)", "value_type": ""})
        else:
            plan = alt["plan"]
            vcs, weights = [], []
            for approach, group in params["approach_groups"].items():
                if group not in plan["groups"]:
                    raise ValueError(f"{aid}: plan has no phase group {group!r} (approach {approach})")
                g = _plan_green(plan, group, params["effective_green"], lost)
                cap = g * per_approach[approach]["s"] / float(plan["cycle_s"])
                vc = per_approach[approach]["q"] / cap
                vcs.append(vc)
                weights.append(per_approach[approach]["q"])
                out.append({"alternative": aid, "criterion": f"vc_{approach}", "raw_value": round(vc, 4),
                            "unit": "ratio", "method": "V/C with capacity = g x s / c (SP 41 p. 75)",
                            "note": f"g = {g:.1f} s, c = {plan['cycle_s']} s", "value_type": ValueType.DERIVED.value})
                if vc >= 1:
                    out[-1]["note"] += "; V/C >= 1: oversaturated, a Webster-type delay would not apply"
            value = max(vcs) if params["congestion_measure"] == "max_vc" else \
                sum(v * w for v, w in zip(vcs, weights)) / sum(weights)
            out.append({"alternative": aid, "criterion": "congestion", "raw_value": round(value, 4), "unit": "ratio",
                        "method": params["congestion_measure"], "note": "lower is less congested",
                        "value_type": ValueType.DERIVED.value})
        out.append({"alternative": aid, "criterion": "delay", "raw_value": "", "unit": "s/veh",
                    "method": params["delay_method"],
                    "note": f"gap: {delay_gap or 'no delay formula in the register (T28)'}", "value_type": ""})
        out.append({"alternative": aid, "criterion": "emission", "raw_value": "", "unit": "",
                    "method": "needs delay or idle time under the plan", "note": "gap until the delay method exists",
                    "value_type": ""})
    path = write_csv(Path(out_dir) / "pre_sumo_scores.csv", SCORE_FIELDS, out)
    write_meta(Path(out_dir) / "pre_sumo_scores.run.json", "J.pre_sumo_scoring", slot,
               {"alternatives": alternatives_json, "capacity_vc": capacity_csv}, {**params, "per_approach": per_approach})
    return path


# --- K: MCE -----------------------------------------------------------------------

MCE_FIELDS = ["alternative", "criterion", "raw_value", "normalised_score", "weight", "weighted", "evidence"]
SENS_FIELDS = ["criterion", "change", "weights", "winner", "ranking", "winner_changed"]


def _rank(alts: list[str], norm: dict[str, dict[str, float]], weights: dict[str, float]) -> list[tuple[str, float]]:
    totals = {a: sum(weights[c] * norm[c][a] for c in weights) for a in alts}
    return sorted(totals.items(), key=lambda kv: -kv[1])


def mce(alternatives_json: Path, scores_csv: Path, slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "weights", "directions", "manual_scores", "scale", "equal_criterion", "sensitivity_step",
            why="MCE weights, directions, scale, how an equal criterion is scored and the sensitivity step (O13)")
    weights = {c: float(w) for c, w in params["weights"].items()}
    if set(weights) != set(CRITERIA):
        raise ValueError(f"weights must cover exactly {CRITERIA}")
    if abs(sum(weights.values()) - 1) > 1e-6:
        raise ValueError(f"weights add up to {sum(weights.values())}, not 1")
    if params["equal_criterion"] not in ("score_zero", "score_one", "drop_and_reweight"):
        raise ValueError("equal_criterion must be score_zero, score_one or drop_and_reweight")
    data = json.loads(Path(alternatives_json).read_text(encoding="utf-8"))
    alts = [a["id"] for a in data["alternatives"]]
    scores = read_csv(scores_csv)
    existing = {r["criterion"]: num(r["raw_value"]) for r in scores if r["alternative"] == "existing"}
    raw: dict[str, dict[str, float]] = {c: {} for c in CRITERIA}
    evidence: dict[tuple[str, str], str] = {}
    missing: dict[tuple[str, str], str] = {}
    for a in alts:
        mine = {r["criterion"]: r for r in scores if r["alternative"] == a}
        for c in ("congestion", "emission"):
            v, base = num((mine.get(c) or {}).get("raw_value")), existing.get(c)
            if v is None or base is None:
                missing[(a, c)] = (mine.get(c) or {}).get("note", "no score")
                continue
            raw[c][a] = base - v  # reduction against the existing plan
            evidence[(a, c)] = f"existing {base} - {a} {v} (pre_sumo_scores.csv)"
        for c in ("safety", "cost", "land"):
            v = (params["manual_scores"].get(c) or {}).get(a)
            if v is None:
                missing[(a, c)] = "no score given in manual_scores"
                continue
            raw[c][a] = float(v)
            evidence[(a, c)] = f"manual score on the scale {params['scale']}"
    policy = params.get("missing_criteria", "error")
    if policy not in ("error", "drop_and_reweight"):
        raise ValueError("missing_criteria must be error or drop_and_reweight")
    dropped = sorted({c for (_, c) in missing}) if policy == "drop_and_reweight" else []
    excluded = {} if dropped else {a: f"{c}: {why}" for (a, c), why in missing.items()}
    if policy == "error" and missing:
        raise ValueError("criteria without scores (set missing_criteria: drop_and_reweight to drop them, a "
                         "method decision under O13): " + "; ".join(f"{a}/{c}: {why}" for (a, c), why in missing.items()))
    criteria = [c for c in CRITERIA if c not in dropped]
    if not criteria:
        raise ValueError("no criterion has scores for every alternative")
    ranked = list(alts)
    directions = params["directions"]
    norm: dict[str, dict[str, float]] = {}
    w = {c: weights[c] for c in criteria}
    for c in criteria:
        if directions.get(c) not in ("higher_is_better", "lower_is_better"):
            raise ValueError(f"direction for {c} must be higher_is_better or lower_is_better")
        vals = [raw[c][a] for a in ranked]
        lo, hi = min(vals), max(vals)
        if hi == lo:
            if params["equal_criterion"] == "drop_and_reweight":
                w.pop(c)
                continue
            norm[c] = {a: 0.0 if params["equal_criterion"] == "score_zero" else 1.0 for a in ranked}
        else:
            x = {a: (raw[c][a] - lo) / (hi - lo) for a in ranked}
            norm[c] = x if directions[c] == "higher_is_better" else {a: 1 - v for a, v in x.items()}
    if not w:
        raise ValueError("every remaining criterion is equal for all alternatives; nothing to rank on")
    total_w = sum(w.values())
    w = {c: v / total_w for c, v in w.items()}
    ranking = _rank(ranked, norm, w)
    rows = [{"alternative": a, "criterion": c, "raw_value": round(raw[c][a], 4),
             "normalised_score": round(norm[c][a], 4) if c in norm else "", "weight": round(w.get(c, 0), 4),
             "weighted": round(w.get(c, 0) * norm[c][a], 4) if c in norm else "", "evidence": evidence.get((a, c), "")}
            for a in ranked for c in criteria]
    write_csv(Path(out_dir) / "mce_scores.csv", MCE_FIELDS, rows)
    step, sens = float(params["sensitivity_step"]), []
    for c in w:
        for sign in (-1, 1):
            nw = dict(w)
            nw[c] = max(0.0, nw[c] + sign * step)
            rest = sum(v for k, v in w.items() if k != c)
            for k in nw:
                if k != c:
                    nw[k] = w[k] / rest * (1 - nw[c]) if rest else 0.0
            r = _rank(ranked, norm, nw)
            sens.append({"criterion": c, "change": f"{sign * step:+}", "weights": json.dumps({k: round(v, 3) for k, v in nw.items()}),
                         "winner": r[0][0], "ranking": " > ".join(a for a, _ in r), "winner_changed": r[0][0] != ranking[0][0]})
    write_csv(Path(out_dir) / "mce_sensitivity.csv", SENS_FIELDS, sens)
    selected = {"slot": slot, "selected": ranking[0][0], "total": round(ranking[0][1], 4),
                "ranking": [{"alternative": a, "total": round(t, 4)} for a, t in ranking], "excluded": excluded,
                "criteria_dropped": {c: sorted({why for (_, cc), why in missing.items() if cc == c}) for c in dropped},
                "weights_used": w, "stable_under_sensitivity": not any(s["winner_changed"] for s in sens),
                "plan": next(a for a in data["alternatives"] if a["id"] == ranking[0][0]),
                "note": "Selected before SUMO from analytical scores (D8); SUMO results do not change this."}
    out = Path(out_dir) / "selected_alternative.json"
    out.write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
    write_meta(Path(out_dir) / "mce.run.json", "K.mce", slot, {"alternatives": alternatives_json, "scores": scores_csv},
               params)
    return out
