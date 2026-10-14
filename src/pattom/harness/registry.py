"""Block registry.

Built-in blocks live in ``pattom.blocks``. Other packages add blocks by
declaring an entry point in the ``pattom.blocks`` group that points at a
module (importing it registers its blocks) or at a Block subclass.
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points

from pattom.harness.block import STATUSES, Block

_BLOCKS: dict[str, type[Block]] = {}
_loaded = False


def register_block(cls: type[Block]) -> type[Block]:
    """Class decorator: make a block available to pipelines by its name."""
    for attr in ("name", "component", "title"):
        if not getattr(cls, attr, None):
            raise TypeError(f"{cls.__name__} must set {attr!r}")
    if cls.status not in STATUSES:
        raise TypeError(f"{cls.__name__}: status must be one of {STATUSES}")
    unknown = set(cls.required_params) - set(cls.params)
    if unknown:
        raise TypeError(f"{cls.__name__}: required params not described: {sorted(unknown)}")
    existing = _BLOCKS.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"two blocks named {cls.name!r}: {existing.__module__} and {cls.__module__}")
    _BLOCKS[cls.name] = cls
    return cls


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    importlib.import_module("pattom.blocks")
    for ep in entry_points(group="pattom.blocks"):
        obj = ep.load()
        if isinstance(obj, type) and issubclass(obj, Block):
            register_block(obj)


def all_blocks() -> dict[str, type[Block]]:
    _load()
    return dict(_BLOCKS)


def get_block(name: str) -> type[Block]:
    _load()
    try:
        return _BLOCKS[name]
    except KeyError:
        raise KeyError(f"no block named {name!r}; known: {', '.join(sorted(_BLOCKS))}") from None
