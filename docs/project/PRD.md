# PRD: Signal-Timing Redesign for Low Vehicular Emissions at Pattom Intersection

**Version:** 0.4 (draft for user and guide review; source register added)
**Date:** 14 October 2026
**Project title:** Optimization of Traffic Management Strategies for Vehicular Emission Reduction at Urban Intersections
**Location:** Pattom intersection, Thiruvananthapuram, Kerala, India
**Group 4:** Allen MT Maliyil (owner), Ayman Ali Noufell, Niramayi S V, Nandana G S
**Guide:** Dr. Reshmy D. S.
**Supersedes:** the earlier report draft, which conflicts with the PPT and the handoff. See `report_ppt_consistency_fixes.md`.
**Related files:** `HANDOFF.md`, `handoff_addendum_2026-10-14.md`, `ARCHITECTURE.md`, `PLAN.md`, `AI_RULES.md`, `tasks.json`, `IRC_SP41_extract.md`, `EMISSION_SOURCES.md`.

Status labels used below: **Decided** (confirmed by the user in chat), **Pending guide** (needs the guide's confirmation), **Open** (not yet decided). Nothing here is a measured result.

---

## 1. Purpose

Test whether changing the signal timing and phasing at Pattom, from the current fixed timing to a re-optimised or dynamic (traffic-responsive) timing, can reduce delay, stops and the estimated vehicular emissions, using video-derived traffic data, a multi-criteria evaluation (MCE) to pick the best alternative, and a SUMO simulation to compare the existing case with that alternative.

## 2. Background

Vehicles at intersections stop, idle, accelerate and decelerate. These conditions increase fuel use and emissions (CO, CO₂, NOx, PM). Pattom currently runs fixed signal timing. Whether the junction is congested, and how badly, must come from the data. It is not assumed.

## 3. Hypothesis (not a result)

Dynamic or re-optimised signal timing may reduce delay and stop-start movement at Pattom and therefore reduce estimated emissions. Dynamic control can also fail to help, or raise emissions in some conditions. The report must state what the data show, not what is hoped.

## 4. Objectives

1. Assess existing conditions at Pattom: traffic volume, queue length, stopped delay, V/C ratio and a congestion index.
2. Estimate baseline emissions from video-derived vehicle activity using a documented emission method.
3. Identify the main operational problems from the congestion and emission analysis.
4. Develop several signal-timing and phasing alternatives after the problems are identified (candidates: re-optimised fixed plan per time of day, vehicle-actuated, adaptive; at least two besides the existing plan).
5. Evaluate the alternatives with an MCE and select the best one.
6. Simulate the existing case and the selected alternative in SUMO under comparable demand and compare them.
7. Recommend a low-emission signal-management concept and state its limitations.

## 5. Scope

### In scope
- Pattom intersection only; fixed camera video in two slots (off-peak and peak).
- YOLO-based detection with tracking; manual validation of counts.
- Traffic parameters, congestion index, emission estimation, congestion-emission analysis.
- Signal-timing alternatives, MCE, SUMO comparison of existing vs selected alternative.

### Out of scope (non-goals)
- Detailed geometric design, widening, new lanes, reconstruction. Existing geometry is recorded only as needed for capacity and the SUMO network.
- Lane-use, turning-movement, pedestrian-phase or parking management as alternatives. The user narrowed the scope to signal timing on 14 October 2026 (D2). If the data show problems that timing cannot address, they are reported as findings and future work.
- Simulating every alternative in SUMO (only the MCE winner is simulated).
- Live deployment on a real signal controller, or using YOLO as a live detector to drive signals (possible future work).
- Training a machine-learning congestion-prediction model.
- Identifying fuel type, model year or emission standard from video.
- Treating pollution-board readings as calibration of the video or of the emission estimates (they may be used as context only).
- Using input values from outside the source register (section 8.1, D15).

## 6. Stakeholders

| Role | Who | Interest |
|---|---|---|
| Owner and sole on-site operator | Allen MT Maliyil | Does recording, processing and the report |
| Group members | Ayman Ali Noufell, Niramayi S V, Nandana G S | Share the project; not on site during recording |
| Guide | Dr. Reshmy D. S. | Approves scope, methods and report |

## 7. Functional requirements

Requirements describe what the workflow must do. IDs are referenced from `tasks.json` and `PLAN.md`.

**Capture and preparation**
- FR-01 Record two slots of about 1.5 hours each (off-peak and peak) from the fixed camera position, in files of 10-15 minutes, with a log of start time, weather and unusual events per slot.
- FR-02 Record a checkerboard calibration clip with the same lens and settings, and measure zebra-crossing dimensions and ground points on site.
- FR-23 Before the full recordings, write down the operational definitions: queue length, the stopped-speed threshold for stopped delay, treatment of free-left vehicles, counting and arrival lines per approach, and the capacity inputs needed. The definitions decide what the camera must cover.
- FR-03 Keep original files untouched. Convert copies to constant frame rate and undistort them before detection.

**Detection, tracking and review**
- FR-04 Detect and classify vehicles with a fine-tuned YOLO model on the agreed classes (proposed: two-wheeler, auto-rickshaw, car, bus, truck) and track them with a documented tracker.
- FR-05 Record model name and version, tracker, thresholds, frame rate and resolution for every run.
- FR-06 Flag low-confidence detections, class changes within a track, vanishing tracks and hard zones; show them in a local review screen (or an export to a labelling tool) with a short clip for context and the full frame for labelling.
- FR-07 Save corrected labels in a training format and use them to retrain. Keep the validation set from a different time block and never train on it.
- FR-08 Validate automated counts against manual counts of sampled playback clips and report the error per approach and class, including for the partly visible west approach.

**Traffic parameters and indices**
- FR-09 Count vehicles at virtual lines per approach and movement. Treat free-left movements separately. Where visible, add arrival lines upstream of the longest queue, because counts at the stop line measure discharge, which is capped by capacity when the junction is oversaturated.
- FR-10 Read the signal phases and cycle from the footage and cross-check with vehicle-start behaviour.
- FR-11 Compute queue length in metres using the ground-point mapping, with the queue definition documented.
- FR-24 Compute the pixel-to-ground mapping from the on-site ground points, map the ground-contact point of each box (bottom centre), report its error in metres on at least one check distance not used to fit it, and check each recording for camera drift.
- FR-12 Compute stopped delay per approach and slot from tracks, with the method and the stopped-speed threshold documented.
- FR-13 Compute V/C using IRC SP 41 (1994) section 7.6 (capacity = g x s / c), stating the page and the vehicle-equivalent (PCU) set. Capacity of a signalised approach depends on saturation flow and the green share of the cycle, so the observed signal plan is an input.
- FR-14 Compute a congestion index from the selected indicators with documented normalisation and weights. The formula must be approved by the guide before use.

**Emissions**
- FR-15 Estimate baseline emissions with a method that responds to signal timing (it must include idle time or speed and acceleration, not only vehicle-kilometres multiplied by a constant per-km factor), using a factor source from the source register (section 8.1) with stated units, categories and assumptions. Phase 1 covers CO₂ (idle time and fuel); other pollutants are added when their sources are registered (O17).
- FR-16 State clearly that emissions are estimates, not measurements, and keep video-based estimates separate from SUMO emission output. Proposed (O18): compute the SUMO cases with the same registered factors applied to SUMO's stop time and distance.

**Alternatives, MCE and SUMO**
- FR-17 Develop several signal-timing alternatives after the problems are identified, each documented with the problem addressed, the change, expected effect, safety, cost, land requirement and feasibility.
- FR-18 Score congestion and emission reduction before SUMO with an analytical estimate from the observed flows (method to be defined and approved). The method must be valid for each alternative type, including when volume/capacity reaches or exceeds 1 and for actuated or adaptive control. SUMO results must not feed the MCE.
- FR-19 Run the MCE on five criteria (congestion reduction, emission reduction, safety improvement, construction cost, land requirement) with a stated scale, direction and weights, state how safety and cost are scored and how a criterion that is equal for all alternatives is scored, and test how the ranking changes when weights vary.
- FR-20 Build the existing Pattom case in SUMO from the observed network, demand and signal plan, and check it against observed flow, queue and delay.
- FR-21 Simulate the selected alternative under demand and assumptions comparable to the existing case, for both slots, with several random seeds chosen in advance and the same seeds in both cases.
- FR-22 Compare existing vs selected alternative on delay, queue length, throughput, travel time and emissions, stating assumptions and limits.

**Source data**
- FR-25 Take every input value from the footage (measured) or from the source register (section 8.1). A value the register does not hold is reported as a gap and not filled from another source. A source is added to the register only with the user's approval and a date.

## 8. Data requirements

- Video: iPhone 15, 0.5x ultra-wide, 4K, 30 fps, HEVC, Lens Correction on, Action Mode off, AE/AF locked, fixed clamped and tethered position. Top-left of the frame is North.
- Storage: measured about 2.93 MB/s (about 10.6 GB per hour). Expect about 16 GB per slot and about 32 GB in total; about 100-130 GB on the PC for working copies unless intermediates are deleted.
- Visibility: North, South and East approaches are visible. West is partly visible (a tree blocks one corner). Free lefts exist on North, South and East according to the user (to confirm on footage).
- Labelled data: 300-500 corrected frames from both slots and all arms, spaced a few seconds apart.

### 8.1 Source register (D15)

Only the sources below supply input values. Every other number is measured from the footage or stated as an assumption.

| Need | Source in the register | Status of its values |
|---|---|---|
| Volumes, phases, queue, stopped delay, speeds | Our own footage | Measured; counts validated against manual counts |
| Saturation flow, capacity, PCU factors, fixed-time cycle and green-split formulas, signal warrants | IRC SP 41 (1994), supplied by the guide; see IRC_SP41_extract.md | Key pages checked against the page images; unread parts are listed in the extract |
| Emission per km (CO, HC, NOx, CO₂, PM) | ARAI 2007 report for CPCB, Table I | Reported; paper to be obtained (T49) |
| Idle emission rates (g/min) | ARAI 2007, Annexure IV | Not public; to be requested (T49) |
| Idle fuel use by vehicle class | Kumar et al. 2015 (CSIR-CRRI); Sharma et al. 2019 (J. Cleaner Production 212:8-21) | CRRI values reported; Sharma citation verified, its values not yet read |
| Fuel carbon factors | WRI/Shakti 2015 | Reported |
| Speed- or VSP-based rates (phase 2) | IVE model and the Indian studies in EMISSION_SOURCES.md section 2 | Reported |
| Air-quality context | Kerala PCB stations, CPCB portal | Context only, never calibration; not downloaded |
| Background literature | The nine papers in the PPT | Background only, not a source of values |

Rules:
1. Every value taken from the register carries its source, page or table, and status. A "reported" value is a working estimate, labelled "source not checked", until it is checked against the paper (T50).
2. If a needed value is not in the register, it is a gap. Do not fill it from memory, a general web figure, another country's standard, SUMO's default models or the earlier report. State what is missing, propose candidate sources with citations, and the user decides. A source enters the register only with a dated entry.
3. The earlier report and PPT numbers are not sources. The IISc ENVIS screenshot table is a copy of ARAI 2007 values and is not a source either; use it only as a CO₂ cross-check until the ARAI report itself is obtained.
4. Gaps today: a delay formula for the pre-SUMO estimate (SP 41 has none; T28); CO, HC, NOx and PM idle and speed-based rates (O17); the local fuel mix (assumed per class); the signal design details that SP 41 refers to IRC 93.
5. Proposed (O18): the emissions of both SUMO cases are computed by applying the same registered factors to SUMO's stop time and distance. SUMO's built-in model, if shown, is a labelled cross-check and not a source.

## 9. Success criteria

These are checks, not targets. No numeric thresholds have been set. Where a tolerance is needed it is to be agreed with the guide.

1. Counting error against manual counts is measured and reported for every approach and class.
2. The existing SUMO model reproduces observed flow, queue and delay within a stated tolerance (to be agreed), and any remaining difference is reported.
3. Every number in the report traces to a recorded task output, a registered source (section 8.1) or a stated assumption.
4. Measured, derived and estimated values are labelled separately everywhere.
5. The MCE method, scores, weights and a weight-sensitivity check are written down before the winner is named.
6. The final comparison uses comparable demand, and limitations are stated.
7. No reduction percentage appears before results exist.

## 10. Constraints and assumptions

- One person on site; no simultaneous manual counts. The video is the ground truth.
- PC with 4 GB VRAM and 16 GB RAM: inference locally, training on Colab, heavy sliced passes run overnight.
- Guide approvals may take time. Decisions that need her are recorded with dates, and the user may close an item as "decided, guide pending".
- The camera sits near a drop edge: clamp and tether it.
- Peak slot: evening outflow (rises from about 4:15 pm) is the main peak. Morning congestion starts about 8:30 (user observation).
- Signal timing: the user's rough estimate is N-S green about 50 s and E-W green about 20-30 s. This is unverified. Phases are read from the footage.

## 11. Decisions

| ID | Decision | Status |
|---|---|---|
| D1 | SUMO simulates only the existing case and the single MCE-selected alternative | Decided; Pending guide |
| D2 | Redesign scope is signal timing and phasing: existing fixed timing vs re-optimised and dynamic timing. No geometry changes. This is the user's instruction of 14 Oct 2026 and narrows HANDOFF.md sections 3.2 and 10 and the earlier fixes file | Decided; Pending guide |
| D3 | MCE keeps the five PPT criteria. Land requirement is equal for all alternatives and cost differs only by hardware, which is stated in the report. How the equal criterion is scored is part of O13 | Decided; Pending guide |
| D4 | Order: problems, alternatives, MCE, selection, SUMO | Listed as agreed in HANDOFF.md; guide confirmation not on record (PPT slide 12 still shows the old order) |
| D5 | Camera and recording setup as in section 8 | Decided |
| D6 | Two slots of about 1.5 hours; evening outflow as the main peak | Decided |
| D7 | Video emissions and SUMO emissions are reported separately | Decided |
| D8 | Congestion and emission reduction are scored before SUMO with an analytical estimate from observed flows | Decided; method pending guide |
| D9 | The congestion index is kept; the formula is agreed with the guide | Decided; formula open |
| D10 | Delay is stopped delay. The stopped-speed threshold is open (O6) | Decided; threshold open |
| D11 | Capacity comes from IRC SP 41 (1994), supplied by the guide. Signalised approach capacity uses its section 7.6 (capacity = g x s / c). The PCU table is still to be chosen | Decided; PCU table open |
| D12 | The west approach is handled after the test clip | Decided (deferred) |
| D13 | Emission-factor sources are researched by the AI and registered only after the user approves. Working plan (user, 14 Oct 2026): phase 1 estimates CO₂ as idle time x idle fuel rate x fuel carbon factor, plus ARAI g/km for moving vehicles; CO, HC, NOx and PM are added when their sources are registered (O17). See EMISSION_SOURCES.md | Decided; Pending guide |
| D14 | IRC SP 41 (1994) is the intersection code supplied by the guide. Cite it for signal warrants, PCU factors, signalised capacity and cycle design. Its geometric chapters stay outside the D2 scope | Decided; guide view on D2 pending |
| D15 | Source data policy: input values come only from the footage or the source register in section 8.1 (IRC SP 41, the emission sources in EMISSION_SOURCES.md). A value the register lacks is reported as a gap and not filled from another source. The user decides whether to add a source | Decided (user, 14 Oct 2026); Pending guide |

## 12. Open decisions

| ID | Question |
|---|---|
| O4 | Congestion index formula: indicators, normalisation, weights, scale |
| O3 | PCU table (SP 41 Table 3.1 or Table III-1) and whether to compare with saturation flow measured from the footage. The capacity method itself is decided |
| O6 | Queue-length operational definition and the stopped-speed threshold (delay itself is settled as stopped delay) |
| O7 | Final YOLO version, tracker, class list, whether tiling is needed |
| O9 | Whether free lefts exist on North, South and East as described |
| O10 | West approach handling after the test clip |
| O11 | Submission and review dates |
| O12 | Whether pollution-board data is used and which station |
| O13 | MCE weights, scoring scale, how safety and cost are scored, and the exact pre-SUMO scoring method |
| O14 | SUMO calibration tolerance (how close simulated and observed flow, queue and delay must be) |
| O15 | Off-peak slot: time and date |
| O16 | Privacy handling for the video (blurring, number plates, who may see frames) |
| O17 | Phase 2 emissions: sources for CO, HC, NOx and PM at idle and by speed (after the papers are obtained, T49) |
| O18 | How SUMO-case emissions are computed: registered factors applied to SUMO stop time and distance (proposed), or SUMO's built-in model (European-based, not in the register) |

## 13. Risks and limitations

| Risk or limitation | Effect | Mitigation |
|---|---|---|
| One camera angle; west partly hidden | West flow partly measured; west queue and delay may not be measurable | Decide after the test clip; label measured, derived or excluded |
| Only two slots recorded; weather, rain and wet roads on the recording day(s) affect detection and traffic | Results may not represent other days or conditions | Log weather per slot; state this limit; avoid general claims |
| Autos not in pretrained models; far vehicles small | Misclassification, missed small vehicles | Fine-tune, tile the far arm, review loop, report error |
| A constant per-km emission factor | Cannot show a timing effect | Use an idle-time or speed-based method |
| Open Indian sources give idle fuel (so CO₂) and per-km CO, HC, NOx and PM; idle and speed-based CO, HC, NOx and PM, and three-wheeler NOx and PM by speed, are not public | First estimate covers CO₂ only; other pollutants wait for the papers | Interim CO₂-first method; obtain ARAI Annexure IV and the priority papers; state gaps |
| SUMO built-in emission models are largely based on European vehicles and are not in the register | Absolute values indicative only | Apply the registered factors to SUMO output (O18); show the built-in model only as a labelled cross-check |
| Source values marked "reported" have not been checked against the papers | A wrong factor could enter a result | Label "source not checked" until T50; obtain the papers (T49) |
| A needed value is not in the source register (for example a delay formula) | Pressure to fill it from memory | Report a gap, propose sources, the user decides (D15) |
| Mixed, lane-less traffic in SUMO | Simulated behaviour is a simplification | Calibrate against video; state limits |
| Dynamic control assumes ideal detection in SUMO | Real deployment needs hardware | State as future work |
| No second person on site | Validation only from playback | Manual counting of sampled clips |
| Guide approvals may be slow | Delayed approvals | Record decisions and dates; close items as "decided, guide pending" where needed |

## 14. References

- IRC SP 41 (1994 edition, supplied by the guide; key pages checked against the page images, see IRC_SP41_extract.md). Still to verify for edition before citing: IRC 93 (traffic signals, including signal-timing design), IRC SP 43 (traffic management techniques for urban areas), IRC 106 (capacity of urban roads; check whether it gives mid-block capacity rather than signalised-approach capacity), IRC 70 (mixed traffic).
- The nine literature entries in the PPT (Lin et al. 2015; Yavuz et al. 2024; Muktar et al. 2025; Khakimov et al. 2021; Nematichari et al. 2022; Liu et al. 2020; Anagnostopoulos et al. 2025; Salami et al. 2024; Butt et al. 2026). Author order for Salami et al. and the source of Butt et al. need checking.
- Emission sources: see EMISSION_SOURCES.md. Registered sources (section 8.1): ARAI 2007 Table I (g/km for CO, HC, NOx, CO₂, PM) and its Annexure IV (idle g/min, not public); CSIR-CRRI idle fuel rates (Kumar et al. 2015); WRI/Shakti 2015 fuel CO₂ factors; the IVE model for speed and VSP bins. Most values there are as reported by a research run and not yet checked against the papers.
