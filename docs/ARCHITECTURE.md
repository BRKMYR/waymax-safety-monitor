# ARCHITECTURE.md — Waymax Safety Monitor: One-Shot "FINISH IT" Implementation Spec

> **Audience:** a single implementation agent (Opus-class) executing this spec in one run, without
> asking questions. Everything needed is in this document plus the existing code. All claims about
> the existing code below were verified by reading every file and by executing the test suite and a
> headless render on 2026-07-12 (Python 3.14.3, numpy 2.5.1, pygame-ce 2.5.7, macOS ARM):
> **41/41 existing tests pass; the dashboard draws headless under `SDL_VIDEODRIVER=dummy`; a full
> 91-timestep trigger sweep of all three demo scenarios is deterministic across runs.**
> Do not invent APIs for existing modules — the public APIs transcribed in Section 6 are the real ones.

---

## 1. Context & Positioning

This repository is the fleet-operations / safety-monitoring artifact in the owner's portfolio. The
owner's one-liner: *"I build the software, data, and validation platforms that let machines operate
safely in the physical world."* The target reviewer is a hiring manager on an AV/robotaxi
**operations and assurance** team. That reviewer will spend roughly three minutes: clone, run one
command, see an ops screen that looks like it belongs in a fleet operations center, skim the
metrics code, and check whether the tests are honest. The spec therefore optimizes for one thing:
a working, deterministic, offline, visually credible end-to-end demo — not for feature breadth.

The product (per the existing README, which is accurate to the intent): a real-time safety
monitoring dashboard for autonomous fleets. It answers one operational question — **when should a
remote operator take over?** Commercial robotaxi fleets (Waymo, Zoox) use remote operators as an
architectural safety backstop; the open problem is proactive trigger timing. This dashboard takes
9.1-second, 91-timestep multi-agent driving scenarios, runs a heuristic safety-metrics pipeline
(TTC, overlap, off-road, wrong-way, lane compliance, composite risk), fires configurable
teleoperation triggers, and renders everything as a pygame ops dashboard: top-down tactical map,
per-vehicle risk halos, teleop trigger panel, incident timeline, fleet aggregate panel, playback
controls.

The project pivoted away from an earlier operational-zones concept. **That concept is forbidden**:
the spec and the resulting code must not reintroduce any form of zone, geo-fence, or [redacted]-region
management (see Non-Goals, Section 3). The current codebase is already clean of it — keep it that
way. The credibility anchor is instead the *Waymax/WOMD-shaped data model*: the internal `Scenario`
dataclasses mirror Waymo Open Motion Dataset structure (91 steps @ 10 Hz, road graph polylines,
typed agents), a real `waymax_loader.py` exists as an optional path, and the bundled synthetic
scenarios are stand-ins with the same shape — stated honestly in the README.

---

## 2. One-Shot Scope Statement

**Goal of this run:** take the current implementation — which is roughly 85% complete and largely
working — to a finished, demonstrable v1. Concretely:

1. **Fix four verified defects** (Section 6, TO-FIX rows): the precompute-wipe bug, the
   level-triggered event spam, the wrong-way/lane-compliance false positives on oncoming traffic and
   pedestrians, and the dead `scenarios/default.json` config file.
2. **Build headless mode as a first-class deliverable**:
   `python -m src.dashboard.app --headless --frames-out docs/screenshots/<name>/` dumps 91
   deterministic PNG frames plus an `events.json`; this is the CI acceptance path and the
   screenshot source.
3. **Extend the bundled scenario set from 3 to 5** deterministic offline scenarios that together
   exercise every trigger type, adding two new noise-free scenarios (`hard_brake`, `stalled_ego`)
   with by-construction exact trigger timesteps.
4. **Add three cheap heuristic trigger types** the new scenarios exercise: hard-brake anomaly,
   stalled vehicle, VRU (pedestrian/cyclist) proximity.
5. **Extend tests** to ≥ 60 passing, including hand-computed metric cases, exact-timestep trigger
   assertions, and a headless integration + determinism test.
6. **Update README + pyproject + add CI workflow** to match reality.

**Environment constraints (binding):**

- Python **3.11+** (verified working on 3.14.3). macOS ARM primary; Linux CI.
- **No GPU. No network at runtime. No account signups.** The default demo path is fully offline.
- Core runtime deps: **numpy + pygame-ce only**. TF/JAX/waymax live exclusively behind the
  `[waymax]` optional extra and are never imported on the default path (already true — keep it so).
- WOMD data requires Google registration + license acceptance; therefore `waymax_loader.py` + WOMD
  remain an **optional, documented** path — never required for demo, tests, or CI.
- Headless rendering via `SDL_VIDEODRIVER=dummy` (verified working with pygame-ce 2.5.7 on macOS).
- Determinism: identical CLI invocation ⇒ byte-identical PNG frames and `events.json` on the same
  machine (font rasterization may differ across OSes; determinism is asserted same-machine only).
- Keep the monochrome/tactical dark visual language exactly as defined in
  `src/renderer/colors.py`. Do not redesign the palette; new UI elements must use existing
  `Colors` constants (add new constants only if strictly necessary, in the same muted register).

**What "done" means:** every acceptance criterion in Section 8 passes as written.

---

## 3. Non-Goals (with reasons)

| Non-goal | Reason |
|---|---|
| **[redacted] / zone / geo-fence management of any kind** (drawing, storing, editing, or evaluating geographic operating regions or zone polygons) | **Out of scope by design.** The project deliberately stays at the monitoring/trigger layer to avoid overlapping adjacent commercial products in this space. Do not add zone concepts to code, config schemas, UI, or docs. Crosswalk/road-graph polygons from scenario data are fine; *operator-managed regions* are not. |
| Live fleet data / real telemetry ingestion | v1 is a scenario-replay analysis tool; live ingestion is a different product with different infra. |
| Web UI | Native pygame rendering is a stated design choice (full control of the draw loop); a web port adds a build system and no reviewer value. |
| WOMD download in CI or tests | Requires Google account + license acceptance; violates the offline constraint. WOMD stays an optional local path. |
| Actual teleoperation control loop (sending commands to a vehicle) | This is a *monitoring* dashboard; closing the loop implies a vehicle stack that doesn't exist here. |
| ML-based risk models | v1 is heuristic-only by design: inspectable, testable with hand-computed cases, zero training data needed. ML ranking is Deferred v2. |
| Occlusion / perception-uncertainty metrics | No uncertainty signal exists in the data model; a heuristic proxy would be fake. Deferred v2 (Section 12). |
| Multi-scenario batch analytics, video export, config-editing UI | Polish beyond the demo's needs; deferred. |

---

## 4. System Overview

