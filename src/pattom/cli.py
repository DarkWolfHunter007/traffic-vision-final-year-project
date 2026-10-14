"""Command line: single stages, the block list and the pipeline harness."""

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


def _phases(args) -> None:
    from pattom.paths import RUNS
    from pattom.phases import run_phases

    out_dir = Path(args.out_dir) if args.out_dir else RUNS / args.slot / "signals"
    for out in run_phases(Path(args.log), args.slot, out_dir):
        print(out)


def _blocks(args) -> None:
    from pattom.harness import all_blocks

    blocks = sorted(all_blocks().values(), key=lambda b: (b.component, b.name))
    if args.json:
        print(json.dumps([b.describe() for b in blocks], indent=2))
        return
    for b in blocks:
        waits = ", ".join(b.tasks + b.waits_on)
        print(f"{b.component}  {b.name:<18} {b.status:<8} {b.title}")
        print(f"     in:  {', '.join(f'{p}={k}' for p, k in b.inputs.items()) or '-'}")
        print(f"     out: {', '.join(b.outputs) or '-'}   [{waits}]")


def _pipeline(args) -> None:
    from pattom.harness import Pipeline, PipelineError

    pipe = Pipeline.load(Path(args.config))
    only = args.only.split(",") if args.only else None
    if args.action == "check":
        for s in pipe.steps:
            state = "on " if s.enabled else "off"
            print(f"[{state}] {s.id:<18} {s.block.status:<8} {', '.join(f'{p}<-{k}' for p, k in s.port_keys().items())}")
        problems = pipe.check(only)
        if problems:
            print("\nProblems:")
            for problem in problems:
                print(f"  - {problem}")
            raise SystemExit(1)
        print("\nReady to run.")
        return
    try:
        manifest = pipe.run(only, log=lambda msg: print(msg, flush=True))
    except PipelineError as e:
        raise SystemExit(str(e)) from None
    for step in manifest["steps"]:
        print(f"{step['id']:<18} {step['status']}  {', '.join(step.get('outputs', {}).values())}")
    print(pipe.manifest_path())


def _view(args) -> None:
    import uvicorn

    from pattom.viewer import create_app

    if args.make_demo:
        from pattom.viewer.demo import make_demo

        print(f"synthetic demo run -> {make_demo()}")
    print(f"Pattom viewer on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


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

    s = sub.add_parser("phases", help="check a signal phase log read from the footage -> cycles per signal head")
    s.add_argument("log")
    s.add_argument("--slot", required=True)
    s.add_argument("--out-dir")
    s.set_defaults(func=_phases)

    s = sub.add_parser("blocks", help="list the pipeline blocks, their inputs, outputs and what they wait on")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_blocks)

    s = sub.add_parser("pipeline", help="check or run the blocks listed in a pipeline file")
    s.add_argument("action", choices=["check", "run"])
    s.add_argument("config", nargs="?", default=str(REPO_ROOT / "configs" / "pipeline.yaml"))
    s.add_argument("--only", help="comma-separated block ids; other inputs come from the last manifest")
    s.set_defaults(func=_pipeline)

    s = sub.add_parser("view", help="local web viewer: video with boxes, tracks and block status (read-only)")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--make-demo", action="store_true", help="first write a synthetic demo run (slot demo)")
    s.set_defaults(func=_view)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
