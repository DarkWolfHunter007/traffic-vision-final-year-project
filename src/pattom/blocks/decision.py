"""I Alternatives, J pre-SUMO scoring, K MCE. SUMO results never feed these (D1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


def _slot_dir(ctx: RunContext) -> Path:
    d = ctx.resolve(f"runs/{ctx.slot}/decision")
    d.mkdir(parents=True, exist_ok=True)
    return d


@register_block
class Alternatives(Block):
    name = "alternatives"
    component = "I"
    title = "Signal-timing alternatives (documented)"
    inputs = {"problems": "problems", "signal_cycles": "signal_cycles"}
    outputs = ("alternatives",)
    params = {"file": "alternatives you wrote (default configs/alternatives.yaml; edit on the Alternatives page)"}
    tasks = ("T27",)
    note = "Developed from the problems, after the analysis (D4). The existing plan comes from the observed cycles."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.alternatives import build_alternatives

        f = ctx.resolve(params.get("file", "configs/alternatives.yaml"))
        return {"alternatives": build_alternatives(inputs["signal_cycles"], inputs["problems"], f, ctx.slot,
                                                   _slot_dir(ctx))}


@register_block
class PreSumoScoring(Block):
    name = "pre-sumo-scoring"
    component = "J"
    title = "Analytical congestion and emission scores before SUMO"
    inputs = {"alternatives": "alternatives", "capacity_vc": "capacity_vc"}
    outputs = ("pre_sumo_scores",)
    params = {"approach_groups": "approach -> phase group, e.g. {north: NS, east: EW}",
              "effective_green": "green or green_plus_amber_minus_lost (as in capacity-vc)",
              "congestion_measure": "max_vc or flow_weighted_vc (O13)",
              "volume_stat": "mean or max of the observed interval volumes (O13)",
              "delay_method": "none, or the register key of a delay formula (none registered yet, T28)"}
    required_params = ("approach_groups", "effective_green", "congestion_measure", "volume_stat", "delay_method")
    tasks = ("T28",)
    waits_on = ("O13",)
    note = "V/C under each fixed-time plan from SP 41 capacity. Delay and emission change stay gaps until a source is registered."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.alternatives import pre_sumo_scores

        return {"pre_sumo_scores": pre_sumo_scores(inputs["alternatives"], inputs["capacity_vc"], ctx.slot, params,
                                                   _slot_dir(ctx))}


@register_block
class MCE(Block):
    name = "mce"
    component = "K"
    title = "Multi-criteria evaluation, sensitivity and selection"
    inputs = {"alternatives": "alternatives", "pre_sumo_scores": "pre_sumo_scores"}
    outputs = ("mce_scores", "mce_sensitivity", "selected_alternative")
    params = {"weights": "{congestion, emission, safety, cost, land} adding up to 1 (O13)",
              "directions": "per criterion: higher_is_better or lower_is_better",
              "manual_scores": "{safety: {A1: 3, A2: 4}, cost: {...}, land: {...}} on your stated scale",
              "scale": "the scale of the manual scores, e.g. '1-5, 5 best'",
              "equal_criterion": "score_zero, score_one or drop_and_reweight (land is equal for timing changes, D3)",
              "sensitivity_step": "weight change for the sensitivity test, e.g. 0.1",
              "missing_criteria": "error (default) or drop_and_reweight a criterion that has no scores yet"}
    required_params = ("weights", "directions", "manual_scores", "scale", "equal_criterion", "sensitivity_step")
    tasks = ("T29", "T30")
    waits_on = ("O13",)
    note = "Congestion and emission are scored as the reduction against the existing plan. Five criteria (D3)."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.alternatives import mce

        out = mce(inputs["alternatives"], inputs["pre_sumo_scores"], ctx.slot, params, _slot_dir(ctx))
        return {"mce_scores": out.parent / "mce_scores.csv", "mce_sensitivity": out.parent / "mce_sensitivity.csv",
                "selected_alternative": out}
