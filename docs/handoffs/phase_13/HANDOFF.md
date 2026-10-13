# Phase 13 Handoff — Export and Research Dashboard

## 1. Delivered Interfaces and Modules

### Pure Export Logic (`backend.export`)
- `compute_observed_period_summary(bins: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`: Aggregates Phase 06 15-minute volume bins across the entire observed period by approach, movement, and vehicle class; calculates total count, observed duration, and extrapolated vehicles per hour.
- `compute_content_hash(data_payload: Mapping[str, Any]) -> str`: Computes deterministic SHA-256 hash across canonical data payload with `export_timestamp` strictly excluded, guaranteeing byte-for-byte identical content hash across separate export invocations.
- `build_export_manifest(run_metadata, exported_files, content_hash, export_timestamp=None) -> dict[str, Any]`: Assembles complete export manifest retaining `run_id`, `source_video_sha256`, `model_version`, `config_hash`, `schema_version`, `code_version`, `export_timestamp`, `content_hash`, and individual file SHA-256 hashes.
- `format_csv_data(rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> str`: Serializes tabular records to deterministic CSV text with standard headers, LF line endings, and empty string representation for null values.
- `generate_sqlite_export_database(target_path: Path, tables_data: Mapping[str, Sequence[Mapping[str, Any]]]) -> None`: Generates a standalone SQLite database containing exported run tables and records that can be independently inspected and queried.
- `file_sha256(file_path: Path) -> str`: Cryptographic SHA-256 hash calculator for disk files.

