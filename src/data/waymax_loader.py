"""Load scenarios from Waymo Open Motion Dataset via Waymax.

Requires optional dependencies: waymax, jax, tensorflow.
Install with: pip install waymax-safety-monitor[waymax]
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from src.data.scenario import (
    AgentTrajectory,
    AgentType,
    Crosswalk,
    LaneLine,
    RoadEdge,
    RoadGraph,
    Scenario,
    TrafficSignal,
)

if TYPE_CHECKING:
    pass

_WOMD_AGENT_TYPES = {1: AgentType.VEHICLE, 2: AgentType.PEDESTRIAN, 3: AgentType.CYCLIST}


def _check_waymax_available() -> None:
    try:
        import waymax  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Waymax is required for loading WOMD data. "
            "Install with: pip install waymax-safety-monitor[waymax]"
        ) from e


def load_womd_scenario(
    data_path: str | Path,
    scenario_index: int = 0,
    max_objects: int = 32,
) -> Scenario:
    """Load a scenario from a WOMD TFRecord file via Waymax.

    Args:
        data_path: Path to a WOMD TFRecord file.
        scenario_index: Index of the scenario within the file.
        max_objects: Maximum number of objects to load.

    Returns:
        A Scenario with all agents, road graph, and traffic signals.
    """
    _check_waymax_available()

    from waymax import config as waymax_config
    from waymax import dataloader

    data_config = waymax_config.DatasetConfig(
        path=str(data_path),
        max_num_objects=max_objects,
        data_format=waymax_config.DataFormat.TFRECORD,
    )

    dataset = dataloader.simulator_state_generator(config=data_config)

    # Advance to the requested scenario
    state = None
    for i, s in enumerate(dataset):
        if i == scenario_index:
            state = s
            break

    if state is None:
        raise ValueError(
            f"Scenario index {scenario_index} not found in {data_path}"
        )

    return _convert_waymax_state(state)


def _convert_waymax_state(state: object) -> Scenario:
    """Convert a Waymax SimulatorState to our Scenario format.

    Written against the waymax 0.2 SimulatorState API. If the field names
    or shapes have drifted in a newer waymax release the AttributeError is
    re-raised with an actionable hint.
    """
    try:
        import jax.numpy as jnp

        log_trajectory = state.log_trajectory

        # Use log trajectory for ground-truth data
        traj = log_trajectory

        num_objects = int(traj.x.shape[0])
        num_timesteps = int(traj.x.shape[1])

        agents = []
        for obj_idx in range(num_objects):
            valid = np.array(traj.valid[obj_idx], dtype=bool)
            if not valid.any():
                continue

            obj_type_val = int(traj.object_type[obj_idx])
            agent_type = _WOMD_AGENT_TYPES.get(obj_type_val, AgentType.VEHICLE)

            agents.append(AgentTrajectory(
                agent_id=obj_idx,
                agent_type=agent_type,
                x=np.array(traj.x[obj_idx], dtype=np.float32),
                y=np.array(traj.y[obj_idx], dtype=np.float32),
                heading=np.array(traj.yaw[obj_idx], dtype=np.float32),
                vx=np.array(traj.vel_x[obj_idx], dtype=np.float32),
                vy=np.array(traj.vel_y[obj_idx], dtype=np.float32),
                length=float(jnp.mean(traj.length[obj_idx][valid])),
                width=float(jnp.mean(traj.width[obj_idx][valid])),
                valid=valid,
            ))

        road_graph = _extract_road_graph(state)

        # Find ego (first valid vehicle or object index 0)
        ego_id = 0
        if agents:
            ego_id = agents[0].agent_id

        return Scenario(
            scenario_id=f"womd_{id(state)}",
            num_timesteps=num_timesteps,
            timestep_duration=0.1,
            agents=agents,
            road_graph=road_graph,
            ego_agent_id=ego_id,
        )
    except AttributeError as e:
        raise AttributeError(
            f"Waymax SimulatorState missing expected attribute: {e}. "
            "This adapter is written against the waymax 0.2 API "
            "(SimulatorState.log_trajectory, .roadgraph_points); verify "
            "field names if your waymax version has drifted."
        ) from e


def _extract_road_graph(state: object) -> RoadGraph:
    """Extract road graph from Waymax state."""
    import jax.numpy as jnp

    roadgraph = state.roadgraph_points

    lanes = []
    road_edges = []
    crosswalks = []

    # Waymax road graph types:
    # 1-3: lane centers, 6-7: road edges, 15-16: crosswalks
    types = np.array(roadgraph.types, dtype=np.int32).flatten()
    xy = np.stack([
        np.array(roadgraph.x, dtype=np.float32).flatten(),
        np.array(roadgraph.y, dtype=np.float32).flatten(),
    ], axis=-1)
    valid = np.array(roadgraph.valid, dtype=bool).flatten()

    # Group points by type
    lane_center_mask = np.isin(types, [1, 2, 3]) & valid
    road_edge_mask = np.isin(types, [6, 7]) & valid
    crosswalk_mask = np.isin(types, [15, 16]) & valid

    if lane_center_mask.any():
        lane_points = xy[lane_center_mask]
        # Segment into polylines by detecting large gaps
        for polyline in _segment_polylines(lane_points, max_gap=5.0):
            if len(polyline) >= 2:
                lanes.append(LaneLine(
                    points=polyline,
                    lane_type="center",
                    lane_id=len(lanes),
                ))

    if road_edge_mask.any():
        edge_points = xy[road_edge_mask]
        for polyline in _segment_polylines(edge_points, max_gap=5.0):
            if len(polyline) >= 2:
                road_edges.append(RoadEdge(points=polyline))

    if crosswalk_mask.any():
        cw_points = xy[crosswalk_mask]
        for polyline in _segment_polylines(cw_points, max_gap=3.0):
            if len(polyline) >= 3:
                crosswalks.append(Crosswalk(polygon=polyline))

    return RoadGraph(
        lanes=lanes,
        road_edges=road_edges,
        crosswalks=crosswalks,
    )


def _segment_polylines(
    points: np.ndarray, max_gap: float = 5.0
) -> list[np.ndarray]:
    """Segment a cloud of points into polylines by detecting gaps."""
    if len(points) == 0:
        return []

    segments = []
    current = [points[0]]

    for i in range(1, len(points)):
        dist = np.linalg.norm(points[i] - points[i - 1])
        if dist > max_gap:
            if len(current) >= 2:
                segments.append(np.array(current, dtype=np.float32))
            current = [points[i]]
        else:
            current.append(points[i])

    if len(current) >= 2:
        segments.append(np.array(current, dtype=np.float32))

    return segments
