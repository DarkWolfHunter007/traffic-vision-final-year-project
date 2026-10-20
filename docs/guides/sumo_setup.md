# Filling in steps H to M (problems to SUMO)

Two files drive the last seven nodes. Copy each from its `.example.yaml`, fill it in, and the node unlocks. A node stays **Locked** and names what is missing until then. Nothing has a default.

| File | Nodes |
|---|---|
| `configs/decision.yaml` | problems, alternatives, pre_sumo, mce |
| `configs/sumo.yaml` | sumo_inputs, sumo_run, comparison |

A working example with made-up TEST values is in `configs/flowtest/`. Use it to see the format only; none of its numbers are site data.

## Before SUMO can run: movements

SUMO needs to know where vehicles go. In `configs/lines.yaml`, add `movements`. Each one is an entry line and an exit line:

```yaml
movements:
  - {approach: north, movement: through, entry_line: N_arrival, exit_line: S_arrival}
  - {approach: north, movement: left,    entry_line: N_stop,    exit_line: E_exit}
```

A vehicle gets a movement only when its track crosses the entry line **and later** the exit line. A clip of a few seconds rarely has any, so SUMO gets no demand. That is why the 2.6 s test clip stops at `sumo_inputs`: "no routable flows". A clip of a few minutes is enough to test it.

## configs/decision.yaml

```yaml
rules:                 # H: what counts as a problem (your thresholds)
  - {indicator: vc_ratio, op: '>', value: 0.85, problem: "north over capacity"}
head_groups: {N: NS, S: NS, E: EW, W: EW}   # signal head in signal_log.csv -> phase group
alternatives:          # I: at least two timing plans, each answering a problem
  - id: A1
    description: longer NS green
    control: fixed
    problem_addressed: "north over capacity"   # same text as the rule
    plan: {cycle_s: 120, groups: {NS: {green_s: 60, amber_s: 3}, EW: {green_s: 50, amber_s: 3}}}
pre_sumo:              # J: how plans are scored before SUMO (O13)
  approach_groups: {north: NS, south: NS, east: EW, west: EW}
  effective_green: displayed_green
  congestion_measure: max_vc
  volume_stat: max
  delay_method: none
mce:                   # K: the five criteria (O13)
  weights: {congestion: , emission: , safety: , cost: , land: }   # add up to 1
  directions: {congestion: higher_is_better, emission: higher_is_better, safety: higher_is_better, cost: lower_is_better, land: lower_is_better}
  manual_scores: {safety: {A1: , A2: }, cost: {A1: , A2: }, land: {A1: , A2: }}
  scale: "1-5, 5 best"
  equal_criterion: score_zero
  sensitivity_step: 0.1
```

The numbers in this example only show the format. Every threshold, plan and weight is your decision and needs the guide's agreement.

## configs/sumo.yaml

```yaml
centre_xy: [0, 0]                 # junction centre, metres
approaches:                       # one per arm: where the modelled road starts, lanes, speed
  north: {end_xy: [0, 150], lanes_in: , lanes_out: , speed_kmh: }
  south: {end_xy: [0, -150], lanes_in: , lanes_out: , speed_kmh: }
  east:  {end_xy: [150, 0], lanes_in: , lanes_out: , speed_kmh: }
  west:  {end_xy: [-150, 0], lanes_in: , lanes_out: , speed_kmh: }
vtypes:                           # one per class you count
  car:         {length_m: , min_gap_m: , max_speed_kmh: , accel: , decel: }
  two_wheeler: {length_m: , min_gap_m: , max_speed_kmh: , accel: , decel: }
  bus:         {...}
  truck:       {...}
inputs:
  approach_groups: {north: NS, south: NS, east: EW, west: EW}
  phase_order: [NS, EW]
  all_red_s:                      # measured from the footage
  demand_line_type: arrival       # arrival lines = demand; stop lines = discharge
  unknown_movement: exclude       # or proportional
run:
  seeds: [1, 2, 3, 4, 5]          # choose before running; the same for both cases
  warmup_s:
comparison:
  emission_method: none           # or registered_idle_factors (O18)
```

Where each value comes from:

- **Lanes, speed limit, arm lengths:** the site, or a map you are allowed to use.
- **Vehicle sizes and accelerations:** the footage or a registered source. SUMO's own defaults are not allowed (D15).
- **All-red time:** read from the footage.
- **Seeds:** pick them before the runs.

## What SUMO runs

Only two cases: the **existing** plan (from `signal_log.csv`) and the **one alternative the MCE selected**. Results are simulated values, kept apart from the video measurements, and never fed back into the MCE (D1).
