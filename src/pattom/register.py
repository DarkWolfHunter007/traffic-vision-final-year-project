"""Source register (PRD section 8.1, decision D15).

Input values come only from the footage or from ``sources/register.yaml``.
Asking for anything else raises :class:`SourceGap`; the code never falls back
to a default number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pattom.paths import REPO_ROOT

DEFAULT_REGISTER = REPO_ROOT / "sources" / "register.yaml"
STATUSES = {"verified", "reported"}


class SourceGap(LookupError):
    """A needed value is not in the register. Report it; do not fill it."""


@dataclass(frozen=True)
class RegisteredValue:
    key: str
    value: Any
    unit: str
    source: str
    ref: str
    status: str
    extra: dict[str, Any]

    @property
    def citation(self) -> str:
        label = f"{self.source}, {self.ref}"
        if self.status == "reported":
            label += " (source not checked)"
        return label


class Register:
    def __init__(self, data: dict[str, Any]):
        self.sources: dict[str, Any] = data.get("sources") or {}
        self._values: dict[str, Any] = data.get("values") or {}
        for key, entry in self._values.items():
            missing = {"value", "unit", "source", "ref", "status"} - entry.keys()
            if missing:
                raise ValueError(f"register entry {key!r} lacks {sorted(missing)}")
            if entry["status"] not in STATUSES:
                raise ValueError(f"register entry {key!r} has unknown status {entry['status']!r}")
            if entry["source"] not in self.sources:
                raise ValueError(f"register entry {key!r} cites unregistered source {entry['source']!r}")

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTER) -> "Register":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {})

    def get(self, key: str) -> RegisteredValue:
        entry = self._values.get(key)
        if entry is None:
            raise SourceGap(
                f"{key!r} is not in the source register (D15). Report it as a gap; "
                "the user decides whether to add a source."
            )
        known = {"value", "unit", "source", "ref", "status"}
        return RegisteredValue(
            key=key,
            value=entry["value"],
            unit=entry["unit"],
            source=entry["source"],
            ref=entry["ref"],
            status=entry["status"],
            extra={k: v for k, v in entry.items() if k not in known},
        )

    def item(self, key: str, name: str) -> tuple[Any, RegisteredValue]:
        """One member of a table-valued entry, e.g. a PCU factor."""
        entry = self.get(key)
        if name not in entry.value:
            raise SourceGap(f"{key!r} has no value for {name!r} ({entry.citation}).")
        return entry.value[name], entry
