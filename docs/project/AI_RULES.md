# AI Rules: Working on the Pattom Project

**Version:** 0.3 (draft; source register added) · **Date:** 14 October 2026
**Applies to:** any AI agent continuing this project.
**Read with:** `HANDOFF.md`, `handoff_addendum_2026-10-14.md`, `PRD.md`, `ARCHITECTURE.md`, `PLAN.md`, `tasks.json`, `IRC_SP41_extract.md`, `EMISSION_SOURCES.md`.

---

## 1. Start of every session

Read in this order, then state in one line what you found and what you will do next.

1. This file.
2. `HANDOFF.md` sections 2 and 18, then `handoff_addendum_2026-10-14.md`.
3. `PRD.md` (what; section 8.1 is the source register), `ARCHITECTURE.md` (how), `PLAN.md` (order). Add `IRC_SP41_extract.md` for capacity and signal timing, and `EMISSION_SOURCES.md` for emissions.
4. `tasks.json` (current state). Continue the first task marked IN_PROGRESS. If none, take the first PENDING task in `review_order` whose dependencies are met.
5. `report_ppt_consistency_fixes.md`, only when touching the report or the PPT.

If something the user mentions is not in these files, treat it as new information: use it, and note it for the ledger (see section 6, rule 5).

## 2. When sources disagree

Do not choose silently. Name the conflict, say which source is newer, ask the user, and record the answer in `tasks.json`. Newer, dated statements replace older ones. The `HANDOFF.md` section 2 constraints change only when the user says so explicitly.

Known case: `HANDOFF.md` sections 3.2 and 10 and the D2 of `report_ppt_consistency_fixes.md` allow lane-use and turning management as alternatives. The user narrowed the scope to signal timing and phasing on 14 October 2026 (ledger D2). Use the narrower scope, and use the id map in `tasks.json` when applying the fixes file.

## 3. Hard constraints (from HANDOFF.md section 2, plus later decisions)

1. The site is Pattom. Do not revert to Kesavadasapuram.
2. Order: problems, alternatives, MCE, selection, SUMO. Never reverse it.
3. SUMO simulates the existing case and the single MCE-selected alternative only. Never say every alternative is simulated.
4. The redesign is a signal-timing change within the existing geometry. No standalone geometric design.
5. YOLO only detects. Never say YOLO calculates traffic volume, delay, V/C, the congestion index or emissions.
6. A single photograph cannot give hourly volume, delay or trajectories.
7. YOLO cannot reliably give fuel, model year or emission standard. Say so wherever it matters.
8. Dynamic timing reducing pollution is a hypothesis. Never state it as a finding before the data show it.
9. SUMO output never feeds the MCE.
10. Keep measured traffic indicators and simulated outputs separate.

## 4. Data integrity

1. **Never invent** traffic counts, emission factors, capacity values, congestion-index weights, MCE scores, signal timings, SUMO results, or reduction percentages. Every number needs a measurement, a cited source, or a stated assumption.
2. Label each value **measured**, **derived** or **estimated**. Keep them apart in tables.
3. The user's remembered signal timings (N-S green about 50 s, E-W green about 20-30 s) are unverified estimates until read from the footage.
4. When quoting a source, give its name, edition or year, and unit. If a page could not be read, say so; do not fill the gap from memory.
5. If a source or tool is blocked (bot protection, paywall), do not work around it. Tell the user and ask for the file.
6. Define every symbol in a formula and check its units before using it.
7. Illustrative examples must be labelled as illustrative and never placed in result tables.
8. **Source register (D15).** Input values come only from the footage (measured) or the sources in `PRD.md` section 8.1. Do not fill a value from memory, a general web figure, another country's standard, SUMO's built-in defaults, or the earlier report and PPT. If the register lacks a needed value, report it as a gap, propose candidate sources with citations, and let the user decide. Add a source to the register only after the user approves, with a date.
9. **Source status.** Values marked "reported" in `EMISSION_SOURCES.md` come from an unchecked research run. Use them only as working estimates labelled "source not checked" until T50 checks them against the paper. Quote SP 41 from `IRC_SP41_extract.md` with its page, and respect its cautions.

## 5. Method rules

