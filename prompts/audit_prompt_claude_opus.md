# Traffic Vision — Independent Technical Audit & Research Prompt
## For Claude Opus in Antigravity

You are acting as an independent computer-vision researcher, traffic-engineering methodologist, software architect, and senior code auditor. Audit the existing Traffic Vision final-year project repository, independently research current best practices, and give a candid evidence-backed verdict on the idea and implementation plan.

Repository: https://github.com/DarkWolfHunter007/traffic-vision-final-year-project
Study site: Pattom Intersection, Thiruvananthapuram, Kerala, India
Project type: Civil Engineering final-year project; offline processing of recorded CCTV footage, not a production surveillance system.

## Mission and operating rules

Perform an AUDIT FIRST. This task is research and review, not implementation. Do not build features, refactor prompts, change schema, edit application code, or commit files unless I explicitly ask in a later task.

Inspect actual repository files and history. Do not rely on README summaries or commit messages alone. Confirm the branch and exact commit SHA being audited. Review both `main` and `refactor/prompts-schema-provenance`, compare their state and intent, and explicitly recommend a baseline. Do not assume the refactor branch is merged into main.

Inspect all relevant files, including:
- `README.md`
- `prompts/master_prompt.md`
- all `prompts/phase_*.md`
- `prompts/review_checklist.md`
- `backend/database/schema.sql`
- `docs/data_dictionary.md`
- dependency manifests, configs, scripts, tests, application code and entry points if present
- branch history and divergence

Treat documents and prompts as claims to verify, not truth. Find contradictions, unowned requirements, unrealistic assumptions, missing dependencies, weak acceptance criteria, schema defects, bugs, methodology risks, and sources of measurement error.

Do not confuse a plan with working software. If there is little/no implementation code, say so and rate design maturity separately from implementation maturity.

## Mandatory web research

You MUST search the internet during the audit using the available browser/search tools. Cite direct source URLs and dates accessed. Do not rely on memory alone, generated summaries, SEO articles or uncited claims. Prefer primary sources: peer-reviewed papers, official documentation, research agencies, benchmark/dataset papers and original implementation repositories.

Use research to compare credible alternatives, not merely justify current choices. For each recommendation, name the source and explain which design decision it supports. Distinguish source-backed findings from your engineering judgment. State disagreements between sources. Never fabricate references, benchmarks, model performance or access to footage.

Research at least:
1. Fixed-CCTV vehicle detection: current YOLO-family options and credible alternatives; small/distant objects; Indian traffic/domain adaptation; occlusion, night, rain, glare, camera angle and compression; when tiling helps and duplicate-merging costs.
2. Tracking: ByteTrack vs BoT-SORT and relevant alternatives for fixed cameras; frame skipping and tracker parameter effects; occlusion recovery, ID switches, fragmentation and evaluation.
3. Indian mixed-traffic classes: auto-rickshaws, motorcycles, buses, trucks, bicycles and relevant local categories; pretrained label limitations; realistic annotation/training options and taxonomy risks.
4. Calibration and speed: homography/road-plane assumptions, perspective, lens distortion, reference-point quality and distribution, bottom-centre ground points, held-out validation/error in metres, source timestamps, VFR footage and speed uncertainty. Explain what one fixed camera can validly measure.
5. Counts and movements: line crossing vs entry/exit zones, direction/movement assignment, duplicate suppression, U-turns/ambiguous movements, time bins, duration and extrapolation limitations, manual ground truth.
6. Queue/stopped-vehicle measurement: queue definitions, stop-line/approach behavior, signal-phase relevance, queue length vs count, physical-measurement constraints and manual validation.
7. Active learning/model fine-tuning: uncertainty vs random/stratified sampling, review cost, correction quality, annotation formats, leakage-safe splits by source video/segment, small-data risks and when fine-tuning is not justified. Clarify why this workflow is not reinforcement learning.
8. Research validation: suitable detection/tracking/counting/speed/queue metrics and protocols, representativeness, uncertainty, train/test leakage and reproducibility.
9. Engineering choices: Python/PyTorch/Ultralytics/OpenCV/ByteTrack, FFmpeg/PyAV or alternatives for timestamp correctness, SQLite constraints/migrations/run provenance, FastAPI/frontend complexity proportional to a student project.
10. Hardware: practical configurations for Windows 11, 16 GB RAM and 4 GB VRAM. Verify actual supported GPU/CUDA/PyTorch setup before assuming acceleration. Give a CPU fallback and distinguish throughput from research quality.

