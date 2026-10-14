"""App tests on a throwaway copy of the project with a synthetic demo run (no footage).

The browser test drives the installed Microsoft Edge with Playwright; nothing
is downloaded. Set PATTOM_HEADED=1 to watch it, PATTOM_SHOTS=<folder inside the
repo> to keep a screenshot of every page. Values typed in by the test (pixel
points, metres, signal times) are synthetic test values, not site data.
"""

import csv
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from pattom.paths import REPO_ROOT  # noqa: E402
from pattom.viewer import create_app  # noqa: E402
from pattom.viewer.demo import make_demo  # noqa: E402
from pattom.viewer.jobs import JobRunner  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
# The app must run from its own files: no AI-agent documents (AI_RULES, CLAUDE.md, the task ledger).
COPY = ["sources/register.yaml", "configs/pipeline.example.yaml",
        "configs/detection.example.yaml", "configs/tracker.example.yaml", "configs/lines.example.yaml",
        "calibration/ground.example.yaml", "configs/study_settings.example.yaml", "configs/sumo_network.example.yaml"]
TOKEN = "test-token"
H = {"X-Pattom-Token": TOKEN}


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    for f in COPY:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / f, root / f)
    make_demo(root)
    return root


@pytest.fixture(scope="module")
def client(root):
    return TestClient(create_app(root, token=TOKEN))


# --- API ---------------------------------------------------------------------

