"""Signal phases read from the footage (FR-10, ARCHITECTURE 4.5, task T19).

The signal plan is measured: the user watches the prepared video and logs each
change of each visible signal head. This module checks the log and turns it
into cycles and green, amber and red durations. Nothing here is assumed; the
remembered timings (N-S about 50 s, E-W about 20-30 s) are not used.

Log file (CSV, one row per change, times in seconds of the prepared video):

    time_s,signal_head,state
    12.4,N,green
    62.9,N,amber
    65.9,N,red

Heads map to approaches in the definitions file (``signal_heads``).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

STATES = ("green", "amber", "red")


@dataclass(frozen=True)
class Interval:
    head: str
    state: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Cycle:
    head: str
    start_s: float  # start of green
    end_s: float  # start of the next green
    green_s: float
    amber_s: float
    red_s: float

    @property
    def length_s(self) -> float:
        return self.end_s - self.start_s


def load_log(path: Path) -> dict[str, list[tuple[float, str]]]:
    by_head: dict[str, list[tuple[float, str]]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            state = row["state"].strip().lower()
            if state not in STATES:
                raise ValueError(f"{path}:{i}: state must be green, amber or red, got {row['state']!r}")
            by_head[row["signal_head"].strip()].append((float(row["time_s"]), state))
    for head, changes in by_head.items():
        changes.sort()
        for (t1, s1), (t2, s2) in zip(changes, changes[1:]):
            if t1 == t2:
                raise ValueError(f"head {head}: two changes at {t1} s")
            if s1 == s2:
                raise ValueError(f"head {head}: {s1} logged twice in a row ({t1} s, {t2} s)")
    if not by_head:
        raise ValueError(f"{path}: empty signal log")
    return dict(by_head)


def intervals(changes: list[tuple[float, str]], head: str) -> list[Interval]:
    """Closed intervals between logged changes; the open tail is dropped."""
    return [Interval(head, s, t, t_next) for (t, s), (t_next, _) in zip(changes, changes[1:])]


def cycles(changes: list[tuple[float, str]], head: str) -> list[Cycle]:
    """Complete cycles from one start of green to the next."""
    greens = [i for i, (_, s) in enumerate(changes) if s == "green"]
    out = []
    for a, b in zip(greens, greens[1:]):
        dur = dict.fromkeys(STATES, 0.0)
        for (t, s), (t_next, _) in zip(changes[a:b], changes[a + 1:b + 1]):
            dur[s] += t_next - t
        out.append(Cycle(head, changes[a][0], changes[b][0], dur["green"], dur["amber"], dur["red"]))
    return out


def state_at(changes: list[tuple[float, str]], t: float) -> str | None:
    """Signal state at time t, or None before the first logged change."""
    current = None
    for ts, s in changes:
        if ts > t:
            break
        current = s
    return current


def summary(log: dict[str, list[tuple[float, str]]]) -> dict[str, dict]:
    """Measured mean cycle, green, amber and red per head (seconds)."""
    out = {}
    for head, changes in log.items():
        cs = cycles(changes, head)
        out[head] = {
            "cycles": len(cs),
            "mean_cycle_s": mean(c.length_s for c in cs) if cs else None,
            "mean_green_s": mean(c.green_s for c in cs) if cs else None,
            "mean_amber_s": mean(c.amber_s for c in cs) if cs else None,
            "mean_red_s": mean(c.red_s for c in cs) if cs else None,
            "value_type": "measured",
        }
    return out
