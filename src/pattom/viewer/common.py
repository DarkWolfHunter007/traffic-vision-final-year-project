"""Helpers shared by the app's routes."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
BROWSER_VIDEO = {".mp4", ".webm", ".m4v"}  # HEVC .MOV originals do not play in browsers


def inside(root: Path, p: str | Path) -> Path:
    """A path under the repository root; anything else is refused."""
    p = Path(p)
    p = (p if p.is_absolute() else root / p).resolve()
    if p != root.resolve() and root.resolve() not in p.parents:
        raise HTTPException(403, "path outside the repository")
    return p


def rel(root: Path, p: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()


def read_json(p: Path) -> dict[str, Any] | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_yaml_or_example(root: Path, path: str, example: str) -> tuple[dict[str, Any], bool]:
    """The local config, or its example if the local copy does not exist yet."""
    p = root / path
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}, False
    ex = root / example
    return (yaml.safe_load(ex.read_text(encoding="utf-8")) or {}) if ex.exists() else {}, True


def validated_write(target: Path, text: str, validate) -> None:
    """Write text to target only if validate(path) accepts a temporary copy.

    validate raises on a bad file; the error is returned to the page as 422.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=target.suffix, dir=target.parent, delete=False,
                                     encoding="utf-8", newline="") as f:
        f.write(text)
        tmp = Path(f.name)
    try:
        validate(tmp)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        msg = str(e).replace(str(tmp), target.name).replace(tmp.name, target.name)
        raise HTTPException(422, f"{type(e).__name__}: {msg}") from None
    tmp.replace(target)


def dump_yaml(data: dict[str, Any], header: str = "") -> str:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110)
    return (header.rstrip() + "\n\n" if header else "") + body
