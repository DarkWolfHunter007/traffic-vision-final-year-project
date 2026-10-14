# Phase 13 - Export and Research Dashboard

## Objective
Implement only traceable CSV/JSON/SQLite export and status-aware research dashboard. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Export, Dashboard, Counting, Speed, Queue, Manual Review, Validation, Provenance, Configuration, Data Integrity (Master sections 4, 5, 12, 13, 14, 15, 18, 19, 20).

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality or out-of-scope modules (e.g. emissions, congestion indices, MCE, SUMO).
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row and summary must retain `run_id` and relevant source video/frame/timestamp provenance.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).
Prefer no schema change: canonical tables already exist in `backend/database/schema.sql`.

## Scope
- Deterministic multi-format data export:
  - Export run results in CSV, JSON, and SQLite-compatible formats into a reproducible directory structure.
  - Exported canonical tables and summaries:
    - `processing_runs` (run metadata, lineage, configuration snapshot, code version, schema version, hashes)
    - `videos` (source video metadata, SHA-256, duration, frame counts, VFR status)
    - `traffic_volume_bins` (15-minute time bins, observed durations, vehicle classes, approaches, movements, counts, extrapolated vehicles/hour)
    - Observed-period summaries (overall duration, aggregate counts, movement breakdown, extrapolated hourly rates aggregated across bins)
    - `crossing_events` (raw timestamped line crossing events with line configuration version and deduplication flag)
    - `speed_observations` (calibrated speed observations in m/s and km/h with status: valid, invalid, unavailable)
    - `stop_events` (detected stopped vehicle episodes with start/end media timestamps and duration)
    - `queue_events` (spatial queue observations with queue length in metres and queued vehicle count)
    - `manual_reviews` (human audit records, original/corrected classes, original/corrected bounding boxes, review statuses)
  - Export manifest (`manifest.json`):
    - Records `run_id`, `source_video_sha256`, `model_version`, `config_hash`, `schema_version`, `code_version`, and `export_timestamp`.
    - Contains file inventory with individual file SHA-256 hashes.
    - Computes `content_hash` over exported data content with `export_timestamp` strictly excluded, ensuring bit-for-bit reproducible content hashing.
- Status-aware research dashboard:
  - Dependency-free static frontend in `frontend/` (plain HTML, CSS, and JS ES modules; no Node build steps, no external CDN dependencies).
  - Served directly by the FastAPI application mounted at `/`, keeping `/health` and `/status` endpoints fully functional.
  - Interactive research interface with run selector dropdown (`#run-selector`).
  - Required functional panels with explicit element IDs:
    - Video metadata panel (`#video-metadata`, `#panel-video-metadata`): video ID, filename, SHA-256, dimensions, duration, nominal FPS, VFR flag.
    - Validation status panel (`#validation-status`, `#panel-validation-status`): explicit status overview across calibration, tracking, speed, queue, and counting.
    - Tracking quality panel (`#tracking-quality`, `#panel-tracking-quality`): total tracks, observation counts, trajectory status distribution (`active`, `complete`, `fragmented`, `invalid`), calibrated coordinates count.
    - Counts and 15-minute volume bins panel (`#counts-bins`, `#panel-counts-bins`, `#volume-bins`): tabular breakdown and an inline SVG bar chart visualization (`#volume-chart`).
    - Speed summary panel (`#speed-summary`, `#panel-speed-summary`): total observations, valid/invalid/unavailable counts, mean and maximum speeds (km/h and m/s).
    - Queue and stop events panel (`#queue-stop-events`, `#panel-queue-summary`): stop events count, queue events count, mean and maximum queue lengths in metres, maximum queued vehicle count.
    - Review status panel (`#review-status`, `#panel-review-status`): total reviews, pending/approved/rejected counts, class/bbox correction totals, snippet counts.
    - Ground-truth comparison panel (`#ground-truth-comparison`, `#panel-ground-truth`): comparison metrics against Phase 06 manual reference counts when available.
    - Export trigger panel/action (`#btn-export`): interactive trigger to generate and download run exports.
  - Scientific integrity and value rendering:
    - Must visibly distinguish `valid`, `invalid`, `unavailable`, and `unvalidated` states using text labels as well as color indicators.
    - Missing or null measurements (e.g. uncalibrated speed or missing queue) must be displayed as text label "Unavailable", NEVER replaced with zero.
    - Research interface, not an acceptance engine: NO pass/fail banners or automated acceptance declarations.
    - Accessible, responsive semantic design: semantic HTML, keyboard navigable, high-contrast styling.
