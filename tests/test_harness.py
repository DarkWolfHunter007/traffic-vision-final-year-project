import json

import pytest

from pattom.harness import Block, BlockNotReady, Pipeline, PipelineError, all_blocks, register_block
from pattom.harness.block import PlannedBlock, RunContext


@register_block
class _Upper(Block):
    name = "test-upper"
    component = "T"
    title = "Upper-case a text file"
    inputs = {"text": "text.raw"}
    outputs = ("text.upper",)
    params = {"suffix": "appended text"}

    def run(self, ctx, inputs, params):
        out = ctx.resolve("out/upper.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(inputs["text"].read_text().upper() + params.get("suffix", ""))
        return {"text.upper": out}


@register_block
class _Count(Block):
    name = "test-count"
    component = "T"
    title = "Count characters"
    inputs = {"text": "text.upper"}
    outputs = ("text.count",)
    params = {"label": "required label"}
    required_params = ("label",)

    def run(self, ctx, inputs, params):
        out = ctx.resolve("out/count.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({params["label"]: len(inputs["text"].read_text())}))
        return {"text.count": out}


@register_block
class _Planned(PlannedBlock):
    name = "test-planned"
    component = "T"
    title = "Not built"
    inputs = {"text": "text.upper"}
    outputs = ("text.other",)
    tasks = ("T99",)
    waits_on = ("O99",)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "in.txt").write_text("abc")
    return tmp_path


def make(repo, blocks, **kw):
    p = Pipeline.from_dict({"slot": "t", "inputs": {"text.raw": "in.txt"}, "blocks": blocks, **kw})
    p.repo_root = repo
    p.runs_dir = repo / "runs"
    return p


def test_builtin_blocks_cover_every_component():
    blocks = all_blocks()
    assert set("BCDEFGHIJKLM") <= {b.component for b in blocks.values()}
    assert blocks["detect"].status == "built" and blocks["queue"].status == "built"


def test_run_writes_outputs_and_manifest(repo):
    p = make(repo, ["test-upper", {"use": "test-count", "params": {"label": "n"}}])
    assert p.check() == []
    manifest = p.run()
    assert [s["status"] for s in manifest["steps"]] == ["done", "done"]
    assert json.loads((repo / "out/count.json").read_text()) == {"n": 3}
    saved = json.loads((repo / "runs/t/pipeline.json").read_text())
    assert saved["artifacts"]["text.count"] == "out/count.json"


def test_switched_off_block_names_the_missing_input(repo):
    p = make(repo, [{"use": "test-upper", "enabled": False}, {"use": "test-count", "params": {"label": "n"}}])
    [problem] = p.check()
    assert "text.upper" in problem and "switched off" in problem
    with pytest.raises(PipelineError):
        p.run()


def test_bind_feeds_another_artifact(repo):
    p = make(repo, [{"use": "test-upper", "enabled": False},
                    {"use": "test-count", "bind": {"text": "text.raw"}, "params": {"label": "n"}}])
    assert p.check() == []
    p.run()
    assert json.loads((repo / "out/count.json").read_text()) == {"n": 3}


def test_required_and_unknown_params(repo):
    p = make(repo, ["test-upper", {"use": "test-count", "params": {"lable": "n"}}])
    problems = " ".join(p.check())
    assert "missing required params ['label']" in problems and "unknown params ['lable']" in problems


def test_planned_block_must_be_off(repo):
    p = make(repo, ["test-upper", "test-planned"])
    [problem] = p.check()
    assert "planned" in problem and "O99" in problem
    with pytest.raises(BlockNotReady, match="T99, O99"):
        _Planned().run(RunContext("t", repo_root=repo), {}, {})


def test_only_reuses_previous_artifacts(repo):
    make(repo, ["test-upper", {"use": "test-count", "params": {"label": "n"}}]).run()
    p = make(repo, ["test-upper", {"use": "test-count", "params": {"label": "m"}}])
    manifest = p.run(only=["test-count"])
    assert [s["id"] for s in manifest["steps"]] == ["test-count"]
    assert json.loads((repo / "out/count.json").read_text()) == {"m": 3}


def test_paths_outside_repo_are_refused(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.txt"
    outside.write_text("x")
    p = Pipeline.from_dict({"slot": "t", "inputs": {"text.raw": str(outside)}, "blocks": ["test-upper"]})
    p.repo_root, p.runs_dir = repo, repo / "runs"
    assert "outside the repository" in p.check()[0]


def test_unknown_block_and_duplicate_ids():
    with pytest.raises(KeyError, match="no block named"):
        Pipeline.from_dict({"slot": "t", "blocks": ["nope"]})
    with pytest.raises(PipelineError, match="two blocks with id"):
        Pipeline.from_dict({"slot": "t", "blocks": ["test-upper", "test-upper"]})


def test_example_pipeline_is_valid():
    from pattom.paths import REPO_ROOT

    p = Pipeline.load(REPO_ROOT / "configs" / "pipeline.example.yaml")
    assert {s.block.name for s in p.steps} >= {"cfr", "detect", "track", "comparison"}
    assert not any(s.enabled and s.block.status == "planned" for s in p.steps)
