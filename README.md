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
| F Signal phases (FR-10) | `pattom.phases` | Done: checks the phase log typed from playback, cycles per signal head |
| Pipeline harness | `pattom.harness`, `pattom.blocks` | Done: every component A-M is a block; see below |
| Workbench (local web app) | `pattom.viewer` | Done: project status, videos, pipeline editor and runner, results viewer, editors for lines, ground points, phase log and settings |
| E Review (FR-06, FR-07) | `pattom.review` | Done: flags (low confidence, class change, vanished, hard zones, random sample); labels in YOLO format and a review log |
| F Stopped delay and queue (FR-11, FR-12) | `pattom.queue_delay` | Done: speed from ground positions; definition (O6) is required, no default |
| F Count validation (FR-08) | `pattom.validation` | Done: manual windows against automatic crossings, error per line and class |
| G Congestion index (FR-14) | `pattom.indices` | Done: your indicators, normalisation and weights (O4) |
| G Emissions phase 1 (FR-15) | `pattom.indices` | Done: CO2 while stopped from registered factors; missing factors listed as gaps |
| H Problems | `pattom.indices` | Done: your rules applied to the indicators |
| I-K Alternatives, pre-SUMO scoring, MCE (FR-17 to FR-19) | `pattom.alternatives` | Done: SP 41 V/C under each plan, delay is a register gap (T28); MCE with sensitivity (O13) |
| L-M SUMO and comparison (FR-20 to FR-22) | `pattom.sumo` | Done: network from site data via netconvert, demand from counts, existing and selected plans, seeded runs, mean and spread |

## Pipeline harness (blocks)

Each stage is a block that reads named artifacts and writes new ones. The pipeline file lists the blocks in order; a block can be switched off, rebound to another input, or replaced, without touching the others.

```text
 video.raw --[cfr]--> video.cfr --[undistort]--> video.undistorted --[detect]--> detections
   --[track]--> tracks --[ground-map]--> tracks.ground --[count]--> crossings, interval_counts
 phase_log --[signal-phases]--> signal_cycles
   ... --[queue] [stopped-delay] [capacity-vc] --> [congestion-index] [emissions] --> [analysis]
   --> [alternatives] --> [pre-sumo-scoring] --> [mce] --> [sumo-inputs] --> [sumo-run] --> [comparison]
```

```text
copy configs\pipeline.example.yaml configs\pipeline.yaml   (then edit)
uv run pattom blocks                          every block, its inputs, outputs and what it waits on
uv run pattom pipeline check                  nothing runs; lists problems
uv run --no-sync pattom pipeline run          writes runs/<slot>/pipeline.json
uv run --no-sync pattom pipeline run --only count
```

- `enabled: false` switches a block off. The check names any later block that loses its input.
- `bind: {video: video.cfr}` feeds a port from another artifact (for example, detection on the CFR copy until the lens calibration exists).
- Every block is built. Where a method depends on an open decision (queue definition O6, PCU table O3, congestion-index formula O4, MCE weights O13, SUMO seeds and tolerance O14, SUMO emissions O18), that setting is **required with no default**: the check names it until you fill it in. Put them in `configs/study_settings.yaml` (one section per block, from `study_settings.example.yaml`) and give the block `params: {settings_file: configs/study_settings.yaml}`.
- Values that are not in the source register are reported as gaps, never filled: the emission per-km factors (ARAI 2007, not obtained yet) and a delay formula for the pre-SUMO scoring (SP 41 has none, T28).
- A block class with status `planned` (`pattom.harness.block.PlannedBlock`) can still be used by a plug-in package for a stage that is not ready.
- Another package can add blocks through the `pattom.blocks` entry-point group.
- All paths must be inside the repository.

## Workbench (local web app)

```text
uv sync --inexact --group dev --extra detect --extra viewer --no-install-package torch --no-install-package torchvision
uv run --no-sync pattom view                 then open http://127.0.0.1:8000
uv run --no-sync pattom view --make-demo     adds a synthetic demo run (slot "demo", not traffic data)
```

