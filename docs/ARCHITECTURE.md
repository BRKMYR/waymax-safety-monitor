# ARCHITECTURE.md — Operational Safety Zones (OSZ)

**One-shot implementation specification.** A single agent run implements everything in this document without asking questions. The repository currently contains only `README.md`; **every file named here is TO-BUILD**. This document is the single source of truth; where the README and this document differ in scope, this document wins.

---

## 1. Context & Positioning

Operational Safety Zones (OSZ) is a self-contained desktop simulation and visualization platform for managing geo-fenced [redacted] ([redacted]) zones for urban robotaxi operations in central London. It renders a top-down, dark tactical map of a real road network, overlays 8–10 [redacted] zones with live GREEN/AMBER/RED status, simulates a small robotaxi fleet moving through the zone network under a scripted 90-second event timeline (school-zone activation, weather degradation, an incident forcing zone suspension, and a rejected dispatch), and validates routes against zone constraints with structured, auditable reports. It demonstrates the operational backbone of commercial robotaxi deployment: zones are where urban autonomy actually launches, and zone management — definition, versioning, live status, route validation, fleet compliance — is the software layer that makes that launch safe and auditable.

The project directly extends the owner's positioning: *"I build the software, data, and validation platforms that let machines operate safely in the physical world."* It carries the same questions into the harder urban robotaxi domain: hyper-local, time-varying conditions (a school zone at 08:00, a street market at noon), regulatory geo-fences, and fleet-level compliance monitoring. Every design decision here (versioned zone JSON, transition logs with cause attribution, structured route rejection reports, zone-spec export) mirrors what a production [redacted]-verification platform must provide to operators and regulators.

The target reviewer is a hiring manager at an AV-software or [redacted]-verification company (Wayve, Oxa, Waymo-adjacent tooling, TÜV/UL-style verification bodies). The artifact must read, in under five minutes, as: real geospatial data handling, a credible [redacted] domain model grounded in BSI PAS 1883 / ISO 34503 vocabulary, deterministic and testable simulation, and a distinctive tactical UI — not a toy map demo. Headless-rendered screenshots and a scripted demo make it reviewable without running anything.

---

## 2. One-Shot Scope Statement

What gets built in this single run — nothing more:

