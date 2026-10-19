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
