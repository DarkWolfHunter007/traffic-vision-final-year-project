"""The block contract.

A block is one stage of the pipeline. It names its input ports and the
artifacts it produces, the ARCHITECTURE component it implements, the project
tasks it serves, and the open decisions it waits on. A block whose method is
not settled is ``planned``: it is listed and checked like any other block but
refuses to run, so no value is produced before its definition is approved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pattom.paths import REPO_ROOT

STATUSES = ("built", "planned")


class BlockNotReady(RuntimeError):
    """A planned block was asked to run. Its tasks or decisions are still open."""


@dataclass
class RunContext:
    """What a block sees while it runs."""

    slot: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    repo_root: Path = REPO_ROOT
    log: Callable[[str], None] = field(default=lambda msg: None, repr=False)  # progress lines

    def resolve(self, path: str | Path) -> Path:
        """A repository path. Anything outside the repository is refused."""
        p = Path(path)
        p = (p if p.is_absolute() else self.repo_root / p).resolve()
        root = self.repo_root.resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"{path} is outside the repository ({root})")
        return p


class Block:
    """Base class for pipeline blocks.

    Subclasses set the class attributes and implement :meth:`run`.

    inputs   port name -> default artifact key. A pipeline entry can bind a
             port to another key (for example ``video: video.cfr`` while the
             lens correction is not available).
    outputs  artifact keys the block produces.
    params   parameter name -> short description. Parameters with no default
             in the block are required; open decisions are always required.
    """

    name: ClassVar[str]
    component: ClassVar[str]  # ARCHITECTURE section 3 id, e.g. "C"
    title: ClassVar[str]
    inputs: ClassVar[dict[str, str]] = {}
    outputs: ClassVar[tuple[str, ...]] = ()
    params: ClassVar[dict[str, str]] = {}
    required_params: ClassVar[tuple[str, ...]] = ()
    tasks: ClassVar[tuple[str, ...]] = ()
    waits_on: ClassVar[tuple[str, ...]] = ()
    status: ClassVar[str] = "built"
    note: ClassVar[str] = ""

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        raise NotImplementedError

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "component": cls.component,
            "title": cls.title,
            "status": cls.status,
            "inputs": dict(cls.inputs),
            "outputs": list(cls.outputs),
            "params": dict(cls.params),
            "required_params": list(cls.required_params),
            "tasks": list(cls.tasks),
            "waits_on": list(cls.waits_on),
            "note": cls.note,
        }


class PlannedBlock(Block):
    """A stage whose method is not yet approved. It never produces values."""

    status = "planned"

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        waits = ", ".join(self.tasks + self.waits_on) or "nothing recorded"
        raise BlockNotReady(f"block {self.name!r} ({self.title}) is planned, not built. "
                            f"It waits on: {waits}. {self.note}".strip())
