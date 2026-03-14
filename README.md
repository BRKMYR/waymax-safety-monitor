# Waymax Safety Monitor Dashboard

**Status: In Development — Q1 2026**

Real-time safety monitoring dashboard for autonomous fleets — teleoperation trigger detection built on Waymax and Waymo Open Motion Dataset.

This is an operations monitoring screen, not a simulator. It answers one question: **when should a remote operator take over?**

---

## Why This Matters

Commercial robotaxi fleets rely on remote human operators as a safety backstop. This is not a failure mode; it is the architecture. Waymo, Cruise, and Zoox all employ teleoperators who can intervene when a vehicle encounters a situation beyond its autonomous capabilities. The ratio of operators to vehicles, the latency of intervention, and the decision criteria for when to intervene are among the most operationally critical parameters in any commercial AV deployment.

The unsolved problem is **when** to trigger teleoperation. Too early wastes expensive human operator time and reduces fleet throughput. Too late creates safety incidents. Current approaches are largely reactive: the vehicle requests help when it is already stuck or uncertain. A monitoring dashboard enables **proactive** intervention by giving operators situational awareness before the vehicle reaches a failure state.

This project uses real driving data from the Waymo Open Motion Dataset — logged scenarios from Waymo's fleet operating in San Francisco and Phoenix. These are not synthetic toy environments. They contain the full complexity of urban driving: unprotected turns, pedestrian crossings, cyclists, construction zones, and multi-agent interactions that expose the edge cases where teleoperation decisions matter most.

The gap between "autonomous vehicle that works in simulation" and "autonomous fleet that operates commercially" is an operations problem. This dashboard sits in that gap.

---

## What This Project Does

Takes Waymax scenarios — each containing 9.1 seconds of multi-agent driving data from real San Francisco and Phoenix roads — runs them through a safety analysis pipeline, and renders the results as a real-time ops dashboard in pygame. The dashboard shows what a fleet safety operator would see: a tactical map of the scenario, risk indicators per vehicle, teleoperation trigger alerts, and an event timeline.

What this is **not**:

- Not a self-driving stack. No perception, no planning, no control.
- Not a simulator. Waymax is the simulator. This is a monitoring layer on top.
- Not a web app. Native 2D rendering for full control over the visual output and update loop.

---

## Dashboard Components

### 1. Top-Down Scenario Viewer

Renders the Waymax road graph — lanes, crosswalks, stop signs, speed bumps, road boundaries — as a 2D tactical map. All agents (ego vehicle, other vehicles, pedestrians, cyclists) are drawn as oriented bounding boxes with heading indicators. The viewer supports scenario playback: play, pause, step forward, step backward, and timeline scrubbing across all 91 timesteps.

The coordinate system comes directly from Waymax. No projection pipeline needed; the data is already in local metric coordinates centered on the ego vehicle.

### 2. Per-Vehicle Risk Indicators

Each vehicle carries a colored halo indicating its current risk level:

| Level | Meaning |
|-------|---------|
| **GREEN** | Nominal. No safety concerns detected. |
| **AMBER** | Elevated risk. One or more metrics approaching thresholds. Operator should monitor. |
| **RED** | Critical. Immediate teleoperation trigger. Operator intervention recommended. |

Risk classification is computed per timestep from a composite of proximity, speed, lane compliance, and heading alignment metrics. Halos are rendered as semi-transparent rings around the vehicle bounding box, with intensity proportional to risk severity.

### 3. Teleoperation Trigger Panel

A side panel listing vehicles that have crossed intervention thresholds. Each trigger entry shows:

- Vehicle ID
- Trigger reason (e.g., "TTC < 2.0s with pedestrian", "off-road excursion", "wrong-way heading")
- Severity (amber / red)
- Timestamp within the scenario

Trigger conditions are configurable. Thresholds can be adjusted to model different operator intervention policies — conservative (trigger early, high operator load) versus permissive (trigger late, higher autonomy trust).

### 4. Incident Timeline

A scrollable chronological log of safety events during scenario playback. Events include near-misses, lane departures, speed violations, bounding box overlaps, and teleoperation triggers. Each event entry is timestamped relative to scenario start (0.0s to 9.1s) and selectable — clicking an event jumps the scenario viewer to that timestep.

The timeline serves as both a real-time feed during playback and a post-hoc analysis tool for reviewing what happened and when.

### 5. Fleet Aggregate Panel

Top-level statistics across all agents in the current scenario:

- Fleet safety score (weighted composite of all per-vehicle risk scores)
- Total violations by category (overlap, off-road, wrong-way)
- Total teleoperation triggers fired
- Worst-case vehicle and worst-case timestep
- Agent count breakdown (vehicles, pedestrians, cyclists)

---

## Safety Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| Collision / Overlap | Waymax `overlap` | Bounding box overlap between any two agents |
| Off-Road | Waymax `offroad` | Vehicle center or bounding box outside drivable area |
| Wrong-Way | Waymax `wrong_way` | Vehicle heading misaligned with lane direction |
| Log Divergence | Waymax `log_divergence` | Deviation from the recorded real-world trajectory |
| Time to Collision (TTC) | Custom | Estimated time until bounding box intersection at current velocities |
| Lane Compliance Score | Custom | Composite of lateral offset from lane center and heading alignment |

