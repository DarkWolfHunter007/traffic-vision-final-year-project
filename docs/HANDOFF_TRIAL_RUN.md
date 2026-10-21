# Handoff: finish the 10-minute trial run (for any AI agent, no prior context needed)

**Written:** 21 Oct 2026, by Claude, for Allen's project. **Repo:** `D:\Work\Personal\traffic-vision-final-year-project` (GitHub `DarkWolfHunter007/traffic-vision-final-year-project`, branch `claude/project-thread-ck0mhd`). **PC:** Windows 11, NVIDIA GTX 1650 (4 GB). **User:** Allen, a civil engineering student, new to git and programming. Use plain words and short answers.

## 0. Read first (project rules, mandatory)

1. `CLAUDE.md` and `docs/project/AI_RULES.md`.
2. The most important rules:
   - **Never invent** counts, emission factors, capacities, weights, timings, scores or SUMO results. Every number is measured from the footage, comes from a cited source, or is typed by Allen.
   - **YOLO only detects.** Volume, delay, V/C, congestion index and emissions are calculated by Python from the tracks.
   - **Never edit originals** in `raw-video/`. Outputs go to new files.
   - If something is missing or two sources disagree, **stop and ask Allen**. Do not pick a value.
   - `TEST` values (folder `configs/flowtest/`) are for software checks only and never go into real results.

## 1. What the project does (one paragraph)

Video of the Pattom junction → steady frame rate copy (**cfr**) → YOLO finds vehicles (**detect**, model UVH-26) → **track** → **ground** (pixels → metres) → **count** (lines) → **delay_queue** → **emissions** (idle CO2) → **indicators** (V/C) → **congestion** index → **problems** → **alternatives** → **pre_sumo** scoring → **mce** picks one plan → **sumo** simulates the existing plan vs the chosen plan → **comparison**. A **review** node shows flagged vehicles with crops. Everything runs from a visual editor on `http://127.0.0.1:8765/`.

## 2. State right now (21 Oct 2026)

| Item | State |
|---|---|
| Code | All 16 nodes + review exist and are pushed. 98 tests pass (`uv run --no-sync pytest -q`). A beta audit (`docs/audit/beta_audit.md`) fixed 15 issues. |
| Test clip | `raw-video/trial_10min.mov` = 10:00–20:00 of `raw-video/FULL-Video.mov` (lossless copy, 600 s, 4K HEVC, 1.93 GB). **Never touch `FULL-Video.mov`** (11.99 GB, kept for the final judgement after fine-tuning). |
| Trial run | **Started 21 Oct ~14:30 local.** Run target: `review` (runs cfr → detect → track → review only; ground, count and later nodes are not part of this first run). Check `curl localhost:8765/status`. cfr writes `data/cfr/trial_10min.mp4`; detect writes `runs/trial/trial_10min/detections.csv`. If the editor is not running, the run was lost; just run again (finished nodes are cached). |
| Model | `models/UVH-26-MV-YOLOv11-S.pt` (IISc UVH-26, Apache-2.0, sha256 `12dbeb8f6fa207d19446fa652fc4313359fbec267027c8c01641004dcf1d0150`), config `configs/detection_uvh26.yaml`. Class map is Allen's (Three-wheeler→auto_rickshaw, Tempo-traveller→car, LCV→truck, etc.). |
| Disk | D: had ~16 GB free on 21 Oct. cfr output ~2 GB. Check before the 1-hour run. |

## 3. Start the editor (and the GPU warning)

```
cd D:\Work\Personal\traffic-vision-final-year-project
uv run --no-sync pattom editor
```
Open http://127.0.0.1:8765/ . A second `pattom editor` reopens the running one (single instance).

**GPU/PyTorch trap:** a plain `uv run` or `uv sync` reinstalls the **CPU-only** PyTorch and detection then takes hours. Always use `--no-sync`. Check:
```
.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"   (must print True)
```
Restore if False:
```
uv pip install --python .venv\Scripts\python.exe --no-deps --reinstall .uv-cache\manual-wheels\torch-2.14.1+cu126-cp312-cp312-win_amd64.whl .uv-cache\manual-wheels\torchvision-0.29.1+cu126-cp312-cp312-win_amd64.whl
```
In `configs/detection_uvh26.yaml` `device: null` lets Ultralytics choose the GPU. Expected: the editor's **Live view** panel shows frames with boxes during detect.