Aim for 12–20 high-quality sources, primarily first-party/peer-reviewed. Include publication/release dates when available and the access date. Only cite sources actually inspected enough to substantiate the claim.

## Research context and scope

Intended flow:
recorded CCTV → media metadata/timestamps → detection → tracking → trajectories → vehicle counts/movements → calibrated speed where valid → stopped/queue observations where valid → human review/correction → versioned dataset/model evaluation → export for downstream Civil Engineering analysis.

This repository does not own final emission calculations, congestion-index methodology, MCE, intersection redesign generation or SUMO simulation. Keep these outside scope except for necessary interfaces.

Initial site is Pattom Intersection, Thiruvananthapuram, Kerala. Make the system configurable for other intersections, but do not assume the camera views or calibration generalize.

Offline, traceable, repeatable measurements and honest limitations matter more than real-time FPS.

## Required audit

### A. Establish repository reality
Inventory branches and files. Determine:
- what is documentation, schema/prompt scaffolding, executable implementation and tests;
- whether manifests, dependencies and entry points exist;
- whether README accurately describes the tree;
- whether all 13 phase prompts are sequential, consistent, bounded and compatible with the schema/data dictionary;
- whether any code exists, and whether it actually runs/tests;
- which branch is the sounder working baseline, with evidence.

### B. Architecture and provenance
Diagram the proposed architecture and data flow. Examine component boundaries, interfaces, DB constraints, provenance, timestamps, calibration lineage, model versions, run lifecycle, configuration snapshots, deterministic processing, errors/retries, cancellation, logging, caching/reprocessing and exports.

Inspect concrete schema risks, including:
- SQLite foreign-key behavior and creation/reference-order concerns;
- whether every derived table that needs it carries `run_id`;
- identity/uniqueness for detections, tracks, crossing events and immutable geometry/configs;
- whether per-frame PTS can represent decoder timestamps reliably;
- whether config/code/model hashes are reproducible and verified;
- safe upstream reuse through `parent_run_id`;
- migration/schema-version support;
- whether accepted calibration is enforced for physical coordinates/speed in runtime behavior;
- queue state vs zero vs invalid/unavailable;
- manual corrections for class and bounding-box geometry and dataset export lineage;
- single-production-model constraints under SQLite;
- model hash, config values, dataset lineage and code version sufficiency for reproducibility.

A schema field is not proof that runtime code enforces it. Verify implementation if present; otherwise mark it planned/unverified.

### C. Scientific validity and feasibility
Answer candidly:
- What is feasible from one fixed-view recorded CCTV video?
- What can be trusted without new labels/calibration, and what remains only a hypothesis?
- Does the actual camera view support defensible speed and physical queue-length metrics?
- What camera metadata and field measurements are essential?
- What if distant vehicles are too small/blurred?
- Which vehicle classes can be identified reliably vs guessed?
- Evaluate electric-vehicle identification through green number plates separately; do not pull number-plate/OCR/emissions work into the core scope without a reason.
- What minimum manual ground truth supports defensible academic claims?
- What is realistic within a final-year project?
- Which features should be simplified or postponed to protect validity?

Keep detection, tracking, counting, movement classification, speed, queue and emission inference distinct. Success in one does not prove the others.

### D. Compare approaches
For each major module, compare at least two credible alternatives where relevant. Include a decision table with options, pros/cons, evidence, complexity, data needs, hardware impact, recommendation, confidence and reasons for rejecting alternatives.

Recommend both a minimal viable research system and a stretch-goal system. Prefer fewer validated features over unvalidated breadth.

