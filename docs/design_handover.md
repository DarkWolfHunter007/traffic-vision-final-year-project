# Traffic Vision — Design Handover

## Repository baseline

The design baseline is `main` at the commit that includes the former `refactor/prompts-schema-provenance` branch. It contains the README, phase prompts, review checklist, data dictionary, and proposed SQLite schema.

## Current maturity

This repository is a **design and specification project**. It does not currently contain executable application code, dependency manifests, automated tests, staged Pattom CCTV footage, trained models, or a runnable pipeline.

## Authoritative documents

- `prompts/master_prompt.md`: phased project specification.
- `prompts/phase_01_video_input_and_playback.md` through `prompts/phase_13_export_and_dashboard.md`: proposed staged work.
- `docs/data_dictionary.md`: planned data terms.
- `docs/methodology_scope_charter.md`: frozen methodological and privacy boundaries.
- `docs/site_footage_configuration_questionnaire.md`: intake form for each future camera scene.

## Vetted decisions

- Use per-connection SQLite foreign-key enforcement when implementation begins. SQLite documents that foreign keys must be enabled separately for each connection: <https://www.sqlite.org/foreignkeys.html#fk_enable>.
- Preserve decoded PTS and time-base information where available; do not infer time quality from nominal FPS alone.
- Treat COCO's absence of a dedicated auto-rickshaw category as a taxonomy limitation, not evidence that every pretrained detector fails identically.
- Treat tracking, model fit, EV colour classification, hardware throughput, and all acceptance thresholds as local validation questions rather than promises.
- The project must remain free of OCR and ANPR data handling.

## Known planning gap

The phase specification requires `video_segments` before Phase 06, while the current proposed schema does not define it. This is a documentation/schema consistency issue to resolve deliberately during the implementation-design review; it is not evidence that SQLite table creation order is broken.

## Handover rule

Before implementation begins, select a representative Pattom fixed-camera clip, complete the site and footage questionnaire, and approve a requirements specification derived from the resulting preflight audit. Do not claim speed, metric queues, auto-rickshaw counts, or EV mode share without their separate validation gates.
