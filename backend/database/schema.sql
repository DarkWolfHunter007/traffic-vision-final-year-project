-- Traffic Vision canonical research data schema
-- This is the source of truth for names, provenance, and relationships.
-- Phase 01 owns migration/bootstrap implementation; later phases must not redefine fields.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    fps_nominal REAL,
    width INTEGER,
    height INTEGER,
    duration_s REAL,
    frame_count INTEGER,
    variable_frame_rate INTEGER NOT NULL DEFAULT 0,
    wall_clock_start TEXT,
    ingested_at TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    model_version TEXT,
    config_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    code_version TEXT,
    source_video_sha256 TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS detections (
    detection_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    class_id INTEGER,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    ground_x REAL,
    ground_y REAL,
    width_px REAL NOT NULL,
    height_px REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tracks (
    track_observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    track_id INTEGER NOT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    vehicle_class TEXT,
    confidence REAL,
    x1 REAL,
    y1 REAL,
    x2 REAL,
    y2 REAL,
    ground_x REAL,
    ground_y REAL,
    world_x REAL,
    world_y REAL,
    trajectory_status TEXT NOT NULL DEFAULT 'complete'
);

CREATE TABLE IF NOT EXISTS counting_lines (
    line_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    name TEXT NOT NULL,
    approach TEXT,
    geometry_json TEXT NOT NULL,
    bidirectional INTEGER NOT NULL DEFAULT 0,
    config_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    name TEXT NOT NULL,
    zone_type TEXT NOT NULL,
    approach TEXT,
    geometry_json TEXT NOT NULL,
    config_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crossing_events (
    crossing_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    line_id TEXT NOT NULL REFERENCES counting_lines(line_id),
    track_id INTEGER NOT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    vehicle_class TEXT,
    direction TEXT,
    approach TEXT,
    movement TEXT
);

CREATE TABLE IF NOT EXISTS traffic_volume_bins (
    bin_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    line_id TEXT NOT NULL REFERENCES counting_lines(line_id),
    bin_start_s REAL NOT NULL,
    bin_duration_s REAL NOT NULL DEFAULT 900,
    vehicle_class TEXT,
    approach TEXT,
    movement TEXT,
    count INTEGER NOT NULL,
    extrapolated_vehicles_per_hour REAL
);

CREATE TABLE IF NOT EXISTS calibration_runs (
    calibration_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    method TEXT NOT NULL,
    point_count INTEGER NOT NULL,
    held_out_point_count INTEGER NOT NULL,
    reprojection_error_m_mean REAL,
    reprojection_error_m_max REAL,
    distortion_checked INTEGER NOT NULL DEFAULT 0,
    flat_road_assumption INTEGER NOT NULL DEFAULT 1,
    accepted INTEGER NOT NULL DEFAULT 0,
    parameters_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration_points (
    calibration_point_id TEXT PRIMARY KEY,
    calibration_id TEXT NOT NULL REFERENCES calibration_runs(calibration_id),
    role TEXT NOT NULL,
    image_x REAL NOT NULL,
    image_y REAL NOT NULL,
    world_x REAL NOT NULL,
    world_y REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS speed_observations (
    speed_observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    track_id INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    speed_mps REAL,
    speed_kmh REAL,
    status TEXT NOT NULL,
    smoothing_window REAL,
    ground_point_method TEXT NOT NULL DEFAULT 'bottom_center'
);

CREATE TABLE IF NOT EXISTS stop_events (
    stop_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    track_id INTEGER NOT NULL,
    start_timestamp_s REAL NOT NULL,
    end_timestamp_s REAL,
    duration_s REAL,
    threshold_kmh REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_events (
    queue_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    zone_id TEXT,
    approach TEXT,
    timestamp_s REAL NOT NULL,
    queue_length_m REAL,
    queued_vehicle_count INTEGER,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    track_id INTEGER,
    detection_id TEXT,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    original_class TEXT,
    corrected_class TEXT,
    original_bbox_json TEXT,
    corrected_bbox_json TEXT,
    reason TEXT NOT NULL,
    review_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_truth_sets (
    ground_truth_set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_description TEXT NOT NULL,
    split_group TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_truth_counts (
    ground_truth_count_id TEXT PRIMARY KEY,
    ground_truth_set_id TEXT NOT NULL REFERENCES ground_truth_sets(ground_truth_set_id),
    video_segment_id TEXT NOT NULL,
    approach TEXT NOT NULL,
    movement TEXT NOT NULL,
    vehicle_class TEXT,
    observed_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS model_versions (
    model_version TEXT PRIMARY KEY,
    model_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dataset_version TEXT,
    created_at TEXT NOT NULL,
    selected_for_production INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_detections_run ON detections(run_id);
CREATE INDEX IF NOT EXISTS idx_tracks_run_track ON tracks(run_id, track_id);
CREATE INDEX IF NOT EXISTS idx_crossings_run_time ON crossing_events(run_id, timestamp_s);
CREATE INDEX IF NOT EXISTS idx_queue_run_time ON queue_events(run_id, timestamp_s);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON manual_reviews(run_id);