- Read-only JSON API endpoints in `backend/app.py`:
  - `GET /api/runs`: list of all available processing runs.
  - `GET /api/runs/{run_id}/summary`: aggregate research summary for the selected run.
  - `GET /api/runs/{run_id}/volume-bins`: 15-minute volume bins and observed-period totals.
  - `GET /api/runs/{run_id}/tracking-quality`: tracking quality metrics and status counts.
  - `GET /api/runs/{run_id}/review-status`: manual review statistics and correction counts.
  - `GET /api/runs/{run_id}/speed-summary`: speed observation statistics and validity breakdown.
  - `GET /api/runs/{run_id}/queue-summary`: stopped vehicle and queue event statistics.
  - `GET /api/runs/{run_id}/video-metadata`: source video technical metadata and ingestion parameters.
  - `GET /api/runs/{run_id}/ground-truth`: ground-truth counting comparison report.
  - `POST /api/runs/{run_id}/export`: trigger export generation for the specified run.

## Inputs and dependencies
- Phase 01: database connection, schema bootstrap, `videos`, `processing_runs`, configuration loading, provenance hashing.
- Phase 03: tracking data in `tracks` table and trajectory status flags.
- Phase 06: counting data in `crossing_events`, `traffic_volume_bins`, `ground_truth_sets`, `ground_truth_counts`.
- Phase 07: calibration data in `calibration_runs` and `calibration_points`.
- Phase 08: speed observations in `speed_observations`.
- Phase 09: stopped vehicle episodes in `stop_events` and spatial queue observations in `queue_events`.
- Phase 10: review records in `manual_reviews`.

## Database schema and persistence
Prefer no schema change. Canonical schema in `backend/database/schema.sql` already provides:
- `videos`: `video_id`, `filename`, `path`, `sha256`, `fps_nominal`, `width`, `height`, `duration_s`, `frame_count`, `variable_frame_rate`, `wall_clock_start`, `ingested_at`, `metadata_json`.
- `processing_runs`: `run_id`, `parent_run_id`, `video_id`, `model_version`, `config_hash`, `config_json`, `schema_version`, `code_version`, `source_video_sha256`, `started_at`, `completed_at`, `status`, `notes`.
- `tracks`: `track_observation_id`, `run_id`, `video_id`, `track_id`, `frame_number`, `timestamp_s`, `vehicle_class`, `confidence`, `x1`, `y1`, `x2`, `y2`, `ground_x`, `ground_y`, `world_x`, `world_y`, `calibration_id`, `trajectory_status`.
- `traffic_volume_bins`: `bin_id`, `run_id`, `video_id`, `line_id`, `bin_start_s`, `bin_duration_s`, `observed_duration_s`, `vehicle_class`, `approach`, `movement`, `count`, `extrapolated_vehicles_per_hour`.
- `crossing_events`: `crossing_event_id`, `run_id`, `video_id`, `line_id`, `track_id`, `frame_number`, `timestamp_s`, `vehicle_class`, `direction`, `approach`, `movement`, `line_config_version`, `deduplicated`.
- `speed_observations`: `speed_observation_id`, `run_id`, `video_id`, `track_id`, `timestamp_s`, `speed_mps`, `speed_kmh`, `calibration_id`, `status`, `smoothing_window`, `ground_point_method`.
- `stop_events`: `stop_event_id`, `run_id`, `video_id`, `track_id`, `start_timestamp_s`, `end_timestamp_s`, `duration_s`, `threshold_kmh`, `status`.
- `queue_events`: `queue_event_id`, `run_id`, `video_id`, `zone_id`, `approach`, `timestamp_s`, `queue_length_m`, `queued_vehicle_count`, `status`.
- `manual_reviews`: `review_id`, `run_id`, `video_id`, `track_id`, `detection_id`, `frame_number`, `timestamp_s`, `original_class`, `corrected_class`, `original_bbox_json`, `corrected_bbox_json`, `reason`, `review_status`, `reviewer`, `reviewed_at`, `snippet_path`.

