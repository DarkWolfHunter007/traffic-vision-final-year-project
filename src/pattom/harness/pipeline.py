"""Pipeline: an ordered list of blocks read from a YAML file.

    slot: test
    inputs:                      # artifacts that exist before the run
      video.raw: data/raw/IMG_1480.MOV
    blocks:
      - use: cfr                 # block name (pattom blocks lists them)
        params: {fps: 30}
      - use: undistort
        enabled: false           # switched off: lens calibration not done yet
      - use: detect
        bind: {video: video.cfr} # feed the CFR copy while undistort is off
        params: {config: configs/detection.yaml}

Blocks run in the listed order. Before anything runs, the whole list is
checked: every input must come from ``inputs``, an earlier block or (with
``only``) the previous run's manifest; required parameters must be set; and a
planned block must not be enabled. The manifest ``runs/<slot>/pipeline.json``
records what each block read and wrote.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import get_block
from pattom.paths import REPO_ROOT, RUNS
from pattom.runmeta import code_revision, sha256_file

ENTRY_KEYS = {"use", "id", "enabled", "bind", "params"}
SETTINGS_FILE = "settings_file"  # any block: a YAML file of parameters (or a section per block)


class PipelineError(RuntimeError):
    pass


@dataclass
class Step:
    id: str
    block: type[Block]
    enabled: bool
    bind: dict[str, str]
    params: dict[str, Any]

    def port_keys(self) -> dict[str, str]:
        """Input port -> artifact key, after the entry's bindings."""
        return {port: self.bind.get(port, key) for port, key in self.block.inputs.items()}

    def effective_params(self, ctx: RunContext) -> dict[str, Any]:
        """The entry's params, on top of the YAML file named by ``settings_file`` (if any)."""
        params = dict(self.params)
        path = params.pop(SETTINGS_FILE, None)
        if not path:
            return params
        f = ctx.resolve(path)
        if not f.exists():
            raise PipelineError(f"{self.id}: settings_file {path} does not exist")
        loaded = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise PipelineError(f"{self.id}: settings_file {path} must hold a mapping of parameters")
        # One file can hold several blocks' settings, in sections named by step id or block name.
        for key in (self.id, self.block.name):
            if isinstance(loaded.get(key), dict):
                loaded = loaded[key]
                break
        return {**loaded, **params}