```
                         DEFAULT (offline)                     OPTIONAL (extra: [waymax])
                 ┌────────────────────────────┐          ┌─────────────────────────────────┐
                 │ src/data/demo_loader.py    │          │ src/data/waymax_loader.py       │
                 │ 5 bundled deterministic    │          │ WOMD TFRecord → Scenario        │
                 │ scenario builders (numpy)  │          │ (requires waymax+jax+tf, local  │
                 └─────────────┬──────────────┘          │  WOMD download, never in CI)    │
                               │                         └───────────────┬─────────────────┘
                               ▼                                         │
                 ┌────────────────────────────────────────────┐          │
                 │ src/data/scenario.py                       │◄─────────┘
                 │ Framework-agnostic dataclasses (numpy only)│
                 │ Scenario / AgentTrajectory / RoadGraph ... │
                 └─────────────┬──────────────────────────────┘
                               │ Scenario
              ┌────────────────┼───────────────────────┐
              ▼                ▼                       │
┌───────────────────────┐  ┌──────────────────────┐    │
│ src/metrics/safety.py │  │ src/metrics/         │    │
│ per-timestep raw      │─▶│ composite.py         │    │
│ metrics: overlap,     │  │ weighted risk score, │    │
│ offroad, wrong-way,   │  │ GREEN/AMBER/RED      │    │
│ TTC, lane compliance  │  │ (RiskConfig)         │    │
└───────────────────────┘  └──────────┬───────────┘    │
                                      │ dict[int, AgentRisk]
                                      ▼                │
                        ┌─────────────────────────────┐│
                        │ src/triggers/engine.py      ││
                        │ TriggerEngine (edge-        ││
                        │ triggered, per-agent state) ││
                        │ + config.py (TriggerConfig, ││
                        │ policy presets)             ││
                        └──────────────┬──────────────┘│
                                       │ list[TriggerEvent]
                                       ▼                ▼
                        ┌───────────────────────────────────────┐
                        │ src/dashboard/state.py                │
                        │ DashboardState: playback, precomputed │
                        │ event timeline, current risks         │
                        └──────────────┬────────────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │ src/dashboard/app.py — DashboardApp                      │
        │  ├── interactive loop (pygame window, 60 fps)            │
        │  └── headless loop (--headless: SDL dummy, PNG frames,   │
        │      events.json)                    [TO-BUILD]          │
        │ renderers: map_renderer / agent_renderer /               │
        │            panel_renderer / colors                       │
        └──────────────────────────────────────────────────────────┘
```

**Component summaries** (one paragraph each):

- **`src/data/scenario.py`** — pure-numpy dataclasses mirroring Waymax/WOMD structure so that
  metrics and rendering never depend on JAX/TF. `Scenario` holds agents (`AgentTrajectory` with
  per-timestep arrays), a `RoadGraph` (lane polylines, road edges, crosswalks, stop signs, speed
  bumps), traffic signals, and playback metadata (91 steps, 0.1 s each). Working; unchanged in
  this run except one additive field (`LaneLine` gains nothing — lane direction is encoded by
  point ordering, see Section 6).
- **`src/data/demo_loader.py`** — deterministic synthetic scenario builders keyed by name and seed.
  Currently ships `intersection_conflict`, `highway_merge`, `pedestrian_crossing`. This run fixes
  lane-direction ordering for opposing-traffic lanes and adds two noise-free scenarios
  (`hard_brake`, `stalled_ego`) with exact, hand-derivable trigger timesteps.
- **`src/data/waymax_loader.py`** — optional WOMD/Waymax adapter converting a Waymax
  `SimulatorState` to `Scenario`. Import-guarded; not exercised by tests or CI (deps unavailable
  offline). Leave functionally untouched; documented as unverified.
- **`src/metrics/safety.py`** — five raw per-timestep metrics over all active agents. TTC uses
  closed-form quadratic on bounding-circle closure; overlap uses SAT on oriented boxes. This run
  fixes wrong-way/lane-compliance/off-road applicability (vehicles+cyclists only) and
  direction-aware lane matching.
- **`src/metrics/composite.py`** — weighted composite risk score per agent + GREEN/AMBER/RED
  classification via `RiskConfig`. Working; unchanged.
- **`src/triggers/config.py` / `src/triggers/engine.py`** — configurable thresholds (with
  `conservative()` / `permissive()` presets) and the trigger engine. This run converts the engine
  from level-triggered (re-fires every timestep; measured 1,082 events in one 91-step scenario) to
  edge-triggered with re-arm, and adds hard-brake / stalled / VRU-proximity trigger kinds.
- **`src/renderer/*`** — pygame drawing: `map_renderer.py` (road graph + `Viewport` world↔screen
  transform), `agent_renderer.py` (oriented boxes, heading arrows, risk halos, trails),
  `panel_renderer.py` (trigger panel, incident timeline, fleet stats, playback bar), `colors.py`
  (the fixed dark/tactical palette). Working headless; one perf fix in trail drawing.
- **`src/dashboard/state.py` / `src/dashboard/app.py`** — playback state machine and the pygame
  app (layout, input handling, draw loop, CLI). This run fixes the precompute-wipe bug and adds
  the headless entry path.

---

## 5. Data Contracts

> **Hallucination firewall:** the schemas below are transcribed from the code and files as they
> exist. Where this run *extends* a contract, the extension is explicitly marked **[NEW]**.
> Anything not listed here does not exist. Field names are exact.

### 5.1 Run-config JSON (`scenarios/*.json`)

**As it actually is** in `scenarios/default.json` today. Currently **read by no code** (verified
by grep — this is the dead-config defect). This run wires it to a `--config PATH` CLI flag.

| Field | Type | Unit / domain | Maps to |
|---|---|---|---|
| `scenario` | string | one of the bundled scenario names (Section 5.6) | `load_demo_scenario(scenario_name=...)` |
| `seed` | int | RNG seed | `load_demo_scenario(seed=...)` |
| `trigger_policy` | string | `"default"` \| `"conservative"` \| `"permissive"` | `TriggerConfig()` / `.conservative()` / `.permissive()` |
| `risk_config` | object | see sub-fields | `RiskConfig(**risk_config)` |
| `risk_config.weight_overlap` | float | 0–1, weights sum to 1.0 | `RiskConfig.weight_overlap` |
| `risk_config.weight_offroad` | float | 0–1 | `RiskConfig.weight_offroad` |
| `risk_config.weight_wrong_way` | float | 0–1 | `RiskConfig.weight_wrong_way` |
| `risk_config.weight_ttc` | float | 0–1 | `RiskConfig.weight_ttc` |
| `risk_config.weight_lane_compliance` | float | 0–1 | `RiskConfig.weight_lane_compliance` |
| `risk_config.ttc_safe` | float | seconds; TTC ≥ this ⇒ zero TTC risk | `RiskConfig.ttc_safe` |
| `risk_config.amber_threshold` | float | composite score 0–1 | `RiskConfig.amber_threshold` |
| `risk_config.red_threshold` | float | composite score 0–1 | `RiskConfig.red_threshold` |
| `trigger_overrides` **[NEW, optional]** | object | any subset of `TriggerConfig` field names (Section 5.3) → float | applied via `dataclasses.replace` after the policy preset |

Complete example instance (this is the literal current content of `scenarios/default.json`, plus
nothing — the file is already valid against this schema; do not rewrite it, only *read* it):

```json
{
    "scenario": "intersection_conflict",
    "seed": 42,
    "trigger_policy": "default",
    "risk_config": {
        "weight_overlap": 0.25,
        "weight_offroad": 0.15,
        "weight_wrong_way": 0.15,
        "weight_ttc": 0.25,
        "weight_lane_compliance": 0.20,
        "ttc_safe": 6.0,
        "amber_threshold": 0.3,
        "red_threshold": 0.6
    }
}
```

Loader behavior: unknown top-level keys ⇒ `ValueError` naming the key. Missing `risk_config` /
`trigger_policy` ⇒ defaults. `--config` composes with other flags; explicit CLI flags win.

### 5.2 In-memory scenario contract (`src/data/scenario.py`) — EXISTS, transcribed

All arrays are numpy; world coordinates are local metric (meters), X east, Y north, headings in
radians CCW from +X. These dataclasses are the interchange format between loaders, metrics, and
renderers. **Do not change existing fields.**

- **`AgentType(IntEnum)`**: `VEHICLE = 0`, `PEDESTRIAN = 1`, `CYCLIST = 2`.
- **`SignalState(IntEnum)`**: `UNKNOWN = 0`, `GREEN = 1`, `YELLOW = 2`, `RED = 3`.
- **`AgentState`** (single agent, single timestep): `x: float` [m], `y: float` [m],
  `heading: float` [rad], `vx: float` [m/s], `vy: float` [m/s], `length: float` [m],
  `width: float` [m], `valid: bool = True`.