## Configuration
Add `export` and `dashboard` configuration sections to `configs/default.yaml` and validate them in `backend/config.py`:
```yaml
export:
  output_dir: data/processed/exports
  formats:
    - csv
    - json
    - sqlite
  default_format: all
  include_raw_events: true
dashboard:
  host: "127.0.0.1"
  port: 8000
  summary_interval_s: 900.0
```
Validation rules:
- `export.output_dir`: non-empty string directory path.
- `export.formats`: non-empty list of strings from `{"csv", "json", "sqlite"}`.
- `export.default_format`: string, one of `{"all", "csv", "json", "sqlite"}`.
- `export.include_raw_events`: boolean flag.
- `dashboard.host`: non-empty string hostname or IP address.
- `dashboard.port`: integer between 1 and 65535.
- `dashboard.summary_interval_s`: positive float > 0.0.

## Interface contract
- Pure logic module in `backend/export.py`:
  - `compute_observed_period_summary(bins) -> list[dict[str, Any]]`: Computes aggregate volume, duration, and hourly extrapolation across all bins.
  - `build_export_manifest(run_metadata, exported_files, content_hash, export_timestamp=None) -> dict[str, Any]`: Assembles manifest with provenance and file SHA-256 hashes.
  - `compute_content_hash(export_data_payload) -> str`: Computes deterministic SHA-256 hash strictly excluding `export_timestamp`.
  - `format_csv_data(rows, fieldnames) -> str`: Produces deterministic CSV text with sorted keys and CRLF/LF normalization.
  - `generate_sqlite_export_database(target_path, tables_data) -> None`: Creates standalone SQLite database containing exported run tables in deterministic order.
