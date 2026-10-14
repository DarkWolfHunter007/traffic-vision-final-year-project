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
| F Capacity and V/C (FR-13) | `pattom.capacity` | Done: SP 41 section 7.6; PCU table must be named (O3) |
| C-E, rest of F, G-M | | Not started |

## Setup

Python 3.12, [uv](https://docs.astral.sh/uv/) and ffmpeg on PATH.

```text
uv sync --python 3.12 --group dev
uv run pytest
```

## Preparation commands

```text
uv run pattom probe data/raw/IMG_1483.MOV
uv run pattom cfr data/raw/IMG_1483.MOV data/cfr/test_01.mp4 --slot test
uv run pattom calibrate-lens data/raw/checkerboard.MOV --cols 9 --rows 6 --square-mm 25
uv run pattom undistort data/cfr/test_01.mp4 data/undistorted/test_01.mp4 --slot test
```

Originals go in `data/raw/` and are never written to. Each output gets a `.run.json` with the source SHA-256, settings and code revision.

## Folder layout

`data/raw`, `data/cfr`, `data/undistorted` (not in git), `sources/`, `calibration/`, `labels/`, `models/`, `runs/<slot>/`, `outputs/`, `sumo/`.