- **`AgentTrajectory`**: `agent_id: int`, `agent_type: AgentType`, and per-timestep arrays of shape
  `(num_timesteps,)`: `x`, `y`, `heading`, `vx`, `vy` (float32), `valid` (bool). Scalars
  `length: float`, `width: float`. Properties/methods: `num_timesteps -> int`,
  `state_at(t) -> AgentState`, `speed -> NDArray` (elementwise `sqrt(vx²+vy²)`).
- **`LaneLine`**: `points: NDArray[(N,2) float32]`, `lane_type: str` in
  `{"center", "left_boundary", "right_boundary"}`, `lane_id: int`. **Contract clarification
  [NEW, semantics only — no field change]:** for `lane_type == "center"`, the point ordering
  defines the legal travel direction (points[i] → points[i+1]). Demo builders must honor this.
- **`RoadEdge`**: `points: NDArray[(N,2) float32]`, `edge_type: str` in `{"boundary", "curb"}`.
- **`Crosswalk`**: `polygon: NDArray[(N,2) float32]`.
- **`TrafficSignal`**: `position: NDArray[(2,) float32]`, `states: NDArray[(T,) int32]`
  (SignalState values), `lane_id: int`.
- **`RoadGraph`**: `lanes: list[LaneLine]`, `road_edges: list[RoadEdge]`,
  `crosswalks: list[Crosswalk]`, `stop_signs: NDArray[(K,2) float32]`,
  `speed_bumps: NDArray[(K,2) float32]`.
- **`Scenario`**: `scenario_id: str`, `num_timesteps: int` (91), `timestep_duration: float`
  (0.1 s), `agents: list[AgentTrajectory]`, `road_graph: RoadGraph`,
  `traffic_signals: list[TrafficSignal]`, `ego_agent_id: int = 0`. Properties:
  `duration -> float` [s], `ego -> AgentTrajectory`,
  `agents_at(t) -> list[tuple[AgentTrajectory, AgentState]]` (valid agents only).

Example instance (minimal, as constructed in `tests/test_metrics.py::_make_single_agent_scenario`):
one `VEHICLE` at (100, 100), heading 0, one lane center from (−50, 0) to (50, 0), 1 timestep,
`timestep_duration=0.1`, `scenario_id="test"`.

### 5.3 Trigger config schema (`src/triggers/config.py`) — EXISTS + [NEW] fields

`TriggerConfig` dataclass. Existing fields (transcribed, with defaults):

| Field | Default | Unit / meaning |
|---|---|---|
| `ttc_red` | `2.0` | s — TTC ≤ this ⇒ RED |
| `ttc_amber` | `4.0` | s — TTC ≤ this ⇒ AMBER |
| `overlap_red` | `0.1` | overlap ratio 0–1 ⇒ RED |
| `overlap_amber` | `0.01` | overlap ratio ⇒ AMBER |
| `offroad_red` | `0.5` | off-road score 0–1 ⇒ RED |
| `offroad_amber` | `0.2` | ⇒ AMBER |
| `wrong_way_red` | `0.6` | fraction of π (≈108°) ⇒ RED |
| `wrong_way_amber` | `0.35` | (≈63°) ⇒ AMBER |
| `lane_compliance_red` | `0.3` | compliance ≤ this ⇒ RED (1.0 = perfect) |
| `lane_compliance_amber` | `0.5` | ⇒ AMBER |
| `composite_red` | `0.6` | composite score ⇒ RED |
| `composite_amber` | `0.3` | ⇒ AMBER |

Classmethod presets `conservative()` and `permissive()` exist with fully-specified overrides
(see file). **[NEW] fields to add** (also add sensible shifted values to both presets;
conservative = triggers earlier, permissive = later):

| Field | Default | Unit / meaning |
|---|---|---|
| `hard_brake_accel` | `-4.0` | m/s² — longitudinal accel ≤ this ⇒ RED hard-brake trigger |
| `stall_speed` | `0.3` | m/s — speed below this counts toward stall dwell |
| `stall_dwell_steps` | `20` | timesteps (2.0 s @ 10 Hz) of continuous sub-`stall_speed` before the stalled trigger fires |
| `vru_distance_red` | `3.0` | m — center distance moving vehicle ↔ pedestrian/cyclist ⇒ RED |
| `vru_distance_amber` | `6.0` | m — ⇒ AMBER |
| `vru_min_vehicle_speed` | `1.0` | m/s — VRU proximity only evaluated for vehicles moving at least this fast |
| `rearm_clear_steps` | `10` | timesteps a condition must stay clear before the same (agent, kind) trigger may re-fire |

Example instance: `TriggerConfig()` (all defaults); example preset: `TriggerConfig.conservative()`
has `ttc_red=3.0, ttc_amber=5.0, ...` exactly as in the existing file.

### 5.4 Event-timeline record (`src/triggers/engine.py::TriggerEvent`) — EXISTS + [NEW] fields

| Field | Type | Unit / domain |
|---|---|---|
| `agent_id` | int | scenario-local agent id |
| `agent_type` | `AgentType` | VEHICLE / PEDESTRIAN / CYCLIST |
| `timestep` | int | 0–90 |
| `time_seconds` | float | `timestep * timestep_duration` |
| `severity` | `TriggerSeverity(IntEnum)` | `AMBER = 1`, `RED = 2` |
| `reason` | str | human-readable, e.g. `"TTC 1.2s — collision imminent"` |
| `metric_value` | float | raw metric value that fired |
| `kind` **[NEW]** | str | machine-readable trigger kind: one of `"ttc"`, `"overlap"`, `"offroad"`, `"wrong_way"`, `"lane_compliance"`, `"composite"`, `"hard_brake"`, `"stalled"`, `"vru_proximity"` |

Property `severity_name -> "RED" | "AMBER"` exists.

**[NEW] JSON serialization** (written by `--events-out` / headless mode as `events.json` — a JSON
array sorted by `(timestep, agent_id, kind)`):

```json
{
  "agent_id": 1,
  "agent_type": "VEHICLE",
  "timestep": 31,
  "time_seconds": 3.1,
  "severity": "RED",
  "kind": "hard_brake",
  "reason": "Hard brake -6.0 m/s2",
  "metric_value": -6.0
}
```

### 5.5 Metrics output (`src/metrics/composite.py::AgentRisk`) — EXISTS, transcribed

Per agent per timestep; produced by `compute_composite_risk(scenario, t, config) -> dict[int, AgentRisk]`.

| Field | Type | Unit / domain |
|---|---|---|
| `agent_id` | int | — |
| `overlap` | float | max pairwise overlap ratio 0–1 (0 = none) |
| `offroad` | float | 0–1 (0 = on road) |
| `wrong_way` | float | 0–1 = \|heading error\|/π |
| `ttc` | float | seconds; `inf` = no predicted collision; `0.0` = already overlapping |
| `lane_compliance` | float | 0–1 (1 = perfect) |
| `composite_score` | float | 0–1 weighted sum per `RiskConfig` (TTC normalized: `1 − ttc/ttc_safe`, clamped; compliance inverted) |
| `risk_level` | `RiskLevel(IntEnum)` | `GREEN = 0`, `AMBER = 1`, `RED = 2` via `classify_risk` |

Example instance: `AgentRisk(agent_id=0, overlap=0.0, offroad=0.0, wrong_way=0.05, ttc=2.4,
lane_compliance=0.92, composite_score=0.166, risk_level=RiskLevel.GREEN)`.

### 5.6 Bundled scenario registry — 3 EXIST + 2 TO-BUILD

