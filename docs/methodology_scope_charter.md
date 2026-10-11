# Traffic Vision — Methodology & Scope Charter v1

## Purpose

Traffic Vision is an offline, reproducible computer-vision measurement project for recorded, fixed-camera intersection footage. It may report traffic measurements only after validation against manual ground truth. It is not a real-time surveillance or signal-control product.

## Scope

### Core measurements

- Local vehicle counts at configured screenlines.
- Turning movements when a vehicle trajectory is sufficiently observed from configured entry to exit zones.
- Fifteen-minute volume bins, aligned to wall-clock time when a trustworthy recording start time is available, otherwise explicitly labelled as elapsed-media-time bins.

### Experimental measurements

- Auto-rickshaw counts only from a registered model with an explicit, validated class mapping.
- EV mode-share estimates only as a colour-only heuristic on a localised candidate plate-region crop. The project must not use whole-vehicle colour, OCR, plate text, identifiers, ANPR matching, or registration lookup.

### Conditional measurements

- Speed in km/h and physical queue length in metres require a site-specific field survey, accepted calibration, and local validation. Until those conditions are met, these values are `unavailable` for that processing run and site configuration.

## Explicit non-objectives

- Live surveillance, alerts, edge deployment, or automated signal actuation.
- OCR, licence-plate transcription, vehicle identity extraction, or ANPR data retention.
- Emissions, dispersion, congestion-index formulation, intersection redesign, multi-criteria evaluation, or SUMO simulation. These may consume traceable exports downstream but are outside this project.

## Footage compatibility contract

The design is configuration-driven: a supported fixed-CCTV video can be analysed through a new site/scene configuration rather than code changes. Compatibility does not guarantee that every metric is valid for every video. Each video must undergo a preflight audit of decoding, timestamp quality, camera stability, visibility, occlusion, lighting, and scene geometry.

Timestamp discontinuities and decoder issues are recorded in the run audit. Affected intervals are excluded or labelled appropriately for time-derived metrics; they do not justify silently estimating missing time.

## Validation and reportability

- A local line count may be valid even when a complete trajectory is not available for a turning-movement label.
- A broken entry/exit trajectory produces `movement = unknown`; it does not invalidate an independently confirmed local screenline crossing.
- Acceptance thresholds are pre-registered and site-specific. This charter does not prescribe universal accuracy, pixel-resolution, GCP-count, or calibration-error thresholds.
- Diagnostic outputs before acceptance use `reportability_status = unvalidated`.
- Outputs used for Civil Engineering analysis require `reportability_status = reportable`, a recorded passed acceptance decision, and a non-null ground-truth version.

## Calibration principle

The selected calibration method must use a pre-registered, spatially distributed calibration-estimation set and a held-out validation set sufficient for that method. If the field data, spatial distribution, road-planarity evidence, or held-out validation is inadequate, speed and metric queue outputs remain unavailable.

## Provenance contract

Each export carries:

- raw-media SHA-256;
- timestamp audit, including time-base and discontinuity findings;
- active configuration and geometry SHA-256;
- registered model identifier and weights SHA-256;
- processing-run identifier;
- ground-truth version, or `null` for unvalidated diagnostics; and
- reportability status.

## Status

**Frozen design baseline. Implementation is not yet authorized by this document.**