@needs_ffmpeg
def test_guard_needs_token_and_local_host(client):
    assert client.put("/api/lines", json={}).status_code == 403
    assert client.get("/api/project", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/").text.count(TOKEN) == 1


@needs_ffmpeg
def test_runs_and_videos(client):
    assert [r["video"] for r in client.get("/api/runs").json()] == ["demo_clip"]
    info = client.get("/api/runs/demo/demo_clip").json()
    assert (info["fps"], info["frame_stride"], info["video_playable"]) == (30, 2, True)
    boxes = client.get("/api/runs/demo/demo_clip/boxes", params={"start": 30, "end": 30}).json()
    assert {b[0] for b in boxes["30"]} == {1, 2, 3}  # synthetic tracks at t = 1 s
    video = client.get("/api/runs/demo/demo_clip/video", headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100
    frame = client.get("/api/videos/frame", params={"path": "data/cfr/demo_clip.mp4", "t": 1, "w": 480})
    assert frame.headers["x-frame-width"] == "960" and frame.content[:2] == b"\xff\xd8"
    assert client.get("/api/videos/frame", params={"path": "../outside.mp4"}).status_code == 403
    table = client.get("/api/runs/demo/demo_clip/table/track_summary.csv").json()
    assert len(table["rows"]) == 4


@needs_ffmpeg
def test_status_and_register(client, root):
    assert not (root / "docs").exists() and not (root / "CLAUDE.md").exists()
    s = client.get("/api/status").json()
    assert s["videos"]["prepared"] == 1 and s["runs"][0]["video"] == "demo_clip" and s["weights"] == []
    assert set(client.get("/api/status/gpu").json()) >= {"torch", "cuda"}
    assert any(v["status"] == "verified" for v in client.get("/api/register").json()["values"])


@needs_ffmpeg
def test_pipeline_save_refuses_unknown_block_and_writes_valid_file(client, root):
    spec = client.get("/api/pipeline").json()["spec"]
    bad = {**spec, "blocks": spec["blocks"] + [{"use": "nope"}]}
    assert client.put("/api/pipeline", json=bad, headers=H).status_code == 422
    r = client.put("/api/pipeline", json=spec, headers=H)
    assert r.status_code == 200 and (root / "configs/pipeline.yaml").exists()
    assert any("does not exist" in p for p in r.json()["problems"])  # the example's video is not in the copy


@needs_ffmpeg
def test_editors_validate_before_writing(client, root):
    assert client.get("/api/lines").json()["spec"] == {"lines": [], "movements": []}  # no placeholders
    bad = {"lines": [{"name": "A", "type": "nope", "approach": "north", "endpoints_px": [[0, 0], [1, 1]],
                      "direction": "left"}], "movements": []}
    assert client.put("/api/lines", json=bad, headers=H).status_code == 422
    assert not (root / "configs/lines.yaml").exists()
    r = client.put("/api/settings/tracker", json={"text": "name: bytetrack\nhigh_thresh: 2\n"}, headers=H)
    assert r.status_code == 422 and not (root / "configs/tracker.yaml").exists()
    rows = [{"time_s": t, "signal_head": "N", "state": s, "phase_group": "NS"}
            for t, s in [(0, "green"), (30, "amber"), (33, "red"), (60, "green")]]
    r = client.put("/api/phases/demo", json={"rows": rows}, headers=H).json()
    assert [c["cycle_s"] for c in r["cycles"]] == [60]
    rows.append({"time_s": 70, "signal_head": "N", "state": "green", "phase_group": "NS"})
    assert client.put("/api/phases/demo", json={"rows": rows}, headers=H).status_code == 422


def test_job_runner_streams_output(tmp_path):
    jobs = JobRunner(REPO_ROOT)
    job = jobs.start(["blocks"])
    for _ in range(200):
        if job.state != "running":
            break
        time.sleep(0.05)
    assert job.state == "done" and any("detect" in line for line in job.lines)
    assert job.command[0] == sys.executable


# --- browser -----------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@needs_ffmpeg
def test_every_page_in_edge(root):
    sync_api = pytest.importorskip("playwright.sync_api")
    import uvicorn

    for f in ("configs/lines.yaml", "calibration/ground.yaml"):
        (root / f).unlink(missing_ok=True)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(root), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    headed = os.environ.get("PATTOM_HEADED") == "1"
    shots = os.environ.get("PATTOM_SHOTS")
    shots_dir = (REPO_ROOT / shots).resolve() if shots else None
    if shots_dir and REPO_ROOT.resolve() not in shots_dir.parents:
        pytest.fail("PATTOM_SHOTS must be inside the repository")
    base = f"http://127.0.0.1:{port}/"

    def shot(page, name):
        if shots_dir:
            shots_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots_dir / f"{name}.png"), full_page=True)

    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=not headed, slow_mo=250 if headed else 0)
            except Exception as e:  # Edge not installed
                pytest.skip(f"Microsoft Edge not available: {e}")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(f"{page.url} {e} {getattr(e, 'stack', '')}"))
            answers = []
            page.on("dialog", lambda d: d.accept(answers.pop(0) if answers else ""))

            # Home: setup checklist from the app's own files
            page.goto(base + "#/home")
            page.wait_for_selector("text=YOLO weights in models/")
            page.wait_for_function("!document.getElementById('gpu')?.textContent.includes('Checking')")
            shot(page, "01_home")

            # Videos: probe the demo clip
            page.goto(base + "#/videos")
            page.locator("[data-probe]").first.click()
            page.wait_for_selector("text=Constant frame rate.")
            shot(page, "02_videos")

            # Pipeline: switch drift on, check, save
            page.goto(base + "#/pipeline")
            page.wait_for_selector(".block")
            # Every planned block on the page is locked off.
            assert page.locator(".block.planned input[data-toggle]:disabled").count() == page.locator(".block.planned").count()
            page.locator('.switch:has([data-toggle="drift"])').click()
            page.wait_for_selector("text=unsaved changes")
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('Pipeline saved')")
            saved = yaml.safe_load((root / "configs/pipeline.yaml").read_text(encoding="utf-8"))
            assert next(b for b in saved["blocks"] if b["use"] == "drift")["enabled"] is True
            shot(page, "03_pipeline")

            # Results: jump to track 3, boxes drawn
            page.goto(base + "#/results/demo/demo_clip")
            page.wait_for_selector("#tracks tr[data-id]")
            page.wait_for_function("document.getElementById('video')?.readyState >= 2")
            page.locator('#tracks tr[data-id="3"]').click()
            page.wait_for_function("document.getElementById('clock')?.textContent.includes('frame 30')")
            page.wait_for_timeout(300)
            drawn = page.evaluate("""() => { const c = document.getElementById('overlay');
                const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; }""")
            assert drawn > 500
            shot(page, "04_results")

            # Counting lines: draw one line, save
            page.goto(base + "#/lines")
            page.wait_for_function("document.querySelector('.fc-img')?.naturalWidth > 0")
            page.locator("#add").click()
            canvas = page.locator(".fc-canvas")
            canvas.click(position={"x": 100, "y": 200})
            canvas.click(position={"x": 400, "y": 200})
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('Counting lines saved')")
            lines = yaml.safe_load((root / "configs/lines.yaml").read_text(encoding="utf-8"))["lines"]
            assert len(lines) == 1 and lines[0]["endpoints_px"][0][1] == lines[0]["endpoints_px"][1][1]
            shot(page, "05_lines")

            # Ground points: one mapping, 4 fit + 1 check point (synthetic metres = pixels / 100)
            page.goto(base + "#/ground")
            page.wait_for_function("document.querySelector('.fc-img')?.naturalWidth > 0")
            answers.append("all")
            page.locator("#addmap").click()
            page.locator('[data-mode="point"]').click()
            for x, y in [(80, 80), (500, 80), (500, 400), (80, 400), (290, 240)]:
                canvas.click(position={"x": x, "y": y})
            rows = page.locator("#points tr[data-p]")
            assert rows.count() == 5
            k = page.evaluate("document.querySelector('.fc-img').naturalWidth / document.querySelector('.fc-img').clientWidth")
            for i in range(5):
                px = page.evaluate(f"document.querySelectorAll('#points tr[data-p]')[{i}].children[1].textContent")
                u, v = (float(s) for s in px.split(","))
                rows.nth(i).locator('[data-pf="mx"]').fill(f"{u / 100:.2f}")
                rows.nth(i).locator('[data-pf="mx"]').dispatch_event("change")
                rows.nth(i).locator('[data-pf="my"]').fill(f"{v / 100:.2f}")
                rows.nth(i).locator('[data-pf="my"]').dispatch_event("change")
            assert k > 0
            page.locator('[data-mode="zone"]').click()
            for x, y in [(20, 20), (700, 20), (700, 400), (20, 400)]:
                canvas.click(position={"x": x, "y": y})
            page.locator("#fit").click()
            page.wait_for_selector("text=largest check error")
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('Ground points saved')")
            assert (root / "calibration/ground.yaml").exists()
            shot(page, "06_ground")

            # Signal phases: one head, marks at synthetic video times, one complete cycle
            page.goto(base + "#/phases/demo")
            page.wait_for_function("document.getElementById('video')?.readyState >= 1")
            page.locator("#hname").fill("N_main")
            page.locator("#hgroup").fill("NS")
            page.locator("#hadd").click()
            for t, state in [(0.5, "g"), (2.0, "a"), (2.5, "r"), (4.5, "g")]:
                page.evaluate(f"document.getElementById('video').currentTime = {t}")
                page.wait_for_function(f"Math.abs(document.getElementById('video')?.currentTime - {t}) < 0.05")
                page.locator(f".head-row:has-text('N_main') button.state-btn.{state}").click()
            page.locator("#save").click()
            page.wait_for_selector("#cycles td b")
            assert "4.0 s" in page.locator("#cycles tr:has-text('N_main') b").inner_text()
            shot(page, "07_phases")

            # Review: open a frame, add a box, save a YOLO label
            page.goto(base + "#/review/demo/demo_clip")
            page.locator("#goto").fill("30")
            page.locator("#gobtn").click()
            page.wait_for_function("document.getElementById('rimg')?.naturalWidth > 0")
            rc = page.locator("#rcanvas")
            page.locator("#add").click()
            rc.click(position={"x": 40, "y": 40})
            rc.click(position={"x": 120, "y": 100})
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('saved as a label')")
            label = root / "labels/demo/demo_clip/labels/demo_clip_f0000030.txt"
            assert label.exists() and len(label.read_text().splitlines()) == 4  # 3 tracked boxes + the added one
            assert (root / "labels/demo/demo_clip/classes.txt").exists()
            shot(page, "10_review")

            # Manual counts: one window with two cars
            page.goto(base + "#/manual/demo/demo_clip")
            page.wait_for_function("document.getElementById('video')?.readyState >= 1")
            page.evaluate("document.getElementById('video').currentTime = 0.5")
            page.locator("#start").click()
            page.locator("[data-c='car']").click()
            page.locator("[data-c='car']").click()
            page.evaluate("document.getElementById('video').currentTime = 4.5")
            page.wait_for_function("document.getElementById('video').currentTime > 4")
            page.locator("#end").click()
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('Manual counts saved')")
            mc = [r for r in csv.DictReader(open(root / "runs/demo/demo_clip/manual_counts.csv")) if r["class"] == "car"]
            assert mc[0]["count"] == "2"
            shot(page, "11_manual")

            # Alternatives page and settings files
            page.goto(base + "#/alternatives")
            page.wait_for_selector("text=SP 41 fixed-time suggestion")
            shot(page, "12_alternatives")
            page.goto(base + "#/files/configs%2Fstudy_settings.yaml")
            page.wait_for_function("document.getElementById('text')?.value.includes('stopped-delay')")
            page.locator("#save").click()
            page.wait_for_selector(".toast.ok:has-text('configs/study_settings.yaml saved')")
            assert (root / "configs/study_settings.yaml").exists()
            shot(page, "13_files")

            # Settings and sources
            page.goto(base + "#/settings")
            page.wait_for_selector("#t-detection")
            shot(page, "08_settings")
            page.goto(base + "#/sources")
            page.wait_for_selector("text=sp41.saturation_flow_per_m")
            shot(page, "09_sources")

            if headed:
                page.wait_for_timeout(1500)
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# --- detection preview and tiling --------------------------------------------