All: 91 timesteps, dt = 0.1 s, ego = agent 0, deterministic given `seed` (verified).

| Name | Status | Exercises trigger kinds | Notes |
|---|---|---|---|
| `intersection_conflict` | EXISTS | ttc, overlap, lane_compliance, composite | 4-way intersection; ego westbound→east, cross traffic, pedestrian appears at t=20, cyclist, parked car; 4 traffic signals. Per-step Gaussian position noise (seeded). |
| `highway_merge` | EXISTS | ttc, lane_compliance, composite | 3-lane highway + ramp; merging vehicle cuts toward ego. |
| `pedestrian_crossing` | EXISTS | ttc, vru_proximity [NEW kind], composite | 2-lane road with crosswalk; two pedestrians (one appears at t=15); ego decelerates toward crosswalk. |
| `hard_brake` | **TO-BUILD** | hard_brake, ttc | Noise-free. Exact construction in Section 6 (`demo_loader.py` row). Hard-brake trigger fires at exactly **t=31**. |
| `stalled_ego` | **TO-BUILD** | stalled, composite | Noise-free. Ego rolls to a stop mid-lane; stalled trigger fires at exactly **t=68**. |

---

## 6. Module Breakdown

Legend: **EXISTS** = working as verified; **TO-FIX** = exists, has a verified defect or required
change; **TO-BUILD** = new. LOC budgets are for the *delta* this run writes (net added+modified
lines, guideline not straitjacket). Implementation order in the last column — follow it; it is
dependency-ordered so the test suite stays green after each step.

