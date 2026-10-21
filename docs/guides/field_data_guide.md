# Field Data Guide: Pattom Intersection Study

**Purpose:** This guide tells you what data to collect on site. The data make the results of the application credible.
**Writing style:** ASD-STE100 (Simplified Technical English) rules. Procedure sentences have 20 words or fewer. Other sentences have 25 words or fewer. See the note at the end of this guide.
**Who uses this guide:** One person on site.

If you do not collect a data item, the application cannot use it. The application does not guess a missing value. The related step stays locked, or the result shows a label that says "estimate".

---

## 1. Safety

**WARNING**
**The camera is near a drop edge. A fall can cause injury.**

1. Clamp the camera to the support.
2. Tie the camera to a fixed point with a tether.
3. Tape the power cable to the support.
4. Do this check each time before you record.

**WARNING**
**Moving vehicles can cause injury or death.**

1. Do not stand on the carriageway to measure.
2. Measure from the pavement or the refuge.
3. Measure across an arm only when its signal is red.

**CAUTION**
**The video shows people and number plates.**

1. Keep the original video on your PC.
2. Do not publish or share video frames that show people or number plates.

---

## 2. Camera Setup

Use the same setup for all recordings.

| Item | Action | Reason |
|---|---|---|
| Position | Use one fixed position. Mark it. Take a photo of the clamp. | The calibration is valid only for the same view. |
| View | Show all approaches. Show the stop lines and the queue area. Write down the hidden parts. | The application cannot count what the camera does not show. |
| Settings | Set 4K, 30 fps, HEVC, 0.5x, Lens Correction on, Action Mode off. | A fixed setup keeps the geometry the same. |
| Focus and exposure | Lock them. | Changes in focus and exposure cause errors in detection. |
| Zoom | Do not change the zoom. | A zoom change makes the calibration invalid. |
| Phone | Set Do Not Disturb. Shade the phone. | A call or a hot phone can stop the recording. |
| Storage | Clear 40 GB. A recording of 1.5 hours uses about 16 GB. | A full phone stops the recording. |
| Files | Record in files of 10 to 15 minutes. | A short file limits the loss if a fault occurs. |
| Power | Use a power bank and a taped cable. | A low battery stops the recording. |
| Reference photo | Take 1 photo at the start and 1 photo at the end of each slot. | The two photos show that the camera did not move. |

---

## 3. Slot Log

A slot is one recording period. Make 1 record for each slot.

| Slot | Date | Start time | End time | Weather | Unusual events | Camera moved? |
|---|---|---|---|---|---|---|
| Peak (evening outflow) | | | | | | |
| Off-peak | | | | | | |

1. Write down each unusual event. Examples: accident, police control, signal fault, road work, procession, heavy rain.
2. The report states each slot with an unusual event.
3. The peak slot starts at about 16:15. The off-peak date and time are not yet decided (open item O15).

**NOTE:** The study compares the existing timing and the new timing. The slot conditions must be known for the comparison to be valid.

---

## 4. Ground Measurements

The ground measurements change pixels into metres. Queue length, speed, stop point and road width all use them. This is the most important task on site.

**Requirements for the application:**
- 4 or more fit points. They must be spread across the junction.
- 1 or more check measurements. A check is a tape distance, or a point that is not used for the fit.

The application shows the check error in metres. It does not work without a check.

### 4.1 Choose the Points

1. Choose points that are flat on the road surface.
2. Choose points that are clear in the video. Examples: corners of zebra stripes, ends of stop lines, kerb corners, a median tip, paint arrows.
3. Put points on opposite sides of the junction. Put points near the camera and far from the camera.
4. Include every approach for which you need queue data.

**CAUTION**
**Points that are close together cause large errors far from the points.**
Do not use one zebra stripe only.

Do not use these points:
- Tops of poles.
- Vehicles.
- Shadows.
- Anything above the road surface.

### 4.2 Measure

Use a steel or fibreglass tape. For long distances, use a measuring wheel or a laser distance meter.

