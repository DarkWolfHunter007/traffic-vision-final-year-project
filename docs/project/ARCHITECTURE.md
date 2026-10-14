# Architecture: Pattom Video-to-SUMO Pipeline

**Version:** 0.3 (draft; source register added) · **Date:** 14 October 2026
**Read with:** `PRD.md` (requirements FR-xx), `PLAN.md`, `AI_RULES.md`, `tasks.json`.
**Status of this file:** a design. Nothing described here has been built yet. Items marked *proposed* are suggestions, not decisions.

---

## 1. Principles

1. **YOLO only detects.** The tracker links detections over time. Traffic numbers come from separate calculations. SUMO needs a network, demand and a signal plan; it cannot read video or raw detections.
2. **Every value carries a label:** measured, derived or estimated.
3. **Detection runs as an offline batch job.** The review screen only reads its results.
4. **Original video is never modified.** Every later stage works on copies.
5. **SUMO runs after the MCE has chosen.** SUMO output never feeds the MCE.
6. **Registered sources only (D15).** Every input value comes from the footage or the source register in `PRD.md` section 8.1. A value the register lacks is a gap to report, not a number to fill in.

## 2. System overview

```text
 Camera (iPhone 15, 0.5x, 4K, 30 fps)
        |
        v
 [A] Raw video (originals, untouched)
        |
        v
 [B] Preparation: constant frame rate -> undistort
        |
        v
 [C] Detection (YOLO; tiled far arm if needed + full-frame pass) <--------+
        |                                                                  |
        v                                                                  |
 [D] Tracking (ByteTrack or BoT-SORT; proposed)                            |
        |                                                                  |
        +--> [E] Review screen (local web app; proposed FastAPI+Uvicorn)   |
        |        flagged clips + full frames -> corrected labels ----------+
        |                                           (retrain on Colab)
        v
 [F] Calculation layer
        counts per line and movement, signal phases, queue, stopped delay, V/C
        |
        v
 [G] Congestion index + emission estimate (idle- or speed-aware)
        |
        v
 [H] Congestion-emission analysis -> problems
        |
        v
 [I] Alternatives (signal timing) -> [J] Pre-SUMO scoring -> [K] MCE -> best alternative
        |
        v
 [L] SUMO: existing case + best alternative  -> [M] Comparison -> recommendation
```

Side inputs to [F]: ground-point mapping (zebra-crossing measurements), the signal phases read from the footage, and capacity values from IRC SP 41 (1994) section 7.6 (D11).

## 3. Components

| Id | Component | Input | Output | Where it runs |
|---|---|---|---|---|
| A | Raw video store | Camera files | Originals | PC disk (backed up) |
| B | Preparation | Originals, calibration clip | Constant-frame-rate, undistorted copies | PC (CPU and RAM) |
| C | Detection | Prepared video, model weights | Boxes, classes, confidences per frame | PC GPU (4 GB, FP16), training on Colab |
| D | Tracking | Detections | Track IDs, positions over time | PC |
| E | Review screen | Flagged frames and clips | Corrected labels, review log | Local web app (proposed) |
| F | Calculation layer | Tracks, counting lines, phases, mapping, capacity | Counts, queue, stopped delay, V/C | PC |
| G | Index and emissions | F outputs, emission method | Congestion index, emission estimates | PC |
| H | Analysis | G outputs | Problem list | PC |
| I-K | Alternatives, scoring, MCE | Problems, observed flows | Documented alternatives, scores, best option | Documents and spreadsheets |
| L | SUMO | Network, demand, signal plan, selected alternative | Simulation outputs | PC |
| M | Comparison | L outputs, observed values | Comparison tables | PC |

## 4. Data contracts between stages

Field names are proposed. Keep units explicit and keep one file per slot.

### 4.1 Run metadata (one per processing run)
`slot`, `video_file`, `fps`, `width`, `height`, `model_name`, `model_version`, `tracker`, `confidence_threshold`, `tiling_settings`, `date_run`, `notes`.

### 4.2 Detections and tracks
| Field | Meaning |
|---|---|
| `frame` | Frame index in the prepared video |
| `time_s` | Time from start of the file, seconds |
| `track_id` | Persistent ID from the tracker |
| `class` | Class label |
| `confidence` | Detection confidence |
| `x1, y1, x2, y2` | Box in prepared-video pixels |
| `ground_x_m, ground_y_m` | Ground-plane position of the box's ground-contact point (bottom centre) after mapping (derived; empty if outside the calibrated zone) |