| # | Path | Status | Responsibility / verified state | Public API (real, transcribed) | Deps | ΔLOC | Order |
|---|---|---|---|---|---|---|---|
| 1 | `src/data/scenario.py` (158 LOC) | **EXISTS — working** | Numpy dataclasses; contract in §5.2. No changes except docstring note that lane-center point order = travel direction. | `AgentType`, `SignalState`, `AgentState`, `AgentTrajectory(.state_at, .speed, .num_timesteps)`, `LaneLine`, `RoadEdge`, `Crosswalk`, `TrafficSignal`, `RoadGraph`, `Scenario(.duration, .ego, .agents_at)` | numpy | ~5 | 1 |
| 2 | `src/triggers/config.py` (76 LOC) | **TO-FIX (additive)** | Threshold dataclass + `conservative()` / `permissive()` presets — working. Add the 7 [NEW] fields of §5.3 with preset variants. | `TriggerConfig`, `TriggerConfig.conservative()`, `TriggerConfig.permissive()` | dataclasses | ~35 | 2 |
| 3 | `src/metrics/safety.py` (312 LOC) | **TO-FIX** | Raw metrics — all five functions work and pass tests, but two produce **verified false positives**: (a) `compute_wrong_way` flags legitimate oncoming traffic RED from t=0 (measured: agent 2 in `intersection_conflict`, `"Wrong-way heading"` at t=0) because all demo lane polylines point the same way and the nearest segment is used regardless of direction; (b) `compute_wrong_way` / `compute_lane_compliance` / `compute_offroad` are applied to pedestrians (measured: `"Lane compliance 0%"` RED for pedestrian agent 1 in `pedestrian_crossing` at t=0). **Fixes:** (1) in wrong-way and lane-compliance, gather all lane-center segments with midpoint within **6.0 m** of the agent and use the segment minimizing \|`_angle_diff(heading, seg_dir)`\| (direction-aware matching; a vehicle with no nearby direction-compatible lane still scores high); (2) skip agents with `agent_type == PEDESTRIAN` in `compute_offroad` (→ 0.0), `compute_wrong_way` (→ 0.0), `compute_lane_compliance` (→ 1.0); vehicles and cyclists stay evaluated. **Add** `compute_accel(scenario, t) -> dict[int, float]` (m/s²): `(speed[t] − speed[t−1]) / dt` per valid agent, `0.0` at t=0; and `compute_vru_distance(scenario, t) -> dict[int, float]`: for each VEHICLE, min center distance to any valid PEDESTRIAN/CYCLIST (else `inf`). | `compute_overlap(scenario,t)->dict[int,float]`, `compute_offroad(...)`, `compute_wrong_way(...)`, `compute_ttc(...)`, `compute_lane_compliance(...)`; helpers `_get_corners(state)`, `_bbox_overlap(a,b)`, `_compute_pairwise_ttc(a,b)`, `_angle_diff(a,b)` (tests import the helpers — keep names) | numpy, scenario | ~90 | 3 |
| 4 | `src/metrics/composite.py` (133 LOC) | **EXISTS — working** | Weighted composite + classification; §5.5. No changes. | `RiskLevel`, `RiskConfig`, `DEFAULT_RISK_CONFIG`, `AgentRisk`, `compute_composite_risk(scenario,t,config=None)`, `classify_risk(score,config=None)` | safety.py | 0 | — |
| 5 | `src/triggers/engine.py` (238 LOC) | **TO-FIX (core fix of this run)** | Trigger engine — works but is **level-triggered**: dedup key is `(agent_id, timestep, base_reason)`, so a persisting condition re-fires **every timestep**. Measured with defaults: `intersection_conflict` 1,082 events (484 RED), `highway_merge` 473, `pedestrian_crossing` 935 — operationally useless spam. **Rewrite firing logic to edge-triggered:** engine keeps `_active: dict[tuple[int, str], TriggerSeverity]` keyed by `(agent_id, kind)` and `_clear_count: dict[tuple[int, str], int]`. A trigger fires only when (agent, kind) transitions inactive→active, or escalates AMBER→RED (escalation fires a new RED event). While the condition holds, no re-fire. When it no longer holds, increment clear count; after `config.rearm_clear_steps` consecutive clear steps, the key re-arms. **Add trigger kinds** using the new metrics: `hard_brake` (accel ≤ `hard_brake_accel`, RED, vehicles only, reason `f"Hard brake {accel:.1f} m/s2"`), `stalled` (speed < `stall_speed` for `stall_dwell_steps` consecutive steps, engine-internal dwell counter per agent, vehicles only, RED for ego / AMBER otherwise, reason `"Stalled in lane"`), `vru_proximity` (VRU distance thresholds + `vru_min_vehicle_speed` gate, reason `f"VRU within {d:.1f} m"`). Every `TriggerEvent` gets the [NEW] `kind` field; `evaluate` signature unchanged. **Important:** `evaluate` must be called with strictly increasing `timestep` for dwell/edge state to be meaningful — document this; `DashboardState` already satisfies it via `precompute_all` (step 7 makes the live path read precomputed events instead of re-evaluating out of order). Keep `reset()`, `events`, `red_events`, `amber_events`, `events_at`, `events_up_to`. | `TriggerSeverity`, `TriggerEvent(+kind)`, `TriggerEngine(config).evaluate(scenario, timestep, risks) -> list[TriggerEvent]`, `.reset()`, `.events`, `.red_events`, `.amber_events`, `.events_at(t)`, `.events_up_to(t)` | config.py, composite.py, safety.py | ~140 | 4 |
| 6 | `src/data/demo_loader.py` (498 LOC) | **TO-FIX + TO-BUILD** | Scenario builders — the existing three work and are seed-deterministic (verified). **Fix lane directions** (feeds the safety.py fix): in `_build_intersection_road_graph`, order eastbound lane-center points west→east (y = −3.5, −1.75) and westbound east→west (y = +1.75, +3.5); northbound south→north (x = +1.75, +3.5), southbound north→south (x = −3.5, −1.75). In `pedestrian_crossing`: y = −1.75 eastbound, y = +1.75 westbound (reverse its points). `highway_merge` is one-way — unchanged. **Do not alter any agent trajectory in the existing three scenarios.** **Build two scenarios** (noise-free: build arrays directly, no `_make_curved_trajectory`, no RNG use for these two): **(a) `hard_brake`** — straight 2-lane eastbound road (reuse pedestrian-crossing-style graph without crosswalk, both lanes west→east). Lead vehicle agent 1 starts (10, −1.75), speed profile `v[t] = 15.0` for t ≤ 30, `max(0, 15.0 − 6.0·(t−30)·0.1)` for t > 30 (v = 0 at t = 55); positions by cumulative sum `x[t] = x[t−1] + v[t]·dt`. Ego agent 0 starts (−25, −1.75) at constant 15 m/s (no braking — it closes on the stopped lead, driving TTC down). One background oncoming vehicle westbound lane for visual life. Derived exactly: accel at t=31 = (14.4 − 15.0)/0.1 = **−6.0 m/s² ⇒ hard_brake RED at t=31**; ego TTC then decays through `ttc_red=2.0` producing a RED ttc trigger in t ∈ [40, 75]. **(b) `stalled_ego`** — same road shape. Ego agent 0: `v[t] = 8.0` for t < 10, `max(0, 8.0 − 2.0·(t−10)·0.1)` for t ≥ 10 → first t with v < 0.3 is **t=49** (v=0.2); with `stall_dwell_steps=20`, dwell counter reaches 20 at **t=68 ⇒ stalled RED at t=68**. Two other vehicles flow past in the adjacent lane. Register both names in `load_demo_scenario` and its docstring. | `load_demo_scenario(scenario_name="intersection_conflict", seed=42) -> Scenario` (names: the 5 in §5.6) | numpy, scenario.py | ~180 | 5 |
| 7 | `src/dashboard/state.py` (107 LOC) | **TO-FIX** | Playback state — works, but has the **verified precompute-wipe bug**: `DashboardApp.__init__` calls `precompute_all()` then `reset()`, and `reset()` calls `trigger_engine.reset()`, discarding the entire precomputed timeline; thereafter events only accumulate for visited timesteps (measured: after init + visiting t ∈ {0,30,60,90}, only 41 events exist vs 1,082 for a full sweep). Additionally `set_timestep` calls `trigger_engine.evaluate` out of order while scrubbing, corrupting any edge/dwell state. **Fix:** `precompute_all()` runs the engine once over t = 0..N−1 (strictly increasing — correct for the new edge-triggered engine) and stores the result in a new field `precomputed_events: list[TriggerEvent]`; `_update_risks()` only recomputes `current_risks` and **no longer calls** `trigger_engine.evaluate`; `reset()` rewinds playback but **does not** clear `precomputed_events`; the `events` property returns `precomputed_events`. Add `events_up_to(t)` convenience filtering the precomputed list. | `DashboardState(scenario, risk_config, trigger_config)`, `.set_timestep(t)`, `.step_forward()`, `.step_backward()`, `.toggle_play()`, `.update(dt)`, `.reset()`, `.change_speed(delta)`, `.precompute_all()`, `.events`, `.current_time_seconds`, fields `current_timestep`, `playing`, `playback_speed`, `current_risks`, `trigger_scroll`, `timeline_scroll` | composite, engine | ~40 | 6 |
| 8 | `src/renderer/colors.py` (65 LOC) | **EXISTS — working, frozen** | The palette (dark tactical: `BG_DARK=(12,12,18)`, halo green/amber/red, monospace-text greys). **Do not change existing values.** May add ≤ 3 constants for new UI (e.g. `BADGE_INFO`) in the same register. | `Colors` (class attributes), `Colors.with_alpha(color, alpha)` | — | ~3 | — |
| 9 | `src/renderer/map_renderer.py` (173 LOC) | **EXISTS — working** | Road graph drawing + `Viewport` transform (world↔screen, zoom clamp 1–50 px/m, pan, `fit_to_bounds`). Verified drawing headless. No changes. | `MapRenderer(surface, viewport).draw(scenario, timestep)`; `Viewport(screen_rect, center, scale)`, `.world_to_screen(p)`, `.screen_to_world(sx,sy)`, `.zoom(f)`, `.pan(dx,dy)`, `.fit_to_bounds(...)` | pygame, scenario | 0 | — |
| 10 | `src/renderer/agent_renderer.py` (220 LOC) | **TO-FIX (perf, minor)** | Boxes/halos/trails/labels — works headless. Defect: `_draw_trail` allocates a full-screen `SRCALPHA` surface **per trail segment per agent per frame** (up to ~10 segments × N agents × 60 fps full-screen blits). Fix: draw all of one agent's trail segments onto a single temporary surface (or precompute faded colors and draw lines directly on the main surface without alpha surfaces). Also cache the label font (`pygame.font.SysFont` is called per label per frame in `_draw_label` — hoist to `__init__` with a `Font(None, 12)` fallback if SysFont raises). | `AgentRenderer(surface, viewport).draw_agent(agent, state, is_ego=False, risk=None, show_trail=True, trail_timesteps=10, current_timestep=0)` | pygame, composite | ~40 | 7 |
| 11 | `src/renderer/panel_renderer.py` (417 LOC) | **TO-FIX (minor)** | Trigger panel / timeline / fleet panel / playback bar — works headless. Two hard-coded assumptions to fix: time labels use `current_timestep * 0.1` instead of the scenario's `timestep_duration` (thread the dt or seconds in as a parameter), and `draw_playback_bar`'s geometry (`bar_x = btn_x + 30`, `bar_w = rect.width − 200`) is duplicated-by-approximation in `app.py::_scrub_playback` (`bar_x = 42`) — export the bar geometry as a module-level function `playback_bar_rect(rect) -> pygame.Rect` used by both. Update the keyboard-hints string for the new scenario keys (1–5). Fonts: same SysFont fallback as row 10. | `PanelRenderer(surface)`, `.draw_trigger_panel(rect, events, scroll_offset=0)`, `.draw_timeline(rect, events, current_timestep, total_timesteps, scroll_offset=0)`, `.draw_fleet_panel(rect, scenario, risks, events, current_timestep)`, `.draw_playback_bar(rect, current_timestep, total_timesteps, playing, speed=1.0)` | pygame, engine, composite | ~40 | 8 |
| 12 | `src/dashboard/app.py` (406 LOC) | **TO-FIX + TO-BUILD (headless)** | Interactive app works (init, layout, input, draw verified headless; 60 fps loop). Changes: **(a) headless mode [TO-BUILD]** — new flags `--headless`, `--frames-out DIR` (default `docs/screenshots/<scenario_id>/`), `--events-out PATH` (default `<frames-out>/events.json`), `--frame-stride N` (default 1). When `--headless`: set `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` **before** `pygame.init()` (restructure: parse args first, then construct `DashboardApp`; move `pygame.init()` out of module import path — it is already inside `__init__`, keep it there and set the env var in `main()` before instantiation). Headless loop: for t in 0..N−1 step stride → `state.set_timestep(t)`; `_draw()`; `pygame.image.save(self.screen, frames_out / f"frame_{t:03d}.png")`; then write `events.json` (schema §5.4, from `state.events`); print a one-line summary (`"91 frames, 23 events (9 RED) -> docs/screenshots/hard_brake"`); exit 0. No `pygame.display.flip()` needed under dummy but harmless — keep `_draw()` shared verbatim between modes. **(b) `--config PATH`** implementing §5.1 (a private `_load_run_config(path) -> tuple[str, int, TriggerConfig, RiskConfig]` helper in this file; no new module). **(c)** extend `--scenario` choices to all 5 names; keys 1–5 switch scenarios (extend `_handle_key`); fix `_scrub_playback` to use `playback_bar_rect` (row 11). **(d)** fix init order: `precompute_all()` once; `reset()` no longer destroys it (row 7 makes this safe). Keep window 1400×900, `RESIZABLE`, layout constants as-is. | `DashboardApp(scenario, risk_config=None, trigger_config=None)`, `.run()`, `main()`; console script `safety-monitor = src.dashboard.app:main`; module runnable as `python -m src.dashboard.app` (has `__main__` guard) | all above | ~170 | 9 |
| 13 | `src/data/waymax_loader.py` (213 LOC) | **EXISTS — unverified, optional** | WOMD TFRecord → `Scenario` via Waymax `DatasetConfig`/`simulator_state_generator`; import-guarded with a clear install hint. **Cannot be executed offline** (deps + licensed data); treat as best-effort reference code. Do not modify except: wrap the `_convert_waymax_state` body's attribute access in a `try/except AttributeError` that re-raises with a message naming the waymax version tested against ("written against waymax 0.2 API; verify field names if it fails"). No tests. | `load_womd_scenario(data_path, scenario_index=0, max_objects=32) -> Scenario` | waymax/jax/tf (optional extra) | ~10 | 10 |
| 14 | `src/*/__init__.py` (5 files) | **EXISTS — working** | Re-export public names (verified contents). Note `src/dashboard/__init__.py` imports `app` ⇒ imports pygame; fine. Add new names only (`TriggerEvent.kind` needs nothing; no new modules). | — | — | ~2 | — |
| 15 | `tests/test_scenario.py` (110 LOC, 10 tests) | **EXISTS — passing** | Dataclass + demo-loader tests incl. determinism. Extend: loader tests for `hard_brake` and `stalled_ego` (91 steps, noise-free ⇒ two loads byte-identical regardless of seed). | pytest classes | — | ~30 | 11 |
| 16 | `tests/test_metrics.py` (236 LOC, 18 tests) | **EXISTS — passing** | Hand-computed helper tests (corners, angle diff, pairwise TTC) + scenario-level checks. Extend per Section 10.1: exact TTC case, accel cases, VRU distance, pedestrian-exclusion, oncoming-not-wrong-way. | pytest classes | — | ~90 | 12 |
| 17 | `tests/test_triggers.py` (123 LOC, 13 tests) | **EXISTS — passing, 2 assertions must be updated** | Engine tests. `test_no_duplicate_events` (same-timestep dedup) still holds under edge-triggering; **`test_full_scenario_produces_events` and `test_conservative_triggers_more` remain valid**; add edge-trigger semantics tests + exact-timestep tests per Section 10.2. Event-count expectations change dramatically (from ~1,082 to tens) — no existing assertion pins counts, so nothing breaks, but verify. | pytest classes | — | ~120 | 13 |
| 18 | `tests/test_headless.py` | **TO-BUILD** | Integration: headless run via `DashboardApp` in-process (not subprocess) into `tmp_path`; determinism double-run. Section 10.3. | pytest, pygame | ~90 | 14 |
| 19 | `pyproject.toml` | **TO-FIX** | Working (`pip install -e ".[dev]"` verified pattern). Change: `requires-python = ">=3.11"`; pin core deps `numpy>=1.26,<3`, `pygame-ce>=2.5,<3`; dev `pytest>=8,<9`, `pytest-cov>=4`; waymax extra unchanged. Keep console script and `include = ["src*"]` packaging as-is. | — | — | ~6 | 15 |
| 20 | `.github/workflows/ci.yml` | **TO-BUILD** | CI: ubuntu-latest, Python 3.11 and 3.12 matrix; `pip install -e ".[dev]"`; `python -m pytest -q`; then the headless acceptance run (`SDL_VIDEODRIVER` is set by `--headless` itself; also `sudo apt-get install -y libsdl2-2.0-0` is NOT needed — pygame-ce wheels bundle SDL) with `--scenario hard_brake --frames-out out/` and assert 91 PNGs exist (`test -f out/frame_090.png`) and `python -c` check that events.json contains a hard_brake event at timestep 31. No WOMD, no waymax. | — | — | ~45 | 16 |
| 21 | `README.md` | **TO-FIX** | Content is good positioning but overstates status ("built on Waymax"). Update honestly: Quickstart (3 commands), the 5 bundled offline scenarios table, headless/screenshot usage, `--config`, screenshots embedded from `docs/screenshots/`, WOMD/waymax as clearly-optional path with install + license caveats, remove "Status: In Development", keep Why-This-Matters and Visual Design sections. | — | — | ~80 | 17 |
| 22 | `docs/screenshots/*.png` | **TO-BUILD (generated)** | Generated by the headless runs listed in Section 9. Commit the 6 curated frames (copied/renamed from headless output), not all 455. | — | — | — | 18 |