- A Python package `src/osz/` with six subpackages: `geo/`, `zones/`, `routing/`, `fleet/`, `render/`, `scenario/`, plus module entry points `osz.demo` and `osz.export_zones`.
- **geo/**: GeoJSON fixture loading (gzip-aware), WGS84→screen projection via local equirectangular approximation (documented in §5.1; no pyproj), shapely `STRtree` spatial index over roads, buildings, and zones.
- **zones/**: zone dataclass (polygon + full attribute schema from README §"Key Components → 2", reproduced as a hard data contract in §5.2), versioned JSON persistence in `data/zones/*.json`, GREEN/AMBER/RED status engine with a transition log carrying timestamped cause attribution.
- **routing/**: road graph built with networkx from the fixture; shortest-path routing (length-weighted Dijkstra); route validator producing a structured `RouteValidationReport` (coverage gaps, zone transitions, boundary margins, constraint mismatches).
- **fleet/**: N=6 simulated vehicles moving edge-by-edge along the road graph at fixed timestep; per-tick [redacted] compliance check; boundary-proximity warnings; pickup/dropoff cycle state machine; handoff trigger when the occupied zone degrades to RED.
- **render/**: pygame-ce renderer — near-black background, monochrome map (roads light grey, buildings dark grey), zone overlays as the ONLY colored elements (GREEN/AMBER/RED), pan/zoom camera, layer toggles, oriented vehicle chevrons with compliance halos, route corridors, HUD stats panel that also renders the most recent RouteValidationReport verdict.
- **scenario/**: a scripted, deterministic 90-second timeline (JSON file, §5.5): t+15s school-zone activation → Z-06 AMBER; t+20s weather degradation → Z-04 and Z-09 AMBER (vehicles in them slow to zone AMBER speed, no new pickups); t+30s traffic incident → Z-03 RED with vehicle egress (complete current ride, then exit); t+45s dispatch request whose route crosses Z-03 is validated and REJECTED, report shown in HUD.
- **Headless mode (first-class)**: `SDL_VIDEODRIVER=dummy` + `python -m osz.demo --headless --frames-out <dir>` writes deterministic PNG frames — the CI acceptance path AND the screenshot source.
- **Data**: committed fixture `data/fixtures/london_core.geojson.gz` (< 10 MB, generated once by the optional fetch script if network allows), guaranteed hand-authored fallback `data/fixtures/fallback_minimal.geojson`, 10 predefined zone JSONs, 2 sample borough boundary polygons.
- **Export**: `python -m osz.export_zones` writes regulatory-style zone spec JSON to `exports/`.
- Tests (all headless), `pyproject.toml`, `.gitignore`, and the fixtures.

**Environment constraints (binding):**

- Python **3.11+**, macOS ARM (Apple Silicon), no GPU, CPU rendering only.
- **No network at runtime.** The app loads committed fixtures only. `scripts/fetch_osm.py` / `scripts/fetch_overture.py` are optional offline tooling, never imported by `osz`.
- Runtime deps: `pygame-ce`, `shapely`, `networkx` **only** (§7). No pyproj (simple projection suffices, §5.1), no DuckDB at runtime, no FastAPI, no GeoParquet.
- All tests run with `SDL_VIDEODRIVER=dummy`; nothing in the test suite opens a window.
- Determinism: fixed `random.Random(seed)` instances (never the global RNG), fixed simulation timestep `DT = 0.1 s`, sim time decoupled from wall clock.

---

## 3. Non-Goals

| Non-goal | Reason |
|---|---|
| Live Overture Maps / OSM / weather / TfL data feeds | Overture is tens of GB; live feeds break determinism, offline operation, and one-shot reliability. Fixtures are committed; fetch scripts are optional generators only. |
| FastAPI dashboard backend | README lists it as optional Phase 4. A second process/UI doubles surface area with zero demo value for a desktop tactical renderer. Deferred (§12). |
| Web UI / browser map frameworks | Explicit README stance: native 2D engine for full control. |
| Full-London coverage | A ~3×4 km central bbox is visually dense and keeps the fixture < 10 MB and STRtree queries fast. Coverage breadth adds nothing to the story. |
| Actual regulatory document generation | Legal drafting is out of scope and risky. Instead: structured JSON export + an informative mapping table in this doc (§5.6). References to UK AV Act 2024 / EU AI Act are informative only, no legal claims. |
| Vehicle-level autonomy / perception / sensor models | README: "city and fleet level, not vehicle perception level." Vehicles are points moving on graph edges. |
| Realistic traffic / pathfinding beyond shortest-path | Dijkstra on edge length is enough to exercise the validator and fleet logic. No traffic assignment, no congestion. |
| Zone editing GUI | Zones are authored as JSON files; the versioning store handles programmatic updates. Editor UI is Phase-2 polish (§12). |
| pyproj / geodesic accuracy | At a 4 km extent the equirectangular error is centimeter-scale relative to rendering needs (§5.1). One less native-wheel dependency. |

---

## 4. System Overview

```
                          ┌────────────────────────────────────────────────┐
                          │                  osz.demo (CLI)                │
                          │   arg parsing · main loop · headless driver    │
                          └───────┬────────────────────────────┬───────────┘
                                  │                            │
             ┌────────────────────▼────────┐        ┌──────────▼──────────────┐
             │        scenario/            │        │        render/          │
             │ timeline loader · event     │        │ camera · map layers ·   │
             │ dispatcher (sim-time)       │        │ zones · fleet · HUD     │
             └───┬───────────┬─────────────┘        └──────────▲──────────────┘
                 │           │                                 │ reads state
   fires events  │           │ fires events                    │
   ┌─────────────▼──┐   ┌────▼───────────────┐      ┌──────────┴──────────────┐
   │    zones/      │   │      fleet/        │      │       routing/          │
   │ ZoneStore      │◄──┤ FleetSimulator     ├─────►│ RoadGraph · Router ·    │
   │ StatusEngine   │   │ Vehicle FSM ·      │      │ RouteValidator          │
   │ TransitionLog  │   │ compliance checks  │      │ (RouteValidationReport) │
   └───────┬────────┘   └────────┬───────────┘      └──────────┬──────────────┘
           │                     │                             │
           │        ┌────────────▼─────────────────────────────▼───┐
           └───────►│                    geo/                      │
                    │ FixtureLoader · Projection · SpatialIndex    │
                    └────────────────────┬─────────────────────────┘
                                         │
                    ┌────────────────────▼─────────────────────────┐
                    │ data/fixtures/*.geojson[.gz] · data/zones/*  │
                    └──────────────────────────────────────────────┘
```

**geo/** is the foundation: it loads the road/building fixture (trying `london_core.geojson.gz` first, falling back to `fallback_minimal.geojson`), builds the local equirectangular projection anchored at the fixture bbox center, and exposes STRtree-backed spatial queries ("which zone contains this point", "roads intersecting this viewport"). Everything above it works in projected meter coordinates; only the loader touches WGS84.

**zones/** owns the [redacted] domain model. `ZoneStore` loads/saves versioned zone JSON files; `StatusEngine` holds current status per zone, applies transitions requested by scenario events or schedule evaluation, enforces the legal transition set, and appends every transition to an in-memory + JSONL `TransitionLog` with cause attribution (event id, cause type, human-readable detail, sim-time and wall-clock timestamps).

**routing/** builds a `networkx.Graph` from fixture road LineStrings (nodes = rounded coordinates, edges = segment geometries with length weights), computes shortest paths, and — the centerpiece — validates a route polyline against the zone network: sampled every 5 m, it detects coverage gaps, zone transitions, minimum boundary margins, and per-zone constraint mismatches, returning a `RouteValidationReport` that is serializable, renderable, and assertable in tests.

**fleet/** runs 6 vehicles as finite state machines (IDLE → EN_ROUTE_PICKUP → OCCUPIED → EN_ROUTE_DEPOT/EGRESS) advancing along routed paths at zone-constrained speeds. Every tick it checks each vehicle's [redacted] compliance (inside an active zone? speed within zone limit? zone not RED?), computes distance to the nearest zone boundary for proximity warnings, and triggers handoff/egress when a vehicle's zone degrades to RED.

**render/** draws the world every frame from read-only state: dark map base, zone fills/outlines (the only chromatic elements), route corridors with margin buffers, vehicle chevrons oriented by heading with compliance halos, and a monospace HUD (sim clock, fleet stats, active warnings, transition ticker, last validation verdict). A `Camera` maps world meters → screen pixels with pan/zoom; layer toggles are keyboard-driven. Headless mode renders to an off-screen surface and saves PNGs.

**scenario/** loads `data/scenarios/demo_90s.json`, and each tick fires any events whose time has come — mutating zone status through `StatusEngine` (never directly), injecting the dispatch request through `Router`/`RouteValidator`, and stamping every effect with the event id so the transition log's cause attribution is complete.

**osz.demo** is the composition root: parses CLI args, seeds RNGs, constructs all components, runs the fixed-timestep loop (windowed at real-time, headless as fast as possible), and exits 0 on clean completion.

---

## 5. Data Contracts

This section is the hallucination firewall. Implement these schemas **exactly**; tests assert against them.

### 5.1 Coordinate systems & projection

- All fixture and zone geometry is **GeoJSON, WGS84 lon/lat** (RFC 7946 order: `[lon, lat]`).
- **Default fixture bbox (binding, EXACT):** `min_lon=-0.145, min_lat=51.500, max_lon=-0.085, max_lat=51.525` — central London, spanning Westminster/Whitehall/Soho west to St Paul's/City fringe east; ≈ 4.16 km E–W × 2.78 km N–S.
- **Projection: local equirectangular** anchored at the *loaded fixture's* bbox center `(lon0, lat0)` (computed at load time, so the fallback fixture works identically):

  ```
  x_m = (lon − lon0) · 111320 · cos(radians(lat0))
  y_m = (lat − lat0) · 110540          # note: y grows north; screen flips sign
  ```

  Documented choice: over a ≤ 5 km extent at 51.5° N, equirectangular distortion vs. a true transverse Mercator is < 0.1 % in distance — invisible at pixel scale and irrelevant to margin calculations quoted at ±1 m. This removes the pyproj native dependency entirely. Inverse: `lon = x/(111320·cos(lat0)) + lon0`, `lat = y/110540 + lat0`.
- All shapely geometry inside the app (zones, roads, routes, STRtree) lives in **projected meters** (x east, y north). Screen conversion `(px = (x − cam.x)·cam.zoom + w/2; py = h/2 − (y − cam.y)·cam.zoom)` happens only in `render/`.

### 5.2 GeoJSON fixture property schema (data contract for BOTH fixtures and both fetch scripts)

A fixture is a single GeoJSON `FeatureCollection`. Every feature MUST have `properties.feature_type` ∈ `{"road", "building", "borough"}`.

**Road feature** — `geometry.type == "LineString"` (fetch scripts must split MultiLineStrings):

| property | type | required | values / units |
|---|---|---|---|
| `feature_type` | str | yes | `"road"` |
| `road_id` | str | yes | unique, e.g. `"R-0042"` (assigned by fetch script or author) |
| `highway` | str | yes | one of `"primary"`, `"secondary"`, `"tertiary"`, `"residential"`, `"service"`, `"pedestrian"` (fetch scripts map any other OSM class to the nearest of these; `motorway|trunk → "primary"`, `unclassified|living_street → "residential"`, `footway|path → "pedestrian"`) |
| `name` | str \| null | yes | street name or null |
| `oneway` | bool | yes | default `false` if unknown |
| `maxspeed_kph` | number \| null | yes | posted limit; null if unknown (loader defaults null → 32 kph, i.e. 20 mph London default) |

**Building feature** — `geometry.type == "Polygon"`:

| property | type | required | values |
|---|---|---|---|
| `feature_type` | str | yes | `"building"` |
| `height_m` | number \| null | yes | null if unknown (render ignores height; kept for data fidelity) |

**Borough feature** — `geometry.type == "Polygon"` (exactly 2 in the default dataset, stored in `data/fixtures/boroughs.geojson`, same schema so the loader treats it as just another fixture file):

| property | type | required | values |
|---|---|---|---|
| `feature_type` | str | yes | `"borough"` |
| `borough_id` | str | yes | `"B-WST"`, `"B-COL"` |
| `name` | str | yes | `"City of Westminster (sample)"`, `"City of London (sample)"` |

The loader **rejects** (raises `FixtureError` naming the offending feature index) any feature missing a required property — this contract is what makes the fetch scripts optional: hand-authored, script-generated, and future Overture-derived files are interchangeable.

**`data/fixtures/fallback_minimal.geojson` (hand-authored, EXACT structure so it can be written deterministically):** an uncompressed FeatureCollection over the *same bbox* containing:

- **12 north–south streets**: LineStrings from `lat 51.500` to `lat 51.525` at longitudes `-0.145 + k·0.005` for `k = 0..12` **excluding** `k=6` (gap creates an [redacted] coverage hole for validator tests). Properties: `road_id="R-NS{k:02d}"`, `highway="secondary"` when `k` is even else `"residential"`, `name="NS Street {k}"`, `oneway=false`, `maxspeed_kph=32`.
- **6 east–west streets**: LineStrings from `lon -0.145` to `lon -0.085` at latitudes `51.500 + j·0.005` for `j = 0..5`. Properties: `road_id="R-EW{j:02d}"`, `highway="primary"` when `j in (1, 4)` else `"tertiary"`, `name="EW Street {j}"`, `oneway=false`, `maxspeed_kph=48` on primary else `32`.
- **1 diagonal avenue**: LineString `[-0.145, 51.500] → [-0.085, 51.525]` with vertices at each 0.005-lon step (13 points, lat linearly interpolated); `road_id="R-DIAG"`, `highway="primary"`, `name="Diagonal Avenue"`, `oneway=false`, `maxspeed_kph=48`. Because its vertices land exactly on grid longitudes but NOT on grid intersection points (except the two corners), the graph builder's node-snapping (§6, `routing/graph.py`) will still connect it at both endpoints — sufficient.
- **12 building footprints**: axis-aligned rectangular Polygons of 0.002° lon × 0.001° lat, one centered in each cell `(i, j)` for `i in (1, 3, 5, 8, 10)` paired cyclically with `j in (1, 2, 3, 4)` — exact placement: centers at `(-0.145 + i·0.005 + 0.0025, 51.500 + j·0.005 + 0.0025)` for the 12 `(i, j)` pairs `(1,1),(3,1),(5,1),(8,1),(10,1),(1,2),(3,2),(5,2),(8,2),(1,3),(3,3),(5,3)`. Properties: `feature_type="building"`, `height_m=null`.

Grid spacing 0.005° lon ≈ 347 m, 0.005° lat ≈ 553 m — a plausible stylized city grid. Total ≈ 31 features; the app must be fully functional (all zones, scenario, tests) on this fixture alone.

**`data/fixtures/london_core.geojson.gz`:** generated ONCE by `scripts/fetch_osm.py` (Overpass) if network allows during the run; geometry simplified with `shapely.simplify(tolerance=0.00002)`, coordinates rounded to 6 decimals, buildings filtered to footprint area > 200 m², target < 10 MB gzipped. **If network is unavailable, skip it — do not fabricate it**; the loader's fallback chain (`london_core.geojson.gz` → `fallback_minimal.geojson`) guarantees startup either way, and all acceptance criteria are written against the fallback-compatible behavior.

### 5.3 Zone JSON schema (`data/zones/Z-*.json`, one file per zone)

Attribute set derives 1:1 from README "Key Components → 2. Urban [redacted] Zone Management" (speed, weather, time-of-day, pedestrian density, road types, intersection complexity) plus versioning ("zones are versioned … timestamps and authorship").

Full field list:

| field | type | units / values | notes |
|---|---|---|---|
| `schema_version` | str | `"1.0"` | reject others |
| `zone_id` | str | `^Z-\d{2}$` | primary key = filename stem |
| `name` | str | — | |
| `version` | int | ≥ 1 | incremented by every `ZoneStore.save()` |
| `created_at` / `updated_at` | str | ISO 8601 UTC (`"2026-07-12T09:00:00Z"`) | |
| `author` | str | — | `"BRKMYR"` for fixtures |
| `default_status` | str | `"GREEN"` | status at sim start |
| `geometry` | object | GeoJSON `Polygon`, WGS84 | outer ring only, ≥ 4 points, closed |
| `attributes.max_speed_kph` | number | kph | zone-wide cap; AMBER cap is `amber_speed_kph` |
| `attributes.amber_speed_kph` | number | kph | speed cap applied while zone is AMBER |
| `attributes.weather.min_visibility_m` | number | meters | zone degrades if ambient visibility < this |
| `attributes.weather.max_precipitation_mmh` | number | mm/h | zone degrades if precipitation > this |
| `attributes.time_restrictions` | array | see below | may be empty |
| `attributes.max_pedestrian_density` | int | ordinal 1–5 (1 = sparse, 5 = crowd) | validator compares vs. vehicle capability |
| `attributes.allowed_road_types` | array[str] | subset of the `highway` enum (§5.2) | validator flags route segments on other classes |
| `attributes.max_intersection_complexity` | int | ordinal 1–5 (1 = signalized simple, 3 = roundabout, 5 = unprotected multi-modal) | informative in v1 validator (checked, single fixture value 2 per intersection) |
| `history` | array | prior full snapshots `{version, updated_at, author, attributes}` | appended on save; geometry history omitted for size |

`time_restrictions[]` entry: `{"label": str, "days": ["mon".."sun"], "start": "HH:MM", "end": "HH:MM", "effect": "AMBER"|"RED", "cause": str}` — evaluated against **scenario clock** (sim start maps to a scenario-defined wall time, §5.5), not the real clock.

**Example instance (`data/zones/Z-06.json`)** — also the template for authoring all ten:

```json
{
  "schema_version": "1.0",
  "zone_id": "Z-06",
  "name": "Bloomsbury School Quarter",
  "version": 1,
  "created_at": "2026-07-12T09:00:00Z",
  "updated_at": "2026-07-12T09:00:00Z",
  "author": "BRKMYR",
  "default_status": "GREEN",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-0.128, 51.518], [-0.118, 51.518], [-0.118, 51.524], [-0.128, 51.524], [-0.128, 51.518]]]
  },
  "attributes": {
    "max_speed_kph": 32,
    "amber_speed_kph": 16,
    "weather": {"min_visibility_m": 150, "max_precipitation_mmh": 8.0},
    "time_restrictions": [
      {"label": "School run", "days": ["mon", "tue", "wed", "thu", "fri"],
       "start": "08:00", "end": "09:30", "effect": "AMBER", "cause": "school_zone_active"}
    ],
    "max_pedestrian_density": 4,
    "allowed_road_types": ["primary", "secondary", "tertiary", "residential"],
    "max_intersection_complexity": 3
  },
  "history": []
}
```

**The 10 predefined zones (author all as axis-aligned rectangles inside the bbox; rectangles are honest for a simulation and trivially deterministic).** All share the Z-06 attribute defaults except where noted:

| zone_id | name | lon range | lat range | notable attributes |
|---|---|---|---|---|
| Z-01 | Westminster Core | −0.132 → −0.120 | 51.500 → 51.507 | `max_pedestrian_density: 5` |
| Z-02 | St James & Green Park East | −0.145 → −0.132 | 51.500 → 51.508 | |
| Z-03 | Covent Garden | −0.128 → −0.118 | 51.509 → 51.514 | `max_pedestrian_density: 5`; **goes RED at t+30** |
| Z-04 | Soho | −0.140 → −0.128 | 51.510 → 51.516 | `weather.min_visibility_m: 200` (weather-sensitive); **AMBER at t+20** |
| Z-05 | Holborn | −0.118 → −0.108 | 51.514 → 51.520 | |
| Z-06 | Bloomsbury School Quarter | −0.128 → −0.118 | 51.518 → 51.524 | school-zone restriction; **AMBER at t+15** |
| Z-07 | Fleet Street / City West | −0.108 → −0.098 | 51.510 → 51.517 | `allowed_road_types` excludes `"residential"` |
| Z-08 | Strand & Embankment | −0.122 → −0.108 | 51.505 → 51.511 | |
| Z-09 | Fitzrovia | −0.142 → −0.130 | 51.516 → 51.523 | `weather.min_visibility_m: 200`; **AMBER at t+20** |
| Z-10 | St Paul's Approach | −0.098 → −0.086 | 51.511 → 51.518 | `max_intersection_complexity: 2` |

Deliberate coverage properties (do not "fix" these): a **coverage gap corridor** around lon −0.115 between Z-03/Z-05 south edges and Z-08's north edge (lat 51.511–51.514, lon −0.118 → −0.108), and unzoned margins near the bbox edges — the route validator must be able to find real gaps. Z-03 is the only zone bridging lat 51.509–51.514 in lon −0.128→−0.118, so east–west routes through the center reliably cross it (the t+45 rejection depends on this).

### 5.4 RouteValidationReport schema

Produced by `routing/validator.py`; serialized with `dataclasses.asdict` → JSON. Example (the t+45 rejected dispatch, illustrative numbers):

```json
{
  "report_id": "RVR-0001",
  "created_at_sim_s": 45.0,
  "origin": {"node": [-0.135, 51.5125], "zone_id": "Z-04"},
  "destination": {"node": [-0.104, 51.5155], "zone_id": "Z-07"},
  "total_length_m": 2610.4,
  "sample_step_m": 5.0,
  "verdict": "REJECTED",
  "failures": [
    {"code": "ZONE_SUSPENDED", "zone_id": "Z-03",
     "message": "Route traverses Z-03 (Covent Garden) which is RED: traffic incident"},
    {"code": "COVERAGE_GAP", "zone_id": null,
     "message": "212.0 m of route outside any [redacted] zone"}
  ],
  "zone_transitions": [
    {"at_m": 480.0, "from_zone": "Z-04", "to_zone": "Z-03"},
    {"at_m": 1310.0, "from_zone": "Z-03", "to_zone": null},
    {"at_m": 1522.0, "from_zone": null, "to_zone": "Z-05"},
    {"at_m": 2280.0, "from_zone": "Z-05", "to_zone": "Z-07"}
  ],
  "coverage_gaps": [
    {"start_m": 1310.0, "end_m": 1522.0, "length_m": 212.0}
  ],
  "boundary_margins": [
    {"zone_id": "Z-04", "min_margin_m": 41.2, "at_m": 455.0}
  ],
  "constraint_mismatches": [
    {"zone_id": "Z-07", "constraint": "allowed_road_types",
     "required": ["primary", "secondary", "tertiary"], "actual": "residential",
     "at_m": 2405.0, "message": "Segment R-0107 is class 'residential', not permitted in Z-07"}
  ]
}
```

Rules (binding): `verdict` ∈ `{"APPROVED", "REJECTED"}`; REJECTED iff `failures` non-empty. Failure codes: `ZONE_SUSPENDED` (any sampled point in a RED zone), `COVERAGE_GAP` (total gap length > `max_gap_m`, default **50.0 m**; gaps ≤ 50 m are listed but non-fatal), `CONSTRAINT_MISMATCH` (any entry in `constraint_mismatches` — road class not in zone's `allowed_road_types`, zone `max_pedestrian_density` > vehicle capability [fixture vehicle capability = **4**], segment `maxspeed_kph` > zone `max_speed_kph` is *not* a failure — the vehicle just obeys the lower). AMBER zones are traversable but the report lists them in `zone_transitions`; an AMBER zone as the **pickup** zone fails with `NO_NEW_PICKUPS`. `boundary_margins` records, per zone traversed, the minimum distance from the route line to that zone's boundary while inside it (`polygon.exterior.distance(point)`), flagging `at_m` where it occurs.

### 5.5 Transition-log record schema

Kept in memory by `StatusEngine` and appended as JSON Lines to `exports/transitions.jsonl` in headless runs (and on demand). One record per line:

```json
{"seq": 3, "sim_t_s": 30.0, "wall_ts": "2026-07-12T10:00:30Z",
 "zone_id": "Z-03", "from_status": "GREEN", "to_status": "RED",
 "cause": {"type": "incident", "event_id": "EV-03",
           "detail": "Multi-vehicle collision reported, Long Acre"}}
```

`cause.type` ∈ `{"schedule", "weather", "incident", "event", "manual", "recovery"}` (matches README's trigger list). Legal transitions: GREEN↔AMBER, AMBER↔RED, GREEN→RED (emergency); RED→GREEN must pass through AMBER — `StatusEngine.set_status` raises `IllegalTransitionError` otherwise. `wall_ts` = scenario `start_wall_time` + `sim_t_s` (deterministic, NOT the real clock).

**Scenario timeline format (`data/scenarios/demo_90s.json`):**

```json
{
  "name": "demo_90s",
  "seed": 42,
  "duration_s": 90.0,
  "start_wall_time": "2026-07-12T08:05:00Z",
  "events": [
    {"event_id": "EV-01", "t_s": 15.0, "type": "schedule_check",
     "detail": "School-run window reached (simulated 08:05→ t+15 crosses 08:00 gate for Z-06)"},
    {"event_id": "EV-02", "t_s": 20.0, "type": "weather_set",
     "params": {"visibility_m": 120, "precipitation_mmh": 10.0},
     "detail": "Fog bank + heavy rain over west-central zones"},
    {"event_id": "EV-03", "t_s": 30.0, "type": "incident_start",
     "params": {"zone_id": "Z-03"},
     "detail": "Multi-vehicle collision reported, Long Acre"},
    {"event_id": "EV-04", "t_s": 45.0, "type": "dispatch_request",
     "params": {"origin_zone": "Z-04", "destination_zone": "Z-07"},
     "detail": "Ride request Soho → City West"},
    {"event_id": "EV-05", "t_s": 75.0, "type": "incident_clear",
     "params": {"zone_id": "Z-03", "to_status": "AMBER"},
     "detail": "Incident cleared; zone in recovery"}
  ]
}
```

Event semantics: `schedule_check` forces re-evaluation of all zones' `time_restrictions` against `start_wall_time + t_s` (with `start_wall_time` 08:05, Z-06's 08:00–09:30 window is active → AMBER, cause type `schedule`). `weather_set` updates global ambient weather; StatusEngine degrades every GREEN zone whose thresholds are violated (Z-04, Z-09 have `min_visibility_m: 200` > 120 → AMBER, cause `weather`; all other zones' threshold is 150 m > 120 too — **set all non-Z-04/Z-09 zones' `min_visibility_m` to 100** so exactly two zones degrade; this overrides the Z-06 example value when authoring the other eight zones). `incident_start` → target zone RED (cause `incident`), triggering fleet egress. `dispatch_request` → route origin/destination chosen as the road-graph nodes nearest the two zone centroids, validated; expected REJECTED (crosses RED Z-03 and/or the coverage gap). `incident_clear` → RED→AMBER (cause `recovery`). Origin zone Z-04 is AMBER at t+45, so `NO_NEW_PICKUPS` also fires — the report shows multiple failure causes, which is the point of the demo beat.

### 5.6 Zone-spec export format (`python -m osz.export_zones`)

Writes `exports/zone_specs.json`: `{"generated_at", "schema_version": "1.0", "zones": [ ... ]}` where each entry is the full zone JSON (§5.3) plus a `regulatory_mapping` block — an **informative** (non-legal) tag map: `{"bsi_pas_1883": ["scenery.zones", "environmental_conditions"], "iso_34503": ["[redacted] taxonomy: geographic area"], "uk_av_act_2024": "informative reference only", "local_authority": "<borough name from §5.2 borough polygons containing the zone centroid, else null>"}`. Also writes `exports/transitions.jsonl` if a scenario ran in the same process (demo does this; the export CLI exports specs only).

---

## 6. Module Breakdown (file-level)

Everything below is TO-BUILD. Layout: `src/` layout package, `pyproject.toml` with `[project] name="osz"`, setuptools, `package-dir = {"" = "src"}`. Implementation order = the `#` column; each step leaves the repo importable and its tests passing.

| # | File | Responsibility | Public API (signatures) | Depends on | ~LOC |
|---|---|---|---|---|---|
| 1 | `pyproject.toml` | Package metadata, pinned deps (§7), pytest config (`env: SDL_VIDEODRIVER=dummy` via `tool.pytest.ini_options` + conftest) | — | — | 40 |
| 2 | `src/osz/__init__.py` | Version string only | `__version__ = "0.1.0"` | — | 3 |
| 3 | `src/osz/config.py` | All constants: `BBOX = (-0.145, 51.500, -0.085, 51.525)`, `DT = 0.1`, `SAMPLE_STEP_M = 5.0`, `MAX_GAP_M = 50.0`, `BOUNDARY_WARN_M = 30.0`, `VEHICLE_CAP_PED_DENSITY = 4`, `N_VEHICLES = 6`, `SEED = 42`, color palette (`BG=(8,10,12)`, `ROAD=(90,95,100)`, `BUILDING=(28,32,36)`, `GREEN=(0,200,90)`, `AMBER=(255,176,0)`, `RED=(230,40,40)`, `UI=(200,205,210)`), path helpers `fixtures_dir() -> Path`, `zones_dir() -> Path` (resolved relative to repo root via `Path(__file__)`) | — | — | 60 |
| 4 | `src/osz/geo/__init__.py` | re-exports | — | — | 5 |
| 5 | `src/osz/geo/projection.py` | Equirectangular WGS84↔meters (§5.1) | `class Projection: __init__(self, lon0: float, lat0: float); to_xy(self, lon: float, lat: float) -> tuple[float, float]; to_lonlat(self, x: float, y: float) -> tuple[float, float]; project_geometry(self, geom: BaseGeometry) -> BaseGeometry` (uses `shapely.ops.transform`); `classmethod from_bbox(cls, bbox) -> Projection` | shapely | 60 |
| 6 | `src/osz/geo/loader.py` | Load fixture GeoJSON(.gz), validate §5.2 contract, project to meters | `class FixtureError(Exception)`; `@dataclass class MapData: roads: list[Road]; buildings: list[Building]; boroughs: list[Borough]; projection: Projection; bounds_m: tuple[float,float,float,float]` with `@dataclass class Road: road_id: str; highway: str; name: str|None; oneway: bool; maxspeed_kph: float; geom_m: LineString`; `Building(height_m, geom_m)`; `Borough(borough_id, name, geom_m)`; `load_fixture(path: Path) -> MapData`; `load_default() -> MapData` (tries `london_core.geojson.gz`, falls back to `fallback_minimal.geojson`, logs which) | projection, config | 150 |
| 7 | `src/osz/geo/spatial.py` | STRtree wrappers | `class SpatialIndex: __init__(self, geoms: list[BaseGeometry], payloads: list[Any]); query(self, geom: BaseGeometry) -> list[Any]` (STRtree returns indices in shapely 2.x — map back to payloads); `nearest(self, geom) -> Any`; module fn `zones_containing(point: Point, zone_index: SpatialIndex) -> list[Zone]` (query then exact `covers` filter) | shapely | 70 |
| 8 | `src/osz/zones/__init__.py` | re-exports | — | — | 5 |
| 9 | `src/osz/zones/model.py` | Zone dataclasses + (de)serialization per §5.3 | `class Status(StrEnum): GREEN, AMBER, RED`; `@dataclass class TimeRestriction(label, days, start, end, effect, cause)` with `active_at(self, wall: datetime) -> bool`; `@dataclass class ZoneAttributes(max_speed_kph, amber_speed_kph, min_visibility_m, max_precipitation_mmh, time_restrictions, max_pedestrian_density, allowed_road_types, max_intersection_complexity)`; `@dataclass class Zone(zone_id, name, version, created_at, updated_at, author, default_status, geom_wgs: Polygon, geom_m: Polygon|None, attributes, history)` with `to_dict()`, `classmethod from_dict(d) -> Zone` (validates schema_version, id pattern, ring closure; raises `ZoneSchemaError`) | shapely | 180 |
| 10 | `src/osz/zones/store.py` | Versioned persistence, one JSON per zone | `class ZoneStore: __init__(self, directory: Path); load_all(self, projection: Projection) -> dict[str, Zone]` (projects `geom_m`); `save(self, zone: Zone) -> Zone` (bumps `version`, sets `updated_at`, appends prior attribute snapshot to `history`, atomic write via temp file + rename); `get(self, zone_id) -> Zone` | model | 100 |
| 11 | `src/osz/zones/status.py` | Status engine + transition log (§5.5) | `class IllegalTransitionError(Exception)`; `@dataclass class Transition(seq, sim_t_s, wall_ts, zone_id, from_status, to_status, cause: dict)`; `class StatusEngine: __init__(self, zones: dict[str, Zone], start_wall: datetime); status(self, zone_id) -> Status; set_status(self, zone_id, to: Status, cause_type: str, event_id: str, detail: str, sim_t: float) -> Transition` (validates legality per §5.5, no-op returns None if unchanged); `apply_weather(self, visibility_m: float, precip_mmh: float, event_id, detail, sim_t) -> list[Transition]` (degrade GREEN→AMBER on threshold breach; recover AMBER→GREEN when cleared AND no other active cause — track `active_causes: dict[zone_id, set[str]]`); `evaluate_schedules(self, sim_t: float, event_id: str) -> list[Transition]`; `log: list[Transition]`; `write_jsonl(self, path: Path) -> None` | model, config | 200 |
| 12 | `src/osz/routing/__init__.py` | re-exports | — | — | 5 |
| 13 | `src/osz/routing/graph.py` | Road graph from MapData | `class RoadGraph: __init__(self, mapdata: MapData)` — nodes = coords rounded to 0.1 m `(round(x,1), round(y,1))` so shared street endpoints/vertices snap together; every LineString vertex becomes a node, every consecutive vertex pair an edge with `length` (euclidean m), `road_id`, `highway`, `maxspeed_kph`; graph is `nx.Graph` (ignore oneway in v1 — documented simplification); `nearest_node(self, x: float, y: float) -> tuple` (linear scan or SpatialIndex of node points); `largest_component(self) -> RoadGraph` (route only on the giant component); property `graph: nx.Graph` | networkx, loader, spatial | 120 |
| 14 | `src/osz/routing/router.py` | Shortest path → polyline | `@dataclass class Route(route_id: str, nodes: list, line_m: LineString, length_m: float, edges: list[dict])`; `class Router: __init__(self, road_graph: RoadGraph); route(self, origin_xy: tuple, dest_xy: tuple) -> Route|None` (`nx.shortest_path(weight="length")`, None if `nx.NetworkXNoPath`); `route_between_zones(self, za: Zone, zb: Zone) -> Route|None` (nearest nodes to zone centroids) | graph | 90 |
| 15 | `src/osz/routing/validator.py` | §5.4 report, exactly | dataclasses `ZoneTransition(at_m, from_zone, to_zone)`, `CoverageGap(start_m, end_m, length_m)`, `BoundaryMargin(zone_id, min_margin_m, at_m)`, `ConstraintMismatch(zone_id, constraint, required, actual, at_m, message)`, `Failure(code, zone_id, message)`, `@dataclass class RouteValidationReport(...)` per §5.4 with `to_dict()`, `verdict` property; `class RouteValidator: __init__(self, zone_index: SpatialIndex, engine: StatusEngine, vehicle_ped_capability: int = 4); validate(self, route: Route, sim_t: float, is_pickup: bool = True) -> RouteValidationReport` — sample `line_m` every `SAMPLE_STEP_M` via `line.interpolate(d)`, resolve containing zone per sample (ties → lowest zone_id, documented), build transitions/gaps/margins/mismatches, apply failure rules incl. `NO_NEW_PICKUPS` when `is_pickup` and origin zone AMBER | spatial, status, router, config | 260 |
| 16 | `src/osz/fleet/__init__.py` | re-exports | — | — | 5 |
| 17 | `src/osz/fleet/vehicle.py` | Vehicle FSM + kinematics | `class VehicleState(StrEnum): IDLE, EN_ROUTE_PICKUP, OCCUPIED, EGRESS`; `@dataclass class Vehicle(vehicle_id: str, state: VehicleState, route: Route|None, dist_along_m: float, speed_kph: float, pos_m: tuple[float,float], heading_rad: float, current_zone: str|None, compliant: bool, warning: str|None)` with `advance(self, dt: float, speed_cap_kph: float) -> None` (move `dist_along_m` by `min(speed, cap)·dt`, update `pos_m = route.line_m.interpolate(dist)`, heading from positional delta), `at_route_end(self) -> bool` | router | 110 |
| 18 | `src/osz/fleet/simulator.py` | Fleet orchestration, per-tick compliance | `@dataclass class FleetStats(n_in_zone: int, n_warnings: int, n_noncompliant: int, n_handoffs: int, rides_completed: int)`; `class FleetSimulator: __init__(self, router: Router, zone_index: SpatialIndex, engine: StatusEngine, validator: RouteValidator, rng: random.Random, n_vehicles: int = 6)` — spawn vehicles at random graph nodes inside GREEN zones; `tick(self, sim_t: float, dt: float) -> FleetStats` per vehicle: resolve `current_zone` (zones_containing), speed cap = zone `max_speed_kph` (AMBER → `amber_speed_kph`), **compliance check**: compliant iff inside a zone AND zone not RED; boundary proximity: if margin `< BOUNDARY_WARN_M` set `warning="BOUNDARY {margin:.0f}m"`; **pickup/dropoff cycle**: IDLE → pick random GREEN-zone destination pair, route validated with `is_pickup=True` — only dispatch if APPROVED → EN_ROUTE_PICKUP → at end flip OCCUPIED with new validated route → at end `rides_completed += 1` → IDLE; **handoff/egress**: if current zone goes RED — OCCUPIED vehicles keep going (complete ride) then EGRESS-route to nearest node outside the RED zone; non-occupied vehicles immediately EGRESS; count `n_handoffs`; expose `vehicles: list[Vehicle]`, `handoff_events: list[dict]` | vehicle, validator, status, spatial, config | 240 |
| 19 | `src/osz/scenario/__init__.py` | re-exports | — | — | 5 |
| 20 | `src/osz/scenario/timeline.py` | Load + dispatch §5.5 events | `@dataclass class ScenarioEvent(event_id, t_s, type, params: dict, detail: str)`; `@dataclass class Scenario(name, seed, duration_s, start_wall: datetime, events: list[ScenarioEvent])` with `classmethod load(path: Path) -> Scenario`; `class ScenarioRunner: __init__(self, scenario, engine: StatusEngine, fleet: FleetSimulator, router: Router, validator: RouteValidator, zones: dict); tick(self, sim_t: float) -> list[str]` (fires events whose `t_s <= sim_t` and not yet fired, in order; returns HUD ticker lines); handlers `_schedule_check`, `_weather_set`, `_incident_start`, `_dispatch_request` (stores `last_report: RouteValidationReport|None` for HUD), `_incident_clear`; property `done(sim_t) -> bool` | status, simulator, validator | 170 |
| 21 | `src/osz/render/__init__.py` | re-exports | — | — | 5 |
| 22 | `src/osz/render/camera.py` | World-m ↔ screen-px | `@dataclass class Camera(cx: float, cy: float, zoom: float, screen_w: int, screen_h: int)` with `to_screen(self, x, y) -> tuple[int,int]`, `to_world(self, px, py)`, `pan(self, dx_px, dy_px)`, `zoom_at(self, px, py, factor)` (clamp zoom 0.05–10 px/m), `classmethod fit(cls, bounds_m, w, h) -> Camera` | — | 80 |
| 23 | `src/osz/render/layers.py` | Map/zone/route/fleet draw passes, each `draw_*(surface, camera, ...)` | `draw_roads(surf, cam, roads, show: bool)` (width by class: primary 3px·zoom-scaled, else 1–2px, color `ROAD`); `draw_buildings(surf, cam, buildings, show)`; `draw_boroughs(surf, cam, boroughs, show)` (dashed grey outline: sample exterior every 8 m, draw alternate segments); `draw_zones(surf, cam, zones, engine, show)` — per zone: fill on a per-frame `SRCALPHA` overlay surface with status color at alpha 45, outline alpha 200 width 2; `draw_route(surf, cam, route, ok: bool)` (corridor: 12 m-wide translucent band via `pygame.draw.lines` on overlay with scaled width + center line); `draw_vehicles(surf, cam, vehicles)` (chevron = 3-point polygon rotated by heading, ~10 px; halo circle: GREEN compliant / AMBER warning / RED non-compliant) | camera, config, pygame | 260 |
| 24 | `src/osz/render/hud.py` | Monospace HUD panel | `class Hud: __init__(self, font_size: int = 14)` (`pygame.font.SysFont("menlo,monaco,monospace", size)`); `draw(self, surf, sim_t, engine, stats: FleetStats, ticker: list[str], report: RouteValidationReport|None, fps: float)` — top-left: clock `T+SS.s`, wall time, zone status table (id, name, status char blocked ▮ in status color); top-right: fleet stats; bottom: last-5 transition ticker; when `report` is set: right-side panel with verdict, failure codes+messages, gap total, transition count (word-wrapped, max 46 chars) | config, pygame | 180 |
| 25 | `src/osz/render/renderer.py` | Compose frame; window & headless surfaces | `class Renderer: __init__(self, width: int = 1280, height: int = 800, headless: bool = False)` — headless: `pygame.Surface((w,h))` only after `pygame.init()` with `SDL_VIDEODRIVER=dummy` already in env (set by demo before `pygame.init()`), windowed: `pygame.display.set_mode`; `layer_flags: dict[str, bool]` (roads/buildings/zones/boroughs/routes/vehicles/hud → True); `render(self, world) -> pygame.Surface` (world = plain namespace bundling mapdata/zones/engine/fleet/runner/camera/report); `save_frame(self, path: Path)`; `handle_event(self, ev, camera)` (pan: arrow keys or mouse-drag; zoom: `+`/`-`/wheel; toggles: `1`=roads `2`=buildings `3`=zones `4`=boroughs `5`=routes `6`=vehicles `h`=hud; `ESC` quit) | camera, layers, hud | 200 |
| 26 | `src/osz/demo.py` + `src/osz/__main__.py` guard | CLI + main loop (composition root) | `main(argv: list[str]|None = None) -> int`; argparse: `--headless` (sets `SDL_VIDEODRIVER=dummy` **before** importing/initing pygame display), `--frames-out DIR` (save 1 PNG per sim-second: `frame_0000.png` … zero-padded seconds), `--duration SECONDS` (default 90.0), `--scenario PATH` (default `data/scenarios/demo_90s.json`), `--fixture PATH` (default auto §6.6), `--seed INT` (default from scenario), `--width/--height`; loop: fixed `DT=0.1` sim steps; windowed: real-time via `pygame.time.Clock().tick(30)` with accumulator; headless: no sleep, render+save only at whole sim-seconds; on completion write `exports/transitions.jsonl` and print summary line `OSZ demo complete: t=90.0s frames=91 transitions=<n> rides=<n> last_verdict=REJECTED`; return 0. `python -m osz.demo` works via `if __name__ == "__main__": raise SystemExit(main())` | everything | 220 |
| 27 | `src/osz/export_zones.py` | §5.6 export CLI | `main(argv=None) -> int`; args `--zones-dir`, `--out` (default `exports/zone_specs.json`), `--boroughs PATH`; loads zones + boroughs, computes `local_authority` by centroid containment, writes JSON, prints `Exported 10 zone specs -> exports/zone_specs.json`; runnable as `python -m osz.export_zones` | store, loader | 90 |
| 28 | `data/fixtures/fallback_minimal.geojson` | §5.2 exact grid — author by running a throwaway generation snippet or by hand; commit the file | — | — | (data) |
| 29 | `data/fixtures/boroughs.geojson` | 2 sample polygons: B-WST rectangle lon −0.145→−0.116 lat 51.500→51.525; B-COL rectangle lon −0.116→−0.085 lat 51.500→51.525 (stylized samples, named "(sample)") | — | — | (data) |
| 30 | `data/zones/Z-01.json` … `Z-10.json` | §5.3 table, Z-06 example as template; remember `min_visibility_m: 100` for all except Z-04/Z-09 (=200) | — | — | (data) |
| 31 | `data/scenarios/demo_90s.json` | exactly §5.5 | — | — | (data) |
| 32 | `scripts/fetch_osm.py` | OPTIONAL, standalone (stdlib `urllib` + `json` + shapely): Overpass API bbox query (`highway` ways of the 6 mapped classes + `building` ways) for the §5.1 bbox, map to §5.2 contract, simplify, write `data/fixtures/london_core.geojson.gz`; graceful `sys.exit(1)` with message on any network error; never imported by `osz` | — | 160 |
| 33 | `scripts/fetch_overture.py` | OPTIONAL, DOCUMENTED-ONLY implementation: DuckDB httpfs query against Overture S3 (`theme=transportation/type=segment`, `theme=buildings`) for the bbox → same contract; guarded `import duckdb` with install hint (duckdb NOT in project deps) | — | 120 |
| 34 | `tests/conftest.py` | `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` at import; fixtures: `mapdata()` (fallback fixture), `zones()`, `engine()`, `road_graph()`, `router()`, `validator()` | — | 60 |
| 35 | `tests/test_projection.py` … `test_scenario_headless.py` (6 files, §10) | — | — | — | 450 |
| 36 | `.gitignore` | `__pycache__/`, `exports/`, `docs/screenshots/`, `.pytest_cache/`, `*.egg-info/` — note: `london_core.geojson.gz` IS committed if generated | — | — | 10 |

Total ≈ 3,700 LOC of Python. If any single file balloons past ~1.5× its budget, cut rendering polish — never cut data contracts, validator logic, or tests.

---

## 7. Dependencies

`pyproject.toml` `[project.dependencies]` — exactly three runtime deps, compatible-release pinned:

| Package | Pin | Justification |
|---|---|---|
| `pygame-ce` | `>=2.5,<3` | Actively maintained pygame fork; prebuilt macOS ARM wheels; SDL2 `dummy` videodriver enables true headless rendering + `pygame.image.save` for PNG frames. |
| `shapely` | `>=2.0,<3` | Shapely 2.x vectorized API + `STRtree` (returns index arrays — code must map indices→payloads); polygons, `covers`, `interpolate`, `distance`, `simplify` cover every geometric need. Binary wheels for macOS ARM. |
| `networkx` | `>=3.2,<4` | Pure-Python (no wheel risk), `shortest_path(weight=...)`, connected-components. Graph size (~10³–10⁴ nodes for the fixture) is well within pure-Python performance. |

`[project.optional-dependencies] dev`: `pytest>=8,<9` (test runner, no plugins needed). **Explicitly excluded**: `pyproj` (§5.1 projection is 4 lines of math at this extent), `duckdb` (only mentioned inside the optional, guarded `scripts/fetch_overture.py`), `numpy` (nothing here needs array math; shapely's internal numpy comes transitively and is not imported directly). `requires-python = ">=3.11"` (uses `StrEnum`, `datetime.UTC`).

---

## 8. Acceptance Criteria

Run all from repo root after `pip install -e ".[dev]"`. Every criterion is `command → observable expected output`.

1. `pip install -e ".[dev]"` → exits 0; `python -c "import osz; print(osz.__version__)"` prints `0.1.0`.
2. `pytest -q` → all tests pass, exit code 0, no window ever opens (conftest sets `SDL_VIDEODRIVER=dummy`).
3. `python -m osz.demo --headless --frames-out /tmp/osz_frames --duration 90` → exit code 0; `/tmp/osz_frames` contains **91 PNGs** (`frame_0000.png` … `frame_0090.png`, one per whole sim-second incl. t=0); final stdout line matches `OSZ demo complete: t=90.0s frames=91 transitions=<int> rides=<int> last_verdict=REJECTED`.
4. Same run → `exports/transitions.jsonl` exists; parsed as JSONL it contains, in `seq` order: a record `{"zone_id": "Z-06", "to_status": "AMBER", "cause": {"type": "schedule", "event_id": "EV-01", ...}}` at `sim_t_s == 15.0`; records for **both** `Z-04` and `Z-09` → AMBER with `cause.type == "weather"`, `event_id == "EV-02"` at `sim_t_s == 20.0`; `Z-03` → RED with `cause.type == "incident"`, `event_id == "EV-03"` at `sim_t_s == 30.0`; `Z-03` RED → AMBER with `cause.type == "recovery"` at `sim_t_s == 75.0`; **no other zone** ever leaves GREEN.
5. Determinism: run criterion 3 twice with `--frames-out /tmp/osz_a` and `/tmp/osz_b` → `cmp /tmp/osz_a/frame_0060.png /tmp/osz_b/frame_0060.png` reports identical (byte-identical frames from fixed seed + fixed timestep).
6. Visual assertions (programmatic, also encoded as the integration test): loading `frame_0035.png` with pygame and sampling the pixel at the screen position of Z-03's centroid (compute via the same `Camera.fit` used by the demo) → red channel > 60 and red > green (RED overlay present); same sample in `frame_0010.png` → green > red (GREEN overlay).
7. Dispatch rejection: during the same headless run, `ScenarioRunner.last_report` after t=45 (asserted in integration test, and visible in HUD frames ≥ `frame_0045.png`) has `verdict == "REJECTED"` with failure codes including `"ZONE_SUSPENDED"`; the serialized report is written to `exports/last_validation_report.json` and is valid JSON matching §5.4 field names.
8. `python -m osz.export_zones` → exit 0; prints `Exported 10 zone specs -> exports/zone_specs.json`; the file parses; `len(data["zones"]) == 10`; every zone has `regulatory_mapping.local_authority` ∈ `{"City of Westminster (sample)", "City of London (sample)"}`; `data["zones"][i]["zone_id"]` are exactly Z-01…Z-10.
9. Fallback guarantee: `python -m osz.demo --headless --fixture data/fixtures/fallback_minimal.geojson --frames-out /tmp/osz_fb --duration 20` → exit 0, ≥ 21 PNGs (app fully functional on the hand-authored grid; this also holds automatically when `london_core.geojson.gz` is absent).
10. Windowed smoke (manual, not CI): `python -m osz.demo` → a 1280×800 window opens showing dark map, colored zones, moving chevrons; keys `1–6`/`h` toggle layers, arrows pan, `+`/`-` zoom, `ESC` exits 0. (If the implementing environment cannot open a window, this criterion is satisfied by criteria 3–6.)
11. `python -m osz.demo --headless --frames-out docs/screenshots --duration 90` → populates `docs/screenshots/` (gitignored) used by §9.
12. Zone versioning: covered by unit test — `ZoneStore.save()` on a loaded zone bumps `version` 1→2, updates `updated_at`, appends one `history` entry, and a reload round-trips equal attributes.

---

## 9. Demo Script

Recording/reviewing flow (~60 s narration over the 90 s scenario; headless frames double as the screenshot set):

```bash
pip install -e ".[dev]"
pytest -q                                                        # green suite first
python -m osz.demo --headless --frames-out docs/screenshots --duration 90
python -m osz.export_zones
python -m osz.demo                                               # live windowed run for the actual demo
```

Narration beats (timestamps = sim time; the presenter just watches the scripted timeline):

- **0:00–0:10 — "This is central London's road network with ten [redacted] zones."** All zones GREEN. Pan/zoom briefly; hit `2` to toggle buildings, `4` to show borough sample boundaries. *Frame kept: `frame_0005.png` — hero shot, all-green board.*
- **0:15 — "08:20 school run: Z-06 self-activates from its time-restriction schedule — no human in the loop, cause-attributed in the log."** Z-06 flips AMBER; HUD ticker shows `schedule` cause. *Frame kept: `frame_0016.png`.*
- **0:20 — "Fog bank rolls in. Two visibility-sensitive zones degrade to AMBER: vehicles inside slow to 16 km/h and take no new pickups."** Z-04, Z-09 AMBER; chevrons in them visibly slow. *Frame kept: `frame_0022.png`.*
- **0:30 — "Incident in Covent Garden. Z-03 goes RED: occupied vehicles complete their ride, everything else egresses immediately — that's the handoff discipline regulators require."** Z-03 RED, egress arrows leave the zone, handoff counter increments. *Frames kept: `frame_0031.png`, `frame_0038.png`.*
- **0:45 — "A dispatch request arrives: Soho to the City. The route validator rejects it — structured report, not a boolean: route crosses a suspended zone, has a 200 m [redacted] coverage gap, and the pickup zone bans new pickups while AMBER."** HUD shows the REJECTED report panel. *Frame kept: `frame_0046.png` — the money shot for [redacted]-verification reviewers.*
- **0:75–0:90 — "Incident clears: RED must recover through AMBER — illegal transitions are rejected by the engine. Every transition you saw is in an auditable JSONL log with cause attribution, and the zone definitions export as versioned, regulator-mappable JSON."** Show `exports/transitions.jsonl` and `exports/zone_specs.json` in a terminal. *Frame kept: `frame_0080.png`.*

The seven kept frames are copied to `docs/screenshots/` (already written there by the headless run); the top three (`0005`, `0031`, `0046`) are the README-embed candidates.

---

## 10. Test Plan

All headless (`SDL_VIDEODRIVER=dummy` via `tests/conftest.py`). Determinism throughout: `random.Random(42)`, `DT=0.1`, scenario wall clock — never `datetime.now()` inside sim logic.

**Unit — `tests/test_projection.py`:** round-trip `to_xy`→`to_lonlat` within 1e-9°; known distance: two points 0.01° lon apart at lat0=51.5125 → Δx = 111320·0.01·cos(51.5125°) ± 0.5 m; y grows north; `project_geometry` preserves polygon area vs. manual vertex projection.

**Unit — `tests/test_zone_store.py`:** load all 10 committed zones → schema-valid, ids Z-01…Z-10; `from_dict` rejects bad `schema_version`, unclosed ring, bad id (raises `ZoneSchemaError`); save→reload version bump per acceptance criterion 12; atomic write leaves no `*.tmp`.

**Unit — `tests/test_status_engine.py`:** legal transitions succeed and append log records with correct `seq`/`wall_ts`; `RED→GREEN` raises `IllegalTransitionError`; `apply_weather(visibility=120)` degrades exactly Z-04/Z-09 (thresholds 200) and not the 100-threshold zones; weather recovery returns AMBER→GREEN only when no other active cause (activate school restriction on Z-04-like fixture zone, clear weather, assert still AMBER); `evaluate_schedules` at wall 08:20 Tue activates Z-06 and is idempotent (second call → no new transitions).

**Unit — `tests/test_validator.py`:** built on the fallback grid + synthetic zones. Cases: (a) **pass** — route entirely inside one GREEN zone → APPROVED, no gaps, ≥ 1 boundary margin entry; (b) **fail RED** — set a traversed zone RED → REJECTED with `ZONE_SUSPENDED`; (c) **gap** — route through the deliberate `k=6` street gap / unzoned corridor → `coverage_gaps` non-empty, REJECTED iff total gap > 50 m, gap lengths sum to within one sample step (±5 m) of geometric truth; (d) **constraint mismatch** — zone with `allowed_road_types=["primary"]` over a residential street → `CONSTRAINT_MISMATCH`; (e) **AMBER pickup** — origin zone AMBER, `is_pickup=True` → `NO_NEW_PICKUPS`; same route `is_pickup=False` → code absent; (f) report `to_dict()` keys exactly match §5.4.

**Unit — `tests/test_fleet_compliance.py`:** vehicle advancing along a route respects AMBER speed cap (position delta per tick = `amber_speed_kph/3.6·DT` ± ε); vehicle inside a zone flipped RED: OCCUPIED → keeps state until route end then EGRESS; IDLE/EN_ROUTE_PICKUP → EGRESS immediately, `n_handoffs` increments once; boundary warning set when within 30 m of zone edge, cleared beyond; `compliant=False` exactly when outside all zones or inside RED.

**Integration — `tests/test_scenario_headless.py`:** run `osz.demo.main(["--headless", "--frames-out", tmp, "--duration", "90"])` in-process → asserts acceptance criteria 3, 4, 6, 7 programmatically (frame count, transition-log contents and ordering, Z-03 centroid pixel color at t=10 vs t=35, `last_verdict REJECTED` with `ZONE_SUSPENDED`); second run into a second tmp dir → `frame_0060.png` byte-identical (criterion 5). This is the CI gate; budget < 60 s wall time (headless runs uncapped).

---

## 11. Risks & Fallbacks

| Risk | Detection | Fallback (all pre-decided — no mid-run judgment calls) |
|---|---|---|
| `london_core.geojson.gz` generation blocked (no network / Overpass down / file > 10 MB) | `scripts/fetch_osm.py` exits non-zero or oversize | Ship on `fallback_minimal.geojson` only; loader's fallback chain makes this invisible to code and tests. All acceptance criteria are satisfiable on the fallback fixture by design. Do NOT stub or fake the London file. |
| pygame display init fails on the build machine (no window server) | `pygame.error` on `set_mode` | Headless is the first-class path: demo sets `SDL_VIDEODRIVER=dummy` before `pygame.init()` when `--headless`; tests always set it. Windowed mode is acceptance criterion 10 only, explicitly waivable. |
| Fonts unavailable for HUD (`SysFont` returns None-ish on bare CI) | `pygame.font` fallback | `SysFont("menlo,monaco,monospace", size)` falls back to pygame's bundled freesansbold via `pygame.font.Font(None, size)` wrapped in try/except — HUD must never crash a frame. |
| STRtree performance with per-tick per-vehicle queries on the real London fixture (~10⁴ roads) | frame time > 33 ms windowed | Zones tree has only 10 geometries — vehicle-zone containment is trivially fast. Roads tree queried only per viewport change; cache the visible-road list on the camera's `(cx, cy, zoom)` key. If still slow: pre-simplify road geometry at load (`simplify(0.5 m)`); render is allowed to drop to 15 fps windowed, headless has no budget. |
| Shapely 2.x `STRtree.query` returns indices, not geometries (classic 1.x→2.x trap) | tests | `SpatialIndex` wrapper (§6 item 7) owns the index→payload mapping; nothing else touches STRtree directly. |
| Overpass returns MultiLineStrings / weird classes | fetch-time | fetch script splits Multi* and maps unknown `highway` to the 6-class enum (§5.2); loader hard-rejects contract violations so bad data fails loud at generation time, not runtime. |
| Route between zone centroids not found (disconnected graph) | `Router.route` returns None | Graph reduced to largest connected component at build; if still None, `dispatch_request` produces a REJECTED report with failure code `NO_ROUTE` (add to §5.4 code set) rather than crashing. |
| Frame PNG nondeterminism (timestamps in encoder) | `cmp` in test | `pygame.image.save` writes no wall-clock metadata for PNG; keep it that way by rendering wall_ts from scenario clock only. If a platform discrepancy ever appears, fall back to comparing surface buffers (`pygame.image.tobytes`) instead of files — test helper supports both. |

---

## 12. Deferred (v2) — mirrors README roadmap items not built here

- **Overture Maps as a first-class source** (README Phase 1): `scripts/fetch_overture.py` is documented-only; v2 wires DuckDB/GeoParquet ingestion and larger coverage.
- **Zone creation/editing UI** (Phase 2): v1 zones are authored JSON; v2 adds in-app polygon drawing and attribute editing on top of the existing versioned `ZoneStore`.
- **Intersection complexity scoring from map topology** (Phase 2): v1 carries the attribute and checks it with a fixture constant; v2 derives per-intersection ratings (signals, arms, turn conflicts) from OSM tags.
- **Live condition feeds** — weather API, TfL disruptions, event calendars (Phase 2/3 triggers): v1 is scenario-scripted by design; v2 adds pluggable condition providers behind the same `StatusEngine.apply_weather`-style interface.
- **Richer fleet behavior** (Phase 3): demand modeling, depot charging, remote-operator handoff sessions (v1 only counts handoff triggers), oneway-aware directed routing.
- **FastAPI dashboard backend + web overlay** (Phase 4, README "optional"): serve fleet/zone state as JSON for external dashboards.
- **Full borough coverage & real GLA boundary data** (Phase 4): v1 ships 2 stylized sample polygons; v2 ingests all 33 authorities from official boundary datasets.
- **Regulatory submission packs** (Phase 4): v1 exports zone-spec JSON + the informative mapping block (§5.6); v2 adds templated PAS 1883/ISO 34503-structured documents.
