# CLAUDE.md

Guidance for Claude (and any AI agent) working in this repository.

## What this project is

Final-year Civil Engineering project, Group 4 (owner: Allen MT Maliyil; guide: Dr. Reshmy D. S.):
**Optimization of Traffic Management Strategies for Vehicular Emission Reduction at Urban Intersections**, Pattom intersection, Thiruvananthapuram, Kerala.

The study tests whether a signal-timing and phasing change at Pattom can reduce delay, stops and estimated emissions. Pipeline: video, preparation, YOLO detection and tracking, review, traffic parameters, congestion index, emission estimate, problems, alternatives, MCE, SUMO (existing case vs the single MCE-selected alternative).

The code was restarted on 14 Oct 2026 from the documents below. The earlier code base is in git history only; do not copy from it unless the user asks.

## Project documents (source of truth)

| File | Use |
|---|---|
| `docs/project/AI_RULES.md` | Rules for any AI agent. Read first, every session. |
| `docs/project/PRD.md` | What and why. Section 8.1 is the source register (D15). |
| `docs/project/ARCHITECTURE.md` | How: components A-M, data contracts, calibration, emission and SUMO constraints. |
| `docs/project/PLAN.md` | Phase order, validation checks, decision gates with the guide. |
| `docs/project/tasks.json` | Task and decision ledger. Current state of work. |
| `docs/project/IRC_SP41_extract.md` | IRC SP 41 extract for capacity and signal timing. Quote with page. |
| `docs/project/EMISSION_SOURCES.md` | Emission part of the source register. |

The rules in AI_RULES.md apply at all times:

@docs/project/AI_RULES.md

Not yet in the repo: `HANDOFF.md`, `handoff_addendum_2026-10-14.md` and `report_ppt_consistency_fixes.md`, which AI_RULES.md and PRD.md refer to. If a task depends on them, ask the user for them instead of guessing their content.

## Start of every session

1. Read `docs/project/AI_RULES.md` (imported above).
2. Read `PRD.md`, `ARCHITECTURE.md`, `PLAN.md` as needed for the task.
3. Check `docs/project/tasks.json` for the current task (follow its `_START_HERE`).
4. Check the "Built so far" table in `README.md` for what code exists.
5. Say in one line what you found and what you will do next.

## Code conventions

- Package: `src/pattom/`, one module per architecture component. Tests in `tests/`.
- **Source register in code.** Every constant (saturation flow, PCU factors, emission and fuel factors) is read from `sources/register.yaml` through `pattom.register`. Never hard-code such a number. A missing value raises `SourceGap`; report it to the user, do not fill it. Add a register entry only with the user's approval and the date.
- **Labelled values.** Results are `pattom.values.Labelled` with a value type (measured, derived, estimated) and sources. Reported (unchecked) sources carry "source not checked".
- **Open decisions stay open in code.** Where the ledger has an open decision (e.g. O3 PCU table, O6 stopped-speed threshold, O4 congestion index), take it as a required argument; never pick a default.
- **Originals are read-only.** Nothing writes to `data/raw/`. Every processing step writes a new file plus a `.run.json` (run metadata, ARCHITECTURE 4.1) with the source SHA-256, settings and code revision.
- Video, weights and run outputs are not committed.

## Non-negotiables (summary; AI_RULES.md is authoritative)

- Never invent counts, emission factors, capacity values, weights, scores, timings or SUMO results.
- YOLO only detects. It does not calculate volume, delay, V/C, congestion index or emissions.
- Never report metres from raw pixels. Never use SUMO output in the MCE.
- When sources disagree, name the conflict and ask the user. Do not choose silently.

## Development

Python 3.12, [uv](https://docs.astral.sh/uv/), ffmpeg on PATH:

```text
uv sync --python 3.12 --group dev
uv run pytest
uv run pattom --help
```