1. Choose 1 point as the origin (0, 0).
2. Choose 1 direction as the x axis. Example: along the north stop line.
3. Measure each point as (x, y) in metres in this one grid.
4. Measure at least 3 straight distances between points that are far apart. These are the check distances.
5. Measure each distance 2 times.
6. If the 2 readings differ by more than 5 cm, measure again.
7. Take a photo of each point with the tape on it.
8. Write the name of each point (Z1, Z2, ...) on the sheet.

### 4.3 Record the Measurements

| Point | Description | x (m) | y (m) | Photo no. |
|---|---|---|---|---|
| Z1 | North stop line, left end | 0.00 | 0.00 | |
| Z2 | | | | |
| Z3 | | | | |
| Z4 | | | | |

| Check | From - To | Measured distance (m) | Photo no. |
|---|---|---|---|
| C1 | | | |
| C2 | | | |
| C3 | | | |

### 4.4 Road Width at the Stop Line

Do this for each approach.

1. Measure the width across the lanes that feed the stop line.
2. Measure from kerb to kerb, or from kerb to median.
3. Write down the number of lanes.
4. Write down parked vehicles, bus stops, and narrow sections in this length.
5. Measure the gradient toward the stop line. A level app on a smartphone gives the value in percent.

**NOTE:** The application calculates capacity with IRC SP 41: s = 525 x w. The symbol w is the width in metres. A wrong width gives a wrong V/C ratio. A gradient of 1 percent changes the saturation flow by 3 percent.

---

## 5. Signal Timing

The application cannot read the signal lights from the video. You read the timing from the video with the Signal Timings page.

**Before you start:**

1. Give a name to each signal head. Example: N, S, E, W.
2. Use the same names in the signal log, in the approach areas, and in the indicator settings.
3. Write down which approach each head controls.
4. Write down each head that controls only one movement. Examples: a free left, a right-turn arrow.

**Log the timing:**

1. Log at least 3 complete cycles for each head. A cycle is green, amber, red, then green again.
2. Do this for each slot.
3. If the plan changes during the day, log a few cycles in each period.
4. Write down the amber time and the all-red time.

**NOTE:** The application uses the green time and the cycle time to calculate capacity. SUMO uses the logged timing as the existing plan. Do not use remembered values. The values 50 s and 20 to 30 s are not verified.

---

## 6. Counting Setup

### 6.1 Counting Lines

Do this for each approach.

1. Mark an arrival line upstream of the longest queue. Traffic must still move at this point.
2. Mark a stop line on the painted stop line.

**NOTE:** The stop-line count shows the discharge. When the junction is full, capacity limits the discharge. The arrival line shows the demand better.

### 6.2 Movements

1. Write down the movements of each approach: through, left, right, free left.
2. Write down the exit approach of each movement.
3. Check on the video if free-left lanes exist on the North, South, and East approaches (open item O9).

**NOTE:** SUMO builds the demand from the movements. SUMO has no vehicles without movements.

### 6.3 Vehicle Classes

1. Write down the vehicle types that you see in large numbers. Examples: car, two-wheeler, auto-rickshaw, bus, truck, tempo-traveller, light commercial vehicle.
2. Write down the fuel of the auto-rickshaws: petrol, diesel, CNG, or LPG. Count 20 autos at the roadside, or use a source that you can cite.
3. Write down other vehicles that matter. Examples: cycle rickshaws, handcarts. Each type needs a class. If not, the report states that the type is dropped.

**NOTE:** The default idle-fuel value is for a 2-stroke petrol auto. This value is probably wrong for Kerala.

---

## 7. Validation Data

The report must state the counting error for each approach and each class. This is the main test of credibility.

1. Choose sample clips of 2 minutes. Take clips from the start, the middle, and the end of each slot.
2. Take clips for each approach. Include the west approach. Mark where the visibility is poor.
3. Count the vehicles by hand from playback. Count for each line and each class.
4. Do not look at the numbers of the application before you count.
5. Write the counts in the format of `configs/manual_counts.example.csv`:
   `interval_start_s, interval_end_s, line_name, class, count`
