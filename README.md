# Waymax Safety Monitor

Real-time safety monitoring dashboard for autonomous fleets: teleoperation trigger detection on driving scenarios in the Waymax and Waymo Open Motion Dataset (WOMD) data shape. The shipped demo runs on synthetic scenes; an optional adapter loads real WOMD scenarios through Waymax if you have access to the dataset.

An operations monitoring surface, not a simulator. It answers one question: **when should a remote operator take over?**

The dashboard consumes 91-timestep (9.1 s at 10 Hz) driving scenarios in the Waymax / WOMD shape, computes per-agent safety metrics, and fires edge-triggered teleoperation events (AMBER escalating to RED) with per-agent kind fields (TTC, overlap, off-road, wrong-way, lane compliance, composite, hard-brake, stalled, VRU proximity).

## Quickstart

Requires Python 3.11+.

```bash
git clone https://github.com/BRKMYR/waymax-safety-monitor.git
cd waymax-safety-monitor
pip install -e ".[dev]"

# Interactive dashboard on a bundled synthetic scenario.
safety-monitor --scenario intersection_conflict

# Or as a module:
python -m src.dashboard.app --scenario hard_brake
```

Keyboard: Space play/pause, arrows step, +/- speed, F fit view, R reset, Home/End jump, 1-5 switch scenario, Q/Esc quit. Mouse: drag to pan, scroll to zoom, click on the playback bar to scrub, click on the timeline to jump.

## Bundled scenarios

All five ship in the repo. No dataset download required.

| Key | Name | Description | Notable trigger |
|-----|------|-------------|-----------------|
| 1 | `intersection_conflict` | 4-way intersection, five vehicles, one pedestrian, one cyclist, signalized | Multiple TTC + composite events |
| 2 | `highway_merge` | Three-lane highway, ramp merger cutting into ego lane | TTC / composite on merge |
| 3 | `pedestrian_crossing` | Two-lane road with two pedestrians on a crosswalk | VRU proximity on ego |
| 4 | `hard_brake` | Lead vehicle decelerates at -6 m/s^2 at t=31 (noise-free) | `hard_brake` RED at (agent 1, t=31) |
| 5 | `stalled_ego` | Ego rolls to a stop; dwell-counter completes at t=68 (noise-free) | `stalled` RED at (agent 0, t=68) |

`hard_brake` and `stalled_ego` are analytically constructed and byte-identical across seeds; the other three include per-timestep Gaussian jitter seeded by `--seed` (default 42).

## Configuring the run

Trigger thresholds ship as three presets:

```bash
safety-monitor --scenario intersection_conflict --policy conservative
safety-monitor --scenario intersection_conflict --policy default
safety-monitor --scenario intersection_conflict --policy permissive
```

A JSON run-config selects scenario, seed, trigger policy, per-field trigger overrides, and risk-scoring weights. See `scenarios/default.json`. Unknown keys raise a config error rather than being silently ignored.

```bash
safety-monitor --config scenarios/default.json
```

CLI flags win over config-file values, so `--config scenarios/default.json --policy permissive` uses the permissive preset with everything else from the file.

## Headless mode: screenshots and CI

The dashboard runs without a display via SDL's dummy driver. It writes one PNG per timestep and a sorted `events.json` for offline inspection.

```bash
safety-monitor \
  --scenario hard_brake \
  --headless \
  --frames-out docs/screenshots/hard_brake \
  --events-out docs/screenshots/hard_brake/events.json \
  --frame-stride 1
```

Frames are named `frame_000.png` .. `frame_090.png`. Events are sorted by `(timestep, agent_id, kind)` and every entry carries `agent_id, agent_type, timestep, time_seconds, severity, kind, reason, metric_value`. This is the same path CI runs to assert that the `hard_brake` scenario emits exactly one `hard_brake` RED event at `(agent_id=1, timestep=31)`.

Use `--frame-stride 10` to keep only every tenth frame (useful for compact demo GIFs).

## Loading real WOMD data (optional)

Waymo Open Motion Dataset support ships as an optional extra to keep the base install lightweight:

```bash
pip install -e ".[waymax]"
safety-monitor --womd-path /path/to/womd.tfrecord --womd-index 0
```

Data access requires registration at [waymo.com/open](https://waymo.com/open); the license is non-commercial research use. The Waymax adapter is written against the waymax 0.2 API (`SimulatorState.log_trajectory`, `.roadgraph_points`); mismatches raise a clearly labeled `AttributeError`.

## Safety metrics

| Metric | Description |
|--------|-------------|
| Overlap | Bounding-box overlap fraction between any two agents |
| TTC | Time to collision estimated from current-frame positions, velocities, and bounding boxes |
| Off-road | Fraction of ego bounding box outside road edges. Pedestrians are excluded (return 0). |
| Wrong-way | Heading misalignment with the closest lane-center segment. Direction is encoded by the ordering of lane points. Pedestrians excluded. |
| Lane compliance | Combined lateral offset from lane center + heading alignment. Pedestrians excluded (return 1.0). |
| Composite | Weighted sum, gated by AMBER / RED thresholds. Weights live in `RiskConfig`. |
| Hard brake | Per-vehicle longitudinal acceleration <= configured floor (default -4 m/s^2). |
| Stalled | Vehicle speed below floor for a dwell counter of consecutive timesteps. |
| VRU proximity | Vehicle within a distance floor of a pedestrian or cyclist, gated on ego speed. |

The trigger engine is edge-triggered: a given `(agent_id, kind)` pair fires exactly once at the inactive-to-active transition, and again on an AMBER -> RED escalation. After the condition clears for `rearm_clear_steps` consecutive steps the pair re-arms.

## Layout

```
waymax-safety-monitor/
  src/
    data/         # scenario dataclasses, demo generator, WOMD loader (optional)
    metrics/      # safety metrics + composite risk
    triggers/     # thresholds, edge-triggered engine, trigger events
    renderer/     # map, agents, panels (pygame-ce)
    dashboard/    # state, layout, headless mode, event loop
  scenarios/      # run-config JSONs
  tests/
  docs/
  pyproject.toml
```

## Tests

```bash
pytest -v
```

Coverage highlights:

- Analytic acceptance: `hard_brake` fires exactly one `hard_brake` RED at `(1, 31)`; `stalled_ego` fires exactly one `stalled` RED at `(0, 68)`.
- Edge-trigger semantics: single event per active window; AMBER->RED escalation emits two events; re-arm after `rearm_clear_steps`.
- Determinism: two independent headless runs of `hard_brake` produce byte-identical `events.json`.
- Pedestrian exclusion for off-road, wrong-way, and lane-compliance metrics.
- Kind integrity: every fired event's `kind` is in the closed set defined in `docs/ARCHITECTURE.md`.

## References

- Gulino et al., "Waymax: An Accelerated, Data-Driven Simulator for Large-Scale Autonomous Driving Research", 2023.
- Ettinger et al., "Large Scale Interactive Motion Forecasting for Autonomous Driving: The Waymo Open Motion Dataset", 2021.

## License

MIT, see [LICENSE](LICENSE). Waymax and the Waymo Open Motion Dataset carry their own non-commercial research licenses and are not included: the Waymax adapter is an optional extra, and dataset access requires your own registration at waymo.com/open.
