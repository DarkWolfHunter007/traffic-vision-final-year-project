import json
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from pattom.graph.server import Handler
from pattom.paths import REPO_ROOT


@pytest.fixture(scope="module")
def editor_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    yield base_url
    server.shutdown()


def test_path_traversal_blocked(editor_server):
    # Attempting to access parent directories via /media/
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{editor_server}/media/../../windows/system32/cmd.exe")
    assert exc_info.value.code == 403


def test_files_api(editor_server):
    resp = urllib.request.urlopen(f"{editor_server}/files?dir=configs&ext=.yaml")
    data = json.loads(resp.read())
    assert isinstance(data, list)
    assert any("detection.yaml" in f["path"] or "tracker.yaml" in f["path"] for f in data)


def test_media_range_request(editor_server):
    # Test reading pyproject.toml via /media/
    req = urllib.request.Request(f"{editor_server}/media/pyproject.toml")
    req.add_header("Range", "bytes=0-10")
    resp = urllib.request.urlopen(req)
    assert resp.status == 206
    content = resp.read()
    assert len(content) == 11
    assert b"build-system" in content or b"[" in content


def test_config_api(editor_server):
    resp = urllib.request.urlopen(f"{editor_server}/config?path=configs/definitions.example.yaml")
    data = json.loads(resp.read())
    assert "definition_version" in data["parsed"]
    assert data["parsed"]["approved"] is False


def test_history_api(editor_server):
    resp = urllib.request.urlopen(f"{editor_server}/history")
    data = json.loads(resp.read())
    assert isinstance(data, list)


def test_nodes_api_includes_schemas_and_gates(editor_server):
    resp = urllib.request.urlopen(f"{editor_server}/nodes")
    nodes = json.loads(resp.read())
    by_name = {n["name"]: n for n in nodes}
    assert "param_schema" in by_name["cfr"]
    assert "video" in by_name["cfr"]["param_schema"]
    # Check gate is present on delay_queue
    assert by_name["delay_queue"]["gate"] is not None
    assert by_name["delay_queue"]["gate"]["decision"] == "O6"


def test_gate_check_api(editor_server):
    req_body = json.dumps({"type": "delay_queue", "params": {"definitions": "configs/definitions.example.yaml", "allow_draft": False}}).encode()
    req = urllib.request.Request(f"{editor_server}/gate_check", req_body, {"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    assert "gate" in data
    assert data["gate"]["locked"] is True
    assert data["gate"]["decision"] == "O6"

    # Test allow_draft toggle still locks if required parameters are empty
    req_body2 = json.dumps({"type": "delay_queue", "params": {"definitions": "configs/definitions.example.yaml", "allow_draft": True}}).encode()
    req2 = urllib.request.Request(f"{editor_server}/gate_check", req_body2, {"Content-Type": "application/json"})
    resp2 = urllib.request.urlopen(req2)
    data2 = json.loads(resp2.read())
    assert data2["gate"]["locked"] is True


def test_config_save_api(editor_server, tmp_path):
    # Save a temporary config
    cfg_path = "configs/test_temp_config.yaml"
    full_path = REPO_ROOT / cfg_path
    try:
        req_body = json.dumps({"path": cfg_path, "content": "test_key: test_val\n"}).encode()
        req = urllib.request.Request(f"{editor_server}/config", req_body, {"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert data["saved"] is True

        # Read it back via GET
        resp2 = urllib.request.urlopen(f"{editor_server}/config?path={cfg_path}")
        data2 = json.loads(resp2.read())
        assert data2["parsed"]["test_key"] == "test_val"
    finally:
        if full_path.exists():
            full_path.unlink()