6. Count each clip 2 times, or ask another person to check a sample. Record the difference between the 2 counts. The difference is the limit of the reference.
7. Keep the validation clips separate from the clips for labelling and training. Use a different time block.

**CAUTION**
**Do not train the model on the validation clips.**
**Do not change the settings to make the error smaller. Report the error as it is.**

---

## 8. Context Data (Optional)

Context data are never used for calibration.

1. Pollution-board readings: Kerala PCB continuous station near Plammoodu. The station is about 0.4 to 0.5 km from Pattom (to be confirmed). Get the hourly values for the same slots. Write the station name and the averaging interval (open item O12).
2. Traffic-police notes: signal changes, closures, and events on the recording days.
3. Fuel shares: use a local source. Cite the source.

---

## 9. Checklist

**Before you go to site**
- [ ] Phone is charged. 40 GB is free.
- [ ] Power bank, taped cable, clamp, and tether are ready.
- [ ] Steel tape, measuring wheel or laser meter, chalk or masking tape, notebook, and this guide are ready.
- [ ] Camera settings are correct (section 2).

**On site: set-up (once)**
- [ ] Camera position is marked and photographed. Reference photo is taken.
- [ ] 4 to 6 spread-out ground points are chosen, named, and photographed.
- [ ] The x and y values of all points are measured in 1 grid. Each distance is measured 2 times.
- [ ] 3 or more check distances are measured between points that are far apart.
- [ ] Width and lane count are measured for each approach. Gradient, parking, and bus-stop notes are written.
- [ ] Signal heads are named and linked to approaches. Free-left movements are written down.
- [ ] Fuel mix of the autos is written down.

**On site: each slot**
- [ ] Slot log is started: date, start time, weather.
- [ ] Reference photo is taken at the start.
- [ ] File changes are checked. Unusual events are written down.
- [ ] Reference photo is taken at the end. The camera did not move.

**After you record**
- [ ] Original files are copied from the phone and backed up.
- [ ] Signal timing is logged on the Signal Timings page: 3 or more cycles for each head.
- [ ] Ground points, lines, areas, and widths are entered on the Calibrate page.
- [ ] Manual counts are written: 2-minute clips, different times, each approach.
- [ ] Problems and unusual items are written in the slot log.

---

## 10. What Each Item Is Used For

| You collect | The application uses it for | If it is missing |
|---|---|---|
| Spread-out ground points and tape checks | Queue length, speed, stopped-delay test, stop points, widths | The metres are not reliable. Queue and delay are not trustworthy. |
| Road widths, lane counts, gradient | Saturation flow, capacity, V/C (IRC SP 41) | V/C cannot be calculated. |
| Signal log (3 or more cycles for each head) | Green time and cycle time, queue at green, existing plan in SUMO | The indicators and SUMO stay locked. |
| Movements (entry line to exit line) | SUMO demand and routes | SUMO has no vehicles. |
| Manual counts | Counting error for each approach and class | The counts are not validated. |
| Slot log | Slot conditions in the report | The comparison cannot state its conditions. |
| Fuel mix of the autos | CO2 for each vehicle class | The emission estimate uses an assumption. |

---

## 11. What the Application Does Not Do

- It does not read the traffic lights from the video.
- It does not find the fuel type, the model year, or the emission standard from the video.
- It does not give metres without a ground check. It does not give metres outside the calibrated area.
- It does not decide your problem rules, your alternative plans, or your MCE weights. You and your guide decide these.
- SUMO results never go into the MCE. SUMO gives a separate, simulated comparison.

---

**Note on the style:** This guide follows the writing rules of ASD-STE100 as far as the author can apply them: short sentences, one instruction in each sentence, active voice, present tense, numbered steps, and WARNING and CAUTION blocks. The author did not check each word against the official STE dictionary. A technical-writing check against the official dictionary is possible if the guide must be certified.