Total delta ≈ 1,200 LOC. Nothing else changes. **Do not** create new top-level packages, a zones
module, a web server, or documentation files beyond the README update and this file's screenshots.

---

## 7. Dependencies

| Package | Pin | Why | Verified |
|---|---|---|---|
| `numpy` | `>=1.26,<3` | All trajectory math and metrics; 2.x verified (2.5.1). 1.26 floor = oldest with Python 3.12 wheels. | ✅ runs |
| `pygame-ce` | `>=2.5,<3` | Rendering + headless via SDL dummy driver; wheels bundle SDL2 (no system deps, offline-friendly). Verified 2.5.7 incl. `pygame.image.save` under dummy driver. | ✅ runs |
| `pytest` | `>=8,<9` (dev) | Test runner. | ✅ runs |
| `pytest-cov` | `>=4` (dev) | Optional coverage; keep, harmless. | — |
| `waymax` | `>=0.2` (**extra `[waymax]` only**) | Optional WOMD path. Pulls JAX/TF — heavy, needs licensed data; never imported on default path, never in CI. | ❌ not installable offline; documented as unverified |
| `jax` | `>=0.4` (extra) | Waymax dependency. | ❌ same |
| `tensorflow` | `>=2.14` (extra) | WOMD TFRecord reading. | ❌ same |

Install commands (the only two supported paths):

```
python -m venv .venv && .venv/bin/pip install -e ".[dev]"        # default, offline demo + tests
.venv/bin/pip install -e ".[waymax]"                             # optional, WOMD (local only)
```

No other runtime dependencies are permitted (no matplotlib, no pillow — pygame saves PNGs itself,
verified; no click/typer — argparse exists and works).

---

## 8. Acceptance Criteria

Each criterion is `command → observable output`. Run from the repo root with the project venv
active (`.venv/bin/python`). All must pass. Windows of the form `t ∈ [a, b]` are deliberate where
seeded noise makes single-step pinning brittle; exact timesteps are required where the scenario is
constructed noise-free.

1. **Install** — `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` → exit 0; no
   TF/JAX/waymax installed (`.venv/bin/pip show tensorflow` → not found).
2. **Test suite** — `.venv/bin/python -m pytest -q` → `0 failed`, **≥ 60 passed**, runtime < 60 s,
   with no display attached and no WOMD data present.
3. **Headless frame dump (count + naming)** —
   `.venv/bin/python -m src.dashboard.app --headless --scenario hard_brake --frames-out /tmp/wsm_a`
   → exit 0; `ls /tmp/wsm_a/frame_*.png | wc -l` prints `91`; files are `frame_000.png` …
   `frame_090.png`; `/tmp/wsm_a/events.json` exists and is a valid JSON array.
4. **Frame geometry** — `python -c "import pygame; s=pygame.image.load('/tmp/wsm_a/frame_045.png'); print(s.get_size())"`
   → `(1400, 900)`; and the frame is not blank: ≥ 1,000 pixels differ from `(12, 12, 18)`
   (checked in `tests/test_headless.py`).
