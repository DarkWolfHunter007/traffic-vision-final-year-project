import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from pattom.graph import NODE_TYPES, GraphError, load_graph, run_graph, validate_graph
from pattom.graph.server import Handler
from pattom.paths import REPO_ROOT

EXAMPLE = REPO_ROOT / "configs" / "graphs" / "pattom.example.yaml"


def test_example_graph_valid_and_ordered():
    order = validate_graph(load_graph(EXAMPLE))
    assert order.index("cfr") < order.index("detect") < order.index("track") < order.index("count")
    assert order.index("indicators") < order.index("congestion")


def test_every_node_runs_a_stage():
    assert all(t.run is not None for t in NODE_TYPES.values())


def test_type_mismatch_rejected():
    spec = load_graph(EXAMPLE)
    spec["edges"].append({"from": "track.tracks", "to": "detect.video"})
    with pytest.raises(GraphError, match="Type mismatch"):
        validate_graph(spec)


def test_missing_required_input_rejected():
    with pytest.raises(GraphError, match="not connected"):
        validate_graph({"nodes": {"d": {"type": "detect"}}, "edges": []})


def test_cycle_rejected():
    spec = {
        "nodes": {"g1": {"type": "ground"}, "g2": {"type": "ground"}},
        "edges": [{"from": "g1.tracks", "to": "g2.tracks"}, {"from": "g2.tracks", "to": "g1.tracks"}],
    }
    with pytest.raises(GraphError, match="cycle"):
        validate_graph(spec)


def test_failure_blocks_only_downstream(tmp_path):
    spec = load_graph(EXAMPLE)
    spec["nodes"]["cfr"]["params"]["video"] = str(tmp_path / "missing.mp4")
    r = run_graph(spec)
    assert r.status["cfr"] == "failed"
    assert all(r.status[n] == "skipped" for n in ("detect", "track", "congestion"))


def test_missing_required_param_and_unknown_param():
    r = run_graph({"nodes": {"c": {"type": "cfr", "params": {"bogus": 1}}}, "edges": []})
    assert r.status["c"] == "failed" and "bogus" in r.errors["c"]
    r = run_graph({"nodes": {"c": {"type": "cfr"}}, "edges": []})
    assert "required" in r.errors["c"]


def test_editor_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        nodes = json.load(urllib.request.urlopen(base + "/nodes"))
        assert {n["name"] for n in nodes} == set(NODE_TYPES)
        req = urllib.request.Request(base + "/validate", json.dumps(load_graph(EXAMPLE)).encode(), {"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))["valid"]
        assert b"Traffic" in urllib.request.urlopen(base + "/").read() or b"pipeline" in urllib.request.urlopen(base + "/").read()
    finally:
        server.shutdown()


def test_ancestor_slicing():
    from pattom.graph.engine import get_ancestors
    spec = load_graph(EXAMPLE)
    ancestors = get_ancestors(spec, "track")
    assert ancestors == {"cfr", "detect", "track"}
    assert "count" not in ancestors
    assert "congestion" not in ancestors


def test_content_hash_caching(tmp_path):
    from pattom.graph.engine import check_cache, compute_cache_key, write_cache
    dummy_out = tmp_path / "dummy.txt"
    dummy_out.write_text("dummy output", encoding="utf-8")
    key = compute_cache_key("cfr", {}, {"slot": "test", "fps": 30.0})
    write_cache("test_node", key, {"video": str(dummy_out)})
    cached = check_cache("test_node", key)
    assert cached is not None
    assert cached["video"] == str(dummy_out)
    # Stale cache if file is modified
    dummy_out.write_text("modified", encoding="utf-8")
    assert check_cache("test_node", key) is None


def test_gate_checks_o3_o4_o6():
    from pattom.graph.nodes import check_gate_o3, check_gate_o4, check_gate_o6
    g6 = check_gate_o6({"definitions": "configs/definitions.example.yaml"})
    assert g6["locked"] is True
    assert "not set yet" in g6["reason"]

    g3 = check_gate_o3({"config": "configs/indicators.example.yaml"})
    assert g3["locked"] is True

    g4 = check_gate_o4({"formula": "configs/congestion.example.yaml"})
    assert g4["locked"] is True


def test_locked_gate_refusal_in_run_graph():
    from pattom.graph.nodes import NodeType, NODE_TYPES
    dummy_type = NodeType(
        name="mock_gated",
        label="Mock Gated",
        inputs=(),
        outputs=(),
        gate_checker=lambda p: {"locked": True, "decision": "MOCK", "reason": "Test locked gate"}
    )
    NODE_TYPES["mock_gated"] = dummy_type
    try:
        spec = {"nodes": {"g": {"type": "mock_gated"}}, "edges": []}
        r = run_graph(spec)
        assert r.status["g"] == "locked"
        assert "Approval gate MOCK locked" in r.errors["g"]
    finally:
        NODE_TYPES.pop("mock_gated", None)


