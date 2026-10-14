"""Signalised capacity per IRC SP 41 (1994) section 7.6 (FR-13, D11).

Every constant comes from the source register. Inputs such as green time and
cycle time are measured from the footage (T19).
"""

from __future__ import annotations

from collections.abc import Mapping

from pattom.register import Register, SourceGap
from pattom.values import Labelled, ValueType


def saturation_flow(width_m: float, register: Register, gradient_pct: float = 0.0) -> Labelled:
    """Saturation flow s in PCU/h for an approach of the given width.

    SP 41 gives a table for narrow approaches (p. 77) and s = 525 w for
    5.5-18 m (p. 76). The two disagree at 5.5 m (2990 vs 2887.5); the formula
    is used from 5.5 m because that is its stated range. Widths between the
    tabulated narrow values are not interpolated: that would be a value the
    register does not hold.

    gradient_pct is positive uphill, negative downhill (p. 77).
    """
    per_m = register.get("sp41.saturation_flow_per_m")
    lo, hi = per_m.extra["valid_range_m"]
    if lo <= width_m <= hi:
        s = per_m.value * width_m
        refs = [per_m.citation]
    elif width_m < lo:
        narrow = register.get("sp41.saturation_flow_narrow")
        if float(width_m) not in narrow.value:
            raise SourceGap(
                f"SP 41 lists narrow-approach saturation flow only for widths "
                f"{sorted(narrow.value)} m; {width_m} m is not listed ({narrow.citation})."
            )
        s = float(narrow.value[float(width_m)])
        refs = [narrow.citation]
    else:
        raise SourceGap(f"SP 41 gives saturation flow only up to {hi} m; {width_m} m is outside ({per_m.citation}).")

    if gradient_pct:
        grad = register.get("sp41.gradient_effect_per_pct")
        s *= 1.0 - grad.value * gradient_pct
        refs.append(grad.citation)
    return Labelled(s, "PCU/h", ValueType.DERIVED, tuple(refs))


def capacity(green_s: float, cycle_s: float, saturation: Labelled) -> Labelled:
    """Capacity = g x s / c (SP 41 p. 75). g is effective green."""
    if not 0 < green_s <= cycle_s:
        raise ValueError("effective green must be positive and not longer than the cycle")
    return Labelled(
        green_s * saturation.value / cycle_s,
        saturation.unit,
        ValueType.DERIVED,
        saturation.sources + ("irc_sp41_1994, p. 75",),
    )


def pcu_flow(counts: Mapping[str, int], interval_s: float, table: str, register: Register) -> Labelled:
    """Convert vehicle counts over an interval to a flow in PCU/h.

    counts maps SP 41 row names (e.g. ``motorcycle_scooter``) to vehicles.
    The PCU table must be named because the project has not chosen one (O3).
    """
    if interval_s <= 0:
        raise ValueError("interval must be positive")
    key = f"sp41.pcu.{table}"
    entry = register.get(key)
    total = 0.0
    for row, n in counts.items():
        factor, _ = register.item(key, row)
        total += factor * n
    return Labelled(total * 3600.0 / interval_s, "PCU/h", ValueType.DERIVED, (entry.citation,))


def vc_ratio(volume_pcu_h: Labelled, cap: Labelled) -> Labelled:
    if volume_pcu_h.unit != "PCU/h" or cap.unit != "PCU/h":
        raise ValueError("V/C needs both volume and capacity in PCU/h")
    return Labelled(
        volume_pcu_h.value / cap.value, "ratio", ValueType.DERIVED, volume_pcu_h.sources + cap.sources
    )


def fixed_time_cycle(lost_time_s: float, flow_ratios: list[float]) -> Labelled:
    """Co = (1.5 L + 5) / (1 - Y), SP 41 p. 78.

    flow_ratios holds the critical y = q/s of each phase; Y is their sum.
    L is the total lost time per cycle (n x l + R), with R measured.
    """
    y_total = sum(flow_ratios)
    if y_total >= 1:
        raise ValueError(f"Y = {y_total:.3f} >= 1: the fixed-time formula does not apply (oversaturated)")
    co = (1.5 * lost_time_s + 5) / (1 - y_total)
    return Labelled(co, "s", ValueType.DERIVED, ("irc_sp41_1994, p. 78",))


def green_split(effective_green_total_s: float, flow_ratios: list[float]) -> list[Labelled]:
    """Effective greens in proportion to each phase's y (SP 41 p. 78)."""
    y_total = sum(flow_ratios)
    return [
        Labelled(effective_green_total_s * y / y_total, "s", ValueType.DERIVED, ("irc_sp41_1994, p. 78",))
        for y in flow_ratios
    ]