5. **Determinism** — run criterion 3's command a second time into `/tmp/wsm_b`, then
   `diff -r /tmp/wsm_a /tmp/wsm_b` → empty output (byte-identical PNGs and events.json,
   same machine).
6. **Hard-brake trigger, exact timestep** —
   `python -c "import json; ev=json.load(open('/tmp/wsm_a/events.json')); hb=[e for e in ev if e['kind']=='hard_brake']; print(len(hb), hb[0]['agent_id'], hb[0]['timestep'], hb[0]['severity'])"`
   → `1 1 31 RED` (exactly one hard-brake event: agent 1 at t=31, by the construction in
   Section 6 row 6a).
7. **TTC trigger follows the hard brake** — in the same `events.json`, at least one event with
   `kind == "ttc"`, `agent_id == 0`, `severity == "RED"`, `timestep ∈ [40, 75]`.
8. **Stalled trigger, exact timestep** —
   `... --headless --scenario stalled_ego --frames-out /tmp/wsm_c` then filter
   `kind == "stalled"` → exactly one event: `agent_id 0, timestep 68, severity RED`
   (derivation: v < 0.3 first at t=49; 20-step dwell ⇒ t=68).
9. **VRU proximity** — `... --headless --scenario pedestrian_crossing --frames-out /tmp/wsm_d` →
   `events.json` contains ≥ 1 event with `kind == "vru_proximity"`, `agent_id == 0`,
   `timestep ∈ [70, 90]`.
10. **Wrong-way false positive eliminated** —
    `... --headless --scenario intersection_conflict --frames-out /tmp/wsm_e` → `events.json`
    contains **zero** events with `kind == "wrong_way"` for agent 2 (the legitimate oncoming
    vehicle; currently it fires RED at t=0 — this criterion locks the fix), and **zero** events of
    kinds `wrong_way`/`lane_compliance`/`offroad` for any `agent_type == "PEDESTRIAN"` in any of
    the five scenarios' event dumps.
11. **Event volume is operational, not spam** — for `intersection_conflict` with default policy,
    total event count in `events.json` is **between 5 and 60** (pre-fix measured baseline was
    1,082; edge-triggering must collapse it by ~2 orders of magnitude while still reporting the
    conflict).
12. **Timeline survives reset (precompute bug fixed)** — assertion in `tests/test_headless.py`:
    construct `DashboardApp` headless for `intersection_conflict`; immediately after `__init__`
    (t=0, before any stepping), `app.state.events` is non-empty and equals the full-run event
    list; calling `app.state.reset()` leaves `app.state.events` unchanged.
13. **Config file honored** —
    `.venv/bin/python -m src.dashboard.app --headless --config scenarios/default.json --frames-out /tmp/wsm_f`
    → exit 0, 91 frames, and the run uses `intersection_conflict` seed 42 (its `events.json` is
    byte-identical to a run with `--scenario intersection_conflict --seed 42`). A config with an
    unknown top-level key → exit non-zero with the key named on stderr.
14. **Policy presets differentiate** — headless `intersection_conflict` with
    `--policy conservative` yields **≥** the event count of `--policy permissive` (strictly, per
    existing test logic).
15. **Interactive smoke (manual, non-CI)** — `.venv/bin/safety-monitor --scenario hard_brake` →
    a 1400×900 window titled "Waymax Safety Monitor"; SPACE plays through 9.1 s; the trigger
    panel shows the hard-brake RED entry at 3.1 s; keys 1–5 switch scenarios; ESC quits cleanly.
16. **Screenshots exist** — after the Section 9 generation step: `ls docs/screenshots/*.png | wc -l`
    → `6`, each 1400×900.
17. **CI green** — `.github/workflows/ci.yml` runs criteria 2, 3, and 6 on ubuntu-latest,
    Python 3.11 + 3.12, with no network access needed beyond `pip install`.

---

## 9. Demo Script (60 seconds)

Recorded live or narrated over the committed screenshots. Frame sources are headless dumps
(`--frames-out`), copied and renamed into `docs/screenshots/`:

| Committed file | Source | Shows |
|---|---|---|
| `docs/screenshots/01_intersection_overview.png` | `intersection_conflict`, frame_000 | Full dashboard at t=0: tactical map, 4-way intersection, signals, all panels nominal |
| `docs/screenshots/02_intersection_conflict.png` | `intersection_conflict`, frame_045 | Mid-scenario: amber/red halos, populated trigger panel + timeline |
| `docs/screenshots/03_hard_brake.png` | `hard_brake`, frame_035 | Hard-brake RED entry at 3.1 s; lead vehicle halo red, ego closing |
| `docs/screenshots/04_stalled_ego.png` | `stalled_ego`, frame_075 | Stalled-in-lane RED on ego; timeline shows dwell history |
| `docs/screenshots/05_pedestrian_vru.png` | `pedestrian_crossing`, frame_085 | VRU-proximity alert as ego reaches the crosswalk |
| `docs/screenshots/06_policy_conservative.png` | `intersection_conflict` with `--policy conservative`, frame_045 | Same scene, denser trigger panel — policy knob visualized |

Narration (≈ 60 s):

> *(0–10 s, screenshot 01)* "Robotaxi fleets keep humans in the loop — remote operators who take
> over when the vehicle can't handle a situation. The open question is *when* to pull them in.
> This is a monitoring dashboard that answers that: scenario playback on the left, live teleop
> triggers and an incident timeline on the right."
> *(10–25 s, 02)* "Every agent gets a per-timestep risk score — time-to-collision, bounding-box
> overlap, off-road, wrong-way, lane compliance — combined into the green/amber/red halo you see.
> When a threshold is crossed, a trigger fires once, with a reason and a timestamp — not a wall of
> repeated alarms."
> *(25–40 s, 03 + 04)* "Here a lead vehicle brakes at six meters per second squared — the
> hard-brake trigger fires at exactly t=3.1 s, then the ego's TTC collapses and escalates to red.
> And here the ego rolls to a stop mid-lane; after two seconds of dwell the stalled-vehicle
> trigger fires. Both are deterministic, tested down to the exact timestep."
> *(40–52 s, 05 + 06)* "Vulnerable road users get a dedicated proximity trigger. And the whole
> intervention policy is a config file — conservative pulls operators in early, permissive trusts
> the autonomy longer. Same scenario, different alert load: that trade-off is the core operational
> dial."
> *(52–60 s)* "Everything runs offline on synthetic WOMD-shaped scenarios; the same data model has
> an adapter for real Waymo Open Motion Dataset logs. One command, ninety-one deterministic
> frames, CI-verified."

---

## 10. Test Plan

Target: ≥ 60 tests, all offline, all headless-safe, `pytest -q` < 60 s. Existing 41 tests must
stay green (two files need no changes to keep passing; see Section 6 rows 15–17).

### 10.1 Unit — metrics (`tests/test_metrics.py`, extend)

Keep all 18 existing tests. Add, with hand-computed expectations:

- **Exact pairwise TTC:** point-like agents (`length=width=0` gives r=0 — instead use
  `length=2, width=0` ⇒ r_a=r_b=1, r=2): a at x=0 v=+10, b at x=22 v=0 ⇒ gap closes 20 m at
  10 m/s ⇒ `ttc == 2.0` exactly (quadratic degenerates to linear; assert `abs(ttc-2.0) < 1e-6`).
- **`compute_accel`:** trajectory with `vx = [10, 10, 4, 4]`, dt=0.1 ⇒ accel at t=2 is
  `(4−10)/0.1 = −60`; at t=0 ⇒ `0.0`; invalid-at-t−1 agents ⇒ `0.0`.
