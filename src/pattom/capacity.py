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