## 4. Node settings for the trial (set in the editor; slot name `trial`)

| Node | Settings |
|---|---|
| cfr | video `raw-video/trial_10min.mov`, out `data/cfr/trial_10min.mp4`, fps 30, slot `trial` |
| detect | slot `trial`, config `configs/detection_uvh26.yaml` |
| track | config `configs/tracker.yaml` |
| ground | config `calibration/ground.yaml` (see §5, open) |
| review | defaults (confidence 0.4, max 60 flags per reason) |
| count | lines `configs/lines.yaml`, interval_s 900 (the 10-min clip makes one partial interval ending at 600 s, which is correct) |
| delay_queue | definitions `configs/definitions.yaml`, signal_log `configs/signal_log.csv`, allow_draft true |
| emissions | `configs/emissions.yaml` |
| indicators | `configs/indicators.yaml`, signal_log `configs/signal_log.csv` |
| congestion | formula `configs/congestion.yaml` |
| problems, alternatives, pre_sumo, mce | `configs/decision.yaml` (empty: stays Locked, see §6) |
| sumo_inputs, sumo_run, comparison | `configs/sumo.yaml` (empty: stays Locked), lines `configs/lines.yaml` |

The editor's **Load Demo Preset** loads all nodes pointing at IMG_1480 / slot `test`. After loading it, change cfr and detect as above. Your graph is remembered in the browser. Use **Run** for the whole chain or **Run Selected** for one node plus the nodes it needs.

## 4a. How to check each step

After a run read the **Execution Logs** tab: each step lists its inputs (with row counts), settings, gate, outputs and notes, and ends with a checklist (✓ done, 🔒 locked with the reason, – skipped, ✗ failed with the real error). Open **Preview** on a node to see the result; the ⬇ Download list has the CSV files.

| Node | Good looks like |
|---|---|
| cfr | `data/cfr/trial_10min.mp4` is ~600 s (`ffprobe`), 30 fps |
| detect | `runs/trial/trial_10min/detections.csv` has many thousand rows. `detections.run.json` lists `ignored_label_counts` (only bicycle/Others expected). |
| track | `tracks.csv`, `track_summary.csv`. Preview shows boxes and IDs on the video. Few class changes. |
| review | Preview gallery: crops with boxes. Autos should be `auto_rickshaw`. Report where the model is wrong. |
| count | `interval_counts.csv`, `crossings.csv`. Needs movements in `lines.yaml` to be useful for SUMO (§5). |
| delay_queue | `stopped_delay.csv`, `queue.csv`. Fails with a clear message until §5 is done. |
| indicators/congestion | `approach_indicators.csv`, `congestion_index.csv`; the index is empty if queue rows are missing (the run notes say why). |

## 5. Open items that block the real numbers (only Allen can provide these; ask him)

1. **Signal head names.** `configs/definitions.yaml` approach areas use `signal_head: north`, but `configs/signal_log.csv` uses `N` (and is still the **template**: 50 s green, 120 s cycle). Both must use the same names. Make the real log with the editor's **Signal Timings** button (page `/signals`): play the trial clip, press 1–4 to pick the head, G/A/R at each light change, Save. Needs at least 3 complete cycles per head.
2. **Ground calibration.** `calibration/ground.yaml` was fitted on one 2 m × 0.5 m zebra stripe; its tape check is off by 0.55 m on 1 m, so every metre value (queue, stop points, widths) is about 10× unreliable. Redo it on the **Calibrate** page (`/calibrate`, button in the editor): 4+ points spread across the junction (use "Single points spread across the junction"), typed real metres, one far check, a valid-area polygon. Save. Then redraw **Approach areas** (stop points are recomputed or cleared when ground is re-saved) and **Road widths**. Allen should supply the metre values (tape or known marking sizes). Never guess them.
3. **Counting lines and movements.** Lines exist (`configs/lines.yaml`, drawn on IMG_1480, may need redrawing for this camera view). Add `movements` (entry line → exit line) by hand; see `docs/guides/sumo_setup.md`. A movement is assigned only when a track crosses the entry line and later the exit line.
4. **Stopped-speed threshold (O6)** is currently typed as 5 km/h by Allen. It should be checked against vehicles known to be standing after the ground fix.
5. **Class/emission decisions:** auto-rickshaw idle fuel row is petrol 2-stroke (probably wrong for Kerala; ask Allen), Tempo-traveller maps to car (needs diesel fuel row), LCV maps to truck (PCU 3.0, Table 3.1 says 1.5). These are Allen's decisions, not yours.

