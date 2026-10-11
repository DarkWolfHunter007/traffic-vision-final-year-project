# Traffic Vision — Site & Footage Configuration Questionnaire

Complete one copy for every fixed camera view or intersection. This is a planning and intake form; it is not an implementation configuration file.

## 1. Basic record

- Site/intersection name:
- City and state:
- Camera identifier or description:
- Video filename and approved local path:
- Recording date, start time, and timezone:
- Source: original recording, DVR export, or re-encoded copy:
- Footage-use authorization:

## 2. Requested measurements

Mark the intended outputs and record why they are needed:

- [ ] Total counts
- [ ] Broad vehicle classes
- [ ] Turning movements
- [ ] Auto-rickshaw counts
- [ ] Experimental green-plate-region EV estimate
- [ ] Queue vehicle count
- [ ] Speed in km/h
- [ ] Queue length in metres

## 3. Camera and media observations

- Is the camera fixed for the entire clip? Note pan, tilt, zoom, or cuts:
- Camera location, mount type, and approximate height if known:
- Visible approaches and exits:
- Obstructions, occlusion, road-contact-point visibility, and lens distortion:
- Resolution, container, codec, and nominal frame rate:
- Lighting, rain, glare, motion blur, and compression artefacts:
- Source of recording time: metadata, on-screen display, operator record, or unknown:
- Suspected time jumps, freezes, missing intervals, or concatenated clips:

## 4. Scene geometry to register from a representative frame

- Road region of interest (ROI):
- Inbound and outbound counting lines, including direction:
- Entry zones and exit zones for movements:
- Stop lines and queue areas, if relevant:
- Excluded sidewalks, parking, service roads, or unrelated lanes:
- Locations where two-wheelers or three-wheelers commonly bypass queues:

## 5. Turning-movement coverage

For each approach, record possible exits, allowed movements, whether the full path is visible, and likely ambiguity or occlusion points.

## 6. Optional field-survey information

Complete only if speed or metric queue length is sought:

- Visible physical landmarks and their measured distances/coordinates:
- Measurement method:
- Road grade, crown, curvature, or other planar-assumption risks:
- Stop-line location and queue-direction reference distances:
- Proposed calibration-estimation landmarks and held-out validation landmarks:

## 7. Manual validation plan

- Reference intervals covering representative operating conditions:
- Independent manual observers:
- Vehicle categories and movements to tally:
- Planned reconciliation method for observer disagreements:
- Pre-registered site-specific acceptance rules:

## 8. Preflight conclusion

For each requested metric, mark one outcome:

- `reportable`: validated and accepted;
- `unvalidated`: diagnostic only; or
- `unavailable`: unsupported by footage, field data, or validation.

Record the reviewer, review date, limitations, and any required follow-up.
