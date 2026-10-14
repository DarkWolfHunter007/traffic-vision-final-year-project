"""Labelled values.

Every number the pipeline produces is measured, derived or estimated, and
carries where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ValueType(StrEnum):
    MEASURED = "measured"  # read from the footage
    DERIVED = "derived"  # computed from measured values and registered formulas
    ESTIMATED = "estimated"  # depends on an assumption or a reported factor


@dataclass(frozen=True)
class Labelled:
    value: Any
    unit: str
    value_type: ValueType
    sources: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = field(default=())

    @property
    def source_not_checked(self) -> bool:
        return any("source not checked" in s for s in self.sources)