### 4.3 Counting lines and movements
`line_name`, `line_type` (stop-line count or arrival line), `approach`, `movement` (through, left, right, free-left), `endpoints_px`, `direction_rule`.
A stop-line count measures discharge, which is capped by capacity when the junction is oversaturated. Where visible, place arrival lines upstream of the longest queue and use them for demand.

### 4.4 Crossings and interval counts
Crossings: `time_s`, `line_name`, `track_id`, `class`, `direction`.
Interval counts: `slot`, `interval_start`, `interval_end` (for example 15 minutes), `approach`, `movement`, `class`, `count`, `value_type` (measured, derived).

### 4.5 Signal phases
`slot`, `time_s`, `signal_head`, `state` (green, amber, red), `phase_group`. Source: the footage (measured). The vehicle-start method is a cross-check.

### 4.6 Queue and delay
Queue: `slot`, `approach`, `cycle_start`, `queue_length_m`, `definition_version`.
Stopped delay: `slot`, `approach`, `interval`, `mean_stopped_delay_s`, `n_vehicles`, `definition_version`.

### 4.7 Capacity and V/C
`approach`, `capacity`, `capacity_unit`, `source` (book, edition, page), `source_status`, `pcu_set`, `volume`, `vc_ratio`, `value_type`.

### 4.8 Emission estimate
`slot`, `approach`, `interval`, `pollutant`, `value`, `unit`, `method_id`, `factor_source`, `factor_ref` (table or page), `source_status` (verified or reported), `vehicle_category`, `value_type` (estimated). Activity inputs must match the factor's unit basis (distance, idle time, or speed-based).

### 4.9 Alternatives and MCE
Alternative: `id`, `description`, `problem_addressed`, `change`, `expected_effect`, `safety_note`, `cost_note`, `land_note`, `feasibility_note`.
Scores: `alternative`, `criterion`, `raw_value`, `normalised_score`, `weight`, `evidence`.

### 4.10 Review screen exports (two separate files)
1. **Labels:** corrected boxes and classes for training (image plus label file per frame).
2. **Review log:** `frame`, `reason_flagged`, `reviewer_action`, `date`.

### 4.11 SUMO inputs (produced by a conversion step)
- Demand: flows per route and interval, with vehicle-type mix, from section 4.4 (arrival counts where available; stop-line counts understate demand when oversaturated).
- Signal plan: from section 4.5 for the existing case; from the selected alternative for the second case.
- Network: built separately from the observed layout (approaches, lanes, allowed turns, free lefts).
- Optional later upgrade: one simulated vehicle per tracked vehicle, using its entry time, type and route. Do not replay recorded trajectories; the simulation must decide how vehicles drive under the new signal plan.

## 5. Review screen (proposed)

- **Purpose:** show detections the system is unsure about, let the user correct labels, and export them for retraining.
- **Flags:** confidence below a threshold (a starting value to be chosen and tuned on the test clip), class change within one track, tracks that vanish suddenly, detections in hard zones (far arm, behind cables). Also include a random sample, because confidence is not accuracy.
- **Display:** a short clip around the event for context, and the full frame for labelling. Spread saved frames a few seconds apart.
- **Technology (proposed by the user):** a local web app served by FastAPI running under Uvicorn. Detection stays a separate batch job that writes files; the app reads those files.
- **Not built.** This is a design only. If the user drops the custom screen, the same flags can be exported to a labelling tool (CVAT or Label Studio).

## 6. Calibration

- **Lens:** checkerboard clip recorded with the same lens, resolution and settings (Lens Correction on). Verify by measuring one zebra stripe width at the centre and at the edge of an undistorted frame.
- **Ground mapping:** at least four known ground points per visible approach from on-site measurements. Four points fit exactly and give no error estimate, so measure extra points or distances and keep them as independent checks; report the error in metres. If the edge error stays large after undistortion, use a separate mapping per approach.
- **Which point is mapped:** the ground-contact point of each box (bottom centre). Only points on the ground plane map correctly.
- **Drift:** check each recording file for camera movement (clamp slip, wind, stabilisation) by tracking fixed landmarks.
- **Rule:** never report metres from raw pixels.

## 7. Emission module (design constraint)