@dataclass
class Pipeline:
    slot: str
    steps: list[Step]
    inputs: dict[str, str] = field(default_factory=dict)
    source: Path | None = None
    runs_dir: Path = RUNS
    repo_root: Path = REPO_ROOT

    @classmethod
    def load(cls, path: Path) -> "Pipeline":
        spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        p = cls.from_dict(spec)
        p.source = Path(path)
        return p

    @classmethod
    def from_dict(cls, spec: dict[str, Any]) -> "Pipeline":
        if not spec.get("slot"):
            raise PipelineError("pipeline needs a slot (e.g. test, offpeak, peak)")
        steps, seen = [], set()
        for i, entry in enumerate(spec.get("blocks") or []):
            if isinstance(entry, str):
                entry = {"use": entry}
            extra = set(entry) - ENTRY_KEYS
            if extra or "use" not in entry:
                raise PipelineError(f"block entry {i}: needs 'use'; unknown keys {sorted(extra)}")
            block = get_block(entry["use"])
            sid = entry.get("id", block.name)
            if sid in seen:
                raise PipelineError(f"two blocks with id {sid!r}; give one an 'id'")
            seen.add(sid)
            bind = dict(entry.get("bind") or {})
            unknown_ports = set(bind) - set(block.inputs)
            if unknown_ports:
                raise PipelineError(f"{sid}: block {block.name!r} has no input ports {sorted(unknown_ports)}")
            steps.append(Step(sid, block, bool(entry.get("enabled", True)), bind, dict(entry.get("params") or {})))
        return cls(slot=str(spec["slot"]), steps=steps, inputs=dict(spec.get("inputs") or {}))

    # --- checking ---------------------------------------------------------

    def manifest_path(self) -> Path:
        return self.runs_dir / self.slot / "pipeline.json"

    def previous_artifacts(self) -> dict[str, str]:
        mp = self.manifest_path()
        if not mp.exists():
            return {}
        return json.loads(mp.read_text(encoding="utf-8")).get("artifacts", {})

    def _selected(self, only: list[str] | None) -> list[Step]:
        if only:
            unknown = set(only) - {s.id for s in self.steps}
            if unknown:
                raise PipelineError(f"no blocks with id {sorted(unknown)}")
        return [s for s in self.steps if s.enabled and (not only or s.id in only)]

    def check(self, only: list[str] | None = None) -> list[str]:
        """Problems that would stop the run. Empty means the run can start."""
        problems: list[str] = []
        ctx = RunContext(self.slot, repo_root=self.repo_root)
        available: dict[str, str] = {}
        if only:
            available.update({k: "previous run" for k in self.previous_artifacts()})
        for key, path in self.inputs.items():
            try:
                if not ctx.resolve(path).exists():
                    problems.append(f"input {key}: {path} does not exist")
            except ValueError as e:
                problems.append(f"input {key}: {e}")
            available[key] = "inputs"
        producers = {k: s.id for s in self.steps for k in s.block.outputs}
        for step in self._selected(only):
            b = step.block
            if b.status == "planned":
                waits = ", ".join(b.tasks + b.waits_on)
                problems.append(f"{step.id}: planned block, not built (waits on {waits}); set enabled: false")
            for port, key in step.port_keys().items():
                if key not in available:
                    hint = ""
                    src = producers.get(key)
                    if src and not next(s for s in self.steps if s.id == src).enabled:
                        hint = f" (produced by {src!r}, which is switched off; bind {port} to another artifact)"
                    elif src:
                        hint = f" (produced by {src!r}, which is not run before it)"
                    problems.append(f"{step.id}: input {port} needs artifact {key!r}, not available{hint}")
            try:
                params = step.effective_params(ctx)
            except PipelineError as e:
                problems.append(str(e))
                params = {}
            missing = [p for p in b.required_params if params.get(p) in (None, "", [], {})]
            if missing:
                problems.append(f"{step.id}: missing required params {missing}")
            unknown = set(params) - set(b.params)
            if unknown:
                problems.append(f"{step.id}: unknown params {sorted(unknown)}")
            for key in b.outputs:
                available[key] = step.id
        return problems

    # --- running ----------------------------------------------------------

    def run(self, only: list[str] | None = None, log: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Run the selected blocks. ``log`` receives progress lines; the manifest is
        rewritten after every step so the app can follow the run."""
        problems = self.check(only)
        if problems:
            raise PipelineError("pipeline check failed:\n  " + "\n  ".join(problems))
        log = log or (lambda msg: None)
        ctx = RunContext(self.slot, repo_root=self.repo_root, log=log)
        artifacts: dict[str, str] = self.previous_artifacts() if only else {}
        artifacts.update(self.inputs)
        manifest: dict[str, Any] = {
            "slot": self.slot,
            "config": str(self.source) if self.source else None,
            "config_sha256": sha256_file(self.source) if self.source else None,
            "code_revision": code_revision(),
            "date_run": _now(),
            "only": only,
            "steps": [],
        }
        selected = self._selected(only)
        manifest["planned_steps"] = [s.id for s in selected]
        try:
            for n, step in enumerate(selected, start=1):
                record: dict[str, Any] = {"id": step.id, "block": step.block.name, "started": _now(),
                                          "params": step.params, "status": "running"}
                manifest["steps"].append(record)
                manifest["artifacts"] = artifacts
                self._write_manifest(manifest)
                log(f"[{n}/{len(selected)}] {step.id}: started")
                ins = {port: ctx.resolve(artifacts[key]) for port, key in step.port_keys().items()}
                record["inputs"] = {port: _rel(p, self.repo_root) for port, p in ins.items()}
                ctx.artifacts = {k: ctx.resolve(v) for k, v in artifacts.items()}
                try:
                    outs = step.block().run(ctx, ins, step.effective_params(ctx))
                except Exception as e:
                    record.update(status="failed", error=f"{type(e).__name__}: {e}", finished=_now())
                    log(f"[{n}/{len(selected)}] {step.id}: FAILED {type(e).__name__}: {e}")
                    raise PipelineError(f"{step.id} failed: {e}") from e
                missing = set(step.block.outputs) - set(outs)
                if missing:
                    record.update(status="failed", error=f"did not produce {sorted(missing)}", finished=_now())
                    raise PipelineError(f"{step.id} did not produce {sorted(missing)}")
                record["outputs"] = {}
                for key, path in outs.items():
                    rel = _rel(ctx.resolve(path), self.repo_root)
                    artifacts[key] = rel
                    record["outputs"][key] = rel
                record.update(status="done", finished=_now())
                log(f"[{n}/{len(selected)}] {step.id}: done -> {', '.join(record['outputs'].values())}")
        finally:
            manifest["artifacts"] = artifacts
            manifest["finished"] = _now()
            self._write_manifest(manifest)
        return manifest

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        mp = self.manifest_path()
        mp.parent.mkdir(parents=True, exist_ok=True)
        tmp = mp.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        tmp.replace(mp)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)
