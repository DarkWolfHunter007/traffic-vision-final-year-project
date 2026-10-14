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
    params = dict(model)
    params.setdefault("selected_for_production", 0)
    connection.execute(
        """
        INSERT OR IGNORE INTO model_versions (
            model_version, model_path, sha256, dataset_version, created_at,
            selected_for_production, metrics_json
        )
        VALUES (
            :model_version, :model_path, :sha256, :dataset_version, :created_at,
            :selected_for_production, :metrics_json
        )
        """,
        params,
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


def insert_calibration_run(connection: sqlite3.Connection, run: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO calibration_runs (
            calibration_id, run_id, video_id, method, point_count,
            held_out_point_count, reprojection_error_m_mean, reprojection_error_m_max,
            distortion_checked, flat_road_assumption, accepted, parameters_json
        ) VALUES (
            :calibration_id, :run_id, :video_id, :method, :point_count,
            :held_out_point_count, :reprojection_error_m_mean, :reprojection_error_m_max,
            :distortion_checked, :flat_road_assumption, :accepted, :parameters_json
        )
        """,
        run,
    )


def insert_calibration_points(connection: sqlite3.Connection, points: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO calibration_points (
            calibration_point_id, calibration_id, role, image_x, image_y, world_x, world_y
        ) VALUES (
            :calibration_point_id, :calibration_id, :role, :image_x, :image_y, :world_x, :world_y
        )
        """,
        points,
    )


def fetch_calibration_run_by_id(connection: sqlite3.Connection, calibration_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT calibration_id, run_id, video_id, method, point_count,
               held_out_point_count, reprojection_error_m_mean, reprojection_error_m_max,
               distortion_checked, flat_road_assumption, accepted, parameters_json
        FROM calibration_runs
        WHERE calibration_id = ?
        """,
        (calibration_id,),
    ).fetchone()


def fetch_calibration_points_for_run(connection: sqlite3.Connection, calibration_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT calibration_point_id, calibration_id, role, image_x, image_y, world_x, world_y
        FROM calibration_points
        WHERE calibration_id = ?
        ORDER BY calibration_point_id ASC
        """,
        (calibration_id,),
    ).fetchall()


def fetch_calibration_runs_for_video(connection: sqlite3.Connection, video_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT calibration_id, run_id, video_id, method, point_count,
               held_out_point_count, reprojection_error_m_mean, reprojection_error_m_max,
               distortion_checked, flat_road_assumption, accepted, parameters_json
        FROM calibration_runs
        WHERE video_id = ?
        ORDER BY calibration_id ASC
        """,
        (video_id,),
    ).fetchall()


def fetch_latest_accepted_calibration(connection: sqlite3.Connection, video_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT calibration_id, run_id, video_id, method, point_count,
               held_out_point_count, reprojection_error_m_mean, reprojection_error_m_max,
               distortion_checked, flat_road_assumption, accepted, parameters_json
        FROM calibration_runs
        WHERE video_id = ? AND accepted = 1
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()


def insert_speed_observations(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO speed_observations (
            speed_observation_id, run_id, video_id, track_id, timestamp_s,
            speed_mps, speed_kmh, calibration_id, status, smoothing_window,
            ground_point_method
        ) VALUES (
            :speed_observation_id, :run_id, :video_id, :track_id, :timestamp_s,
            :speed_mps, :speed_kmh, :calibration_id, :status, :smoothing_window,
            :ground_point_method
        )
        """,
        rows,
    )


def fetch_speed_observations_for_run(
    connection: sqlite3.Connection, run_id: str, track_id: int | None = None
) -> list[sqlite3.Row]:
    if track_id is not None:
        return connection.execute(
            """
            SELECT speed_observation_id, run_id, video_id, track_id, timestamp_s,
                   speed_mps, speed_kmh, calibration_id, status, smoothing_window,
                   ground_point_method
            FROM speed_observations
            WHERE run_id = ? AND track_id = ?
            ORDER BY timestamp_s ASC
            """,
            (run_id, track_id),
        ).fetchall()
    return connection.execute(
        """
        SELECT speed_observation_id, run_id, video_id, track_id, timestamp_s,
               speed_mps, speed_kmh, calibration_id, status, smoothing_window,
               ground_point_method
        FROM speed_observations
        WHERE run_id = ?
        ORDER BY track_id ASC, timestamp_s ASC
        """,
        (run_id,),
    ).fetchall()


def _as_run_id_list(run_id: str | Iterable[str]) -> list[str]:
    return [run_id] if isinstance(run_id, str) else list(run_id)


def fetch_speed_observation_stats(
    connection: sqlite3.Connection, run_id: str | Iterable[str]
) -> dict[str, object]:
    """Speed stats for one run id or aggregated across several run ids."""
    run_ids = _as_run_id_list(run_id)
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) as total_count,
            SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END) as valid_count,
            SUM(CASE WHEN status = 'unavailable' THEN 1 ELSE 0 END) as unavailable_count,
            SUM(CASE WHEN status = 'invalid' THEN 1 ELSE 0 END) as invalid_count,
            AVG(CASE WHEN status = 'valid' THEN speed_kmh ELSE NULL END) as mean_speed_kmh,
            MAX(CASE WHEN status = 'valid' THEN speed_kmh ELSE NULL END) as max_speed_kmh,
            AVG(CASE WHEN status = 'valid' THEN speed_mps ELSE NULL END) as mean_speed_mps,
            MAX(CASE WHEN status = 'valid' THEN speed_mps ELSE NULL END) as max_speed_mps
        FROM speed_observations
        WHERE run_id IN ({','.join('?' for _ in run_ids)})
        """,
        run_ids,
    ).fetchone()

    if row is None:
        return {
            "total_count": 0,
            "valid_count": 0,
            "unavailable_count": 0,
            "invalid_count": 0,
            "mean_speed_kmh": None,
            "max_speed_kmh": None,
            "mean_speed_mps": None,
            "max_speed_mps": None,
        }

    return {
        "total_count": int(row["total_count"] or 0),
        "valid_count": int(row["valid_count"] or 0),
        "unavailable_count": int(row["unavailable_count"] or 0),
        "invalid_count": int(row["invalid_count"] or 0),
        "mean_speed_kmh": round(float(row["mean_speed_kmh"]), 2) if row["mean_speed_kmh"] is not None else None,
        "max_speed_kmh": round(float(row["max_speed_kmh"]), 2) if row["max_speed_kmh"] is not None else None,
        "mean_speed_mps": round(float(row["mean_speed_mps"]), 2) if row["mean_speed_mps"] is not None else None,
        "max_speed_mps": round(float(row["max_speed_mps"]), 2) if row["max_speed_mps"] is not None else None,
    }


def insert_stop_events(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO stop_events (
            stop_event_id, run_id, video_id, track_id, start_timestamp_s,
            end_timestamp_s, duration_s, threshold_kmh, status
        ) VALUES (
            :stop_event_id, :run_id, :video_id, :track_id, :start_timestamp_s,
            :end_timestamp_s, :duration_s, :threshold_kmh, :status
        )
        """,
        rows,
    )


