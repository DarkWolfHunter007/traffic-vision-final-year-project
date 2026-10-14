# Plan: Pattom Signal-Timing Study

**Version:** 0.3 (draft; source register added) · **Date:** 14 October 2026
**Read with:** `PRD.md` (section 8.1 is the source register), `ARCHITECTURE.md`, `AI_RULES.md`, `tasks.json` (task ids T01-T50 are referenced below), `IRC_SP41_extract.md`, `EMISSION_SOURCES.md`.
**Dates:** not set. Submission and review deadlines are open decision O11. Fill the schedule once they are known.

---

## 1. How the work is organised

Eight phases with gates. A gate is a check that must pass before the next phase relies on its output. The task ledger (`tasks.json`) holds status and evidence; this file explains the order and the reasons.

```text
P0 Planning and approvals
  -> P1 Site and data capture
  -> P2 Preprocessing
  -> P3 YOLO (detect, track, review, validate)
  -> P4 Traffic parameters
  -> P5 Emissions and problems
  -> P6 Alternatives and MCE
  -> P7 SUMO and comparison
  -> P8 Writing
```

Some tasks run in parallel (for example the emission-source research alongside recording).

## 2. Phases

### P0 Planning and approvals
- **Goal:** fixed documents and the guide's confirmation of D1-D4, D8, D9, D13 and D15, or a dated "decided, guide pending" from the user.
- **Tasks:** T38 (guide confirmation), T41-T43 (documents and review), T44 (keep handoff and ledger current).
- **Exit gate:** the user approves the five documents; guide responses are recorded with dates.

### P1 Site and data capture
- **Goal:** a trustworthy recording setup and two usable slots.
- **Tasks:** T01 (angle, done), T02 (test clip), T46 (operational definitions), T03 (checkerboard clip), T04 (ground points), T05 (off-peak slot), T06 (peak slot, evening outflow main), T07 (optional pollution-board context).
- **Order:** test clip first, then the written definitions (queue, stopped-speed threshold, counting and arrival lines, capacity inputs). Do not record the full slots until the test clip shows the setup works and the definitions are approved, because the definitions decide what the camera must cover.
- **Exit gate:** the test clip shows the approaches as visible (the west is partly hidden), a full signal cycle on each visible approach, the definitions are approved, and the checkerboard clip has at least 20 usable frames.
- **Field safety:** clamp and tether the phone at the drop edge; tape down the power cable.

### P2 Preprocessing
- **Tasks:** T08 (back up and constant frame rate), T09 (lens calibration and check), T10 (undistort), T48 (pixel-to-ground mapping with an independent check and a drift check). T08 and T10 are repeated on every slot recording.
- **Exit gate:** a zebra stripe measured at the centre and at the edge of an undistorted frame agrees closely, or a per-approach mapping is chosen instead; the mapping error in metres is stated.

### P3 YOLO
- **Tasks:** T11 (test pretrained model on the test clip), T12 (classes and labelling rules), T13 (labelled frames), T14 (fine-tune on Colab), T45 (review screen build, only when the user says go), T15 (review loop, uses the review screen), T16 (run both slots), T17 (validate against manual counts).
- **Decisions here:** the findings of T11 are put to the user for the final YOLO version and tracker (O7), tiling need, free lefts (O9) and west handling (O10).
- **Exit gate:** counting error is known for each approach and class, including the west approach.

### P4 Traffic parameters
- **Tasks:** T18 (counting and arrival lines, movements), T19 (signal phases from footage), T47 (propose the congestion-index formula), T20 (queue), T21 (stopped delay), T22 (capacity and V/C from IRC SP 41 section 7.6), T23 (compute the congestion index).
- **Decisions here:** queue definition and stopped-speed threshold (O6, written in T46) and the congestion-index formula (O4, proposed in T47).
- **Exit gate:** every definition is written down before values are computed, and the index formula is approved by the guide.

### P5 Emissions and problems
- **Tasks:** T24 (emission method and source), T49 (the user obtains the papers; runs alongside), T50 (check "reported" values against the papers), T25 (baseline emissions), T26 (congestion-emission analysis).
- **Source rule:** values come from the source register (PRD section 8.1). Phase 1 is CO₂ from idle time; phase 2 adds CO, HC, NOx and PM when their sources are registered (O17). Until T50, reported values are labelled "source not checked".
- **Constraint:** the method must respond to signal timing (idle time or speed and acceleration).
- **Exit gate:** emission method, units and assumptions documented; problems taken from the data.