Waymax provides the first four metrics natively through its reward/metric API. TTC and lane compliance are custom metrics computed from Waymax state data (agent positions, velocities, headings, and road graph geometry).

The composite risk score that drives the green/amber/red classification is a weighted combination of all six metrics, with weights configurable per deployment policy.

---

## Visual Design

The dashboard uses a dark theme, high contrast aesthetic. Design principles:

- **Dark background** with light road graph edges and muted lane boundaries. The map recedes; operational data comes forward.
- **Agent bounding boxes** rendered as oriented rectangles with heading arrows. Ego vehicle visually distinct from other agents.
- **Risk halos** as semi-transparent colored rings around vehicles. Color intensity scales with risk severity.
- **Side panels** use monospace text for the teleoperation trigger list and incident timeline. Dense, scannable, no decoration.
- **Information hierarchy** controlled by visual weight. Critical alerts (red halos, active triggers) dominate. Nominal state (green halos, empty timeline) fades into the background.

The visual language is deliberately utilitarian — closer to an air traffic control display than a consumer ride-hailing app. Every pixel carries operational meaning.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Simulation Engine | Waymax (JAX-based) |
| Driving Data | Waymo Open Motion Dataset (WOMD) |
| 2D Rendering | pygame-ce |
| Computation | JAX, NumPy |
| Safety Metrics | Waymax metrics + custom |
| Language | Python |

The stack is intentionally minimal. Waymax provides the simulation backbone and data pipeline. pygame-ce provides the rendering surface. Everything between is Python and NumPy.

JAX is required as a Waymax dependency. GPU acceleration via CUDA is beneficial for batch scenario processing but not mandatory — JAX runs on CPU for single-scenario dashboard use.

---

## Data

This project uses the **Waymo Open Motion Dataset (WOMD)**, which contains real logged driving scenarios from Waymo's autonomous fleet operating in San Francisco and Phoenix.

- Each scenario is approximately 9.1 seconds at 10Hz (91 timesteps)
- Scenarios contain: full road graph (lanes, boundaries, crosswalks, signals), all agent trajectories (vehicles, pedestrians, cyclists), and traffic signal states
- The dataset contains 100,000+ scenarios covering diverse urban driving situations
- Data access requires free registration at [waymo.com/open](https://waymo.com/open)

The dataset is available for non-commercial research use under the Waymo Open Dataset License. This is real driving data, not synthetic generation — every scenario in the dataset was recorded by a Waymo vehicle on public roads.

---

## Project Roadmap

### Phase 1: Data Pipeline and Scenario Rendering

- Set up Waymax data loading from WOMD
- Parse road graph (lanes, crosswalks, boundaries, traffic signals)
- Render top-down scenario view in pygame-ce (road graph + agent bounding boxes)
- Implement scenario playback controls (play, pause, step, scrub)

### Phase 2: Safety Metrics Engine

- Integrate Waymax built-in metrics (overlap, offroad, wrong_way, log_divergence)
- Implement custom TTC calculation between all agent pairs
- Build lane compliance scoring from road graph geometry
- Compute per-vehicle composite risk score (green / amber / red classification)
- Render risk halos on the scenario viewer

### Phase 3: Teleoperation Trigger System

- Define configurable trigger thresholds (TTC < Xs, risk score > Y)
- Build trigger detection engine evaluating every timestep
- Render teleoperation trigger panel with live alerts
- Build incident timeline with event logging
- Implement timeline-to-viewer linking (click event to jump to timestep)

### Phase 4: Fleet Dashboard and Polish

- Aggregate statistics panel (fleet safety score, violation counts)
- Multi-scenario batch analysis (run N scenarios, aggregate results)
- Dashboard layout refinement and visual polish
- Screenshot and recording export for presentation
- Documentation and usage guide

---

## Project Structure

```
waymax-safety-monitor/
├── src/
│   ├── data/           # Waymax data loading and preprocessing
│   ├── metrics/        # Safety metrics (built-in + custom TTC, lane compliance)
│   ├── triggers/       # Teleoperation trigger logic and thresholds
│   ├── renderer/       # pygame-ce rendering (map, agents, halos, panels)
│   └── dashboard/      # Dashboard layout, state management, playback controls
├── scenarios/          # Sample scenario configurations
├── tests/
├── README.md
└── pyproject.toml
```

---

## References

- **Waymax** — Gulino et al., "Waymax: An Accelerated, Data-Driven Simulator for Large-Scale Autonomous Driving Research" (2023). [GitHub](https://github.com/waymo-research/waymax)
- **Waymo Open Motion Dataset** — Ettinger et al., "Large Scale Interactive Motion Forecasting for Autonomous Driving: The Waymo Open Motion Dataset" (2021). [waymo.com/open](https://waymo.com/open)
- **SAE J3016** — Taxonomy and definitions for terms related to driving automation systems
- **ISO 34503** — Taxonomy for [redacted] for automated driving systems

---

## License

MIT

This project's source code is MIT licensed. Note that Waymax and the Waymo Open Motion Dataset have their own license terms (non-commercial research use). See their respective repositories for details.

---

## Author

[BRKMYR](https://github.com/BRKMYR)
