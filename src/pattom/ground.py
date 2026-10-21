"""Pixel-to-ground mapping and camera-drift check (FR-24, ARCHITECTURE section 6).

- A planar homography maps the ground-contact point of each box (bottom
  centre) in the undistorted frame to metres on the ground.
- Points are split into "fit" points (used to estimate the mapping) and
  "check" points or tape distances that are never used to fit it. Four fit
  points fit exactly and say nothing about error, so at least one check is
  required, and the error is reported in metres.
- A separate mapping per approach is supported for when one mapping is not
  accurate enough at the edges.
- Only points inside the calibrated zone get ground coordinates; others stay
  empty. Metres are never reported from raw pixels.

Config file (calibration/ground.yaml):

    mappings:
      north:                      # one mapping per approach, or a single "all"
        zone_px: [[u, v], ...]    # polygon where this mapping is valid
        points:
          - {id: Z1, px: [u, v], m: [x, y], role: fit}
          - {id: Z9, px: [u, v], m: [x, y], role: check}
        check_distances:          # optional tape measurements between two pixels
          - {a_px: [u, v], b_px: [u, v], distance_m: 3.5}
    landmarks:                    # fixed features for the drift check
      - {id: pole1, box_px: [x1, y1, x2, y2]}
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from pattom.runmeta import RunMetadata, sha256_file


@dataclass
class Mapping:
    name: str
    homography: list[list[float]]
    zone_px: list[list[float]]
    n_fit: int
    check_point_errors_m: dict[str, float]
    check_distance_errors_m: list[float]
    max_check_error_m: float
    rms_fit_residual_m: float

    def h(self) -> np.ndarray:
        return np.array(self.homography)

    def contains(self, u: float, v: float) -> bool:
        poly = np.array(self.zone_px, np.float32)
        return cv2.pointPolygonTest(poly, (float(u), float(v)), False) >= 0


def to_ground(h: np.ndarray, px: np.ndarray) -> np.ndarray:
    px = np.asarray(px, float).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(px, h).reshape(-1, 2)


def fit_mapping(name: str, spec: dict) -> Mapping:
    pts = spec.get("points") or []
    fit = [p for p in pts if p.get("role") == "fit"]
    check = [p for p in pts if p.get("role") == "check"]
    dists = spec.get("check_distances") or []
    bad = [p.get("id") for p in pts if p.get("role") not in ("fit", "check")]
    if bad:
        raise ValueError(f"{name}: points need role fit or check: {bad}")
    if len(fit) < 4:
        raise ValueError(f"{name}: at least 4 fit points are needed, got {len(fit)}")
    if not check and not dists:
        raise ValueError(f"{name}: no check point or check distance; the mapping error would be unknown (FR-24)")
    if not spec.get("zone_px") or len(spec["zone_px"]) < 3:
        raise ValueError(f"{name}: zone_px polygon (at least 3 corners) is required")
    src = np.array([p["px"] for p in fit], float)
    dst = np.array([p["m"] for p in fit], float)
    h, _ = cv2.findHomography(src, dst, 0)
    if h is None:
        raise ValueError(f"{name}: homography could not be fitted (points collinear?)")
    resid = np.linalg.norm(to_ground(h, src) - dst, axis=1)
    point_err = {
        str(p["id"]): float(np.linalg.norm(to_ground(h, np.array([p["px"]]))[0] - np.array(p["m"], float)))
        for p in check
    }
    dist_err = []
    for d in dists:
        a, b = to_ground(h, np.array([d["a_px"], d["b_px"]], float))
        dist_err.append(float(abs(np.linalg.norm(a - b) - d["distance_m"])))
    errors = list(point_err.values()) + dist_err
    return Mapping(
        name=name,
        homography=h.tolist(),
        zone_px=spec["zone_px"],
        n_fit=len(fit),
        check_point_errors_m=point_err,
        check_distance_errors_m=dist_err,
        max_check_error_m=max(errors),
        rms_fit_residual_m=float(np.sqrt(np.mean(resid**2))),
    )


@dataclass
class GroundCalibration:
    mappings: list[Mapping]
    source_file: str
    source_sha256: str
    landmarks: list[dict] = field(default_factory=list)

    @classmethod
    def from_config(cls, path: Path) -> "GroundCalibration":
        spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        maps = spec.get("mappings") or {}
        if not maps:
            raise ValueError(f"{path}: no mappings")
        return cls(
            mappings=[fit_mapping(n, s) for n, s in maps.items()],
            source_file=str(path),
            source_sha256=sha256_file(Path(path)),
            landmarks=spec.get("landmarks") or [],
        )

    def report(self) -> dict:
        return {m.name: {"fit_points": m.n_fit, "max_check_error_m": m.max_check_error_m,
                         "check_point_errors_m": m.check_point_errors_m,
                         "check_distance_errors_m": m.check_distance_errors_m,
                         "rms_fit_residual_m": m.rms_fit_residual_m} for m in self.mappings}

    def locate(self, u: float, v: float) -> tuple[float, float] | None:
        """Ground position of a pixel, from the first mapping whose zone holds it."""
        for m in self.mappings:
            if m.contains(u, v):
                x, y = to_ground(m.h(), np.array([[u, v]]))[0]
                return float(x), float(y)
        return None


def bottom_centre(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    return (x1 + x2) / 2.0, y2


def map_tracks(tracks_csv: Path, cal: GroundCalibration) -> Path:
    """Write tracks_ground.csv: tracks.csv with ground_x_m / ground_y_m filled in.
    tracks.csv itself is left as the tracker wrote it (each step writes a new file)."""
    with open(tracks_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    inside = 0
    for r in rows:
        g = cal.locate(*bottom_centre(*(float(r[k]) for k in ("x1", "y1", "x2", "y2"))))
        r["ground_x_m"], r["ground_y_m"] = ("", "") if g is None else (round(g[0], 3), round(g[1], 3))
        inside += g is not None
    out = tracks_csv.with_name("tracks_ground.csv")
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(out)
    meta = json.loads(tracks_csv.with_suffix(".run.json").read_text(encoding="utf-8"))
    RunMetadata(
        slot=meta["slot"],
        stage="F.ground_mapping",
        video_file=meta["video_file"],
        video_sha256=meta["video_sha256"],
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
        parameters={"ground_config": cal.source_file, "ground_config_sha256": cal.source_sha256,
                    "mapping_report": cal.report(), "rows": len(rows), "rows_mapped": inside,
                    "ground_point": "bottom centre of box", "source_tracks": str(tracks_csv)},
    ).write(out.with_suffix(".run.json"))
    return out


# --- Camera drift ----------------------------------------------------------

@dataclass
class DriftSample:
    time_s: float
    shifts_px: dict[str, float]
    max_shift_px: float


def drift_check(frames_with_time, reference: np.ndarray, landmarks: list[dict],
                search_margin_px: int = 40) -> list[DriftSample]:
    """Track fixed landmarks against a reference frame by template matching.

    frames_with_time yields (time_s, frame). Returns the shift of each
    landmark in pixels per sampled frame. The tolerance is not set here; it is
    agreed with the guide and applied by the caller.
    """
    if not landmarks:
        raise ValueError("no landmarks configured for the drift check")
    ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY) if reference.ndim == 3 else reference
    out = []
    for t, frame in frames_with_time:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        shifts = {}
        for lm in landmarks:
            x1, y1, x2, y2 = lm["box_px"]
            tpl = ref[y1:y2, x1:x2]
            sx1, sy1 = max(0, x1 - search_margin_px), max(0, y1 - search_margin_px)
            sx2, sy2 = min(gray.shape[1], x2 + search_margin_px), min(gray.shape[0], y2 + search_margin_px)
            res = cv2.matchTemplate(gray[sy1:sy2, sx1:sx2], tpl, cv2.TM_CCOEFF_NORMED)
            _, _, _, (bx, by) = cv2.minMaxLoc(res)
            shifts[str(lm["id"])] = float(np.hypot(sx1 + bx - x1, sy1 + by - y1))
        out.append(DriftSample(float(t), shifts, max(shifts.values())))
    return out


def write_drift(samples: list[DriftSample], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(s) for s in samples], indent=2) + "\n", encoding="utf-8")
    return path