### E. Audit each implementation prompt
For each phase 01–13, report:
- completeness and scope correctness;
- dependencies and interface contracts;
- overlap/gaps with adjacent phases;
- objective acceptance tests and scientific relevance;
- likely coding-agent misinterpretations;
- prerequisite fixes;
- whether phase order is sound.

Check key phase gates: timestamps, preprocessing/tile-merge behavior, tracker settings under frame skipping, ground-truth counting, calibration validation, signal-phase scope for queue analysis, bounding-box correction, leakage-safe evaluation and export contract readiness.

Create a requirement traceability matrix:
requirement → owner phase → source-of-truth schema/interface → evidence/test oracle → priority → state.
Use states like `not implemented`, `planned only`, `present but unverified`, and `verified`, based on actual inspection.

### F. Validation protocol
Design a feasible, rigorous protocol covering:
- 2–3 diverse clips as a starting minimum and why this is insufficient for broad generalization claims;
- manual counts by class/approach/movement, with double-checking/inter-rater checks where feasible;
- labeled subset for detection and tracking;
- absolute counting error and percentage-error denominator policy;
- speed reference measurement and limitations;
- manual queue-length measurement and queue-tail definition;
- calibration fit versus held-out error;
- lighting/weather/congestion, occlusion and small/distant object variation;
- splits by independent source video/segment, never adjacent frames alone;
- confidence intervals/uncertainty appropriate to sample size;
- acceptance thresholds fixed before final evaluation;
- failure reporting and invalid/unavailable statuses.

Separate essential validation for the minimum viable project from stretch goals.

### G. Schedule and resources
Estimate engineering effort by phase in days/weeks with explicit assumptions. Identify schedule risks and what to cut first. Account for Windows 11, 16 GB RAM, 4 GB VRAM and offline footage. Clearly state unknowns.

## Required report

Write a new `AUDIT_REPORT.md` file in the workspace. Do not overwrite existing files. Do not modify app code, project prompts or schema as part of this audit.

Use this report structure in order:
1. Executive verdict: go/conditional go/no-go, scientific defensibility, top three risks and whether ready to implement.
2. What was actually inspected: branches, exact commit SHAs, paths, tools/commands run and unavailable items; separate inspected code from docs.
3. Repository maturity and branch comparison.
4. Proposed architecture and data flow, including trust boundaries.
5. Research findings with citations, source dates and how they affect design decisions.
6. Strategy comparison and recommended stack.
7. Scientific validity and required data.
8. Schema/provenance audit with concrete path/line/section evidence.
9. Phase-by-phase audit (01–13).
10. Requirement traceability matrix.
11. Validation protocol.
12. Prioritized findings P0/P1/P2/P3, each with evidence, impact and recommendation.
13. Revised roadmap with dependencies, effort, deliverables and objective exit criteria.
14. Minimal viable project vs stretch goals.
15. Field questions and unverified assumptions.
16. Final recommendation and next five actions.
17. References actually consulted.

## Quality bar
- Be candid; audit to improve, not validate existing choices.
- Repo findings cite paths and preferably lines/functions/tables. Research findings cite sources.
- Label findings as verified defect, probable defect, research risk, open question or improvement.
- Give severity and confidence on major findings.
- No generic filler. Separate repo facts, source-backed facts and recommendations.
- Explain trade-offs instead of merely saying "best practice."
- A test is not passed unless run; include command and raw result.
- Do not claim the app runs unless actually executed.
- If browsing/tools/runtime are unavailable, disclose limitations and proceed with evidence available.
- Challenge the model/tracker/decoder/calibration choices where justified and explain switching cost.
- Do not equate polished UI, high FPS, high mAP or feature count with a successful Civil Engineering result.
- Do not implement anything during the audit.

## Final response in Antigravity
After writing `AUDIT_REPORT.md`, give a short executive summary with: verdict; feasibility; strongest approach and reasons; top unresolved risks; five highest-priority actions; and report path.

If independent subagents are available, use them for bounded tasks (scientific methodology, schema/provenance, prompt consistency, literature research), then synthesize and verify. Ensure the final recommendation matches the evidence.
