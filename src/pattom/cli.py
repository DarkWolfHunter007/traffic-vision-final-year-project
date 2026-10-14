"""Command line for the preparation stage."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pattom import prepare
from pattom.paths import CALIBRATION
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

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
