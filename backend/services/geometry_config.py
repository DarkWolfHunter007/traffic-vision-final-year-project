"""Phase 05 geometry configuration service.

Handles loading, validating, deterministic hashing, and idempotent immutable persistence
of counting lines and polygonal zones into the canonical schema, as well as preview rendering.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import cv2
import yaml

from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_counting_line_by_id,
    fetch_counting_lines_for_video,
    fetch_zone_by_id,
    fetch_zones_for_video,
    insert_counting_line,
    insert_zone,
)
from backend.geometry import (
    compute_config_version,
    compute_geometry_sha256,
    validate_counting_line,
    validate_zone,
)
from backend.media import preview_frame
from backend.visualization import render_geometry_overlay


def load_geometry_config(
    video_id: str,
    config_path_or_dict: Path | str | dict[str, Any],
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Load and validate geometry configuration for a video, persisting into canonical tables.

    Reloading identical geometry configuration is idempotent.
    Modifying geometry for an existing line/zone/version is rejected to preserve immutability.
    """
    if isinstance(config_path_or_dict, (str, Path)):
        cfg_path = Path(config_path_or_dict)
        if not cfg_path.is_absolute() and repository_root:
            cfg_path = repository_root / cfg_path
        if not cfg_path.exists():
            raise FileNotFoundError(f"Geometry configuration file does not exist: {cfg_path}")
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif isinstance(config_path_or_dict, dict):
        data = config_path_or_dict
    else:
        raise TypeError(f"Expected Path, str, or dict, got {type(config_path_or_dict)}")

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        video = conn.execute(
            "SELECT video_id, width, height, path FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if not video:
            raise ValueError(f"Video '{video_id}' does not exist in videos table")

        width = float(video["width"]) if video["width"] is not None else None
        height = float(video["height"]) if video["height"] is not None else None

        # 1. Declared approaches
        approaches_raw = data.get("approaches", [])
        if not isinstance(approaches_raw, list):
            raise ValueError("approaches must be a list of approach names")
        declared_approaches: set[str] = set()
        for app in approaches_raw:
            if isinstance(app, dict):
                val = app.get("id") or app.get("name")
                if val:
                    declared_approaches.add(str(val))
            elif app:
                declared_approaches.add(str(app))

        # 2. Counting lines
        lines_raw = data.get("counting_lines", [])
        if not isinstance(lines_raw, list):
            raise ValueError("counting_lines must be a list")
        validated_lines: list[dict[str, Any]] = []
        for idx, item in enumerate(lines_raw):
            if not isinstance(item, dict):
                raise ValueError(f"Counting line at index {idx} must be a dictionary")
            name = item.get("name")
            if not name or not isinstance(name, str):
                raise ValueError(f"Counting line at index {idx} must have a non-empty 'name'")
            line_id = str(item.get("line_id") or f"{name.lower().replace(' ', '_')}")
            approach = item.get("approach")
            if approach is not None:
                approach = str(approach)
                if approach not in declared_approaches:
                    raise ValueError(
                        f"Counting line '{name}' references undeclared approach '{approach}'"
                    )

            bidirectional = bool(item.get("bidirectional", False))
            endpoints = item.get("endpoints")
            if endpoints is None and "geometry" in item and isinstance(item["geometry"], dict):
                endpoints = item["geometry"].get("endpoints")

            direction_vector = item.get("direction_vector")
            if direction_vector is None and "geometry" in item and isinstance(item["geometry"], dict):
                direction_vector = item["geometry"].get("direction_vector")

            norm_endpoints, norm_dir = validate_counting_line(
                endpoints=endpoints,
                direction_vector=direction_vector,
                bidirectional=bidirectional,
                frame_width=width,
                frame_height=height,
            )

            geom_dict = {
                "direction_vector": list(norm_dir) if norm_dir is not None else None,
                "endpoints": [list(pt) for pt in norm_endpoints],
            }
            geom_json = json.dumps(geom_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            geom_sha256 = compute_geometry_sha256(geom_dict, approach, name)
            config_version = compute_config_version(geom_sha256)

            validated_lines.append(
                {
                    "line_id": line_id,
                    "video_id": video_id,
                    "name": name,
                    "approach": approach,
                    "geometry_json": geom_json,
                    "bidirectional": 1 if bidirectional else 0,
                    "config_version": config_version,
                    "geometry_sha256": geom_sha256,
                }
            )

        # 3. Zones (including optional rois key)
        zones_raw = list(data.get("zones", []))
        if not isinstance(zones_raw, list):
            raise ValueError("zones must be a list")
        if "rois" in data and isinstance(data["rois"], list):
            for roi_item in data["rois"]:
                if isinstance(roi_item, dict):
                    r_copy = dict(roi_item)
                    r_copy.setdefault("zone_type", "roi")
                    zones_raw.append(r_copy)

        validated_zones: list[dict[str, Any]] = []
        for idx, item in enumerate(zones_raw):
            if not isinstance(item, dict):
                raise ValueError(f"Zone at index {idx} must be a dictionary")
            name = item.get("name")
            if not name or not isinstance(name, str):
                raise ValueError(f"Zone at index {idx} must have a non-empty 'name'")
            zone_type = str(item.get("zone_type", "roi"))
            zone_id = str(item.get("zone_id") or f"{name.lower().replace(' ', '_')}")
            approach = item.get("approach")
            if approach is not None:
                approach = str(approach)

            vertices = item.get("vertices")
            if vertices is None and "geometry" in item and isinstance(item["geometry"], dict):
                vertices = item["geometry"].get("vertices")

            norm_vertices, v_type, v_app = validate_zone(
                vertices=vertices,
                zone_type=zone_type,
                approach=approach,
                declared_approaches=declared_approaches,
                frame_width=width,
                frame_height=height,
            )

            geom_dict = {
                "vertices": [list(pt) for pt in norm_vertices],
            }
            geom_json = json.dumps(geom_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            geom_sha256 = compute_geometry_sha256(geom_dict, v_app, name)
            config_version = compute_config_version(geom_sha256)

            validated_zones.append(
                {
                    "zone_id": zone_id,
                    "video_id": video_id,
                    "name": name,
                    "zone_type": v_type,
                    "approach": v_app,
                    "geometry_json": geom_json,
                    "config_version": config_version,
                    "geometry_sha256": geom_sha256,
                }
            )

        # 4. Idempotent persistence with immutability guarantees
        inserted_lines = 0
        for line in validated_lines:
            existing = fetch_counting_line_by_id(conn, line["line_id"])
            if existing:
                if existing["geometry_sha256"] == line["geometry_sha256"]:
                    # Idempotent reload: unchanged
                    continue
                else:
                    raise ValueError(
                        f"Counting line '{line['line_id']}' already exists with config_version '{existing['config_version']}'. "
                        "Modifying geometry for an existing version is rejected; changed geometry yields a new version."
                    )
            else:
                insert_counting_line(conn, line)
                inserted_lines += 1

        inserted_zones = 0
        for zone in validated_zones:
            existing = fetch_zone_by_id(conn, zone["zone_id"])
            if existing:
                if existing["geometry_sha256"] == zone["geometry_sha256"]:
                    # Idempotent reload: unchanged
                    continue
                else:
                    raise ValueError(
                        f"Zone '{zone['zone_id']}' already exists with config_version '{existing['config_version']}'. "
                        "Modifying geometry for an existing version is rejected; changed geometry yields a new version."
                    )
            else:
                insert_zone(conn, zone)
                inserted_zones += 1

        conn.commit()

        return {
            "video_id": video_id,
            "counting_lines_count": len(validated_lines),
            "zones_count": len(validated_zones),
            "lines_inserted": inserted_lines,
            "zones_inserted": inserted_zones,
            "status": "loaded",
        }

    if connection is not None:
        return _execute(connection)

    database_path = (
        Path(config["paths"]["database_path"])
        if config
        else Path("data/processed/traffic_vision.sqlite3")
    )
    if not database_path.is_absolute() and repository_root:
        database_path = repository_root / database_path

    with database_connection(database_path) as conn:
        return _execute(conn)


def fetch_geometry_for_video(
    connection: sqlite3.Connection,
    video_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Retrieve all counting lines and zones configured for a given video."""
    lines = fetch_counting_lines_for_video(connection, video_id)
    zones = fetch_zones_for_video(connection, video_id)
    return {
        "counting_lines": [dict(row) for row in lines],
        "zones": [dict(row) for row in zones],
    }


def render_geometry_preview(
    video_id: str,
    output_path: Path | str,
    frame_number: int = 0,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> Path:
    """Render configured lines and zones overlaid on a video frame preview to an image file.

    Creates NO processing_run record in processing_runs table.
    """
    if frame_number < 0:
        raise ValueError(f"frame_number must be >= 0, got {frame_number}")

    out_file = Path(output_path)
    if not out_file.is_absolute() and repository_root:
        out_file = repository_root / out_file

    def _render(conn: sqlite3.Connection) -> Path:
        video = conn.execute(
            "SELECT video_id, path, width, height FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if not video:
            raise ValueError(f"Video '{video_id}' not found in database")

        video_path = Path(video["path"])
        if not video_path.is_absolute() and repository_root:
            video_path = repository_root / video_path

        preview = preview_frame(video_path, frame_number)
        image = preview.frame.to_ndarray(format="rgb24")

        lines = fetch_counting_lines_for_video(conn, video_id)
        zones = fetch_zones_for_video(conn, video_id)

        annotated = render_geometry_overlay(image, lines, zones)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(out_file), bgr)
        return out_file

    if connection is not None:
        return _render(connection)

    database_path = (
        Path(config["paths"]["database_path"])
        if config
        else Path("data/processed/traffic_vision.sqlite3")
    )
    if not database_path.is_absolute() and repository_root:
        database_path = repository_root / database_path

    with database_connection(database_path) as conn:
        return _render(conn)