class _FakeDetector:
    """Stands in for YOLO: one box per pass, at a fixed place in the pass's image."""
    name, version = "fake", "0"

    def predict(self, image, imgsz):
        h, w = image.shape[:2]
        return [(np.array([w * 0.4, h * 0.4, w * 0.6, h * 0.6]), 0.9, "car")]


@needs_ffmpeg
def test_preview_compares_whole_frame_and_tiles(client, root, monkeypatch):
    from pattom.viewer import routes_detect

    (root / "models").mkdir(exist_ok=True)
    (root / "models/fake.pt").write_bytes(b"x")
    text = (REPO_ROOT / "configs/detection.example.yaml").read_text(encoding="utf-8").replace(
        "weights: models/yolo11m.pt", "weights: models/fake.pt")
    (root / "configs/detection.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setattr("pattom.detection.MODELS", root / "models")
    monkeypatch.setattr("pattom.detection.REPO_ROOT", root)
    monkeypatch.setattr(routes_detect, "_detectors", {str((root / "models/fake.pt").resolve()): _FakeDetector()})
    body = {"path": "data/cfr/demo_clip.mp4", "t": 1, "tile_grid": {"size": 480, "overlap": 0}}
    r = client.post("/api/detect/preview", json=body, headers=H).json()
    assert len(r["tiles"]) == 4 and len(r["whole_frame"]["boxes"]) == 1  # 960x540 -> 2 x 2 tiles of 480
    assert len(r["with_tiles"]["boxes"]) == 5 and {b["pass"] for b in r["with_tiles"]["boxes"]} >= {"full", "tile0"}
    saved = client.put("/api/settings/detection/tiling", headers=H,
                       json={"tiles": [], "tile_grid": {"size": 1280, "overlap": 256}, "merge_inside": 0.85}).json()
    assert saved["saved"]["merge_inside"] == 0.85
    out = yaml.safe_load((root / "configs/detection.yaml").read_text(encoding="utf-8"))
    assert out["tile_grid"] == {"size": 1280, "overlap": 256} and out["class_map"]["car"] == "car"
    bad = client.put("/api/settings/detection/tiling", headers=H, json={"tile_grid": {"size": 100, "overlap": 200}})
    assert bad.status_code == 422


def test_grid_tiles_cover_the_frame():
    from pattom.detection import grid_tiles

    tiles = grid_tiles(3840, 2160, 1280, 256)
    assert len(tiles) == 8 and tiles[0][:2] == [0, 0] and tiles[-1][2:] == [3840, 2160]
    assert grid_tiles(3840, 2160, 1280, 256, [0, 0, 3840, 1080])[-1][3] == 1080


def test_inside_merge_drops_tile_edge_halves():
    from pattom.boxes import nms

    boxes = np.array([[0, 0, 100, 100], [0, 0, 50, 100], [200, 200, 300, 300]], float)
    scores = np.array([0.9, 0.8, 0.7])
    assert nms(boxes, scores, 0.6) == [0, 1, 2] and nms(boxes, scores, 0.6, 0.85) == [0, 2]
