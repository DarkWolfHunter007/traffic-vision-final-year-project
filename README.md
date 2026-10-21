# Pattom signal-timing study

Final-year Civil Engineering project, Group 4: *Optimization of Traffic Management Strategies for Vehicular Emission Reduction at Urban Intersections*, Pattom intersection, Thiruvananthapuram.

The study tests whether re-optimised or dynamic signal timing at Pattom can reduce delay, stops and estimated emissions. Pipeline (see `docs/project/ARCHITECTURE.md`):

```text
raw video -> preparation (CFR, lens correction) -> YOLO detection -> tracking -> review
  -> traffic parameters (counts, signal phases, queue, stopped delay, V/C)
  -> congestion index + emission estimate -> problems -> alternatives -> MCE -> SUMO
```

This is a fresh start (14 Oct 2026) built only from the documents in `docs/project/`. The earlier code base is kept in git history.

## Documents

| File | Use |
|---|---|
| `docs/project/PRD.md` | What and why. Section 8.1 is the source register. |
| `docs/project/ARCHITECTURE.md` | Components, data contracts, design constraints. |
| `docs/project/PLAN.md` | Phases, gates, validation checks. |
| `docs/project/AI_RULES.md` | Rules for AI agents working here. |
| `docs/project/tasks.json` | Task and decision ledger. |
| `docs/project/IRC_SP41_extract.md` | IRC SP 41 (1994) extract. |
| `docs/project/EMISSION_SOURCES.md` | Emission sources. |

## Quick start (install and visual editor)

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and `ffmpeg` on PATH:

```bash
uv sync --python 3.12 --group dev --extra detect
uv run pytest
uv run pattom editor
```
Opens the browser at `http://127.0.0.1:8765/` to visually wire, run, and preview the pipeline.

```text
uv run pattom graph configs/graphs/pattom.example.yaml --validate-only
uv run pattom graph my_pipeline.yaml
```


## Built so far

| Stage | Module | Status |
|---|---|---|
| Source register (D15) | `sources/register.yaml`, `pattom.register` | Done: missing values raise `SourceGap` |
| Labelled values | `pattom.values` | Done: measured / derived / estimated |
| Run metadata (4.1) | `pattom.runmeta` | Done |
| B Preparation | `pattom.prepare` | Done: VFR probe, CFR copy, checkerboard lens calibration, undistortion |
| C Detection | `pattom.detection` | Done: YOLO (Ultralytics), optional far-arm tiles merged by NMS, explicit label mapping |
| D Tracking | `pattom.tracking` | Done: ByteTrack on the detections file, per-track class changes |
| F Ground mapping and drift (FR-24) | `pattom.ground` | Done: homography per approach, check points required, error in metres, landmark drift check |
| F Counting (FR-09) | `pattom.counting` | Done: stop and arrival lines, one-way crossings, movements incl. free left, interval counts |
| F Capacity and V/C (FR-13) | `pattom.capacity` | Done: SP 41 section 7.6; PCU table must be named (O3) |
| F Signal phases (FR-10) | `pattom.signals` | Done: signal log read from the footage, cycles and green/amber/red |
| F Stopped delay and queue (FR-11, FR-12) | `pattom.delay` | Done: needs approved T46 definitions (O6), or runs as a labelled draft |
| F Indicator table (T22) | `pattom.indicators` | Done: PCU/h, SP 41 capacity, V/C, delay, queue per approach and interval |
| G Emissions phase 1 (FR-15, D13) | `pattom.emissions` | Done: idle CO2 from registered factors, "source not checked"; moving CO2 is a gap until ARAI is obtained |
| G Congestion index (FR-14) | `pattom.congestion` | Done: formula from a versioned config; no default weights (O4) |
| E review screen, H-M (problems, alternatives, MCE, SUMO) | | Not started |

## Setup

Python 3.12, [uv](https://docs.astral.sh/uv/) and ffmpeg on PATH. Everything installs inside the repository: packages in `.venv/`, uv's cache in `.uv-cache/`, Ultralytics settings in `.ultralytics/`, weights in `models/`.

```text
uv sync --python 3.12 --group dev --extra detect
uv run pytest
```

**GPU on Windows.** PyPI's PyTorch for Windows is CPU-only. For the NVIDIA GPU, replace it inside the repo's `.venv` and then run commands with `--no-sync` so uv does not swap it back:

```text
uv pip install --reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126
uv run --no-sync python -c "import torch; print(torch.cuda.is_available())"
```

Weights are never downloaded by the code. Put the `.pt` file in `models/` and name it in `configs/detection.yaml`.

## Preparation commands

```text
uv run pattom probe data/raw/IMG_1483.MOV
uv run pattom cfr data/raw/IMG_1483.MOV data/cfr/test_01.mp4 --slot test
uv run pattom calibrate-lens data/raw/checkerboard.MOV --cols 9 --rows 6 --square-mm 25
uv run pattom undistort data/cfr/test_01.mp4 data/undistorted/test_01.mp4 --slot test
```

## Detection and tracking

```text
copy configs\detection.example.yaml configs\detection.yaml   (then edit)
copy configs\tracker.example.yaml configs\tracker.yaml
uv run pattom detect data/undistorted/test_01.mp4 --slot test
uv run pattom track runs/test/test_01/detections.csv
```

Outputs in `runs/<slot>/<video>/`: `detections.csv`, `tracks.csv` (ARCHITECTURE 4.2; ground columns are filled later by the ground mapping), `track_summary.csv` (per-track class and class changes, for the review flags) and a `.run.json` for each step.

## Ground mapping, drift and counting

```text
uv run pattom ground --tracks runs/test/test_01/tracks.csv        (calibration/ground.yaml)
uv run pattom drift data/undistorted/test_01.mp4 --out runs/test/test_01/drift.json
uv run pattom count runs/test/test_01/tracks.csv --interval-s 900  (configs/lines.yaml)
```

Writes `crossings.csv` and `interval_counts.csv` (ARCHITECTURE 4.4). Examples: `calibration/ground.example.yaml`, `configs/lines.example.yaml`.

## Delay, queue, V/C, emissions and congestion index

```text
uv run pattom signals configs/signal_log.csv
uv run pattom delay runs/peak/p01/tracks.csv --signal-log configs/signal_log.csv   (add --draft before T46 is approved)
uv run pattom emissions runs/peak/p01/vehicle_delay.csv
uv run pattom indicators runs/peak/p01 --signal-log configs/signal_log.csv
uv run pattom congestion runs/peak/p01/approach_indicators.csv
```

Outputs: `vehicle_delay.csv`, `stopped_delay.csv`, `queue.csv`, `emissions.csv`, `approach_indicators.csv`, `congestion_index.csv`, each with run metadata. Example configs are in `configs/*.example.yaml`; values marked `null` are open decisions and the run stops until they are filled.

Originals go in `data/raw/` and are never written to. Each output gets a `.run.json` with the source SHA-256, settings and code revision.

## Folder layout

`data/raw`, `data/cfr`, `data/undistorted` (not in git), `sources/`, `calibration/`, `labels/`, `models/`, `runs/<slot>/`, `outputs/`, `sumo/`.