## 6. Steps H to M (problems → SUMO): need Allen's decisions, do not invent

`configs/decision.yaml` (rules, alternatives, MCE weights) and `configs/sumo.yaml` (lanes, speeds, vehicle sizes, seeds) are empty on purpose, so those 7 nodes stay Locked. Format: `docs/guides/sumo_setup.md` and `*.example.yaml`. To only test the **flow**, use the files in `configs/flowtest/` (local only, not on GitHub; all values are TEST and labelled) into a separate slot; results are then banner-marked TEST in the comparison view. **Open in SUMO** button (comparison preview) opens two SUMO-GUI windows if SUMO is installed (`SUMO_HOME=C:\Program Files (x86)\Eclipse\Sumo`).

## 7. Manual count check (needed for the final report)

Count vehicles by hand for 1–2 minutes of the trial clip into `configs/manual_counts.example.csv`'s format, then:
```
uv run --no-sync pattom count-check my_manual_counts.csv runs/trial/trial_10min/interval_counts.csv
```
It prints the error per line and class. Report it; do not tune anything to hide errors.

## 8. Pitfalls (learned the hard way)

- `uv run` without `--no-sync` breaks the GPU (see §3).
- Do not commit `configs/*.yaml` that are local (gitignored, local to Allen's PC: `configs/` detection, tracker, lines, definitions, emissions, indicators, congestion, decision, sumo, signal_log.csv, `configs/flowtest/`, and `calibration/ground.yaml`), `data/`, `runs/`, `models/*.pt` or video.
- Windows paths: use forward slashes or quote paths. The editor page only accepts requests from itself (security); use it, not `curl` from another site.
- Cache: finished nodes are reused until their own code, inputs or settings change. To force a re-run use `force` on `/run` or change a setting. After editing `ground.yaml`, ground/count/delay/etc. re-run automatically.
- `ground` writes `tracks_ground.csv` (it no longer overwrites `tracks.csv`).
- Showing `[sys] Execution ... failed` with only an exit code used to hide the real error; now the last log line is shown.
- Browser pane or old tabs can show an old page: press Ctrl+F5.
- Disk space on D: is tight (see §2).
- Never delete `FULL-Video.mov`, never write into `raw-video/` except new clips named `trial_*.mov`.

## 9. Git routine

```
git pull
(make changes, run tests: uv run --no-sync pytest -q)
git add <files>
git commit -m "what and why"
git push
```
Branch `claude/project-thread-ck0mhd`. Do not force-push. If a pull conflicts, stop and ask Allen. The project uses a shared GitHub repo; cloud Claude threads push to the same branch.

## 10. What to report back to Allen

1. Which nodes ran (use the end-of-run checklist) and how long each took.
2. Detection summary: detections, tracks by class, flags by reason (from the review notes), whether autos are found.
3. Everything still Locked or failed, with the exact message, and which item of §5/§6 unblocks it.
4. Any number that looks wrong (e.g. all queue lengths empty, V/C very low) and the likely cause. Do not "fix" it by changing configs without Allen's approval.

## Related files

- `docs/guides/trial_run_checklist.md` (step order and alignment tips)
- `docs/guides/sumo_setup.md` (how to fill `decision.yaml` and `sumo.yaml`)
- `docs/audit/beta_audit.md` (what was fixed and what is open)
- `docs/project/*` (PRD, ARCHITECTURE, PLAN, tasks.json: the source of truth for decisions)
