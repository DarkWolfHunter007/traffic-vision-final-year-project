# CLAUDE.md

Guidance for Claude (and any AI agent) working in this repository.

## What this project is

Final-year Civil Engineering project, Group 4 (owner: Allen MT Maliyil; guide: Dr. Reshmy D. S.):
**Optimization of Traffic Management Strategies for Vehicular Emission Reduction at Urban Intersections**, Pattom intersection, Thiruvananthapuram, Kerala.

The study tests whether a signal-timing and phasing change at Pattom can reduce delay, stops and estimated emissions. Pipeline: video, YOLO detection and tracking, traffic parameters, congestion index, emission estimate, problems, alternatives, MCE, SUMO (existing case vs the single MCE-selected alternative).

This repository (`traffic-vision`) is the video-processing subsystem: ingestion, detection, tracking, counting, calibration, speed, queues, review, export. Emissions, the congestion index, MCE and SUMO are part of the wider study described in `docs/project/` but are not built here unless the user says so.

## Project documents (source of truth)

All planning documents live in `docs/project/`:

| File | Use |
|---|---|
| `docs/project/AI_RULES.md` | Rules for any AI agent. Read first, every session. |
| `docs/project/PRD.md` | What and why. Section 8.1 is the source register (D15). |
| `docs/project/ARCHITECTURE.md` | How: pipeline, data contracts, calibration, emission and SUMO design constraints. |
| `docs/project/PLAN.md` | Phase order, validation checks, decision gates with the guide. |
| `docs/project/tasks.json` | Task and decision ledger. Current state of work. |
| `docs/project/IRC_SP41_extract.md` | IRC SP 41 extract for capacity and signal timing. Quote with page. |
| `docs/project/EMISSION_SOURCES.md` | Emission part of the source register. |

Repository-specific contracts:

- `backend/database/schema.sql` and `docs/data_dictionary.md`: canonical field names and provenance.
- `docs/methodology_scope_charter.md`, `docs/design_handover.md`, `docs/handoffs/`: methodology and phase handoffs.
- `prompts/`: phase implementation prompts. Implement only the phase you are given.

The rules in AI_RULES.md apply at all times:

@docs/project/AI_RULES.md

## Start of every session

1. Read `docs/project/AI_RULES.md` (imported above).
2. Read `docs/project/PRD.md`, `ARCHITECTURE.md`, `PLAN.md` as needed for the task.
3. Check `docs/project/tasks.json` for the current task (follow its `_START_HERE`).
4. For code work, read the matching `prompts/phase_XX_*.md` and the latest `docs/handoffs/` entry.
5. Say in one line what you found and what you will do next.

Not yet in the repo: `HANDOFF.md`, `handoff_addendum_2026-10-14.md` and `report_ppt_consistency_fixes.md`, which AI_RULES.md and PRD.md refer to. If a task depends on them, ask the user for them instead of guessing their content.

## Non-negotiables (summary; AI_RULES.md is authoritative)

- Never invent counts, emission factors, capacity values, weights, scores, timings or SUMO results. Every value comes from the footage or the source register (PRD 8.1), or is reported as a gap.
- Label every value as measured, derived or estimated.
- YOLO only detects. It does not calculate volume, delay, V/C, congestion index or emissions.
- Never edit original videos. Never report metres from raw pixels.
- `timestamp_s` is authoritative; `frame_number / FPS` is not, for variable-frame-rate footage.
- Every derived table carries `run_id`; every source video has a SHA-256.
- All paths resolve inside the repository root. Do not create folders outside it.
- When sources disagree, name the conflict and ask the user. Do not choose silently.

## Development

Python 3.12 with [uv](https://docs.astral.sh/uv/), from the repository root:

```text
uv sync --python 3.12 --group dev
uv run pytest
uv run traffic-vision bootstrap-db
uv run uvicorn backend.app:app
```