- **`compute_vru_distance`:** vehicle at (0,0), pedestrian at (3,4) ⇒ `5.0` exactly; scenario with
  no VRUs ⇒ `inf`; pedestrians themselves absent from the returned dict.
- **Pedestrian exclusion:** pedestrian standing at (100, 100) far off-lane ⇒
  `compute_offroad == 0.0`, `compute_wrong_way == 0.0`, `compute_lane_compliance == 1.0`.
- **Direction-aware wrong-way:** road with eastbound lane at y=−1.75 (points west→east) and
  westbound at y=+1.75 (points east→west); vehicle at (0, 1.75) heading π ⇒ wrong_way < 0.1;
  same vehicle heading 0 (against the westbound lane, but within 6 m of the eastbound one too)
  ⇒ wrong_way < 0.1 (matches best-aligned nearby lane); vehicle at (0, 1.75) heading π/2 with no
  north-south lane within 6 m ⇒ wrong_way ≥ 0.4.

### 10.2 Unit — trigger engine (`tests/test_triggers.py`, extend)

Keep all 13 existing tests (verify `test_conservative_triggers_more` still holds post-fix — it
compares the same engine semantics under two configs, so it must). Add:

- **Edge semantics:** hand-built 2-timestep scenario where a TTC condition holds at t=0 and t=1 ⇒
  exactly 1 ttc event; condition clears for `rearm_clear_steps` then re-occurs ⇒ 2 events;
  clears for fewer steps than `rearm_clear_steps` then re-occurs ⇒ still 1 event.
- **Escalation:** condition AMBER at t=0, RED at t=1 ⇒ 2 events (AMBER then RED).
- **Hard brake exact:** `load_demo_scenario("hard_brake")`, full sweep ⇒ exactly one
  `kind=="hard_brake"` event, `(agent_id, timestep, severity) == (1, 31, RED)`.
- **Stalled exact:** `stalled_ego` sweep ⇒ exactly one `kind=="stalled"` event at
  `(0, 68, RED)`.
- **VRU window:** `pedestrian_crossing` sweep ⇒ ≥1 `vru_proximity` event for agent 0 with
  `70 <= timestep <= 90`; none for the parked/slow cases below `vru_min_vehicle_speed`.
- **Spam ceiling:** `intersection_conflict` default-policy sweep ⇒ `5 <= len(events) <= 60`.
- **`kind` integrity:** every event's `kind` is in the closed set of §5.4.

### 10.3 Integration — headless (`tests/test_headless.py`, new)

All tests set `os.environ["SDL_VIDEODRIVER"] = "dummy"` before importing/initializing pygame
(module-level, first thing in the file).

- **Frame dump:** run the headless path in-process (call the same function `main()` dispatches to,
  e.g. `run_headless(app, frames_out, events_out)` — factor it so tests don't need subprocess) for
  `hard_brake` into `tmp_path` ⇒ 91 files `frame_000.png..frame_090.png`; `frame_045.png` is
  1400×900 and has ≥ 1,000 non-background pixels; `events.json` parses and matches §5.4 schema
  keys exactly.
- **Determinism:** two runs into two tmp dirs ⇒ identical SHA-256 for every frame and for
  `events.json`.
- **Precompute-survives-reset:** criterion 12 as a test.
- **Config loading:** `_load_run_config("scenarios/default.json")` returns
  (`"intersection_conflict"`, 42, default `TriggerConfig`, `RiskConfig` matching the file's 8
  values); unknown key ⇒ `ValueError`.

### 10.4 Determinism ground rules

Existing three scenarios use seeded RNG noise — already verified byte-deterministic per seed. The
two new scenarios use **no RNG at all**. Rendering determinism relies on same-machine font
rasterization; CI asserts frame *count/geometry/non-blankness* plus events.json content on Linux,
and full byte-determinism within the same job (double run).

---

## 11. Risks & Fallbacks

| Risk | Likelihood | Mitigation / fallback |
|---|---|---|
| **WOMD/waymax unusable** (no account, heavy TF/JAX deps, API drift vs `waymax_loader.py` which is untested) | Certain in CI, likely locally | Already mitigated by design: default path never touches it. Loader stays import-guarded with an actionable error; README labels it "optional, written against waymax 0.2, unverified"; the added try/except names the tested API version. Never attempt to pip-install waymax during this run. |
| **pygame display unavailable / SysFont missing** (CI, SSH sessions; minimal Linux images without a monospace SysFont) | Medium | `--headless` sets `SDL_VIDEODRIVER=dummy` itself (verified working). Every font construction gets a `pygame.font.Font(None, size)` fallback wrapped around `SysFont`. pygame-ce wheels bundle SDL2 ⇒ no apt packages needed. |
| **Cross-machine frame hashes differ** (font rendering, SDL versions) | High across OSes | Determinism is asserted same-machine only (double-run in the same CI job); cross-machine acceptance uses counts, geometry, non-blankness, and events.json equality instead of pixel hashes. |
| **Playback performance** (`compute_composite_risk` is O(agents²) pure Python per timestep; trail drawing allocated full-screen surfaces per segment) | Low at demo scale | Measured: full 91-step sweep of all 3 scenarios ≈ 1 s total on M-series CPU — fine for ≤ 10 agents. The precompute fix means the live loop only computes the *current* timestep's risks. Trail-drawing fix (Section 6 row 10) removes the per-segment full-screen blits. If interactive fps still dips below 30 with 5 scenarios: cache `compute_composite_risk` per timestep in `DashboardState` (dict keyed by t) — a 10-line fallback, only if needed. |
| **Edge-trigger rewrite breaks existing passing tests** | Medium | The two at-risk assertions (`test_full_scenario_produces_events`, `test_conservative_triggers_more`) were checked against the new semantics: full sweeps still produce > 0 events and conservative ≥ permissive by monotonicity of thresholds. Run pytest after step 4 (order column) before proceeding. |
| **Exact-timestep criteria (t=31, t=68) off by one** due to velocity-array indexing convention | Medium | The construction in Section 6 row 6 defines `v[t]` arrays analytically and positions as cumulative sums — accel at t is `(v[t]−v[t−1])/dt` by definition of `compute_accel`, making t=31/t=68 arithmetic, not empirical. If an off-by-one still appears, fix the *scenario builder* to match the spec'd timeline, never loosen the test to a window. |
| **Scope creep toward forbidden territory** (zones, geo-fences, [redacted] regions) | — | Hard rule: any such abstraction is out of scope by design (Section 3). If a feature seems to need "regions", it doesn't belong in v1. |

---

## 12. Deferred to v2

- **Verified Waymax integration**: execute `waymax_loader.py` against real WOMD TFRecords, fix API
  drift, add an ego-selection heuristic (currently "first valid agent"), extract traffic signals
  and stop signs from the real road graph, and add a recorded (non-CI) validation notebook/script.
- **WOMD adapters beyond motion**: lane connectivity/successor graph for proper lane assignment
  (replacing the nearest-segment heuristic), signalized-lane association, speed-limit attributes.
- **ML-based risk models**: learned trigger ranking / anomaly scores trained on WOMD, replacing or
  augmenting the heuristic composite; calibration analysis (precision/recall of triggers vs
  labeled incidents).
- **Occlusion / uncertainty metrics**: requires a perception-uncertainty signal or a
  visibility-polygon approximation over the road graph — real work, not a v1 heuristic.
- **Operator-workload analytics**: triggers-per-operator-hour under a policy across a scenario
  batch; policy A/B comparison report (the batch runner CLI is the natural seed).
- **Video/GIF export** of headless frame sequences (ffmpeg post-processing; keep out of runtime deps).
- **Multi-scenario batch mode** (`--batch N` aggregating fleet stats across scenarios).

---

*End of spec. Execute Section 6 in the given order; Section 8 defines done.*