- **Video:** never edit originals. Work on constant-frame-rate, undistorted copies. Never report metres from raw pixels.
- **Training data:** keep the validation set from a different time block and never train on it. Confidence is not accuracy: review a random sample as well as flagged frames.
- **Counts:** validate against manual counts from playback and report the error per approach and class, including the west.
- **Delay:** stopped delay (decided). The stopped-speed threshold and the queue definition are open (O6): do not compute queue length or stopped delay until they are written down and approved.
- **Capacity:** use IRC SP 41 (1994) section 7.6 (D11), with its page and the PCU set. Choose the PCU table with the user (O3). Do not use the approach-road values (1,400 to 2,400 PCU/h) as saturation flow.
- **Emissions:** estimates, not measurements. The method must respond to signal timing (idle time, or speed and acceleration). Do not use vehicles x distance x a constant per-km factor to claim a timing effect. Match the unit basis of the factor to the activity data. Sources come from the register (D15). Working plan (D13): phase 1 is CO₂ as idle time x idle fuel rate x fuel carbon factor, plus ARAI g/km for moving vehicles. Do not add CO, HC, NOx or PM numbers until their sources are registered (O17).
- **Congestion index:** kept. The formula is open and needs the guide's approval. Do not propose weights as if they were decided.
- **MCE:** five criteria. Write the scale, direction, weights, how safety and cost are scored, and the sensitivity method before scoring. Land requirement is equal for all timing alternatives; say so, and state how it is scored (a criterion that is equal everywhere gives no spread under min-max scaling).
- **Pre-SUMO scoring:** the method must be valid for each alternative type (Webster-type formulas assume fixed-time, undersaturated operation). Say when an alternative cannot be scored. SP 41 has no delay formula: that is a gap in the register (T28).
- **SUMO:** several random seeds per case, matched demand, the same warm-up and duration. SUMO emissions are a relative comparison only, reported separately from the video-based estimate. How they are computed is open (O18); the proposal is the registered factors applied to SUMO's stop time and distance. Do not replay recorded trajectories to test a new signal plan.
- **West approach:** decide only after the test clip. Until then do not assume it is measurable or excluded.

## 6. How to work with the user

1. **Plan before build.** Do not write files or code during a discussion. Write files only when the user asks or gives a go-ahead such as "build the docs". If a request could mean "talk about it" or "write it", ask one short question.
2. **No code unless asked.** The user is still in the planning phase (instruction of 14 October 2026). A design, a sketch in words, or a diagram is not a request for code.
3. **Ask less, decide less.** Ask only when a wrong guess is expensive or a decision belongs to the user. When the user says "don't ask me", pick the most reasonable reading, state it, and move on. Never ask the user for facts they have already given.
4. **Do not apologise.** Say what happened and what changed.
5. **Record decisions without surprising the user.** At the end of a planning discussion, list the decisions made and ask once whether to update the ledger and documents. After the user says yes, update them as decisions arise for the rest of that session. No decision should stay only in chat for long.
6. **Do not overclaim.** Report what was done and what was checked. Say when something was not checked.
7. **Check the work.** Re-read numbers against their sources, run any arithmetic, open files you produced.
8. **Stay in scope.** Out-of-scope ideas (live signal control, a machine-learning congestion predictor, geometric redesign) go into "future work" notes, not into the plan.
9. **The user is alone on site.** Do not propose steps that need a second person. Offer a one-person version.

## 7. Communication style

- Short answers that read well on a phone. Plain words. Explain a technical term the first time it appears.
- The user is a visual learner: use a diagram or a picture-like layout when a process or data flow is being explained.
- Lead with the answer or the result. Do not narrate effort.
- Offer Malayalam explanations or a WhatsApp-ready version when it would help (HANDOFF.md section 2, item 12). Do not switch language unprompted.
- No numbered walls of options. One recommendation with the reason, and the alternative only if it matters.

## 8. Ledger rules (`tasks.json`)

1. A task becomes DONE only when its `done_when` condition is met and `evidence` names what was produced (file, table, or number with its source).
2. BLOCKED means the task waits on an open decision that is not DECIDED. A task waiting only on other tasks stays PENDING. When an open decision becomes DECIDED, set the tasks that waited only on it back to PENDING. Do not decide an open decision for the user.
3. Start rule: continue the first IN_PROGRESS task that is not marked `ongoing`; otherwise take the first PENDING task whose T dependencies are DONE and whose O dependencies are DECIDED.
4. If the guide has not answered, the user may close an item as "decided, guide pending" with a date. Record that in `guide_confirmed` and keep it visible.
5. Version: `X` for scope or method change, `Y` for tasks added, removed or reordered, `Z` for status, evidence or wording.
6. Add a line to `_meta.history` and to the task's own `history` after every change. Resetting a task never deletes its history.
7. Before ending a session, make sure the ledger and the documents agree.

## 9. Review rules

When a reviewer model checks the documents, it works read-only and reports: its own stated model name, contradictions with `HANDOFF.md`, values that look invented, gaps, and anything unsupported by a source. The author fixes valid findings and tells the user which findings were rejected and why.

## 10. Safety and privacy

- The camera sits near a drop edge. Always remind the user to clamp and tether it before a recording day.
- Video shows people and vehicles on a public road. Privacy handling (blurring, plate numbers, who may see frames) is not decided. Do not publish or share frames that show people or number plates, and do not extract plate numbers, without the user's approval.
- Do not identify individuals from the footage.
