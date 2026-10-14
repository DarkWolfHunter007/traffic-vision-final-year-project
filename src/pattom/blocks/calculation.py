"""F Calculation layer: stopped delay, queue length, capacity and V/C, count validation.

Settings that are open project decisions are required parameters with no
default. Long settings can live in a YAML file named by ``settings_file``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block

DEFINITION = {
    "stopped_speed_kmh": "speed below which a vehicle is stopped, km/h (O6)",
    "speed_window_s": "window for speed from ground positions, s (O6)",
    "definition_version": "name of the approved written definition (O6)",
}


@register_block
class StoppedDelay(Block):
    name = "stopped-delay"
    component = "F"
    title = "Stopped delay per approach and interval"
    inputs = {"tracks": "tracks.ground", "crossings": "crossings"}
    outputs = ("stopped_delay", "stopped_delay_vehicles")
    params = {**DEFINITION, "interval_s": "interval length, s (default 900)",
              "offset_s": "start of this file within its slot, s (default 0)"}
    required_params = tuple(DEFINITION)
    tasks = ("T21",)
    note = "Time each vehicle spends stopped before crossing its stop line. Needs ground-mapped tracks."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.queue_delay import stopped_delay

        out = stopped_delay(inputs["tracks"], inputs["crossings"], ctx.slot, params, inputs["tracks"].parent)
        return {"stopped_delay": out, "stopped_delay_vehicles": out.parent / "stopped_delay_vehicles.csv"}


@register_block
class Queue(Block):
    name = "queue"
    component = "F"
    title = "Queue length in metres per approach and cycle"
    inputs = {"tracks": "tracks.ground", "crossings": "crossings", "signal_cycles": "signal_cycles"}
    outputs = ("queue",)
    params = {**DEFINITION, "measure_at": "green_start or max_during_red (O6)",
              "approach_heads": "approach -> signal head, e.g. {north: N_main}",
              "lines": "counting lines (default configs/lines.yaml)",
              "ground": "ground points (default calibration/ground.yaml)"}
    required_params = (*DEFINITION, "measure_at", "approach_heads")
    tasks = ("T20",)
    note = "Distance from the stop line to the farthest stopped vehicle not yet across it."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.queue_delay import queue_lengths

        lines = ctx.resolve(params.get("lines", "configs/lines.yaml"))
        ground = ctx.resolve(params.get("ground", "calibration/ground.yaml"))
        out = queue_lengths(inputs["tracks"], inputs["crossings"], inputs["signal_cycles"], lines, ground, ctx.slot,
                            params, inputs["tracks"].parent)
        return {"queue": out}


@register_block
class CapacityVC(Block):
    name = "capacity-vc"
    component = "F"
    title = "Capacity (IRC SP 41 section 7.6) and V/C per approach"
    inputs = {"interval_counts": "interval_counts", "signal_cycles": "signal_cycles"}
    outputs = ("capacity_vc",)
    params = {"pcu_table": "SP 41 PCU table: table_3_1 or table_III_1 (O3)",
              "class_rows": "project class -> SP 41 PCU row, e.g. {car: passenger_car}",
              "approaches": "{north: {width_m, gradient_pct, signal_head, volume_line}} (site measurements)",
              "effective_green": "green or green_plus_amber_minus_lost"}
    required_params = ("pcu_table", "class_rows", "approaches", "effective_green")
    tasks = ("T22",)
    note = "Capacity = g x s / c with s from SP 41 (p. 76-77). Stop-line counts understate demand when oversaturated."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.capacity import run_capacity

        return {"capacity_vc": run_capacity(inputs["interval_counts"], inputs["signal_cycles"], ctx.slot, params,
                                            inputs["interval_counts"].parent)}


@register_block
class CountValidation(Block):
    name = "count-validation"
    component = "F"
    title = "Automatic counts against manual counts from playback"
    inputs = {"crossings": "crossings", "manual_counts": "manual_counts"}
    outputs = ("count_error",)
    tasks = ("T17",)
    note = "Make the manual counts on the Manual counts page. Error per line and class, including the west."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.validation import compare

        return {"count_error": compare(inputs["crossings"], inputs["manual_counts"], ctx.slot,
                                       inputs["crossings"].parent)}
