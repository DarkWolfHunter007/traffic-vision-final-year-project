"""Checks for the beta-audit fixes (docs/audit/beta_audit.md)."""

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from pattom.counting import interval_counts
from pattom.graph import engine
from pattom.graph.server import Handler


def test_last_interval_ends_at_video_end():  # C1
    x = {"line_type": "arrival", "time_s": 1.0, "track_id": 1, "line_name": "A", "approach": "n", "class": "car"}
    rows = interval_counts([x], {}, "s", 900, 0, video_end_s=60.0)
    assert rows[0]["interval_end_s"] == 60.0
    assert interval_counts([x], {}, "s", 900)[0]["interval_end_s"] == 900.0


def test_cache_key_ignores_unrelated_code(monkeypatch):  # E1
    monkeypatch.setattr(engine, "code_revision", lambda: "changed")
    a = engine.compute_cache_key("detect", {}, {"x": 1})
    monkeypatch.setattr(engine, "code_revision", lambda: "changed-again")
    assert engine.compute_cache_key("detect", {}, {"x": 1}) == a


def test_emissions_cache_watches_vehicle_delay(tmp_path):  # C6
    d = tmp_path / "stopped_delay.csv"
    d.write_text("a\n1\n")
    v = tmp_path / "vehicle_delay.csv"
    v.write_text("x\n1\n")
    k1 = engine.compute_cache_key("emissions", {"delays": str(d)}, {})
    v.write_text("x\n2\n")
    assert engine.compute_cache_key("emissions", {"delays": str(d)}, {}) != k1


@pytest.fixture(scope="module")
def server():
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_cross_site_requests_refused(server):  # S1
    req = urllib.request.Request(f"{server}/nodes", headers={"Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    assert urllib.request.urlopen(f"{server}/nodes").status == 200


def test_config_save_limited_to_config_folders(server):  # S1
    req = urllib.request.Request(f"{server}/config", method="POST", data=b'{"path": "src/pattom/x.py", "content": "a: 1"}',
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403


def test_invalid_graph_does_not_leave_server_running():  # E4
    from pattom.graph.server import ExecutionManager

    m = ExecutionManager()
    with pytest.raises(Exception):
        m.start_run({"nodes": {"a": {"type": "nope"}}, "edges": []})
    assert m.state != "running"