def insert_queue_events(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO queue_events (
            queue_event_id, run_id, video_id, zone_id, approach,
            timestamp_s, queue_length_m, queued_vehicle_count, status
        ) VALUES (
            :queue_event_id, :run_id, :video_id, :zone_id, :approach,
            :timestamp_s, :queue_length_m, :queued_vehicle_count, :status
        )
        """,
        rows,
    )


def fetch_stop_events_for_run(
    connection: sqlite3.Connection, run_id: str, track_id: int | None = None
) -> list[sqlite3.Row]:
    if track_id is not None:
        return connection.execute(
            """
            SELECT stop_event_id, run_id, video_id, track_id, start_timestamp_s,
                   end_timestamp_s, duration_s, threshold_kmh, status
            FROM stop_events
            WHERE run_id = ? AND track_id = ?
            ORDER BY start_timestamp_s ASC
            """,
            (run_id, track_id),
        ).fetchall()
    return connection.execute(
        """
        SELECT stop_event_id, run_id, video_id, track_id, start_timestamp_s,
               end_timestamp_s, duration_s, threshold_kmh, status
        FROM stop_events
        WHERE run_id = ?
        ORDER BY track_id ASC, start_timestamp_s ASC
        """,
        (run_id,),
    ).fetchall()


def fetch_queue_events_for_run(
    connection: sqlite3.Connection,
    run_id: str,
    zone_id: str | None = None,
    approach: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT queue_event_id, run_id, video_id, zone_id, approach,
               timestamp_s, queue_length_m, queued_vehicle_count, status
        FROM queue_events
        WHERE run_id = ?
    """
    params: list[object] = [run_id]
    if zone_id is not None:
        query += " AND zone_id = ?"
        params.append(zone_id)
    if approach is not None:
        query += " AND approach = ?"
        params.append(approach)
    query += " ORDER BY timestamp_s ASC, zone_id ASC"
    return connection.execute(query, params).fetchall()


def fetch_queue_detection_stats(
    connection: sqlite3.Connection, run_id: str | Iterable[str]
) -> dict[str, object]:
    """Stop/queue stats for one run id or aggregated across several run ids."""
    run_ids = _as_run_id_list(run_id)
    placeholders = ",".join("?" for _ in run_ids)
    stop_row = connection.execute(
        f"""
        SELECT
            COUNT(*) as total_stops,
            SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END) as valid_stops,
            AVG(CASE WHEN status = 'valid' THEN duration_s ELSE NULL END) as mean_stop_duration_s,
            MAX(CASE WHEN status = 'valid' THEN duration_s ELSE NULL END) as max_stop_duration_s
        FROM stop_events
        WHERE run_id IN ({placeholders})
        """,
        run_ids,
    ).fetchone()

    queue_row = connection.execute(
        f"""
        SELECT
            COUNT(*) as total_queue_events,
            SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END) as valid_queue_events,
            SUM(CASE WHEN status = 'unavailable' THEN 1 ELSE 0 END) as unavailable_queue_events,
            SUM(CASE WHEN status = 'invalid' THEN 1 ELSE 0 END) as invalid_queue_events,
            SUM(CASE WHEN status = 'valid' AND queue_length_m > 0 THEN 1 ELSE 0 END) as formed_queue_events,
            AVG(CASE WHEN status = 'valid' AND queue_length_m > 0 THEN queue_length_m ELSE NULL END) as mean_queue_length_m,
            MAX(CASE WHEN status = 'valid' THEN queue_length_m ELSE NULL END) as max_queue_length_m,
            MAX(queued_vehicle_count) as max_queued_vehicles
        FROM queue_events
        WHERE run_id IN ({placeholders})
        """,
        run_ids,
    ).fetchone()

    return {
        "total_stops": int(stop_row["total_stops"] or 0) if stop_row else 0,
        "valid_stops": int(stop_row["valid_stops"] or 0) if stop_row else 0,
        "mean_stop_duration_s": round(float(stop_row["mean_stop_duration_s"]), 2) if stop_row and stop_row["mean_stop_duration_s"] is not None else None,
        "max_stop_duration_s": round(float(stop_row["max_stop_duration_s"]), 2) if stop_row and stop_row["max_stop_duration_s"] is not None else None,
        "total_queue_events": int(queue_row["total_queue_events"] or 0) if queue_row else 0,
        "valid_queue_events": int(queue_row["valid_queue_events"] or 0) if queue_row else 0,
        "unavailable_queue_events": int(queue_row["unavailable_queue_events"] or 0) if queue_row else 0,
        "invalid_queue_events": int(queue_row["invalid_queue_events"] or 0) if queue_row else 0,
        "formed_queue_events": int(queue_row["formed_queue_events"] or 0) if queue_row else 0,
        "mean_queue_length_m": round(float(queue_row["mean_queue_length_m"]), 2) if queue_row and queue_row["mean_queue_length_m"] is not None else None,
        "max_queue_length_m": round(float(queue_row["max_queue_length_m"]), 2) if queue_row and queue_row["max_queue_length_m"] is not None else None,
        "max_queued_vehicles": int(queue_row["max_queued_vehicles"] or 0) if queue_row and queue_row["max_queued_vehicles"] is not None else 0,
    }


def insert_manual_review(connection: sqlite3.Connection, review: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO manual_reviews (
            review_id, run_id, video_id, track_id, detection_id, frame_number,
            timestamp_s, original_class, corrected_class, original_bbox_json,
            corrected_bbox_json, reason, review_status, reviewer, reviewed_at,
            snippet_path
        ) VALUES (
            :review_id, :run_id, :video_id, :track_id, :detection_id, :frame_number,
            :timestamp_s, :original_class, :corrected_class, :original_bbox_json,
            :corrected_bbox_json, :reason, :review_status, :reviewer, :reviewed_at,
            :snippet_path
        )
        """,
        review,
    )


def update_manual_review_record(
    connection: sqlite3.Connection, review_id: str, updates: dict[str, object]
) -> None:
    set_clauses = [f"{k} = :{k}" for k in updates]
    if not set_clauses:
        return
    params = dict(updates)
    params["review_id"] = review_id
    query = f"UPDATE manual_reviews SET {', '.join(set_clauses)} WHERE review_id = :review_id"
    connection.execute(query, params)


def fetch_manual_reviews(
    connection: sqlite3.Connection,
    run_id: str | None = None,
    video_id: str | None = None,
    review_status: str | None = None,
    reviewer: str | None = None,
    track_id: int | None = None,
    detection_id: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT review_id, run_id, video_id, track_id, detection_id, frame_number,
               timestamp_s, original_class, corrected_class, original_bbox_json,
               corrected_bbox_json, reason, review_status, reviewer, reviewed_at,
               snippet_path
        FROM manual_reviews
        WHERE 1 = 1
    """
    params: list[object] = []
    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)
    if video_id is not None:
        query += " AND video_id = ?"
        params.append(video_id)
    if review_status is not None:
        query += " AND review_status = ?"
        params.append(review_status)
    if reviewer is not None:
        query += " AND reviewer = ?"
        params.append(reviewer)
    if track_id is not None:
        query += " AND track_id = ?"
        params.append(track_id)
    if detection_id is not None:
        query += " AND detection_id = ?"
        params.append(detection_id)
    query += " ORDER BY timestamp_s ASC, frame_number ASC"
    if limit is not None and limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    return connection.execute(query, params).fetchall()


def fetch_manual_review_by_id(
    connection: sqlite3.Connection, review_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT review_id, run_id, video_id, track_id, detection_id, frame_number,
               timestamp_s, original_class, corrected_class, original_bbox_json,
               corrected_bbox_json, reason, review_status, reviewer, reviewed_at,
               snippet_path
        FROM manual_reviews
        WHERE review_id = ?
        """,
        (review_id,),
    ).fetchone()


def fetch_detection_by_id(
    connection: sqlite3.Connection, detection_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT detection_id, run_id, video_id, frame_number, timestamp_s,
               class_id, class_name, confidence, x1, y1, x2, y2, ground_x, ground_y,
               width_px, height_px
        FROM detections
        WHERE detection_id = ?
        """,
        (detection_id,),
    ).fetchone()


def fetch_track_observation_by_id(
    connection: sqlite3.Connection, track_observation_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT track_observation_id, run_id, video_id, track_id, frame_number,
               timestamp_s, vehicle_class, confidence, x1, y1, x2, y2, ground_x,
               ground_y, world_x, world_y, calibration_id, trajectory_status
        FROM tracks
        WHERE track_observation_id = ?
        """,
        (track_observation_id,),
    ).fetchone()


def fetch_manual_review_stats(
    connection: sqlite3.Connection, run_id: str | None = None
) -> dict[str, object]:
    query = """
        SELECT
            COUNT(*) as total_reviews,
            SUM(CASE WHEN review_status = 'pending' THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN review_status = 'approved' THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN review_status = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
            SUM(CASE WHEN corrected_class IS NOT NULL THEN 1 ELSE 0 END) as class_corrected_count,
            SUM(CASE WHEN corrected_bbox_json IS NOT NULL THEN 1 ELSE 0 END) as bbox_corrected_count,
            SUM(CASE WHEN snippet_path IS NOT NULL THEN 1 ELSE 0 END) as snippet_count
        FROM manual_reviews
    """
    params: list[object] = []
    if run_id is not None:
        query += " WHERE run_id = ?"
        params.append(run_id)
    row = connection.execute(query, params).fetchone()
    if row is None:
        return {
            "total_reviews": 0,
            "pending_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "class_corrected_count": 0,
            "bbox_corrected_count": 0,
            "snippet_count": 0,
        }
    return {
        "total_reviews": int(row["total_reviews"] or 0),
        "pending_count": int(row["pending_count"] or 0),
        "approved_count": int(row["approved_count"] or 0),
        "rejected_count": int(row["rejected_count"] or 0),
        "class_corrected_count": int(row["class_corrected_count"] or 0),
        "bbox_corrected_count": int(row["bbox_corrected_count"] or 0),
        "snippet_count": int(row["snippet_count"] or 0),
    }


def fetch_approved_manual_reviews(
    connection: sqlite3.Connection,
    run_id: str | None = None,
    video_id: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT review_id, run_id, video_id, track_id, detection_id, frame_number,
               timestamp_s, original_class, corrected_class, original_bbox_json,
               corrected_bbox_json, reason, review_status, reviewer, reviewed_at,
               snippet_path
        FROM manual_reviews
        WHERE review_status = 'approved'
    """
    params: list[object] = []
    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)
    if video_id is not None:
        query += " AND video_id = ?"
        params.append(video_id)
    query += " ORDER BY video_id ASC, timestamp_s ASC, frame_number ASC"
    return connection.execute(query, params).fetchall()


def fetch_ground_truth_segments(
    connection: sqlite3.Connection, video_id: str | None = None
) -> list[sqlite3.Row]:
    query = """
        SELECT DISTINCT vs.segment_id, vs.video_id, vs.start_s, vs.end_s,
               vs.start_frame, vs.end_frame, vs.label, vs.condition_notes,
               gts.ground_truth_set_id, gts.name as ground_truth_set_name, gts.split_group
        FROM video_segments vs
        JOIN ground_truth_counts gtc ON vs.segment_id = gtc.video_segment_id
        JOIN ground_truth_sets gts ON gtc.ground_truth_set_id = gts.ground_truth_set_id
    """
    params: list[object] = []
    if video_id is not None:
        query += " WHERE vs.video_id = ?"
        params.append(video_id)
    query += " ORDER BY vs.video_id ASC, vs.start_s ASC"
    return connection.execute(query, params).fetchall()


def fetch_video_by_id(
    connection: sqlite3.Connection, video_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT video_id, filename, path, sha256, fps_nominal, width, height,
               duration_s, frame_count, variable_frame_rate, wall_clock_start,
               ingested_at, metadata_json
        FROM videos
        WHERE video_id = ?
        """,
        (video_id,),
    ).fetchone()


def fetch_model_version(
    connection: sqlite3.Connection, model_version: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT model_version, model_path, sha256, dataset_version, created_at,
               selected_for_production, metrics_json
        FROM model_versions
        WHERE model_version = ?
        """,
        (model_version,),
    ).fetchone()


def fetch_all_model_versions(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT model_version, model_path, sha256, dataset_version, created_at,
               selected_for_production, metrics_json
        FROM model_versions
        ORDER BY created_at DESC
        """
    ).fetchall()


def fetch_production_model(
    connection: sqlite3.Connection,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT model_version, model_path, sha256, dataset_version, created_at,
               selected_for_production, metrics_json
        FROM model_versions
        WHERE selected_for_production = 1
        """
    ).fetchone()


def update_model_metrics(
    connection: sqlite3.Connection, model_version: str, metrics_json: str
) -> None:
    connection.execute(
        """
        UPDATE model_versions
        SET metrics_json = ?
        WHERE model_version = ?
        """,
        (metrics_json, model_version),
    )


def set_production_model_version(
    connection: sqlite3.Connection, model_version: str
) -> None:
    existing = connection.execute(
        "SELECT model_version FROM model_versions WHERE model_version = ?",
        (model_version,),
    ).fetchone()
    if existing is None:
        raise ValueError(f"Model version not found: {model_version}")

    connection.execute(
        "UPDATE model_versions SET selected_for_production = 0 WHERE selected_for_production = 1"
    )
    connection.execute(
        "UPDATE model_versions SET selected_for_production = 1 WHERE model_version = ?",
        (model_version,),
    )


def fetch_all_runs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT run_id, parent_run_id, video_id, model_version, config_hash,
               schema_version, code_version, source_video_sha256,
               started_at, completed_at, status, notes
        FROM processing_runs
        ORDER BY started_at DESC, run_id DESC
        """
    ).fetchall()


def fetch_video_for_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT v.video_id, v.filename, v.path, v.sha256, v.fps_nominal,
               v.width, v.height, v.duration_s, v.frame_count,
               v.variable_frame_rate, v.wall_clock_start, v.ingested_at, v.metadata_json
        FROM videos v
        JOIN processing_runs r ON v.video_id = r.video_id
        WHERE r.run_id = ?
        """,
        (run_id,),
    ).fetchone()


def fetch_tracking_quality_stats(connection: sqlite3.Connection, run_id: str) -> dict[str, object]:
    target_run_id = run_id
    row_count = connection.execute(
        "SELECT COUNT(*) FROM tracks WHERE run_id = ?", (target_run_id,)
    ).fetchone()[0]
    if row_count == 0:
        parent = connection.execute(
            "SELECT parent_run_id FROM processing_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if parent and parent["parent_run_id"]:
            p_count = connection.execute(
                "SELECT COUNT(*) FROM tracks WHERE run_id = ?", (parent["parent_run_id"],)
            ).fetchone()[0]
            if p_count > 0:
                target_run_id = parent["parent_run_id"]

    row = connection.execute(
        """
        SELECT
            COUNT(*) as total_observations,
            COUNT(DISTINCT track_id) as total_tracks,
            SUM(CASE WHEN trajectory_status = 'complete' THEN 1 ELSE 0 END) as complete_count,
            SUM(CASE WHEN trajectory_status = 'active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN trajectory_status = 'fragmented' THEN 1 ELSE 0 END) as fragmented_count,
            SUM(CASE WHEN trajectory_status = 'invalid' THEN 1 ELSE 0 END) as invalid_count,
            SUM(CASE WHEN world_x IS NOT NULL THEN 1 ELSE 0 END) as calibrated_points_count
        FROM tracks
        WHERE run_id = ?
        """,
        (target_run_id,),
    ).fetchone()
    total_obs = int(row["total_observations"] or 0)
    return {
        "target_run_id": target_run_id,
        "total_observations": total_obs,
        "total_tracks": int(row["total_tracks"] or 0),
        "trajectory_status_counts": {
            "complete": int(row["complete_count"] or 0),
            "active": int(row["active_count"] or 0),
            "fragmented": int(row["fragmented_count"] or 0),
            "invalid": int(row["invalid_count"] or 0),
        },
        "calibrated_points_count": int(row["calibrated_points_count"] or 0),
    }


def fetch_lineage_run_ids(connection: sqlite3.Connection, run_id: str) -> list[str]:
    """Run ids related to ``run_id``: itself, parent, siblings and children (deterministic order)."""
    related = [run_id]
    row = connection.execute(
        "SELECT parent_run_id FROM processing_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    parent_id = row["parent_run_id"] if row else None
    queries = []
    if parent_id:
        related.append(parent_id)
        queries.append(("SELECT run_id FROM processing_runs WHERE parent_run_id = ? ORDER BY run_id", parent_id))
    queries.append(("SELECT run_id FROM processing_runs WHERE parent_run_id = ? ORDER BY run_id", run_id))
    for sql, arg in queries:
        for r in connection.execute(sql, (arg,)).fetchall():
            if r["run_id"] not in related:
                related.append(r["run_id"])
    return related


def fetch_run_export_data(
    connection: sqlite3.Connection, run_id: str, include_raw: bool = True
) -> dict[str, object] | None:
    run_row = fetch_run_by_id(connection, run_id)
    if run_row is None:
        return None
    run_dict = dict(run_row)

    video_row = fetch_video_for_run(connection, run_id)
    video_dict = dict(video_row) if video_row else None
    video_id = video_dict["video_id"] if video_dict else run_dict.get("video_id")

    # Find related lineage runs to assemble full cross-phase results
    related_run_ids = [run_id]
    if run_dict.get("parent_run_id"):
        parent_id = run_dict["parent_run_id"]
        if parent_id not in related_run_ids:
            related_run_ids.append(parent_id)
        # Sibling runs
        siblings = connection.execute(
            "SELECT run_id FROM processing_runs WHERE parent_run_id = ?", (parent_id,)
        ).fetchall()
        for sib in siblings:
            if sib["run_id"] not in related_run_ids:
                related_run_ids.append(sib["run_id"])
    children = connection.execute(
        "SELECT run_id FROM processing_runs WHERE parent_run_id = ?", (run_id,)
    ).fetchall()
    for ch in children:
        if ch["run_id"] not in related_run_ids:
            related_run_ids.append(ch["run_id"])

    # 1. Volume bins
    bins_rows = connection.execute(
        f"""
        SELECT bin_id, run_id, video_id, line_id, bin_start_s, bin_duration_s,
               observed_duration_s, vehicle_class, approach, movement, count,
               extrapolated_vehicles_per_hour
        FROM traffic_volume_bins
        WHERE run_id IN ({','.join('?' for _ in related_run_ids)})
        ORDER BY bin_start_s ASC, line_id ASC, vehicle_class ASC
        """,
        related_run_ids,
    ).fetchall()
    volume_bins = [dict(r) for r in bins_rows]

    # 2. Crossing events (if included)
    crossings = []
    if include_raw:
        crossing_rows = connection.execute(
            f"""
            SELECT crossing_event_id, run_id, video_id, line_id, track_id,
                   frame_number, timestamp_s, vehicle_class, direction, approach,
                   movement, line_config_version, deduplicated
            FROM crossing_events
            WHERE run_id IN ({','.join('?' for _ in related_run_ids)})
            ORDER BY timestamp_s ASC, crossing_event_id ASC
            """,
            related_run_ids,
        ).fetchall()
        crossings = [dict(r) for r in crossing_rows]

    # 3. Speed observations
    speed_rows = connection.execute(
        f"""
        SELECT speed_observation_id, run_id, video_id, track_id, timestamp_s,
               speed_mps, speed_kmh, calibration_id, status, smoothing_window,
               ground_point_method
        FROM speed_observations
        WHERE run_id IN ({','.join('?' for _ in related_run_ids)})
        ORDER BY timestamp_s ASC, track_id ASC
        """,
        related_run_ids,
    ).fetchall()
    speed_observations = [dict(r) for r in speed_rows]

    # Speed summary stats
    speed_stats = {
        "total_observations": 0,
        "total_count": 0,
        "valid_count": 0,
        "invalid_count": 0,
        "unavailable_count": 0,
        "mean_speed_kmh": None,
        "max_speed_kmh": None,
        "mean_speed_mps": None,
        "max_speed_mps": None,
    }
    # Aggregate across the whole lineage (not just the first run with rows), so the
    # summary is consistent with the exported speed_observations rows.
    s_stats = fetch_speed_observation_stats(connection, related_run_ids)
    if s_stats.get("total_count", 0) > 0:
        speed_stats = dict(s_stats)
        speed_stats["total_observations"] = s_stats["total_count"]

    # 4. Stop events
    stop_rows = connection.execute(
        f"""
        SELECT stop_event_id, run_id, video_id, track_id, start_timestamp_s,
               end_timestamp_s, duration_s, threshold_kmh, status
        FROM stop_events
        WHERE run_id IN ({','.join('?' for _ in related_run_ids)})
        ORDER BY start_timestamp_s ASC, track_id ASC
        """,
        related_run_ids,
    ).fetchall()
    stop_events = [dict(r) for r in stop_rows]

    # 5. Queue events
    queue_rows = connection.execute(
        f"""
        SELECT queue_event_id, run_id, video_id, zone_id, approach, timestamp_s,
               queue_length_m, queued_vehicle_count, status
        FROM queue_events
        WHERE run_id IN ({','.join('?' for _ in related_run_ids)})
        ORDER BY timestamp_s ASC
        """,
        related_run_ids,
    ).fetchall()
    queue_events = [dict(r) for r in queue_rows]

    # Queue summary stats
    raw_q_stats = {
        "total_stops": 0,
        "valid_stops": 0,
        "mean_stop_duration_s": None,
        "max_stop_duration_s": None,
        "total_queue_events": 0,
        "valid_queue_events": 0,
        "formed_queue_events": 0,
        "mean_queue_length_m": None,
        "max_queue_length_m": None,
        "max_queued_vehicles": 0,
    }
    q_s = fetch_queue_detection_stats(connection, related_run_ids)
    if q_s.get("total_stops", 0) > 0 or q_s.get("total_queue_events", 0) > 0:
        raw_q_stats = q_s

    queue_stats = {
        **raw_q_stats,
        "stops": {
            "total": raw_q_stats.get("total_stops", 0),
            "valid_stops": raw_q_stats.get("valid_stops", 0),
            "mean_duration_s": raw_q_stats.get("mean_stop_duration_s"),
            "max_duration_s": raw_q_stats.get("max_stop_duration_s"),
        },
        "queues": {
            "total": raw_q_stats.get("total_queue_events", 0),
            "valid_queues": raw_q_stats.get("valid_queue_events", 0),
            "formed_queues": raw_q_stats.get("formed_queue_events", 0),
            "mean_queue_length_m": raw_q_stats.get("mean_queue_length_m"),
            "max_queue_length_m": raw_q_stats.get("max_queue_length_m"),
            "max_queued_vehicles": raw_q_stats.get("max_queued_vehicles"),
        },
    }

    # 6. Manual reviews
    rev_rows = connection.execute(
        f"""
        SELECT review_id, run_id, video_id, track_id, detection_id, frame_number,
               timestamp_s, original_class, corrected_class, original_bbox_json,
               corrected_bbox_json, reason, review_status, reviewer, reviewed_at,
               snippet_path
        FROM manual_reviews
        WHERE run_id IN ({','.join('?' for _ in related_run_ids)}) OR video_id = ?
        ORDER BY timestamp_s ASC, review_id ASC
        """,
        [*related_run_ids, video_id],
    ).fetchall()
    manual_reviews = [dict(r) for r in rev_rows]

    review_stats = fetch_manual_review_stats(connection, run_id)
    if review_stats["total_reviews"] == 0 and video_id:
        v_rev_stats = connection.execute(
            """
            SELECT
                COUNT(*) as total_reviews,
                SUM(CASE WHEN review_status = 'pending' THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN review_status = 'approved' THEN 1 ELSE 0 END) as approved_count,
                SUM(CASE WHEN review_status = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
                SUM(CASE WHEN corrected_class IS NOT NULL THEN 1 ELSE 0 END) as class_corrected_count,
                SUM(CASE WHEN corrected_bbox_json IS NOT NULL THEN 1 ELSE 0 END) as bbox_corrected_count,
                SUM(CASE WHEN snippet_path IS NOT NULL THEN 1 ELSE 0 END) as snippet_count
            FROM manual_reviews
            WHERE video_id = ?
            """,
            (video_id,),
        ).fetchone()
        if v_rev_stats and v_rev_stats["total_reviews"]:
            review_stats = {
                "total_reviews": int(v_rev_stats["total_reviews"] or 0),
                "pending_count": int(v_rev_stats["pending_count"] or 0),
                "approved_count": int(v_rev_stats["approved_count"] or 0),
                "rejected_count": int(v_rev_stats["rejected_count"] or 0),
                "class_corrected_count": int(v_rev_stats["class_corrected_count"] or 0),
                "bbox_corrected_count": int(v_rev_stats["bbox_corrected_count"] or 0),
                "snippet_count": int(v_rev_stats["snippet_count"] or 0),
            }

    # 7. Tracking quality
    tracking_quality = fetch_tracking_quality_stats(connection, run_id)

    # 8. Calibration
    cal_row = connection.execute(
        """
        SELECT calibration_id, run_id, video_id, method, point_count,
               held_out_point_count, reprojection_error_m_mean,
               reprojection_error_m_max, distortion_checked,
               flat_road_assumption, accepted, parameters_json
        FROM calibration_runs
        WHERE video_id = ?
        ORDER BY accepted DESC, reprojection_error_m_mean ASC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    calibration = dict(cal_row) if cal_row else None

    return {
        "run": run_dict,
        "video": video_dict,
        "traffic_volume_bins": volume_bins,
        "crossing_events": crossings,
        "speed_observations": speed_observations,
        "stop_events": stop_events,
        "queue_events": queue_events,
        "manual_reviews": manual_reviews,
        "tracking_quality": tracking_quality,
        "speed_stats": speed_stats,
        "queue_stats": queue_stats,
        "review_stats": review_stats,
        "calibration": calibration,
    }

