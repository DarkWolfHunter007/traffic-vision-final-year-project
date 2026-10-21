# 10-minute trial run: steps and alignment tips

## Before you start
- Cut the clip from the downloaded video. Never edit the original.
  `ffmpeg -ss 00:10:00 -i data/raw/FULL.MOV -t 600 -c copy data/raw/trial_10min.MOV`
- Pick a busy 10 minutes with **at least 3 full signal cycles** for every approach.
- Run `git pull`, then `uv run pattom editor`.

## Order of work

| Step | Where | What |
|---|---|---|
| 1 | Editor, cfr node | Set `video` to the trial clip, `out` to `data/cfr/trial_10min.mp4`, and `slot` to `trial`. Run up to **track** with *Run Selected*. |
| 2 | Calibrate → Ground points | Map pixels to metres (tips below). |
| 3 | Calibrate → Counting lines | Draw arrival and stop lines for each approach (tips below). |
| 4 | Calibrate → Approach areas | Draw one queue area per approach, click its stop point, and type its signal head. |
| 5 | Calibrate → Road widths | Click the two road edges at each stop line, or type a tape width. |
| 6 | Signal Timings | Log every light change for each head over the 10 min. |
| 7 | `configs/lines.yaml` | Add the movements (entry line → exit line). |
| 8 | Editor | **Run** the whole chain. Read the checklist at the end of the log. |
| 9 | Review node | Look through the flagged crops. Note where autos, buses or far vehicles are wrong. |
| 10 | Manual counts | Count 2 minutes by hand, then run `pattom count-check`. |

## Tips: ground points (the most important step)
- **Spread the points out.** Pick 4 to 6 points around the **whole** area you will measure, for example the stop-line corners on opposite arms, a median tip and a kerb corner. Points close together, like one zebra stripe, give large errors far away.
- **Use points flat on the road surface:** paint corners, kerb bases. Never use pole tops or vehicles.
- **Measure their positions in one site grid.** Take one corner as (0, 0) and run x along one road edge. Use a tape, or the marking sizes if you know them for certain.
- **Add at least one check point or tape distance far from the fit points.** Its error is your accuracy. Aim for well under 0.5 m before trusting queue lengths.
- **Make the valid area cover only the road you need.** Points outside it get no metres, by design.
- **Click at 75 or 100% zoom.** One pixel off at the far arm can be tens of centimetres.

## Tips: counting lines
- Draw **across the full width** of the lanes, at a right angle to the traffic.
- **Arrival lines** go upstream of the longest queue, where traffic still moves. They measure demand.
- **Stop lines** go on the painted stop line. They measure discharge.
- Put lines **where vehicles are clearly visible and not hidden by others.** Avoid the far edge of the frame.
- The arrow must point the way traffic goes. Use **flip** if it doesn't.

## Tips: camera and video
- **Same camera position for every recording.** Clamp and tether the camera (it sits near a drop edge).
- **No zoom changes during recording.** A changed zoom makes all calibration wrong.
- **Record when the light is steady.** Rain and night glare make detection weaker.

## What "good" looks like after the trial
- Every node is ✓, or 🔒 with a reason you expect.
- The ground check error is small, and the queue lengths look right when you watch the video.
- Review shows few class changes, and autos are labelled auto_rickshaw.
- `count-check` error is within what you and your guide accept, per approach and class.