### Export Orchestration Service (`backend.services.export`)
- `export_run(run_id, output_dir=None, export_format="all", include_raw=True, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Orchestrates deterministic export across CSV, JSON, and SQLite formats; writes files to `<output_dir>/<run_id>/`; calculates content hash; writes `manifest.json`; and returns execution summary.
- `get_export_manifest(manifest_path: Path | str) -> dict[str, Any]`: Loads and validates an export manifest JSON from disk.

### Dashboard Data Service (`backend.services.dashboard`)
- `get_dashboard_runs(config=None, repository_root=None, connection=None) -> list[dict[str, Any]]`: Queries all processing runs ordered by start time descending for the run selector.
- `get_dashboard_run_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Compiles aggregate research metrics, validation status indicators, tracking quality, volume summary, speed summary, queue summary, review summary, and ground-truth availability.
- `get_dashboard_volume_bins(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves 15-minute volume bins and observed-period summary for the selected run.
- `get_dashboard_tracking_quality(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves tracking observation counts, distinct tracks, trajectory status distribution (`complete`, `active`, `fragmented`, `invalid`), and calibrated coordinate counts.
- `get_dashboard_speed_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves speed observation validity counts and mean/max speeds (km/h and m/s).
- `get_dashboard_queue_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves stop event statistics and queue length statistics.
- `get_dashboard_review_status(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves manual review status counts, corrections, and snippet counts.
- `get_dashboard_video_metadata(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Retrieves technical video metadata for the run's source media.
- `get_dashboard_ground_truth(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Computes or returns counting ground-truth comparison report if manual reference data exists for the video.

### Repository Operations (`backend.database.repository`)
- `fetch_all_runs(connection: sqlite3.Connection) -> list[sqlite3.Row]`: Queries all processing runs ordered by `started_at DESC, run_id DESC`.
- `fetch_video_for_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None`: Queries video row joined through `processing_runs`.
- `fetch_tracking_quality_stats(connection: sqlite3.Connection, run_id: str) -> dict[str, object]`: Aggregates tracking quality statistics across direct run or parent run.
- `fetch_run_export_data(connection: sqlite3.Connection, run_id: str, include_raw: bool = True) -> dict[str, object] | None`: Assembles complete cross-phase run data across lineage for export.

### CLI Commands (`backend.cli`)
- `traffic-vision export RUN_ID [--output-dir DIR] [--format FORMAT] [--no-raw] [--config CONFIG]`: Exports run data to directory and prints execution JSON.
- `traffic-vision show-export-manifest PATH [--config CONFIG]`: Displays manifest metadata from export directory or manifest file.
- `traffic-vision dashboard-summary RUN_ID [--config CONFIG]`: Queries and outputs JSON dashboard summary for a processing run.

### FastAPI Application Endpoints (`backend.app`)
- `GET /api/runs`: Lists all available processing runs.
- `GET /api/runs/{run_id}/summary`: Aggregate summary for the selected run.
- `GET /api/runs/{run_id}/volume-bins`: 15-minute volume bins and observed-period summary.
- `GET /api/runs/{run_id}/tracking-quality`: Tracking quality metrics and trajectory status distribution.
- `GET /api/runs/{run_id}/review-status`: Manual review statistics.
- `GET /api/runs/{run_id}/speed-summary`: Speed observations summary.
- `GET /api/runs/{run_id}/queue-summary`: Stopped vehicle and queue event summary.
- `GET /api/runs/{run_id}/video-metadata`: Source video metadata.
- `GET /api/runs/{run_id}/ground-truth`: Counting ground-truth comparison report.
- `POST /api/runs/{run_id}/export`: Triggers export generation and returns manifest details.
- Root mount `app.mount("/", StaticFiles(directory="frontend", html=True))` serving static dashboard assets while preserving `/health` and `/status`.

### Static Frontend Dashboard (`frontend/`)
- `frontend/index.html`: Accessible semantic HTML5 layout with controls and required panels:
  - Run selector (`#run-selector`)
  - Video metadata panel (`#video-metadata`, `#panel-video-metadata`)
  - Validation status panel (`#validation-status`, `#panel-validation-status`)
  - Tracking quality panel (`#tracking-quality`, `#panel-tracking-quality`)
  - Volume bins panel (`#counts-bins`, `#panel-counts-bins`, `#volume-bins`) with table and inline SVG bar chart (`#volume-chart`)
  - Speed summary panel (`#speed-summary`, `#panel-speed-summary`)
  - Queue and stop events panel (`#queue-stop-events`, `#panel-queue-summary`, `#queue-summary`)
  - Review status panel (`#review-status`, `#panel-review-status`)
  - Ground-truth comparison panel (`#ground-truth-comparison`, `#panel-ground-truth`)
  - Export trigger button (`#btn-export`) and status feedback (`#export-status`)
- `frontend/style.css`: Clean, dependency-free CSS with WCAG AA contrast, status badges (`status-valid`, `status-invalid`, `status-unavailable`, `status-unvalidated`), and responsive layout.
- `frontend/app.js`: Vanilla ES module fetching dashboard endpoints, rendering panels, drawing the inline SVG chart, and triggering exports.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_13_export_and_dashboard.md` | Modified | Audited and revised in place: exact schema tables/columns, config keys with defaults, CLI/API interfaces, and measurable test plan TP13-01..16. |
| `configs/default.yaml` | Modified | Added default `export` and `dashboard` configuration blocks. |
| `backend/config.py` | Modified | Added `export` and `dashboard` defaults to `DEFAULT_CONFIG` and validation logic in `_validate()`. |
| `backend/database/repository.py` | Modified | Added additive queries: `fetch_all_runs`, `fetch_video_for_run`, `fetch_tracking_quality_stats`, `fetch_run_export_data`. |
| `backend/cli.py` | Modified | Added additive CLI subcommands: `export`, `show-export-manifest`, `dashboard-summary`. |
| `backend/app.py` | Modified | Added additive FastAPI routes for dashboard panels, export trigger, and mounted static frontend at `/`. |
| `frontend/index.html` | Modified | Static dashboard HTML with required panel IDs, run selector, and accessible structure. |
| `frontend/style.css` | Created | High-contrast, dependency-free CSS styling with status badges and responsive grid. |
| `frontend/app.js` | Created | ES module client logic for run selection, panel updates, inline SVG bar chart, and export trigger. |
| `backend/export.py` | Created | Pure export logic: CSV formatting, observed-period summary, SQLite database creation, and deterministic content hashing. |
| `backend/services/export.py` | Created | Export orchestration service and manifest reader. |
| `backend/services/dashboard.py` | Created | Read-only dashboard query services for all panels. |
| `tests/test_export.py` | Created | Pure logic unit tests covering TP13-01..06, TP13-11. |
| `tests/test_export_service.py` | Created | Integration tests covering TP13-07..10, TP13-12, TP13-16, CLI commands, and SQLite exports. |
| `tests/test_dashboard_api.py` | Created | Integration tests covering TP13-13..15 (FastAPI panel endpoints, export trigger, static frontend serving). |
| `docs/handoffs/phase_13/HANDOFF.md` | Created | This handoff documentation. |

---

## 3. Schema Usage and Invariants

No schema changes were required. Canonical tables from `backend/database/schema.sql` are used strictly as designed:
- `videos`: Technical video resolution, FPS, duration, SHA-256, and ingestion metadata.
- `processing_runs`: Processing run records, configuration snapshots, config hashes, Git revisions, schema versions, and status.
- `tracks`: Track observations, trajectory status (`complete`, `active`, `fragmented`, `invalid`), and calibrated coordinate points.
- `traffic_volume_bins`: 15-minute volume bins, observed durations, and extrapolated hourly volume rates.
- `crossing_events`: Line crossing events, vehicle classes, approaches, movements, and deduplication flags.
- `speed_observations`: Calibrated vehicle speeds (m/s and km/h), calibration references, and status flags (`valid`, `invalid`, `unavailable`).
- `stop_events`: Stopped vehicle episodes and durations.
- `queue_events`: Queue evaluations, queued vehicle counts, queue lengths in metres, and status flags.
- `manual_reviews`: Human review records, class/bbox corrections, and review statuses.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
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

Validation rules enforced in `backend/config.py`:
- `export.output_dir`: non-empty string.
- `export.formats`: non-empty list of format strings from `{"csv", "json", "sqlite"}`.
- `export.default_format`: string in `{"all", "csv", "json", "sqlite"}`.
- `export.include_raw_events`: boolean flag.
- `dashboard.host`: non-empty string.
- `dashboard.port`: integer between 1 and 65535.
- `dashboard.summary_interval_s`: positive float > 0.

---

## 5. Raw Test Results

### Phase 13 Focused Tests:
Running `uv run pytest tests/test_export.py tests/test_export_service.py tests/test_dashboard_api.py -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 16 items

tests/test_export.py::test_tp13_01_csv_export_deterministic_formatting PASSED [  6%]
tests/test_export.py::test_tp13_02_observed_period_summary_calculation PASSED [ 12%]
tests/test_export.py::test_tp13_02_empty_bins_observed_summary PASSED    [ 18%]
tests/test_export.py::test_tp13_03_sqlite_export_database_generation PASSED [ 25%]
tests/test_export.py::test_tp13_04_manifest_provenance_retention PASSED  [ 31%]
tests/test_export.py::test_tp13_05_content_hash_excludes_export_timestamp PASSED [ 37%]
tests/test_export.py::test_tp13_11_null_research_values_not_zero PASSED  [ 43%]
tests/test_export_service.py::test_tp13_07_export_run_multi_format_and_determinism PASSED [ 50%]
tests/test_export_service.py::test_tp13_08_sqlite_export_readability PASSED [ 56%]
tests/test_export_service.py::test_tp13_09_tracking_and_review_quality_computation PASSED [ 62%]
tests/test_export_service.py::test_tp13_10_speed_and_queue_summaries_in_dashboard PASSED [ 68%]
tests/test_export_service.py::test_tp13_12_cli_export_and_dashboard_commands PASSED [ 75%]
tests/test_export_service.py::test_tp13_16_configuration_validation PASSED [ 81%]
tests/test_dashboard_api.py::test_tp13_13_dashboard_read_only_api_endpoints PASSED [ 87%]
tests/test_dashboard_api.py::test_tp13_14_export_trigger_endpoint PASSED [ 93%]
tests/test_dashboard_api.py::test_tp13_15_static_frontend_served_with_required_panels PASSED [100%]

============================= 16 passed in 3.74s ==============================
```

### Full Repository Regression Run:
Running `uv run pytest -q`:

```text
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
..............                                                           [100%]
230 passed in 33.95s
```

All 214 pre-existing tests plus 16 new Phase 13 tests passed (230 tests total, 0 failed, 0 errors).

---

## 6. Assumptions and Limitations

1. **Deterministic Hashing**: `content_hash` computation excludes `export_timestamp` so that multiple exports of identical run data yield identical SHA-256 hashes.
2. **Missing Research Values**: Missing speeds, queue lengths, or durations are strictly preserved as `null` / `"Unavailable"`, never fabricated as 0.
3. **Research Interface**: The dashboard is designed as an accessible scientific audit tool; it presents factual indicators and error metrics without pass/fail banners or automated acceptance claims.
4. **Dependency-Free Frontend**: The dashboard uses vanilla HTML, CSS, and ES module JavaScript without any build tools, node_modules, or external CDNs.
5. **Software Test Fixtures**: All test cases use synthetic software fixtures explicitly labelled as software fixtures.

---

## 7. Dependencies for Next Phases / Production Handover

- Phase 13 completes the foundational computer-vision and data extraction pipeline for the final-year engineering study.
- Downstream civil engineering modeling (congestion index, emission calculations, multi-criteria evaluation, and SUMO simulations) can consume the deterministic CSV, JSON, and SQLite exports generated by Phase 13.

---

## 8. Independent Review Notice

In accordance with master project guidelines, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
