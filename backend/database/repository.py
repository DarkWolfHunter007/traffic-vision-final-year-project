"""Phase 01 persistence operations using the canonical schema."""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable


def insert_video(connection: sqlite3.Connection, video: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO videos (
            video_id, filename, path, sha256, fps_nominal, width, height,
            duration_s, frame_count, variable_frame_rate, wall_clock_start,
            ingested_at, metadata_json
        ) VALUES (
            :video_id, :filename, :path, :sha256, :fps_nominal, :width, :height,
            :duration_s, :frame_count, :variable_frame_rate, :wall_clock_start,
            :ingested_at, :metadata_json
        )
        """,
        video,
    )


def insert_run(connection: sqlite3.Connection, run: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO processing_runs (
            run_id, parent_run_id, video_id, model_version, config_hash,
            config_json, schema_version, code_version, source_video_sha256,
            started_at, status, notes
        ) VALUES (
            :run_id, :parent_run_id, :video_id, :model_version, :config_hash,
            :config_json, :schema_version, :code_version, :source_video_sha256,
            :started_at, :status, :notes
        )
        """,
        run,
    )


def update_run_status(
    connection: sqlite3.Connection, run_id: str, status: str, completed_at: str | None = None, notes: str | None = None
) -> None:
    connection.execute(
        """
        UPDATE processing_runs
        SET status = :status, completed_at = :completed_at, notes = COALESCE(:notes, notes)
        WHERE run_id = :run_id
        """,
        {"run_id": run_id, "status": status, "completed_at": completed_at, "notes": notes},
    )


def insert_frame_batch(connection: sqlite3.Connection, video_id: str, frames: Iterable[tuple[int, float]]) -> None:
    connection.executemany(
        "INSERT INTO video_frames (video_id, frame_number, pts_s) VALUES (?, ?, ?)",
        ((video_id, frame_number, pts_s) for frame_number, pts_s in frames),
    )


def metadata_json(metadata: dict[str, object]) -> str:
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def insert_model_version(connection: sqlite3.Connection, model: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO model_versions (model_version, model_path, sha256, dataset_version, created_at, metrics_json)
        VALUES (:model_version, :model_path, :sha256, :dataset_version, :created_at, :metrics_json)
        """,
        model,
    )


def insert_detections(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO detections (
            detection_id, run_id, video_id, frame_number, timestamp_s, class_id, class_name,
            confidence, x1, y1, x2, y2, ground_x, ground_y, width_px, height_px
        ) VALUES (
            :detection_id, :run_id, :video_id, :frame_number, :timestamp_s, :class_id, :class_name,
            :confidence, :x1, :y1, :x2, :y2, :ground_x, :ground_y, :width_px, :height_px
        )
        """,
        rows,
    )


def insert_tracks(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO tracks (
            track_observation_id, run_id, video_id, track_id, frame_number, timestamp_s,
            vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y,
            world_x, world_y, calibration_id, trajectory_status
        ) VALUES (
            :track_observation_id, :run_id, :video_id, :track_id, :frame_number, :timestamp_s,
            :vehicle_class, :confidence, :x1, :y1, :x2, :y2, :ground_x, :ground_y,
            :world_x, :world_y, :calibration_id, :trajectory_status
        )
        """,
        rows,
    )


def fetch_detections_for_tracking(
    connection: sqlite3.Connection,
    run_id: str,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> list[sqlite3.Row]:
    if start_frame is not None and end_frame is not None:
        return connection.execute(
            """
            SELECT detection_id, run_id, video_id, frame_number, timestamp_s,
                   class_id, class_name, confidence, x1, y1, x2, y2, ground_x, ground_y
            FROM detections
            WHERE run_id = ? AND frame_number BETWEEN ? AND ?
            ORDER BY frame_number ASC, confidence DESC
            """,
            (run_id, start_frame, end_frame),
        ).fetchall()
    return connection.execute(
        """
        SELECT detection_id, run_id, video_id, frame_number, timestamp_s,
               class_id, class_name, confidence, x1, y1, x2, y2, ground_x, ground_y
        FROM detections
        WHERE run_id = ?
        ORDER BY frame_number ASC, confidence DESC
        """,
        (run_id,),
    ).fetchall()


def fetch_tracks_for_run(connection: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT track_observation_id, run_id, video_id, track_id, frame_number, timestamp_s,
               vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y,
               world_x, world_y, calibration_id, trajectory_status
        FROM tracks
        WHERE run_id = ?
        ORDER BY track_id ASC, frame_number ASC, timestamp_s ASC
        """,
        (run_id,),
    ).fetchall()