A formula of vehicles x distance x a constant per-km factor cannot show a signal-timing effect, because timing changes waiting, not distance or the factor. (A speed-dependent per-km factor would respond through average speed.) The method must include idle time or speed and acceleration. The factor sources are the registered ones (D15, EMISSION_SOURCES.md). Pollutants beyond CO₂ are open (O17). The user's screenshot of the IISc ENVIS table (ARAI 2007), not independently verified, lists per-km CO₂, CH₄ and N₂O for motorcycles/scooters/mopeds, cars and jeeps, taxis, buses, light motor vehicles, trucks and lorries, and tractors, and has no three-wheeler row. It is a copy of ARAI 2007 values and is not a registered source: use it only as a CO₂ cross-check until the ARAI report itself is obtained.

Working plan (adopted by the user on 14 Oct 2026, guide pending; EMISSION_SOURCES.md): phase 1 estimates CO₂ as idle seconds x idle fuel rate x fuel carbon factor, plus constant per-km ARAI factors for moving vehicles. This captures the idle effect only and misses stop-start and acceleration effects. Phase 2 adds CO, HC, NOx and PM using idle g/min (ARAI Annexure IV) and speed or VSP-bin rates (the IVE model, scaled to ARAI Table I). Fuel type is assumed per class because video cannot tell it.

## 8. Pre-SUMO analytical estimate (design constraint)

The MCE needs congestion and emission scores before any SUMO run (D8). The method is still to be defined (T28, O13). It must:

- use the observed flows and signal plan as inputs and avoid SUMO results;
- be valid for each alternative type. A Webster-type delay formula assumes fixed-time, isolated, undersaturated operation (volume/capacity below 1). State what is used when volume/capacity reaches or exceeds 1, and how actuated or adaptive control is approximated;
- say plainly if an alternative cannot be scored, and then drop it or record the limit;
- take its formulas from the register. IRC SP 41 gives fixed-time cycle and green-split formulas (sections 7.6.3 and 7.6.4) but no delay formula, so the delay method is a gap (D15). The user adds a source before T28 closes.

## 9. SUMO interface

- SUMO has static (fixed-time), actuated (gap-based), delay-based and NEMA signal control built in. A true adaptive scheme needs external control (TraCI), which is a coding task. Settings for any dynamic alternative (for example minimum and maximum green, detector placement) must be chosen and documented.
- Run each case several times with random seeds chosen in advance, and use the same seeds in both cases. Report the average and spread.
- Use the same demand, duration and warm-up in both cases for both slots.
- Calibrate on one slot and check on the other where the data allow. Compare observed stopped delay with SUMO's waiting measure (time at or below a stopped speed), not with time loss.
- SUMO's built-in emission models are largely based on European vehicles and are not a registered source. Proposed (O18): compute the emissions of both SUMO cases by applying the registered factors to SUMO's stop time and distance per vehicle type, and report them as a relative comparison separate from the video-based estimate. The built-in model output, if shown, is a labelled cross-check.

## 10. Proposed folder layout

```text
project/
  docs/            PRD.md, ARCHITECTURE.md, PLAN.md, AI_RULES.md, HANDOFF.md, tasks.json,
                   IRC_SP41_extract.md, EMISSION_SOURCES.md
  sources/         the papers, the IRC SP 41 scan, dated register entries
  data/raw/        originals (read-only)
  data/cfr/        constant-frame-rate copies
  data/undistorted/
  calibration/     checkerboard clip, parameters, ground points
  labels/          corrected labels, train/validation split by time block
  models/          weights with run metadata
  runs/<slot>/     tracks, crossings, interval counts, phases, queue, delay
  outputs/         index, emissions, MCE, comparison tables
  sumo/            network, demand, signal plans, configs, results
```

## 11. Hardware plan

- PC: 4 GB VRAM, 16 GB RAM. Use RAM and several threads to decode and prepare frames while the GPU runs inference in FP16.
- Process at about 10-15 fps unless the test clip shows a need for more.
- Run the heavy sliced pass overnight. Train on Google Colab.
- Budget about 100-130 GB for working copies unless intermediates are deleted.

## 12. Failure points to watch

- Tracking ID switches behind buses and cables create missed or double counts. Check against manual counts.
- Variable frame rate breaks delay timing. Convert to constant frame rate first.
- Tiles and full-frame detections must be merged before tracking.
- Mixing emission sources of different years or methods in one table. Record the source per row.
- Filling a missing value from memory or from a source outside the register. Report a gap instead (D15).
- Using SUMO results to score the MCE. This breaks the agreed order.
- Taking demand from stop-line counts when the junction is oversaturated. Discharge understates arrivals.
- A ground mapping fitted with only four points and never checked. Keep independent check distances.