| Page | What it does |
|---|---|
| Home | Setup checklist from the app's own files (videos, weights, settings, pipeline check, runs, lines, ground points, phase logs), the next step, and whether PyTorch sees the GPU. |
| Videos | Originals and prepared copies; probe frame rate (VFR check); set a video as the pipeline input. |
| Pipeline | Switch blocks on and off, bind inputs, set options, check, save, run (all or ticked blocks) with a live log. |
| Results | The prepared video with track or detection boxes, the track list (click to jump), and the run's CSV tables. |
| Counting lines | Click two points on a frame to add a line; set type, approach and counted direction; movements. Writes `configs/lines.yaml` (T18). |
| Ground points | Click points, type the site metres, mark fit or check; zone, check distances, drift landmarks; "Fit and check" shows the error in metres. Writes `calibration/ground.yaml` (T04, T48). |
| Signal phases | Play the video and press G / A / R per signal head (keys 1-9, G, A, R). Writes `runs/<slot>/phase_log.csv` and shows the cycles (T19). |
| Review and labels | Flagged frames; fix, delete or draw boxes; save YOLO-format training labels to `labels/<slot>/<video>/`. |
| Manual counts | Play a run's video, count a window per line with keys 1-9; writes `manual_counts.csv` for count-validation. |
| Alternatives | Write the signal-timing alternatives (fixed or actuated); SP 41 fixed-time suggestion from a capacity result. |
| Detection settings | Tiles preview, detection and tracker settings as YAML. |
| Settings files | Any YAML in `configs/` or `calibration/`, e.g. `study_settings.yaml` and `sumo_network.yaml`. |
| Source register | `sources/register.yaml`, read-only, with verified / reported status. |

The app runs on its own files only: it does not read the planning or AI-agent documents in `docs/project/` or `CLAUDE.md`, and YOLO is the only machine-learning model it uses. Every save goes through the loader the pipeline uses, so the app cannot write a file the pipeline would refuse. The app adds no values: positions, distances and signal times come from you, results from the pipeline. Runs start `pattom pipeline run` as a separate process with the repository's interpreter.

Only `127.0.0.1` is served, and every change needs the token the server puts in the page, so another website cannot drive it: the footage shows people and number plates and privacy handling is open (O16). The browser plays the `.mp4` copies, not the HEVC `.MOV` originals.

Tests: `uv run --no-sync pytest tests/test_viewer.py` checks the API and walks every page in the installed Microsoft Edge with Playwright (no download), on a throwaway copy with the synthetic demo. Add `PATTOM_HEADED=1` to watch it and `PATTOM_SHOTS=outputs/viewer_check` for screenshots.

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

**4K video and tiles.** YOLO sees each frame shrunk to `imgsz` (1280) pixels wide, so far vehicles in a 3840x2160 frame become a few pixels and are missed. `tiles` (listed boxes) or `tile_grid: {size: 1280, overlap: 256, region: [x1, y1, x2, y2]}` add passes at full resolution, merged with the whole-frame pass; `merge_inside: 0.85` also drops halves of vehicles cut by a tile edge. In the app, Settings shows the tiles on a frame and previews detection with and without them. Each tile adds about one pass of work per frame.

**Offline.** Nothing needs the internet. Ultralytics runs with `YOLO_OFFLINE`, usage analytics off and its settings in `.ultralytics/`; the app loads no files from outside the PC.

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

## Signal phases

Play the prepared video and type one row per signal change into a CSV with the columns `slot,time_s,signal_head,state,phase_group` (state is green, amber or red; `time_s` is the video time).

```text
uv run pattom phases runs/test/phase_log.csv --slot test
```

Writes `signal_phases.csv` and `signal_cycles.csv` (green, amber, red and cycle length per complete cycle, measured) in `runs/<slot>/signals/`. Cycles that do not run green-amber-red are flagged, not dropped.

Originals go in `data/raw/` and are never written to. Each output gets a `.run.json` with the source SHA-256, settings and code revision.

## Folder layout

`data/raw`, `data/cfr`, `data/undistorted` (not in git), `sources/`, `calibration/`, `labels/`, `models/`, `runs/<slot>/`, `outputs/`, `sumo/`.
