"""Pipeline editing, checking and running from the app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from pattom.harness import Pipeline, PipelineError, all_blocks
from pattom.viewer.common import dump_yaml, inside, load_yaml_or_example, read_json, validated_write
from pattom.viewer.jobs import JobRunner

CONFIG = "configs/pipeline.yaml"
EXAMPLE = "configs/pipeline.example.yaml"
HEADER = """# Pipeline for one slot, saved from the Pattom app. See configs/pipeline.example.yaml
# for the commented version. Planned blocks must stay off (enabled: false)."""


def _pipeline(root: Path, spec: dict[str, Any]) -> Pipeline:
    try:
        p = Pipeline.from_dict(spec)
    except (PipelineError, KeyError) as e:
        raise HTTPException(422, str(e).strip("'\"")) from None
    p.repo_root, p.runs_dir = root, root / "runs"
    return p


def router(root: Path, jobs: JobRunner) -> APIRouter:
    r = APIRouter(prefix="/api")

    def describe(p: Pipeline, spec: dict[str, Any], from_example: bool) -> dict[str, Any]:
        manifest = read_json(p.manifest_path()) or {}
        ran = {s["id"]: s for s in manifest.get("steps", [])}
        steps = []
        for s in p.steps:
            d = s.block.describe()
            d.update(id=s.id, enabled=s.enabled, bind=s.bind, step_params=s.params, ports=s.port_keys(),
                     last_run=ran.get(s.id))
            steps.append(d)
        return {"spec": spec, "from_example": from_example, "steps": steps, "problems": p.check(),
                "manifest": {k: manifest.get(k) for k in ("date_run", "finished", "artifacts", "planned_steps")},
                "config": CONFIG}

    @r.get("/blocks")
    def blocks() -> list[dict[str, Any]]:
        return [b.describe() for b in sorted(all_blocks().values(), key=lambda b: (b.component, b.name))]

    @r.get("/pipeline")
    def get_pipeline() -> dict[str, Any]:
        spec, from_example = load_yaml_or_example(root, CONFIG, EXAMPLE)
        return describe(_pipeline(root, spec), spec, from_example)

    @r.post("/pipeline/check")
    def check(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return describe(_pipeline(root, spec), spec, False)

    @r.put("/pipeline")
    def save(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _pipeline(root, spec)
        validated_write(inside(root, CONFIG), dump_yaml(spec, HEADER), lambda path: Pipeline.load(path))
        return describe(_pipeline(root, spec), spec, False)

    @r.get("/pipeline/manifest/{slot}")
    def manifest(slot: str) -> dict[str, Any]:
        return read_json(inside(root, root / "runs" / slot / "pipeline.json")) or {}

    @r.post("/pipeline/run")
    def run(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if not (root / CONFIG).exists():
            raise HTTPException(409, "save the pipeline first")
        spec, _ = load_yaml_or_example(root, CONFIG, EXAMPLE)
        only = [s for s in body.get("only") or [] if s]
        problems = _pipeline(root, spec).check(only or None)
        if problems:
            raise HTTPException(422, "pipeline check failed: " + "; ".join(problems))
        args = ["pipeline", "run", CONFIG] + (["--only", ",".join(only)] if only else [])
        try:
            return jobs.start(args).as_dict()
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None

    @r.get("/jobs/current")
    def job(since: int = 0) -> dict[str, Any]:
        return jobs.job.as_dict(since) if jobs.job else {"state": "idle", "lines": [], "n_lines": 0}

    @r.post("/jobs/stop")
    def stop() -> dict[str, Any]:
        return {"stopped": jobs.stop()}

    return r
