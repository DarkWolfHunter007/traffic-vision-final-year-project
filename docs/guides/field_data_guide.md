# Field guide: what to collect so the results are credible

Pattom intersection study, Group 4. For one person on site. Every number the app reports is only as good as these inputs, and the app never guesses a missing one. If an item below is not collected, the matching step stays locked or its result is labelled as an estimate.

**How to use this:** print it, take it to the site, and tick each box. Section 9 is the one-page checklist.

---

## 1. Safety first

- The camera sits near a **drop edge**. Clamp it and tether it every time. Tape down the power cable.
- Do not stand on the carriageway to measure. Measure on the pavement or refuge, or when the signal is red for that arm.
- Do not record faces or number plates for publication. Raw video stays on your PC and is never shared (project rule).

## 2. Camera setup (the same for every recording)

| Item | What to do | Why it matters |
|---|---|---|
| Position | Use **one fixed spot** for all slots, and mark it (photo of the clamp position). | Calibration is only valid for the exact same view. A moved camera needs a new calibration. |
| View | All approaches visible, as much road as possible, **stop lines and the queue area in clear view**. Note which part is hidden (the west corner behind the tree). | Anything outside the view cannot be counted or measured. |
| Settings | 4K, 30 fps, HEVC, 0.5× (widest), Lens Correction on, Action Mode off, **focus and exposure locked**, Do Not Disturb, shade the phone. | A steady frame rate and no zoom changes keep the geometry fixed. |
| Zoom | **Never change zoom** between or during recordings. | A zoom change invalidates the ground mapping. |
| Storage | About 16 GB per 1.5 hours. Clear 40 GB on the phone. Record in 10–15 minute files. | Avoids a full disk in the middle of a peak. |
| Power | Power bank, taped cable. Check the phone at each file change. | Missing minutes cannot be re-recorded. |
| Reference photo | One still photo of the same view at the start of each slot. | Lets you check later that the camera did not drift. |

## 3. Slot log (one line per slot)

Keep a small table, one row per recording slot:

| Slot | Date | Start time | End time | Weather | Unusual events | Camera moved? |
|---|---|---|---|---|---|---|
| peak (evening outflow) | | | | | | |
| off-peak | | | | | | |

- Record **unusual events**: accident, police control, signal fault, road work, procession, heavy rain. A slot with one is flagged in the report, not silently used.
- The peak slot is the evening outflow (from about 4:15 pm). The off-peak time and date are not decided yet (open item O15).
- **Why:** the study compares existing and redesigned timing for the peak and off-peak slots. The result is credible only if the slot conditions are stated.

## 4. Ground measurements (turns pixels into metres)

This is the most important field task. Every queue length, speed, stop point and road width depends on it.

**What the app needs:** 4 or more **fit points** that are spread across the junction, plus at least 1 **check** (a tape distance or a point not used for fitting) far from them. The app reports the check error in metres. It refuses to work without a check.

### 4.1 Choose the points
- Pick points that are **flat on the road surface and clearly visible in the video**: corners of zebra stripes, stop-line ends, kerb corners at the base, a median tip, paint arrows.
- **Spread them:** put points on **opposite sides** of the junction, near and far. Points close together (one stripe) give errors of several metres far away.
- **Avoid:** pole tops, vehicles, shadows, anything above the road surface.
- Cover **every approach** you want queues for. A point outside the calibrated area gets no metres by design.

### 4.2 Measure
- Use a **steel or fibreglass tape**; for long distances use a measuring wheel or laser distance meter.
- Pick one point as the origin **(0, 0)** and one direction as the x axis (for example along the north stop line). Write each point as **(x, y) in metres** in this one grid. Measure along the grid, not diagonally, where you can.
- **Also measure at least 3 straight distances** between pairs of points that are far apart. These are the check distances.
- **Photograph each point** with the tape on it, and write its name (Z1, Z2, …) on the sheet. Mark it on a still frame later.
- Measure each distance **twice**. If the two readings differ by more than about 5 cm, measure again.

### 4.3 What to write down

| Point | Where it is (description) | x (m) | y (m) | Photo # |
|---|---|---|---|---|
| Z1 | N stop line, left end | 0.00 | 0.00 | |
| Z2 | | | | |

| Check | From → To | Measured distance (m) | Photo # |
|---|---|---|---|
| C1 | | | |

### 4.4 Road widths (per approach, at the stop line)
- Measure the **kerb-to-kerb or kerb-to-median width** of each approach across the lanes that feed the stop line. Write the width and **the lane count**.
- Write whether any **parked vehicles, bus stops or narrowing** are in that stretch.
- **Gradient:** note if the approach slopes uphill or downhill toward the stop line, and roughly how much (a smartphone level app gives %). IRC SP 41 changes saturation flow by 3% per 1% slope.
- **Why:** the capacity (and so V/C) uses IRC SP 41 s = 525 × width; a wrong width is a wrong V/C.

## 5. Signal timing (the video cannot read the lights by itself)