def fetch_tracks_for_frame(connection: sqlite3.Connection, run_id: str, frame_number: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT track_observation_id, run_id, video_id, track_id, frame_number, timestamp_s,
               vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y,
               world_x, world_y, calibration_id, trajectory_status
        FROM tracks
        WHERE run_id = ? AND frame_number = ?
        ORDER BY track_id ASC
        """,
        (run_id, frame_number),
    ).fetchall()


def fetch_run_by_id(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT run_id, parent_run_id, video_id, model_version, config_hash, config_json,
               schema_version, code_version, source_video_sha256, started_at, completed_at,
               status, notes
        FROM processing_runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()


def insert_counting_line(connection: sqlite3.Connection, line: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO counting_lines (
            line_id, video_id, name, approach, geometry_json, bidirectional,
            config_version, geometry_sha256
        ) VALUES (
            :line_id, :video_id, :name, :approach, :geometry_json, :bidirectional,
            :config_version, :geometry_sha256
        )
        """,
        line,
    )


def insert_zone(connection: sqlite3.Connection, zone: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO zones (
            zone_id, video_id, name, zone_type, approach, geometry_json,
            config_version, geometry_sha256
        ) VALUES (
            :zone_id, :video_id, :name, :zone_type, :approach, :geometry_json,
            :config_version, :geometry_sha256
        )
        """,
        zone,
    )


def fetch_counting_lines_for_video(
    connection: sqlite3.Connection, video_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT line_id, video_id, name, approach, geometry_json, bidirectional,
               config_version, geometry_sha256
        FROM counting_lines
        WHERE video_id = ?
        ORDER BY line_id ASC
        """,
        (video_id,),
    ).fetchall()


def fetch_zones_for_video(
    connection: sqlite3.Connection, video_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT zone_id, video_id, name, zone_type, approach, geometry_json,
               config_version, geometry_sha256
        FROM zones
        WHERE video_id = ?
        ORDER BY zone_id ASC
        """,
        (video_id,),
    ).fetchall()


def fetch_counting_line_by_id(
    connection: sqlite3.Connection, line_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT line_id, video_id, name, approach, geometry_json, bidirectional,
               config_version, geometry_sha256
        FROM counting_lines
        WHERE line_id = ?
        """,
        (line_id,),
    ).fetchone()


def fetch_zone_by_id(
    connection: sqlite3.Connection, zone_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT zone_id, video_id, name, zone_type, approach, geometry_json,
               config_version, geometry_sha256
        FROM zones
        WHERE zone_id = ?
        """,
        (zone_id,),
    ).fetchone()


def insert_video_segment(connection: sqlite3.Connection, segment: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO video_segments (
            segment_id, video_id, start_s, end_s, start_frame, end_frame, label, condition_notes
        ) VALUES (
            :segment_id, :video_id, :start_s, :end_s, :start_frame, :end_frame, :label, :condition_notes
        )
        """,
        segment,
    )


def insert_video_segments(connection: sqlite3.Connection, segments: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO video_segments (
            segment_id, video_id, start_s, end_s, start_frame, end_frame, label, condition_notes
        ) VALUES (
            :segment_id, :video_id, :start_s, :end_s, :start_frame, :end_frame, :label, :condition_notes
        )
        """,
        segments,
    )


def fetch_video_segments_for_video(connection: sqlite3.Connection, video_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT segment_id, video_id, start_s, end_s, start_frame, end_frame, label, condition_notes
        FROM video_segments
        WHERE video_id = ?
        ORDER BY start_s ASC
        """,
        (video_id,),
    ).fetchall()