### P6 Alternatives and MCE
- **Tasks:** T27 (alternatives), T28 (pre-SUMO scoring method), T29 (scale, weights, sensitivity), T30 (score and select).
- **Order rule:** alternatives are developed from the problems found, before the MCE. The scoring method and weights are written and approved (O13) before scores are assigned. Keep at least two alternatives besides the existing plan.
- **Method check:** the pre-SUMO scoring method must be valid for each alternative type (see ARCHITECTURE.md section 8).
- **Exit gate:** one alternative selected, a written reason, and the weight-sensitivity result.

### P7 SUMO and comparison
- **Tasks:** T31 (network), T32 (demand), T33 (calibrate), T34 (run existing), T35 (run selected alternative), T36 (emission model and limits), T37 (compare).
- **Exit gate:** the existing model matches observed flow, queue and delay within a tolerance agreed with the guide (O14), the comparison uses matched demand, and both cases use the same pre-chosen random seeds.

### P8 Writing
- **Tasks:** T39 (apply the report and PPT fixes), T40 (results and recommendation).
- **Exit gate:** every number in the report traces to a task output.

## 3. Critical path

T02 test clip -> T46 definitions -> T05/T06 recordings -> T08-T10, T48 preparation and mapping -> T11 detection test -> T13-T15 labelling, training, review -> T16 runs -> T17 validation -> T18-T22 parameters -> T23-T26 index, emissions and problems -> T27-T30 alternatives and MCE -> T31-T36 SUMO build -> T34-T35 runs -> T37 comparison -> T40 writing.

Items that can run alongside: T24 and T49 emission sources, T22 capacity (SP 41 section 7.6), T38 guide approvals, T41-T43 documents.

## 4. Validation checks by phase

| Phase | Check | How |
|---|---|---|
| P2 | Lens correction works | Zebra width at centre vs edge |
| P3 | Counts are right | Manual counting of sampled playback clips per approach and class |
| P3 | Model is not tested on its training data | Validation frames from a different time block |
| P4 | Signal phases are right | Footage read-out, cross-checked with vehicle-start behaviour |
| P4 | Queue in metres is valid | Ground-point mapping; far-arm accuracy limit stated |
| P5 | Emission units consistent | Check factor unit basis against activity data |
| P6 | Ranking is stable | Vary weights and report the change |
| P7 | SUMO baseline is credible | Compare with observed flow, queue, delay |
| P7 | Result is not noise | Several random seeds chosen in advance and the same in both cases; report average and spread |

## 5. Decision gates with the guide

Record the date and answer for each.

1. Scope: signal-timing redesign (the user's narrowing of HANDOFF.md 3.2 and 10); SUMO for existing plus the single best alternative (D1, D2). Also the order of work (D4), which is not on record as guide-confirmed.
2. MCE criteria and the note that land requirement is equal for all options (D3).
3. Pre-SUMO scoring method (D8).
4. Congestion-index formula (D9, O4).
5. Emission working plan (CO₂ from idle time first) and the source register (D13, D15); the phase 2 pollutants (O17).
6. How the west approach is reported (O10).
7. SUMO calibration tolerance (O14).
8. How SUMO-case emissions are computed (O18).

## 6. Resources and constraints

- One person on site and for recording. No simultaneous manual counts.
- PC with 4 GB VRAM and 16 GB RAM; Colab for training.
- Phone storage about 40 GB free before recording; PC about 100-130 GB for working copies.
- Recording per slot: about 1.5 hours, about 16 GB.

## 7. Recording-day checklist

1. Clear about 40 GB on the phone; charge it; power bank and taped cable.
2. Clamp and tether the phone; check the frame covers all approaches.
3. Camera settings: 0.5x, 4K, 30 fps, HEVC, Lens Correction on, Action Mode off, AE/AF locked, Do Not Disturb, shade the phone.
4. Record in 10-15 minute files. Check the phone at each file change.
5. Note start time, weather and unusual events for each slot.
6. Copy the originals off the phone and back them up before processing.

## 8. Risks and responses

| Risk | Response |
|---|---|
| Test clip shows poor far-arm detection | Tile that region; fine-tune on crops at the same scale |
| West approach cannot be tracked | Report flow where visible; derive or exclude queue and delay; label clearly |
| Registered sources do not give idle or speed-based CO, HC, NOx and PM | First results cover CO₂; add the others when the papers are obtained (T49, T50); state gaps |
| A needed value is not in the source register (for example a delay formula) | Report a gap; propose sources; the user decides; never fill from memory |
| SUMO baseline does not match observations | Report the gap; adjust demand and driver parameters; do not hide differences |
| Guide does not respond | Proceed under recorded decisions; flag items awaiting approval |
| Deadline pressure | Cut scope in this order: optional pollution-board data, then alternatives beyond two, never validation |

## 9. Schedule

To be filled after O11 is answered. Build it backwards from the submission date, keeping the critical path above.
