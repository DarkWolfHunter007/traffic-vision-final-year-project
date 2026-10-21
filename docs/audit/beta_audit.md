# Pattom editor: alpha → beta audit (20 Oct 2026)

Scope: the node editor and every stage it runs (cfr → detect → track → ground/review → count → delay/queue → emissions → indicators → congestion → problems → alternatives → pre-SUMO → MCE → SUMO → comparison), the Calibrate page, and the server.

How it was checked:
- read the code;
- ran the full chain on IMG_1480 and the TEST flow;
- ran 90 automated tests;
- checked results by hand against the CSV files.

Status: **✓ fixed** = fixed and pushed (commit cd01627), checked by tests and a full run. **YOU** = needs your decision or a site value.

## Critical: wrong or missing numbers

| # | Problem | Where | Fix | Status |
|---|---|---|---|---|
| C1 | The last time interval is treated as full length. A 1-min clip counted in 15-min intervals is turned into PCU/h as if it lasted 15 min, so volume and V/C come out about 15× too low. The 2.6 s test gave 12 PCU/h. This also affects the final part-interval of any long video. | `counting.interval_counts`, `indicators` | End each interval at the video's real end. Mark short intervals as partial. | ✓ fixed |
| C2 | Queue length is never computed in the editor. The preset's delay_queue node has no signal log, so `queue.csv` is never written. Max queue is therefore always empty, and so is the **congestion index**. | editor preset | Give delay_queue `configs/signal_log.csv` in the preset. | ✓ fixed |
| C3 | Signal head names don't match. Both approach areas use head `north`, but `signal_log.csv` uses `N`. Once C2 is fixed, delay_queue will stop with a clear error until they match. | `configs/definitions.yaml` | Use the same head names in both files. | YOU |
| C4 | The ground mapping is about 10× off. It was fitted on one 2 m × 0.5 m stripe, and the 1 m tape check is off by 0.55 m. All metres are wrong: queue, stop points, speeds and the stopped/moving test. | `calibration/ground.yaml` | Redo it with 4+ points spread across the junction and a check far away. | YOU |
| C5 | Indicators silently drops any approach that lacks a signal head or width. A missing approach vanishes from V/C and the index with no warning. | `indicators.load_config` | Write the skipped approaches into the run notes so the log shows them. | ✓ fixed |
| C6 | Stale CO₂ is possible. The emissions cache doesn't watch `vehicle_delay.csv`, which is the file it actually reads. Indicators doesn't watch `queue.csv` either. | `engine.compute_cache_key` | Hash the files each stage reads besides its input. | ✓ fixed |
| C7 | Stopped delay is cut off at the clip end. A vehicle still waiting when the clip ends gets only the part seen. | `delay.vehicle_delays` | Report how many vehicles are cut off. Only matters at the clip end. | note |

## Pipeline engine

| # | Problem | Fix | Status |
|---|---|---|---|
| E1 | Every git commit or `git pull` invalidates **all** caches, YOLO included. The cache key uses the git revision, and an untracked file marks the tree "dirty" for good. On a 1-hour video, every update means hours of re-detection. | Key each stage on its own code files, not the whole repository. | ✓ fixed |
| E2 | The 11 GB video's SHA-256 is recomputed on every run, at each node that reads it. That is minutes of waiting before anything starts. | Remember the hash per file (size + modified time). | ✓ fixed |
| E3 | Ground mapping overwrites `tracks.csv` in place. This breaks the rule that every step writes a new file, and it makes `track` re-run every time. | Write `tracks_ground.csv` instead. | ✓ fixed |
| E4 | An invalid graph leaves the server stuck in "running". You can't run again until a restart. | Validate before marking it running. | ✓ fixed |
| E5 | If the run crashes, the page never learns, because the "error" event is ignored. The Run button stays disabled. | Handle the event. | ✓ fixed |
| E6 | **Run Selected** leaves every other node showing "queued" forever. | Only list the nodes that actually run. | ✓ fixed |
| E7 | When a slot has several videos, the preview may show the wrong video's results. It picks the first folder it finds. | Prefer the outputs of the current run. | note |

## Editor and viewer at full scale

| # | Problem | Fix | Status |
|---|---|---|---|
| U1 | The track, ground and count previews send every track point to the browser at once. For 1 hour that is millions of rows, and the page freezes. | Send points for the part of the video being played. | ✓ fixed |
| U2 | Review has no limit on flags. 1 hour could produce thousands of crops and a very slow review step. | Cap each reason (default 60), and say how many were left out. | ✓ fixed |
| U3 | Graph edits are lost on refresh. The preset is hard-wired to IMG_1480 (`raw-video/`, slot `test`). | Save the graph in the browser and restore it. Keep the preset as a reset. | ✓ fixed |
| U4 | The preset turns on `allow_draft` for delay_queue, which runs it even when the O6 definitions are not approved. | Default it off (your definitions are approved now). | YOU |

## Security (your browser)

| # | Problem | Fix | Status |
|---|---|---|---|
| S1 | Any web page open in the same browser could call the editor in the background. It could start runs, write any file in the project via `/config` (code included), read footage frames, or open SUMO. | Accept requests only from the editor's own page. Let `/config` write only `configs/` and `calibration/` YAML. | ✓ fixed |

## Gaps against the plan (PRD and PLAN)

| # | Gap | Status |
|---|---|---|
| G1 | Signal timings are typed by hand into `signal_log.csv`. A small "press a key at each light change" tool while the video plays would make this quick. | proposal |
| G2 | Automated counts are not checked against manual counts (FR, T17). There is no page for that yet. | proposal |
| G3 | There is no screen to define movements (entry line → exit line), and SUMO needs them for demand. | proposal |
| G4 | Lens calibration and undistortion, and the camera-drift check, are not in the editor. | proposal |
| G5 | Class decisions are still open. The auto-rickshaw emission row is petrol 2-stroke (Kerala autos are mostly diesel or CNG). Tempo-traveller needs diesel fuel. For LCV, the PCU is 1.5 in Table 3.1 but it is mapped to truck (3.0). | YOU |
| G6 | The UVH-26 model is not yet checked against your manual counts. | YOU (needs the 1-min clip) |
