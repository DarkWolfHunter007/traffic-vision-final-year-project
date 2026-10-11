# Phase 01 Handoff — Video Input and Foundational Scaffolding

## Delivered interfaces

- `traffic-vision bootstrap-db`: creates a new canonical SQLite database or confirms a recorded matching schema version.
- `traffic-vision ingest VIDEO`: streams one supported video through PyAV, persists `videos`, `processing_runs`, and `video_frames` records, and records a timestamp audit.
- `GET /health` and `GET /status`: minimal FastAPI wiring only.
- `frontend/index.html`: minimal UI entry point only.

## Configuration

`configs/default.yaml` owns raw/processed paths, database path, supported formats, decoder-PTS timestamp policy, streaming batch size, resource placeholders, and logging level. Configuration is canonicalised and SHA-256 hashed before it is stored on each processing run.

## Database and migration behaviour

- `backend/database/schema.sql` remains the canonical data contract.
- Every opened SQLite connection enables `PRAGMA foreign_keys = ON`.
- `schema_migrations` records the content hash of the schema used for a fresh bootstrap.
- A non-empty database with no recorded schema hash, or with a different recorded schema hash, is rejected. It must be explicitly migrated or treated as disposable; Phase 01 does not silently reinterpret it.

## Input/output contract

- Inputs: MP4, AVI, MOV, and MKV only when supported by the installed decoder and configured formats.
- Outputs: source-file SHA-256; stream metadata; per-frame decoder PTS; a timestamp continuity/VFR audit; exact config snapshot/hash; schema hash; code revision; and processing-run lineage.
- Missing decoder PTS fails ingestion explicitly. No frame-number/FPS reconstruction is substituted as an authoritative timestamp.

## Tests run

On this branch, using Python 3.12.13:

```text
uv run pytest
11 passed

uv run traffic-vision bootstrap-db
{"database_path": ".../data/processed/traffic_vision.sqlite3", "schema_version": "<SHA-256>"}

GET /health
200 {"status": "ok", "phase": "01", "version": "0.1.0"}
```

The ingestion test generates a labelled software fixture with FFmpeg; it is not traffic footage or evidence of model performance.

## Limitations and dependencies for later phases

- No Pattom footage is available, so no real-scene analysis has been performed.
- Detection, tracking, geometry, movements, counting, calibration, speed, queues, review, training, export, and dashboard features remain excluded.
- Phase 06 will require a deliberate schema/data-dictionary resolution for the documented `video_segments` contract before it is implemented.
