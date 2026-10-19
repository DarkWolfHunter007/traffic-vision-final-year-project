"""Command line for the preparation stage."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pattom import prepare
from pattom.paths import CALIBRATION, REPO_ROOT
from pattom.runmeta import sha256_file


def _probe(args) -> None:
    print(json.dumps(asdict(prepare.probe(Path(args.video))), indent=2))


def _cfr(args) -> None:
    meta = prepare.to_cfr(Path(args.video), Path(args.out), args.fps, args.slot)
    print(json.dumps(asdict(meta), indent=2))


def _calibrate(args) -> None:
    video = Path(args.video)
    lens = prepare.calibrate_lens(
        prepare.sample_frames(video, args.every),
        (args.cols, args.rows),
        args.square_mm,
        source_video=str(video),
        source_sha256=sha256_file(video),
    )
    out = lens.save(Path(args.out))
    print(f"{lens.frames_used} frames used, RMS reprojection {lens.rms_reprojection_px:.3f} px -> {out}")


def _undistort(args) -> None:
    lens = prepare.LensCalibration.load(Path(args.lens))
    meta = prepare.undistort_video(Path(args.video), Path(args.out), lens, args.slot)
    print(json.dumps(asdict(meta), indent=2))


def _detect(args) -> None:
    from pattom.detection import DetectionConfig, run_detection

    out = run_detection(Path(args.video), args.slot, DetectionConfig.load(Path(args.config)))
    print(out)


def _track(args) -> None:
    from pattom.tracking import TrackerConfig, run_tracking

    print(run_tracking(Path(args.detections), TrackerConfig.load(Path(args.config))))


def _ground(args) -> None:
    from pattom.ground import GroundCalibration, map_tracks

    cal = GroundCalibration.from_config(Path(args.config))
    print(json.dumps(cal.report(), indent=2))
    if args.tracks:
        print(map_tracks(Path(args.tracks), cal))


def _drift(args) -> None:
    import yaml

    from pattom.ground import drift_check, write_drift

    landmarks = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}).get("landmarks") or []
    frames = prepare.sample_frames(Path(args.video), args.every)
    reference = next(frames)
    samples = drift_check(((i * args.every, f) for i, f in enumerate(frames, start=1)), reference, landmarks)
    out = write_drift(samples, Path(args.out))
    worst = max((s.max_shift_px for s in samples), default=0.0)
    print(f"{len(samples)} frames checked, largest landmark shift {worst:.1f} px -> {out}")


def _count(args) -> None:
    from pattom.counting import run_counting

    print(run_counting(Path(args.tracks), Path(args.lines), args.interval_s, args.offset_s))


def _signals(args) -> None:
    from pattom.signals import load_log, summary

    print(json.dumps(summary(load_log(Path(args.log))), indent=2))


def _delay(args) -> None:
    from pattom.delay import run_delay_queue

    print(run_delay_queue(Path(args.tracks), Path(args.definitions), args.interval_s,
                          Path(args.signal_log) if args.signal_log else None, args.offset_s, args.draft))


def _emissions(args) -> None:
    from pattom.emissions import run_emissions

    print(run_emissions(Path(args.vehicle_delay), Path(args.config), args.interval_s, args.offset_s))


def _indicators(args) -> None:
    from pattom.indicators import run_indicators

    print(run_indicators(Path(args.run_dir), Path(args.config), Path(args.signal_log)))


def _congestion(args) -> None:
    from pattom.congestion import run_congestion

    print(run_congestion(Path(args.indicators), Path(args.formula)))


def _graph(args) -> None:
    from pattom.graph import load_graph, run_graph, validate_graph

    spec = load_graph(Path(args.graph))
    if args.validate_only:
        print(json.dumps({"valid": True, "order": validate_graph(spec)}))
        return
    r = run_graph(spec)
    print(json.dumps({"order": r.order, "status": r.status, "errors": r.errors, "outputs": r.outputs}, indent=2))
    if any(v != "completed" for v in r.status.values()):
        raise SystemExit(1)


def _editor(args) -> None:
    from pattom.graph.server import serve

    serve(args.port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pattom")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("probe", help="show stream info and whether a video is variable frame rate")
    s.add_argument("video")
    s.set_defaults(func=_probe)

    s = sub.add_parser("cfr", help="write a constant-frame-rate copy")
    s.add_argument("video")
    s.add_argument("out")
    s.add_argument("--fps", type=float, default=30.0)
    s.add_argument("--slot", required=True, help="e.g. test, offpeak, peak")
    s.set_defaults(func=_cfr)

    s = sub.add_parser("calibrate-lens", help="lens calibration from a checkerboard clip")
    s.add_argument("video")
    s.add_argument("--cols", type=int, required=True, help="inner corners across")
    s.add_argument("--rows", type=int, required=True, help="inner corners down")
    s.add_argument("--square-mm", type=float, required=True)
    s.add_argument("--every", type=float, default=0.5, help="seconds between sampled frames")
    s.add_argument("--out", default=str(CALIBRATION / "lens.json"))
    s.set_defaults(func=_calibrate)

    s = sub.add_parser("undistort", help="write an undistorted copy of a constant-frame-rate video")
    s.add_argument("video")
    s.add_argument("out")
    s.add_argument("--lens", default=str(CALIBRATION / "lens.json"))
    s.add_argument("--slot", required=True)
    s.set_defaults(func=_undistort)

    s = sub.add_parser("detect", help="run YOLO on a prepared video -> runs/<slot>/<video>/detections.csv")
    s.add_argument("video")
    s.add_argument("--slot", required=True)
    s.add_argument("--config", default=str(REPO_ROOT / "configs" / "detection.yaml"))
    s.set_defaults(func=_detect)

    s = sub.add_parser("track", help="run ByteTrack on a detections.csv -> tracks.csv")
    s.add_argument("detections")
    s.add_argument("--config", default=str(REPO_ROOT / "configs" / "tracker.yaml"))
    s.set_defaults(func=_track)

    s = sub.add_parser("ground", help="fit the pixel-to-ground mapping, report check errors, optionally map a tracks.csv")
    s.add_argument("--config", default=str(CALIBRATION / "ground.yaml"))
    s.add_argument("--tracks", help="tracks.csv to fill with ground_x_m / ground_y_m")
    s.set_defaults(func=_ground)

    s = sub.add_parser("drift", help="check a recording for camera movement using fixed landmarks")
    s.add_argument("video")
    s.add_argument("--config", default=str(CALIBRATION / "ground.yaml"))
    s.add_argument("--every", type=float, default=10.0, help="seconds between checked frames")
    s.add_argument("--out", required=True)
    s.set_defaults(func=_drift)

    s = sub.add_parser("count", help="crossings, movements and interval counts from tracks.csv")
    s.add_argument("tracks")
    s.add_argument("--lines", default=str(REPO_ROOT / "configs" / "lines.yaml"))
    s.add_argument("--interval-s", type=float, default=900.0, help="interval length (default 15 min)")
    s.add_argument("--offset-s", type=float, default=0.0, help="start of this file within its slot")
    s.set_defaults(func=_count)

    s = sub.add_parser("signals", help="check a signal log read from the footage and summarise cycles")
    s.add_argument("log")
    s.set_defaults(func=_signals)

    s = sub.add_parser("delay", help="stopped delay per vehicle and approach, and queue length at each green")
    s.add_argument("tracks")
    s.add_argument("--definitions", default=str(REPO_ROOT / "configs" / "definitions.yaml"))
    s.add_argument("--signal-log", help="signal log CSV; needed for queue length")
    s.add_argument("--interval-s", type=float, default=900.0)
    s.add_argument("--offset-s", type=float, default=0.0)
    s.add_argument("--draft", action="store_true", help="run with definitions not yet approved (rows say draft)")
    s.set_defaults(func=_delay)

    s = sub.add_parser("emissions", help="idle CO2 estimate from vehicle_delay.csv (registered factors only)")
    s.add_argument("vehicle_delay")
    s.add_argument("--config", default=str(REPO_ROOT / "configs" / "emissions.yaml"))
    s.add_argument("--interval-s", type=float, default=900.0)
    s.add_argument("--offset-s", type=float, default=0.0)
    s.set_defaults(func=_emissions)

    s = sub.add_parser("indicators", help="volume, SP 41 capacity, V/C, delay and queue per approach and interval")
    s.add_argument("run_dir")
    s.add_argument("--signal-log", required=True)
    s.add_argument("--config", default=str(REPO_ROOT / "configs" / "indicators.yaml"))
    s.set_defaults(func=_indicators)

    s = sub.add_parser("congestion", help="congestion index from approach_indicators.csv")
    s.add_argument("indicators")
    s.add_argument("--formula", default=str(REPO_ROOT / "configs" / "congestion.yaml"))
    s.set_defaults(func=_congestion)

    s = sub.add_parser("graph", help="validate and run a node-graph pipeline file")
    s.add_argument("graph")
    s.add_argument("--validate-only", action="store_true")
    s.set_defaults(func=_graph)

    s = sub.add_parser("editor", help="open the local visual node editor")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=_editor)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
