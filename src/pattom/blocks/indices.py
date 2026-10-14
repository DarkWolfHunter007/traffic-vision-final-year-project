"""G Congestion index and emission estimate; H congestion-emission analysis (problem list)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class CongestionIndex(Block):
    name = "congestion-index"
    component = "G"
    title = "Congestion index"
    inputs = {"capacity_vc": "capacity_vc", "stopped_delay": "stopped_delay", "queue": "queue"}
    outputs = ("congestion_index",)
    params = {"indicators": "[{source: capacity_vc|stopped_delay|queue, weight, direction: higher_is_worse, "
                            "normalise: {method: minmax} or {method: reference, min, max}}] (O4)",
              "formula_version": "name of the approved formula (O4)",
              "bands": "optional interpretation scale, e.g. [{max: 0.33, label: low}, ...]",
              "queue_aggregate": "mean (default) or max of the cycles in an interval",
              "interval_s": "interval length, s (default 900)"}
    required_params = ("indicators", "formula_version")
    tasks = ("T47", "T23")
    note = "Weights must add up to 1; each indicator is scaled to 0-1 with 1 the worst."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.indices import congestion_index

        used = {i["source"] for i in params["indicators"]}
        tables = {k: v for k, v in inputs.items() if k in used}
        return {"congestion_index": congestion_index(tables, ctx.slot, params, inputs["capacity_vc"].parent)}


@register_block
class Emissions(Block):
    name = "emissions"
    component = "G"
    title = "Baseline emission estimate (phase 1: CO2 while stopped)"
    inputs = {"vehicles": "stopped_delay_vehicles"}
    outputs = ("emissions", "emission_gaps")
    params = {"class_fuel": "class -> {idle_row, fuel}, e.g. {car: {idle_row: car_petrol, fuel: petrol}} (assumption)",
              "moving_factor_key": "register key of the per-km factors (default arai.co2_g_per_km)",
              "interval_s": "interval length, s (default 900)", "offset_s": "file start within the slot, s"}
    required_params = ("class_fuel",)
    tasks = ("T24", "T25")
    waits_on = ("O17",)
    note = ("Estimates, not measurements. Factors only from sources/register.yaml; missing ones are listed in "
            "emission_gaps.csv. CO, HC, NOx and PM wait for their sources (O17).")

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.indices import emissions

        out = emissions(inputs["vehicles"], ctx.slot, params, inputs["vehicles"].parent)
        return {"emissions": out, "emission_gaps": out.parent / "emission_gaps.csv"}


@register_block
class Analysis(Block):
    name = "analysis"
    component = "H"
    title = "Congestion-emission analysis and problem list"
    inputs = {"capacity_vc": "capacity_vc", "stopped_delay": "stopped_delay", "queue": "queue",
              "congestion_index": "congestion_index", "emissions": "emissions"}
    outputs = ("indicators", "problems")
    params = {"rules": "[{indicator: vc_ratio|mean_stopped_delay_s|queue_length_m|congestion_index|co2_kg, "
                       "op: '>', value, problem: text}]",
              "interval_s": "interval length, s (default 900)"}
    required_params = ("rules",)
    tasks = ("T26",)
    note = "Problems come from your rules applied to the data; no threshold is built in."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.indices import problems

        out = problems(inputs, ctx.slot, params, inputs["capacity_vc"].parent)
        return {"indicators": out.parent / "indicators.csv", "problems": out}