def fetch_video_segment_by_id(connection: sqlite3.Connection, segment_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT segment_id, video_id, start_s, end_s, start_frame, end_frame, label, condition_notes
        FROM video_segments
        WHERE segment_id = ?
        """,
        (segment_id,),
    ).fetchone()


def insert_ground_truth_set(connection: sqlite3.Connection, gt_set: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO ground_truth_sets (
            ground_truth_set_id, name, source_description, split_group, created_at
        ) VALUES (
            :ground_truth_set_id, :name, :source_description, :split_group, :created_at
        )
        """,
        gt_set,
    )


def fetch_ground_truth_set_by_id(connection: sqlite3.Connection, ground_truth_set_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT ground_truth_set_id, name, source_description, split_group, created_at
        FROM ground_truth_sets
        WHERE ground_truth_set_id = ?
        """,
        (ground_truth_set_id,),
    ).fetchone()


def insert_ground_truth_counts(connection: sqlite3.Connection, counts: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO ground_truth_counts (
            ground_truth_count_id, ground_truth_set_id, video_segment_id, approach,
            movement, vehicle_class, observed_count
        ) VALUES (
            :ground_truth_count_id, :ground_truth_set_id, :video_segment_id, :approach,
            :movement, :vehicle_class, :observed_count
        )
        """,
        counts,
    )


def fetch_ground_truth_counts_for_set(connection: sqlite3.Connection, ground_truth_set_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT ground_truth_count_id, ground_truth_set_id, video_segment_id, approach,
               movement, vehicle_class, observed_count
        FROM ground_truth_counts
        WHERE ground_truth_set_id = ?
        ORDER BY video_segment_id ASC, approach ASC, movement ASC
        """,
        (ground_truth_set_id,),
    ).fetchall()


def insert_crossing_events(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO crossing_events (
            crossing_event_id, run_id, video_id, line_id, track_id, frame_number,
            timestamp_s, vehicle_class, direction, approach, movement,
            line_config_version, deduplicated
        ) VALUES (
            :crossing_event_id, :run_id, :video_id, :line_id, :track_id, :frame_number,
            :timestamp_s, :vehicle_class, :direction, :approach, :movement,
            :line_config_version, :deduplicated
        )
        """,
        rows,
    )


def fetch_crossing_events_for_run(connection: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT crossing_event_id, run_id, video_id, line_id, track_id, frame_number,
               timestamp_s, vehicle_class, direction, approach, movement,
               line_config_version, deduplicated
        FROM crossing_events
        WHERE run_id = ?
        ORDER BY timestamp_s ASC, frame_number ASC
        """,
        (run_id,),
    ).fetchall()


def insert_traffic_volume_bins(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO traffic_volume_bins (
            bin_id, run_id, video_id, line_id, bin_start_s, bin_duration_s,
            observed_duration_s, vehicle_class, approach, movement,
            count, extrapolated_vehicles_per_hour
        ) VALUES (
            :bin_id, :run_id, :video_id, :line_id, :bin_start_s, :bin_duration_s,
            :observed_duration_s, :vehicle_class, :approach, :movement,
            :count, :extrapolated_vehicles_per_hour
        )
        """,
        rows,
    )


def fetch_traffic_volume_bins_for_run(connection: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT bin_id, run_id, video_id, line_id, bin_start_s, bin_duration_s,
               observed_duration_s, vehicle_class, approach, movement,
               count, extrapolated_vehicles_per_hour
        FROM traffic_volume_bins
        WHERE run_id = ?
        ORDER BY bin_start_s ASC, line_id ASC
        """,
        (run_id,),
    ).fetchall()


