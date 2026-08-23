"""Generate synthetic demo scenarios for development without WOMD data.

Creates realistic-looking multi-agent urban driving scenarios with
intersections, lane structures, and diverse agent behaviors. Scenarios
that rely on exact trigger timesteps for tests (``hard_brake``,
``stalled_ego``) are noise-free and constructed analytically.
"""

from __future__ import annotations

import numpy as np

from src.data.scenario import (
    AgentTrajectory,
    AgentType,
    Crosswalk,
    LaneLine,
    RoadEdge,
    RoadGraph,
    Scenario,
    SignalState,
    TrafficSignal,
)


def _make_lane(
    start: tuple[float, float],
    end: tuple[float, float],
    n_points: int = 20,
    lane_type: str = "center",
    lane_id: int = 0,
) -> LaneLine:
    points = np.linspace(start, end, n_points, dtype=np.float32)
    return LaneLine(points=points, lane_type=lane_type, lane_id=lane_id)


def _make_curved_trajectory(
    start_xy: tuple[float, float],
    start_heading: float,
    speed: float,
    num_timesteps: int,
    dt: float,
    turn_rate: float = 0.0,
    accel: float = 0.0,
    noise_scale: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate a smooth trajectory with optional turning and acceleration."""
    if rng is None:
        rng = np.random.default_rng()

    x = np.zeros(num_timesteps, dtype=np.float32)
    y = np.zeros(num_timesteps, dtype=np.float32)
    heading = np.zeros(num_timesteps, dtype=np.float32)
    vx = np.zeros(num_timesteps, dtype=np.float32)
    vy = np.zeros(num_timesteps, dtype=np.float32)

    cx, cy = start_xy
    h = start_heading
    s = speed

    for t in range(num_timesteps):
        x[t] = cx + rng.normal(0, noise_scale)
        y[t] = cy + rng.normal(0, noise_scale)
        heading[t] = h
        vx[t] = s * np.cos(h)
        vy[t] = s * np.sin(h)

        h += turn_rate * dt
        s = max(0.0, s + accel * dt)
        cx += s * np.cos(h) * dt
        cy += s * np.sin(h) * dt

    return x, y, heading, vx, vy


def _build_intersection_road_graph() -> RoadGraph:
    """Build a 4-way intersection road graph with direction-encoded lanes.

    Lane-center point ordering encodes travel direction (see LaneLine
    docstring). Eastbound lanes at y in {-3.5, -1.75} run west -> east;
    westbound lanes at y in {1.75, 3.5} run east -> west. Similarly for
    the north-south road.
    """
    lanes = []
    lane_id = 0

    # East-west road:
    # y = -3.5 and y = -1.75 are eastbound  -> ordered west -> east.
    for y_off in [-3.5, -1.75]:
        lanes.append(
            _make_lane((-80, y_off), (80, y_off), lane_type="center", lane_id=lane_id)
        )
        lane_id += 1
    # y = +1.75 and y = +3.5 are westbound -> ordered east -> west.
    for y_off in [1.75, 3.5]:
        lanes.append(
            _make_lane((80, y_off), (-80, y_off), lane_type="center", lane_id=lane_id)
        )
        lane_id += 1

    # North-south road:
    # x = +1.75, +3.5 are northbound -> south -> north.
    for x_off in [1.75, 3.5]:
        lanes.append(
            _make_lane((x_off, -80), (x_off, 80), lane_type="center", lane_id=lane_id)
        )
        lane_id += 1
    # x = -3.5, -1.75 are southbound -> north -> south.
    for x_off in [-3.5, -1.75]:
        lanes.append(
            _make_lane((x_off, 80), (x_off, -80), lane_type="center", lane_id=lane_id)
        )
        lane_id += 1

    # Lane boundaries for east-west road
    for y_off in [-5.25, 0.0, 5.25]:
        lanes.append(
            _make_lane((-80, y_off), (80, y_off), lane_type="left_boundary", lane_id=lane_id)
        )
        lane_id += 1

    # Lane boundaries for north-south road
    for x_off in [-5.25, 0.0, 5.25]:
        lanes.append(
            _make_lane((x_off, -80), (x_off, 80), lane_type="left_boundary", lane_id=lane_id)
        )
        lane_id += 1

    # Road edges
    road_edges = [
        RoadEdge(
            points=np.array([[-80, -5.25], [80, -5.25]], dtype=np.float32),
            edge_type="boundary",
        ),
        RoadEdge(
            points=np.array([[-80, 5.25], [80, 5.25]], dtype=np.float32),
            edge_type="boundary",
        ),
        RoadEdge(
            points=np.array([[-5.25, -80], [-5.25, 80]], dtype=np.float32),
            edge_type="boundary",
        ),
        RoadEdge(
            points=np.array([[5.25, -80], [5.25, 80]], dtype=np.float32),
            edge_type="boundary",
        ),
    ]

    # Crosswalks at the intersection
    crosswalks = [
        Crosswalk(
            polygon=np.array(
                [[-6, 6], [-6, 8], [6, 8], [6, 6]], dtype=np.float32
            )
        ),
        Crosswalk(
            polygon=np.array(
                [[-6, -8], [-6, -6], [6, -6], [6, -8]], dtype=np.float32
            )
        ),
        Crosswalk(
            polygon=np.array(
                [[6, -6], [8, -6], [8, 6], [6, 6]], dtype=np.float32
            )
        ),
        Crosswalk(
            polygon=np.array(
                [[-8, -6], [-6, -6], [-6, 6], [-8, 6]], dtype=np.float32
            )
        ),
    ]

    # Stop signs
    stop_signs = np.array(
        [[-6, -6], [-6, 6], [6, -6], [6, 6]], dtype=np.float32
    )

    return RoadGraph(
        lanes=lanes,
        road_edges=road_edges,
        crosswalks=crosswalks,
        stop_signs=stop_signs,
    )


def _build_two_lane_road_graph(
    with_crosswalk: bool = False,
) -> RoadGraph:
    """Build a straight two-lane road: one eastbound at y = -1.75,
    one westbound at y = +1.75. Used by hard_brake and stalled_ego.
    """
    lanes = []
    lane_id = 0

    # Eastbound center (west -> east)
    lanes.append(_make_lane((-60, -1.75), (60, -1.75), lane_id=lane_id))
    lane_id += 1
    # Westbound center (east -> west)
    lanes.append(_make_lane((60, 1.75), (-60, 1.75), lane_id=lane_id))
    lane_id += 1

    # Boundaries
    for y_off in [-3.5, 0.0, 3.5]:
        lanes.append(
            _make_lane((-60, y_off), (60, y_off), lane_type="left_boundary", lane_id=lane_id)
        )
        lane_id += 1

    road_edges = [
        RoadEdge(points=np.array([[-60, -3.5], [60, -3.5]], dtype=np.float32)),
        RoadEdge(points=np.array([[-60, 3.5], [60, 3.5]], dtype=np.float32)),
    ]

    crosswalks: list[Crosswalk] = []
    if with_crosswalk:
        crosswalks.append(
            Crosswalk(
                polygon=np.array(
                    [[8, -5], [8, 5], [11, 5], [11, -5]], dtype=np.float32
                )
            )
        )

    return RoadGraph(
        lanes=lanes,
        road_edges=road_edges,
        crosswalks=crosswalks,
    )


_BUNDLED_SCENARIOS = (
    "intersection_conflict",
    "highway_merge",
    "pedestrian_crossing",
    "hard_brake",
    "stalled_ego",
)


def load_demo_scenario(
    scenario_name: str = "intersection_conflict",
    seed: int = 42,
) -> Scenario:
    """Load a pre-built demo scenario.

    Available scenarios:
        - "intersection_conflict": Multi-agent intersection with near-miss.
        - "highway_merge":         Highway merge with aggressive lane change.
        - "pedestrian_crossing":   Crosswalk with two pedestrians.
        - "hard_brake":            Lead vehicle brakes at -6 m/s^2 at t=31 (noise-free).
        - "stalled_ego":           Ego rolls to a stop; stalled trigger fires at t=68 (noise-free).
    """
    rng = np.random.default_rng(seed)
    num_timesteps = 91
    dt = 0.1

    if scenario_name == "highway_merge":
        return _build_highway_merge(rng, num_timesteps, dt)
    elif scenario_name == "pedestrian_crossing":
        return _build_pedestrian_crossing(rng, num_timesteps, dt)
    elif scenario_name == "hard_brake":
        return _build_hard_brake(num_timesteps, dt)
    elif scenario_name == "stalled_ego":
        return _build_stalled_ego(num_timesteps, dt)
    elif scenario_name == "intersection_conflict":
        return _build_intersection_conflict(rng, num_timesteps, dt)
    else:
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. "
            f"Available: {', '.join(_BUNDLED_SCENARIOS)}"
        )


def _build_intersection_conflict(
    rng: np.random.Generator, num_timesteps: int, dt: float
) -> Scenario:
    """Intersection scenario with near-miss conflict."""
    road_graph = _build_intersection_road_graph()
    agents: list[AgentTrajectory] = []

    # Ego vehicle: approaching intersection from west, going straight
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-60, -1.75), start_heading=0.0, speed=12.0,
        num_timesteps=num_timesteps, dt=dt, accel=-1.5, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Cross-traffic vehicle: approaching from south, turning left
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(1.75, -55), start_heading=np.pi / 2, speed=10.0,
        num_timesteps=num_timesteps, dt=dt, turn_rate=-0.02, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=1, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.8, width=2.1, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Oncoming vehicle: approaching from east
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(50, 1.75), start_heading=np.pi, speed=11.0,
        num_timesteps=num_timesteps, dt=dt, accel=-0.5, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=2, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=5.0, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Pedestrian crossing at the intersection
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-4, 7), start_heading=-np.pi / 2, speed=1.4,
        num_timesteps=num_timesteps, dt=dt, noise_scale=0.02, rng=rng,
    )
    valid = np.ones(num_timesteps, dtype=bool)
    valid[:20] = False  # appears at t=20
    agents.append(AgentTrajectory(
        agent_id=3, agent_type=AgentType.PEDESTRIAN,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=0.5, width=0.5, valid=valid,
    ))

    # Cyclist on the road
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-40, -3.5), start_heading=0.0, speed=5.0,
        num_timesteps=num_timesteps, dt=dt, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=4, agent_type=AgentType.CYCLIST,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=1.8, width=0.7, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Parked vehicle on the side
    x = np.full(num_timesteps, 25.0, dtype=np.float32)
    y = np.full(num_timesteps, -4.5, dtype=np.float32)
    agents.append(AgentTrajectory(
        agent_id=5, agent_type=AgentType.VEHICLE,
        x=x, y=y,
        heading=np.zeros(num_timesteps, dtype=np.float32),
        vx=np.zeros(num_timesteps, dtype=np.float32),
        vy=np.zeros(num_timesteps, dtype=np.float32),
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Traffic signals
    signals = [
        TrafficSignal(
            position=np.array([-6, 6], dtype=np.float32),
            states=_make_signal_cycle(num_timesteps, offset=0),
            lane_id=0,
        ),
        TrafficSignal(
            position=np.array([6, -6], dtype=np.float32),
            states=_make_signal_cycle(num_timesteps, offset=0),
            lane_id=1,
        ),
        TrafficSignal(
            position=np.array([6, 6], dtype=np.float32),
            states=_make_signal_cycle(num_timesteps, offset=30),
            lane_id=4,
        ),
        TrafficSignal(
            position=np.array([-6, -6], dtype=np.float32),
            states=_make_signal_cycle(num_timesteps, offset=30),
            lane_id=5,
        ),
    ]

    return Scenario(
        scenario_id="demo_intersection_conflict",
        num_timesteps=num_timesteps,
        timestep_duration=dt,
        agents=agents,
        road_graph=road_graph,
        traffic_signals=signals,
        ego_agent_id=0,
    )


def _build_highway_merge(
    rng: np.random.Generator, num_timesteps: int, dt: float
) -> Scenario:
    """Highway merge scenario with aggressive lane change (one-way traffic)."""
    lanes = []
    lane_id = 0

    # Three highway lanes (all one-way eastbound; ordering west -> east)
    for y_off in [-3.5, 0.0, 3.5]:
        lanes.append(
            _make_lane((-100, y_off), (100, y_off), n_points=40, lane_id=lane_id)
        )
        lane_id += 1

    # Lane boundaries
    for y_off in [-5.25, -1.75, 1.75, 5.25]:
        lanes.append(
            _make_lane((-100, y_off), (100, y_off), lane_type="left_boundary", lane_id=lane_id)
        )
        lane_id += 1

    # Merge ramp
    ramp_points = np.array(
        [[-100, 15], [-80, 12], [-60, 9], [-40, 7], [-20, 5.25]],
        dtype=np.float32,
    )
    lanes.append(LaneLine(points=ramp_points, lane_type="center", lane_id=lane_id))

    road_edges = [
        RoadEdge(points=np.array([[-100, -5.25], [100, -5.25]], dtype=np.float32)),
        RoadEdge(points=np.array([[-100, 5.25], [100, 5.25]], dtype=np.float32)),
    ]

    road_graph = RoadGraph(lanes=lanes, road_edges=road_edges)
    agents: list[AgentTrajectory] = []

    # Ego in middle lane
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-80, 0.0), start_heading=0.0, speed=25.0,
        num_timesteps=num_timesteps, dt=dt, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Merging vehicle from ramp — cuts into ego's lane
    merge_x, merge_y, merge_h, merge_vx, merge_vy = _make_curved_trajectory(
        start_xy=(-70, 10), start_heading=-0.15, speed=22.0,
        num_timesteps=num_timesteps, dt=dt, turn_rate=-0.005, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=1, agent_type=AgentType.VEHICLE,
        x=merge_x, y=merge_y, heading=merge_h, vx=merge_vx, vy=merge_vy,
        length=4.8, width=2.1, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Slow truck in right lane
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-50, 3.5), start_heading=0.0, speed=18.0,
        num_timesteps=num_timesteps, dt=dt, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=2, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=8.0, width=2.5, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Fast car in left lane
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-90, -3.5), start_heading=0.0, speed=30.0,
        num_timesteps=num_timesteps, dt=dt, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=3, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.2, width=1.9, valid=np.ones(num_timesteps, dtype=bool),
    ))

    return Scenario(
        scenario_id="demo_highway_merge",
        num_timesteps=num_timesteps,
        timestep_duration=dt,
        agents=agents,
        road_graph=road_graph,
        ego_agent_id=0,
    )


def _build_pedestrian_crossing(
    rng: np.random.Generator, num_timesteps: int, dt: float
) -> Scenario:
    """Pedestrian crossing with approaching vehicles."""
    lanes = []
    lane_id = 0

    # Two-lane road with direction-encoded lanes.
    # Eastbound at y = -1.75 (west -> east), westbound at y = +1.75 (east -> west).
    lanes.append(_make_lane((-60, -1.75), (60, -1.75), lane_id=lane_id))
    lane_id += 1
    lanes.append(_make_lane((60, 1.75), (-60, 1.75), lane_id=lane_id))
    lane_id += 1

    # Boundaries
    for y_off in [-3.5, 0.0, 3.5]:
        lanes.append(
            _make_lane((-60, y_off), (60, y_off), lane_type="left_boundary", lane_id=lane_id)
        )
        lane_id += 1

    road_edges = [
        RoadEdge(points=np.array([[-60, -3.5], [60, -3.5]], dtype=np.float32)),
        RoadEdge(points=np.array([[-60, 3.5], [60, 3.5]], dtype=np.float32)),
    ]

    crosswalks = [
        Crosswalk(
            polygon=np.array(
                [[8, -5], [8, 5], [11, 5], [11, -5]], dtype=np.float32
            )
        ),
    ]

    road_graph = RoadGraph(
        lanes=lanes, road_edges=road_edges, crosswalks=crosswalks,
    )
    agents: list[AgentTrajectory] = []

    # Ego approaching the crosswalk
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(-40, -1.75), start_heading=0.0, speed=10.0,
        num_timesteps=num_timesteps, dt=dt, accel=-1.0, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Pedestrian 1: crossing south to north, paced to be at ego lane when ego arrives
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(9.5, -5), start_heading=np.pi / 2, speed=0.4,
        num_timesteps=num_timesteps, dt=dt, noise_scale=0.02, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=1, agent_type=AgentType.PEDESTRIAN,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=0.5, width=0.5, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Pedestrian 2: crossing north to south, starts later
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(10.0, 4), start_heading=-np.pi / 2, speed=1.5,
        num_timesteps=num_timesteps, dt=dt, noise_scale=0.02, rng=rng,
    )
    valid = np.ones(num_timesteps, dtype=bool)
    valid[:15] = False
    agents.append(AgentTrajectory(
        agent_id=2, agent_type=AgentType.PEDESTRIAN,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=0.5, width=0.5, valid=valid,
    ))

    # Oncoming vehicle
    x, y, h, vx, vy = _make_curved_trajectory(
        start_xy=(50, 1.75), start_heading=np.pi, speed=8.0,
        num_timesteps=num_timesteps, dt=dt, accel=-0.5, rng=rng,
    )
    agents.append(AgentTrajectory(
        agent_id=3, agent_type=AgentType.VEHICLE,
        x=x, y=y, heading=h, vx=vx, vy=vy,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    return Scenario(
        scenario_id="demo_pedestrian_crossing",
        num_timesteps=num_timesteps,
        timestep_duration=dt,
        agents=agents,
        road_graph=road_graph,
        ego_agent_id=0,
    )


def _build_hard_brake(num_timesteps: int, dt: float) -> Scenario:
    """Noise-free scenario: lead vehicle brakes hard at t=31.

    Lead vehicle (agent 1) speed profile (m/s):
        v[t] = 15.0                                for t <= 30
        v[t] = max(0.0, 15.0 - 6.0 * (t - 30) * dt) for t > 30

    Acceleration at t=31: (14.4 - 15.0) / 0.1 = -6.0 m/s^2 => hard_brake RED.
    Ego (agent 0) cruises at 15 m/s and closes on the stopping lead, driving
    its TTC below the RED threshold in t in [40, 75].
    """
    road_graph = _build_two_lane_road_graph(with_crosswalk=False)
    agents: list[AgentTrajectory] = []

    # Lead vehicle (agent 1)
    v_lead = np.empty(num_timesteps, dtype=np.float32)
    for t in range(num_timesteps):
        if t <= 30:
            v_lead[t] = 15.0
        else:
            v_lead[t] = max(0.0, 15.0 - 6.0 * (t - 30) * dt)

    x_lead = np.empty(num_timesteps, dtype=np.float32)
    x_lead[0] = 10.0
    for t in range(1, num_timesteps):
        x_lead[t] = x_lead[t - 1] + v_lead[t] * dt
    y_lead = np.full(num_timesteps, -1.75, dtype=np.float32)
    h_lead = np.zeros(num_timesteps, dtype=np.float32)
    vx_lead = v_lead.copy()
    vy_lead = np.zeros(num_timesteps, dtype=np.float32)

    # Ego (agent 0): constant 15 m/s eastbound, starts behind lead
    v_ego = np.full(num_timesteps, 15.0, dtype=np.float32)
    x_ego = np.empty(num_timesteps, dtype=np.float32)
    x_ego[0] = -25.0
    for t in range(1, num_timesteps):
        x_ego[t] = x_ego[t - 1] + v_ego[t] * dt
    y_ego = np.full(num_timesteps, -1.75, dtype=np.float32)
    h_ego = np.zeros(num_timesteps, dtype=np.float32)

    agents.append(AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=x_ego, y=y_ego, heading=h_ego,
        vx=v_ego, vy=np.zeros(num_timesteps, dtype=np.float32),
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    agents.append(AgentTrajectory(
        agent_id=1, agent_type=AgentType.VEHICLE,
        x=x_lead, y=y_lead, heading=h_lead, vx=vx_lead, vy=vy_lead,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Background oncoming vehicle in westbound lane for visual life.
    v_onc = 10.0
    x_onc = np.empty(num_timesteps, dtype=np.float32)
    x_onc[0] = 40.0
    for t in range(1, num_timesteps):
        x_onc[t] = x_onc[t - 1] - v_onc * dt
    y_onc = np.full(num_timesteps, 1.75, dtype=np.float32)
    h_onc = np.full(num_timesteps, np.pi, dtype=np.float32)
    vx_onc = np.full(num_timesteps, -v_onc, dtype=np.float32)
    vy_onc = np.zeros(num_timesteps, dtype=np.float32)

    agents.append(AgentTrajectory(
        agent_id=2, agent_type=AgentType.VEHICLE,
        x=x_onc, y=y_onc, heading=h_onc, vx=vx_onc, vy=vy_onc,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    return Scenario(
        scenario_id="demo_hard_brake",
        num_timesteps=num_timesteps,
        timestep_duration=dt,
        agents=agents,
        road_graph=road_graph,
        ego_agent_id=0,
    )


def _build_stalled_ego(num_timesteps: int, dt: float) -> Scenario:
    """Noise-free scenario: ego rolls to a stop; stalled trigger fires at t=68.

    Ego (agent 0) speed profile:
        v[t] = 8.0                                    for t < 10
        v[t] = max(0.0, 8.0 - 2.0 * (t - 10) * dt)    for t >= 10

    First t with v < 0.3 is t=49 (v = 0.2). With stall_dwell_steps = 20 the
    dwell counter reaches 20 at t=68 (49 + 19 = 68), where the stalled RED
    trigger fires.
    """
    road_graph = _build_two_lane_road_graph(with_crosswalk=False)
    agents: list[AgentTrajectory] = []

    v_ego = np.empty(num_timesteps, dtype=np.float32)
    for t in range(num_timesteps):
        if t < 10:
            v_ego[t] = 8.0
        else:
            v_ego[t] = max(0.0, 8.0 - 2.0 * (t - 10) * dt)

    x_ego = np.empty(num_timesteps, dtype=np.float32)
    x_ego[0] = -20.0
    for t in range(1, num_timesteps):
        x_ego[t] = x_ego[t - 1] + v_ego[t] * dt
    y_ego = np.full(num_timesteps, -1.75, dtype=np.float32)
    h_ego = np.zeros(num_timesteps, dtype=np.float32)
    vy_ego = np.zeros(num_timesteps, dtype=np.float32)

    agents.append(AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=x_ego, y=y_ego, heading=h_ego, vx=v_ego, vy=vy_ego,
        length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
    ))

    # Two other vehicles flow past in the westbound (adjacent) lane.
    for idx, (start_x, speed) in enumerate([(40.0, 8.0), (60.0, 10.0)], start=1):
        v = np.full(num_timesteps, speed, dtype=np.float32)
        x = np.empty(num_timesteps, dtype=np.float32)
        x[0] = start_x
        for t in range(1, num_timesteps):
            x[t] = x[t - 1] - speed * dt
        y = np.full(num_timesteps, 1.75, dtype=np.float32)
        h = np.full(num_timesteps, np.pi, dtype=np.float32)
        vx = np.full(num_timesteps, -speed, dtype=np.float32)
        vy = np.zeros(num_timesteps, dtype=np.float32)
        agents.append(AgentTrajectory(
            agent_id=idx, agent_type=AgentType.VEHICLE,
            x=x, y=y, heading=h, vx=vx, vy=vy,
            length=4.5, width=2.0, valid=np.ones(num_timesteps, dtype=bool),
        ))

    return Scenario(
        scenario_id="demo_stalled_ego",
        num_timesteps=num_timesteps,
        timestep_duration=dt,
        agents=agents,
        road_graph=road_graph,
        ego_agent_id=0,
    )


def _make_signal_cycle(
    num_timesteps: int, offset: int = 0
) -> np.ndarray:
    """Generate a traffic signal state cycle."""
    states = np.full(num_timesteps, int(SignalState.GREEN), dtype=np.int32)
    for t in range(num_timesteps):
        cycle_pos = (t + offset) % 91
        if cycle_pos < 40:
            states[t] = int(SignalState.GREEN)
        elif cycle_pos < 50:
            states[t] = int(SignalState.YELLOW)
        else:
            states[t] = int(SignalState.RED)
    return states
