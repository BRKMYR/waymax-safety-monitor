# Operational Safety Zones

**Status: In Development — Q1 2026**

A simulation and visualization platform for managing Operational Safety Zones for autonomous vehicles. Renders a top-down tactical map view of London showing geo-fenced zones where autonomous vehicles can operate, with real-time monitoring of zone status, [redacted] compliance, and route safety validation.

---

## Why This Matters

Autonomous vehicles will not operate everywhere at once. Commercial AV deployment begins with defined geographic zones -- carefully scoped [redacted]s where the vehicle's capabilities are proven safe. This is not a limitation; it is the architecture of real-world autonomy.

The problem is that no one has built the operational tooling for this model:

- **Cities and regulators** need to define where AVs can operate, under what conditions, and with what constraints. They need auditable zone configurations tied to regulatory requirements.
- **AV operators** need to monitor zone status in real time -- weather degradation, construction, incidents -- and ensure their fleets only operate within approved boundaries.
- **Route planning systems** need to validate that every meter of a planned route falls within an active, compliant [redacted] zone before dispatching a vehicle.
- **The transition from geo-fenced pilots to scalable operations** requires systematic [redacted] management: versioned zone definitions, dynamic status, compliance tracking, and fleet-level monitoring.

Zone management is the operational backbone of commercial AV deployment. This is where mapping expertise meets autonomous driving operations.

---

## What This Project Does

Operational Safety Zones is a self-contained simulation platform that models the full operational lifecycle of AV zone management for a real city (London). It combines a real-time 2D map renderer with a zone management engine, fleet simulation, and compliance layer.

The system ingests real geospatial data (OpenStreetMap / Overture Maps), renders it as a top-down tactical map, and overlays operational zones with live status. A simulated AV fleet operates within the zones, subject to dynamic conditions and [redacted] constraints.

This is a planning, monitoring, and validation tool -- not a vehicle autonomy stack. It operates at the city and fleet level, not at the vehicle perception level.

---

## Key Components

### 1. Top-Down Map Renderer

Real-time 2D map visualization of London using OpenStreetMap and Overture Maps data. Renders road networks, building footprints, and zone boundaries in a clean, high-contrast style inspired by tactical map systems. Supports pan, zoom, and layer toggling. The map is the primary interface -- all other components are rendered on top of it.

### 2. [redacted] Zone Management

Define, edit, and monitor [redacted]s as geographic polygons. Each zone carries a structured attribute set:

- Speed limits (per road segment or zone-wide)
- Weather constraints (visibility minimums, precipitation thresholds)
- Time-of-day restrictions (operational windows)
- Sensor requirements (LiDAR range, camera availability)
- Road type constraints (motorway, urban, single carriageway)

Zones are versioned. Changes to zone definitions are tracked with timestamps and authorship.

### 3. Dynamic Zone Status

Zones have a real-time status derived from live conditions:

| Status | Meaning |
|--------|---------|
| **GREEN** | Fully operational. All [redacted] constraints satisfied. |
| **AMBER** | Degraded. One or more constraints approaching limits. Vehicles may continue with restrictions. |
| **RED** | Suspended. [redacted] violated. No autonomous operation permitted. |

Status changes are triggered by weather degradation, construction zones, incident response, or time-based activation/deactivation schedules. All status transitions are logged.

### 4. Route Safety Validation

Given a proposed route (origin to destination), the system validates whether the entire path stays within approved, active [redacted] zones. The validator:

- Flags every zone transition along the route
- Identifies gaps in [redacted] coverage (road segments outside any zone)
- Calculates safety margins (distance to zone boundaries)
- Reports [redacted] constraint mismatches (e.g., route enters a zone requiring sensors the vehicle lacks)

Routes that fail validation are rejected with a structured report explaining each failure.

### 5. Fleet Monitoring Dashboard

A simulated AV fleet operates within the zone network. The dashboard tracks:

- Vehicle positions (real-time on the map)
- Per-vehicle [redacted] compliance status
- Proximity to zone boundaries (with configurable warning thresholds)
- Handoff triggers: conditions under which a vehicle must transition from autonomous to manual control
- Fleet-level statistics: vehicles in zone, vehicles approaching boundaries, active handoff events

### 6. Regulatory Compliance Layer

Zone configurations are mapped to regulatory requirements:

- UK Automated Vehicles Act framework
- EU AI Act risk classification for high-risk AI systems
- Local authority approval boundaries

The system can export zone specifications in structured formats suitable for regulatory submission and audit.

---

## Visual Design

The map renderer uses a dark-theme, high-contrast aesthetic. Design principles:

- **Dark background** with light road networks and muted building footprints. The map recedes; operational data comes forward.
- **Zone overlays** rendered as semi-transparent colored polygons. GREEN, AMBER, RED status is immediately readable at a glance.
- **Zone boundaries** drawn as clean vector outlines with optional dashed patterns for pending or draft zones.
- **Vehicle icons** are simple geometric markers (oriented triangles or chevrons) with color-coded compliance halos.
- **Route lines** rendered as directional paths with safety margin buffers visualized as shaded corridors.
- **Information density is controlled by zoom level.** Zoomed out: zone status overview. Zoomed in: individual vehicles, road-level [redacted] attributes, boundary warnings.

The visual language is deliberately utilitarian -- closer to an air traffic control display or military tactical map than a consumer mapping product.

---

## Planned Tech Stack

| Layer | Technology |
|-------|------------|
| 2D Rendering | `pygame-ce` |
| Geospatial Data | OpenStreetMap, Overture Maps Foundation |
| Data Formats | GeoJSON, GeoParquet |
| Geospatial Queries | DuckDB (with spatial extension) |
| Geometry Operations | Shapely |
| Language | Python |
| Dashboard Backend (optional) | FastAPI |

The stack is intentionally lightweight. No browser-based map frameworks. The renderer is a native 2D engine for full control over the visual output and update loop.

---

## Project Roadmap

### Phase 1: Map Foundation

- Ingest and parse London map data (road network, building footprints) from Overture Maps / OSM
- Implement the top-down 2D renderer with pan, zoom, and layer control
- Establish the coordinate system and projection pipeline (WGS84 to screen space)

### Phase 2: Zone Engine

- Define the [redacted] zone data model (polygon geometry, attribute schema, versioning)
- Implement zone creation, editing, and persistence
- Build the dynamic status engine (condition evaluation, status transitions, logging)
- Implement route safety validation

### Phase 3: Fleet Simulation

- Simulate vehicle movement along road networks within zones
- Implement [redacted] compliance checking per vehicle per frame
- Build zone boundary proximity detection and handoff trigger logic

### Phase 4: Dashboard and Compliance

- Fleet monitoring overlay (vehicle tracking, compliance indicators, statistics)
- Regulatory compliance mapping and zone spec export
- Optional FastAPI backend for serving dashboard data

---

## References

- **BSI PAS 1883:2020** -- [redacted] taxonomy for automated driving systems
- **UK Automated Vehicles Act 2024** -- Legislative framework for self-driving vehicle authorization in the UK
- **EU AI Act (Regulation 2024/1689)** -- Risk-based classification framework; autonomous driving classified as high-risk AI
- **SAE J3016** -- Taxonomy and definitions for terms related to driving automation systems
- **ISO 34503** -- Taxonomy for [redacted] for automated driving systems
- **Overture Maps Foundation** -- Open map data schema and datasets (buildings, transportation, places)

---

## License

MIT

---

## Author

[BRKMYR](https://github.com/BRKMYR)