- Service module in `backend/services/export.py`:
  - `export_run(run_id, output_dir=None, export_format="all", include_raw=True, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Orchestrates export across CSV, JSON, and SQLite formats, writes manifest, and returns export summary.
  - `get_export_manifest(manifest_path) -> dict[str, Any]`: Reads and parses an export `manifest.json`.
- Dashboard data service module in `backend/services/dashboard.py` (or `backend/services/export.py`):
  - `get_dashboard_runs(config=None, repository_root=None, connection=None) -> list[dict[str, Any]]`
  - `get_dashboard_run_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_volume_bins(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_tracking_quality(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_speed_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_queue_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_review_status(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_video_metadata(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dashboard_ground_truth(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
- Repository operations in `backend/database/repository.py`:
  - `fetch_all_runs(connection) -> list[sqlite3.Row]`: Lists all processing runs ordered by `started_at DESC`.
  - `fetch_run_by_id(connection, run_id) -> sqlite3.Row | None`: Fetches single processing run.
  - `fetch_video_for_run(connection, run_id) -> sqlite3.Row | None`: Fetches video row associated with run.
  - `fetch_tracking_quality_stats(connection, run_id) -> dict[str, Any]`: Computes tracking observations, distinct tracks, trajectory status distribution.
  - `fetch_run_export_data(connection, run_id, include_raw=True) -> dict[str, Any]`: Retrieves all table records associated with a run for export.
- CLI commands in `backend/cli.py`:
  - `traffic-vision export RUN_ID [--output-dir DIR] [--format FORMAT] [--config CONFIG]`
  - `traffic-vision show-export-manifest PATH [--config CONFIG]`
  - `traffic-vision dashboard-summary RUN_ID [--config CONFIG]`
- FastAPI endpoints in `backend/app.py`:
  - `GET /api/runs`: List all runs.
  - `GET /api/runs/{run_id}/summary`: Run summary.
  - `GET /api/runs/{run_id}/volume-bins`: Volume bins and observed-period summary.
  - `GET /api/runs/{run_id}/tracking-quality`: Tracking quality metrics.
  - `GET /api/runs/{run_id}/review-status`: Manual review statistics.
  - `GET /api/runs/{run_id}/speed-summary`: Speed observations summary.
  - `GET /api/runs/{run_id}/queue-summary`: Queue and stop events summary.
  - `GET /api/runs/{run_id}/video-metadata`: Video metadata.
  - `GET /api/runs/{run_id}/ground-truth`: Ground-truth comparison report.
  - `POST /api/runs/{run_id}/export`: Trigger export for run.
  - Static mount at `/` serving `frontend/index.html` and assets.

## Error handling
- Explicitly reject invalid or unknown `run_id` with 404 / `ValueError`.
- Do not silently replace null research values (e.g. uncalibrated speed or missing queue measurements) with 0; report as `Unavailable`.
- Ensure export directory creation does not overwrite unrelated files.
- Fail explicitly when corrupted or unparseable export formats are requested.

## Tests and evidence
Add focused tests:
- `tests/test_export.py`: Pure logic unit tests (CSV formatting, JSON payload, SQLite export, content hashing determinism, exclusion of export_timestamp, observed-period summary computation).
- `tests/test_export_service.py`: Export service integration, multi-format export, SQLite DB readability, manifest verification, CLI commands.
- `tests/test_dashboard_api.py`: FastAPI endpoints for all dashboard panels, export trigger endpoint, static files serving, panel IDs verification, status badges verification.
All existing 214 tests plus new phase tests must pass (`uv run pytest -q`).
Report raw test results in `docs/handoffs/phase_13/HANDOFF.md`.
Software fixtures only; never fabricate research data.

## Handoff
Create `docs/handoffs/phase_13/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies.

## Completion criteria (measurable test plan TP13-01..TP13-16)
- **TP13-01**: Deterministic CSV exports: volume bins, observed-period summary, crossing events, speed observations, stop events, queue events exported with exact headers and sorted rows.
- **TP13-02**: Deterministic JSON export: structured JSON output containing complete run metadata, video metadata, bins, and summaries.
- **TP13-03**: SQLite standalone export: valid SQLite database containing exported run tables and records that can be opened and queried independently.
- **TP13-04**: Manifest provenance retention: `run_id`, `source_video_sha256`, `model_version`, `config_hash`, `schema_version`, and `code_version` recorded in manifest.
- **TP13-05**: Deterministic content hash: content hash calculation excludes `export_timestamp`; identical database data yields bit-for-bit identical content hash across separate export invocations.
- **TP13-06**: 15-minute and observed-period volume bin summaries computed accurately from Phase 06 bins.
- **TP13-07**: Speed summary computation: valid, invalid, and unavailable counts, mean and max speeds in km/h and m/s, null when uncalibrated or empty.
- **TP13-08**: Queue and stop summary computation: stops, queue formation, mean and max queue lengths in metres, null when uncalibrated.
- **TP13-09**: Tracking quality metrics computation: total tracks, observations count, trajectory status breakdown (`active`, `complete`, `fragmented`, `invalid`).
- **TP13-10**: Review status metrics computation: review counts by status and correction counts.
- **TP13-11**: Null values represented as unavailable: missing speeds/queues/durations output text "unavailable" / None, never fabricated zero.
- **TP13-12**: CLI export commands: `export`, `show-export-manifest`, and `dashboard-summary` execute and return valid output.
- **TP13-13**: FastAPI dashboard read-only API endpoints return correct HTTP 200 and schema for all panel data.
- **TP13-14**: FastAPI export trigger endpoint initiates export and returns manifest details.
- **TP13-15**: Static frontend serving: `GET /` serves `index.html` with all required panel IDs (`#video-metadata`, `#validation-status`, `#tracking-quality`, `#counts-bins`, `#speed-summary`, `#queue-stop-events`, `#review-status`, `#ground-truth-comparison`, `#run-selector`), inline SVG chart, and semantic accessible HTML; preserves `/health` and `/status`.
- **TP13-16**: Configuration validation: `backend/config.py` validates all `export` and `dashboard` keys, format choices, port range, and types.

## Explicit exclusions
New CV algorithms, downstream congestion index / emissions modeling / MCE / SUMO simulation, silent historical data repair or overwrite, pass/fail acceptance banners.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.