You read the timings off the footage with the **Signal Timings** page. For each **signal head** that controls an approach:
- Decide the **head names** now and use them everywhere (for example N, S, E, W). The same names must be in `signal_log.csv`, the approach areas, and the indicator settings.
- Note which **approach** each head serves and whether any head serves **only a turning movement** (free left, right-turn arrow). Free-left traffic that never stops needs separate handling.
- Log **at least 3 complete cycles per head** (green → amber → red → green) for each slot. For a plan that changes during the day, log a few cycles in each period.
- Note the **amber and all-red** times seen. The simulator needs them.
- **Why:** capacity needs green time and cycle length; the "existing plan" in SUMO is these timings. Do not use remembered values (the 50 s and 20–30 s figures are unverified estimates).

## 6. Counting setup

### 6.1 Lines
- Mark, on a still frame, for each approach: an **arrival line** (upstream of the longest queue, where traffic still moves) and a **stop line** (on the painted line).
- **Why both:** the stop-line count is discharge, which is capped by capacity when the junction is full. Demand is better measured upstream.

### 6.2 Movements
- Write down for each approach which **movements** exist: through, left, right, **free left**. For each, the **exit approach**.
- Confirm on the footage whether free-left lanes exist on the North, South and East (open item O9).
- **Why:** SUMO builds demand from movements. Without them it has no vehicles to simulate.

### 6.3 Classes
- List which vehicle types you see in numbers: car, two-wheeler, auto-rickshaw, bus, truck, tempo-traveller, light commercial.
- Note the **fuel of the autos** (petrol, diesel, CNG, LPG; from a quick roadside count of 20 autos or an RTO source). The default idle-fuel row is a 2-stroke petrol auto and is probably wrong for Kerala.
- Note any other vehicle that matters (cycle rickshaws, handcarts, KSRTC buses). Each needs a class or is dropped, and the report says so.

## 7. Validation data (how you prove the counts are right)

The report must state the counting error per approach and class. This is the main credibility test.

- Choose **sample clips of 2 minutes** from each slot, in different parts of the slot (start, middle, end) and for each approach.
- Count **by hand from playback**, per line, per class, **without looking at the app's numbers first**. Use the manual-counts sheet (`configs/manual_counts.example.csv`):

  `interval_start_s, interval_end_s, line_name, class, count`

- Do the manual counts **twice** (or have another person check a sample) and note the difference between your two counts. That gives the limit of the reference.
- Count the **west approach** too, even if it is partly hidden, and mark where visibility is poor.
- Keep the **validation clips separate from any clips used for labelling or fine-tuning**. Never train on them (project rule). Use a **different time block**.
- **Do not change settings to make the error look smaller.** Report the error as it is.

## 8. Context data (optional, never used for calibration)

- **Pollution-board readings** (Kerala PCB continuous station near Plammoodu, about 0.4–0.5 km away, to be confirmed): hourly values for the same slots, with the station name and averaging interval. Used as context only (open item O12).
- **Traffic police notes:** any signal changes, closures or events on the recording days.
- **Fuel/vehicle notes:** fuel type shares if available from a local source. Cite the source.

## 9. One-page checklist

**Before going to site**
- [ ] Phone charged, 40 GB free, power bank, taped cable, clamp and tether
- [ ] Steel tape, measuring wheel or laser meter, chalk or masking tape, notebook, this sheet
- [ ] Camera settings checked (see section 2)

**On site: setup (once)**
- [ ] Camera spot marked and photographed; reference still taken
- [ ] 4–6 spread-out ground points chosen, named and photographed
- [ ] (x, y) of every point measured in one grid; each distance measured twice
- [ ] 3+ check distances between far-apart points
- [ ] Width and lane count of every approach at its stop line; gradient, parking, bus stop notes
- [ ] Signal heads named and linked to approaches; free-left movements noted
- [ ] Auto fuel mix noted

**On site: each slot**
- [ ] Slot log started (date, start time, weather)
- [ ] Reference still at the start
- [ ] File changes checked; unusual events written down
- [ ] Reference still at the end (camera did not move)

**After recording**
- [ ] Originals copied off the phone and backed up
- [ ] Signal timings logged on the Signal Timings page (3+ cycles per head)
- [ ] Ground points, lines, areas and widths entered on the Calibrate page
- [ ] Manual counts (2-minute clips, different times, per approach) written down
- [ ] Anything that went wrong or looks odd written in the slot log

## 10. What each item feeds (so you know why it is needed)

| You collect | The app uses it for | If missing |
|---|---|---|
| Spread ground points + tape checks | Queue length, speeds, stopped-delay test, stop points, widths | Metres are unreliable; queue and delay are not trustworthy |
| Road widths + lane counts + gradient | Saturation flow, capacity, V/C (IRC SP 41) | V/C cannot be computed |
| Signal log (3+ cycles per head) | Green and cycle for capacity, queue at green, existing plan in SUMO | Indicators and SUMO stay locked |
| Movements (entry → exit line) | SUMO demand and routes | SUMO has no vehicles |
| Manual counts | Counting error per approach and class | Counts cannot be called validated |
| Slot log | Slot conditions and flagged events in the report | The comparison cannot state its conditions |
| Auto fuel mix | CO₂ per vehicle class | The emission estimate rests on an assumption |

## 11. Things the app will not do (so do not expect them)

- It does not read the traffic lights from video.
- It does not find fuel type, model year or emission standard from video.
- It does not report metres without a ground check, and not outside the calibrated area.
- It does not decide your problem rules, alternative plans or MCE weights. Those are yours and your guide's.
- SUMO results never feed back into the MCE. They are a separate, simulated comparison.