# --- Capacity and V/C per approach and interval (block capacity-vc) ---------

CAPACITY_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "volume_line", "volume_pcu_h",
                   "saturation_flow_pcu_h", "effective_green_s", "cycle_s", "n_cycles", "capacity_pcu_h",
                   "capacity_unit", "vc_ratio", "pcu_set", "effective_green", "source", "source_status", "value_type"]
EFFECTIVE_GREEN = ("green", "green_plus_amber_minus_lost")


def run_capacity(interval_counts_csv, cycles_csv, slot: str, params: dict, out_dir, register: Register | None = None):
    """V/C per approach and interval.

    params (all required, no defaults):
      pcu_table      SP 41 PCU table to use (open decision O3)
      class_rows     project class -> SP 41 PCU row, e.g. {car: passenger_car}
      approaches     {north: {width_m, gradient_pct, signal_head, volume_line}}; width and gradient
                     are site measurements; volume_line is the counting line whose counts give demand
      effective_green  "green" (observed green) or "green_plus_amber_minus_lost"
                     (green + amber - SP 41 lost time per phase, p. 78)
    Cycle and green are the means over the complete cycles observed for the head.
    """
    from collections import defaultdict
    from statistics import mean

    from pattom.tables import read_csv, require, write_csv, write_meta

    require(params, "pcu_table", "class_rows", "approaches", "effective_green",
            why="PCU table (O3), class mapping, measured approach geometry and the effective-green definition")
    if params["effective_green"] not in EFFECTIVE_GREEN:
        raise ValueError(f"effective_green must be one of {EFFECTIVE_GREEN}")
    register = register or Register.load()
    lost = register.get("sp41.lost_time_per_phase_s") if params["effective_green"] != "green" else None
    cycles = read_csv(cycles_csv)
    counts = read_csv(interval_counts_csv)
    rows = []
    for approach, spec in sorted(params["approaches"].items()):
        for k in ("width_m", "gradient_pct", "signal_head", "volume_line"):
            if k not in spec:
                raise ValueError(f"approach {approach}: missing {k} (gradient_pct is measured; use 0 only if measured flat)")
        own = [c for c in cycles if c["signal_head"] == spec["signal_head"]]
        if not own:
            raise ValueError(f"approach {approach}: no complete cycles for signal head {spec['signal_head']!r}")
        c_s = mean(float(c["cycle_s"]) for c in own)
        g_s = mean(float(c["green_s"]) for c in own)
        if lost is not None:
            g_s = g_s + mean(float(c["amber_s"]) for c in own) - float(lost.value)
        sat = saturation_flow(float(spec["width_m"]), register, float(spec["gradient_pct"]))
        cap = capacity(g_s, c_s, sat)
        per_interval = defaultdict(lambda: defaultdict(int))
        for r in counts:
            if r["line_name"] == spec["volume_line"]:
                per_interval[(float(r["interval_start_s"]), float(r["interval_end_s"]))][r["class"]] += int(r["count"])
        for (start, end), by_class in sorted(per_interval.items()):
            unmapped = sorted(set(by_class) - set(params["class_rows"]))
            if unmapped:
                raise ValueError(f"classes {unmapped} have no SP 41 PCU row in class_rows")
            sp41_counts = defaultdict(int)
            for cls, n in by_class.items():
                sp41_counts[params["class_rows"][cls]] += n
            vol = pcu_flow(sp41_counts, end - start, params["pcu_table"], register)
            vc = vc_ratio(vol, cap)
            rows.append({"slot": slot, "approach": approach, "interval_start_s": start, "interval_end_s": end,
                         "volume_line": spec["volume_line"], "volume_pcu_h": round(vol.value, 1),
                         "saturation_flow_pcu_h": round(sat.value, 1), "effective_green_s": round(g_s, 2),
                         "cycle_s": round(c_s, 2), "n_cycles": len(own), "capacity_pcu_h": round(cap.value, 1),
                         "capacity_unit": cap.unit, "vc_ratio": round(vc.value, 3), "pcu_set": params["pcu_table"],
                         "effective_green": params["effective_green"], "source": "; ".join(vc.sources),
                         "source_status": "verified" if not any("not checked" in s for s in vc.sources) else "reported",
                         "value_type": ValueType.DERIVED.value})
    from pathlib import Path

    out = write_csv(Path(out_dir) / "capacity_vc.csv", CAPACITY_FIELDS, rows)
    write_meta(Path(out_dir) / "capacity_vc.run.json", "F.capacity_vc", slot,
               {"interval_counts": interval_counts_csv, "signal_cycles": cycles_csv}, params)
    return out
