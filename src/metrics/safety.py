"""Safety metrics for driving scenarios.

Computes per-agent, per-timestep safety metrics including overlap detection,
off-road detection, wrong-way detection, time-to-collision, lane compliance,
longitudinal acceleration, and VRU (vulnerable road user) proximity.

Applicability rules:
- overlap and ttc apply to all agent types.
- offroad, wrong_way, and lane_compliance are only meaningful for
  road-following agents (vehicles and cyclists). Pedestrians are skipped
  and return neutral values (0.0 for offroad/wrong_way, 1.0 for compliance).
- accel and vru_distance are helpers for the trigger engine; accel is
  computed for every valid agent, vru_distance is computed for vehicles.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from src.data.scenario import AgentState, AgentType, Scenario


# Radius (m) used to gather lane-center segments for direction-aware matching.
_LANE_MATCH_RADIUS = 6.0


def compute_overlap(scenario: Scenario, t: int) -> dict[int, float]:
    """Check bounding box overlap between all agent pairs at timestep t.

    Returns a dict mapping agent_id -> maximum overlap ratio (0.0 = none, 1.0 = full).
    """
    active = scenario.agents_at(t)
    overlaps: dict[int, float] = {}

    for i, (agent_i, state_i) in enumerate(active):
        max_overlap = 0.0
        corners_i = _get_corners(state_i)

        for j, (agent_j, state_j) in enumerate(active):
            if i == j:
                continue
            corners_j = _get_corners(state_j)
            overlap = _bbox_overlap(corners_i, corners_j)
            max_overlap = max(max_overlap, overlap)

        overlaps[agent_i.agent_id] = max_overlap

    return overlaps


def compute_offroad(
    scenario: Scenario, t: int
) -> dict[int, float]:
    """Check if agents are off the drivable surface at timestep t.

    Returns dict mapping agent_id -> off-road score (0.0 = on road, 1.0 = off road).
    Uses distance to nearest lane center as a proxy. Pedestrians are excluded
    (returned as 0.0) because they are not constrained to the drivable surface.
    """
    active = scenario.agents_at(t)
    road_graph = scenario.road_graph
    offroad: dict[int, float] = {}

    # Collect all lane center points as the "drivable area"
    lane_points = []
    for lane in road_graph.lanes:
        if lane.lane_type == "center":
            lane_points.append(lane.points)

    if not lane_points:
        return {agent.agent_id: 0.0 for agent, _ in active}

    all_lane_points = np.concatenate(lane_points, axis=0)

    for agent, state in active:
        if agent.agent_type == AgentType.PEDESTRIAN:
            offroad[agent.agent_id] = 0.0
            continue

        pos = np.array([state.x, state.y], dtype=np.float32)
        dists = np.linalg.norm(all_lane_points - pos, axis=1)
        min_dist = float(np.min(dists))

        # Consider off-road if more than lane_width + margin from any lane center
        lane_half_width = 2.0  # typical lane half-width in meters
        margin = 1.0
        threshold = lane_half_width + margin

        if min_dist > threshold:
            offroad[agent.agent_id] = min(1.0, (min_dist - threshold) / threshold)
        else:
            offroad[agent.agent_id] = 0.0

    return offroad


def compute_wrong_way(
    scenario: Scenario, t: int
) -> dict[int, float]:
    """Check if agents are heading in the wrong direction relative to lane.

    Returns dict mapping agent_id -> wrong-way score (0.0 = aligned, 1.0 = opposite).

    Uses direction-aware lane matching: for each agent, the nearby lane-center
    segment (within ``_LANE_MATCH_RADIUS`` meters of the agent position) whose
    direction best aligns with the agent's heading is selected, and the score
    is the absolute angular difference between the agent heading and that
    segment's direction, normalized by pi.

    Pedestrians are excluded (returned as 0.0) since lane direction does not
    apply to them.
    """
    active = scenario.agents_at(t)
    road_graph = scenario.road_graph
    wrong_way: dict[int, float] = {}

    # Compute lane directions from center lane polylines
    lane_mids: list[NDArray[np.float32]] = []
    lane_dirs: list[float] = []
    for lane in road_graph.lanes:
        if lane.lane_type == "center" and len(lane.points) >= 2:
            for k in range(len(lane.points) - 1):
                p1 = lane.points[k]
                p2 = lane.points[k + 1]
                mid = (p1 + p2) / 2
                direction = float(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
                lane_mids.append(mid)
                lane_dirs.append(direction)

    if not lane_mids:
        return {agent.agent_id: 0.0 for agent, _ in active}

    seg_mids = np.array(lane_mids, dtype=np.float32)
    seg_dirs = np.array(lane_dirs, dtype=np.float32)

    for agent, state in active:
        if agent.agent_type == AgentType.PEDESTRIAN:
            wrong_way[agent.agent_id] = 0.0
            continue

        pos = np.array([state.x, state.y], dtype=np.float32)
        dists = np.linalg.norm(seg_mids - pos, axis=1)

        near_mask = dists <= _LANE_MATCH_RADIUS

        if not near_mask.any():
            # No nearby lane at all: use nearest single segment (fallback).
            nearest_idx = int(np.argmin(dists))
            if dists[nearest_idx] > 5.0:
                # Genuinely off the map — treat as no info.
                wrong_way[agent.agent_id] = 0.0
                continue
            best_diff = abs(_angle_diff(state.heading, float(seg_dirs[nearest_idx])))
        else:
            near_dirs = seg_dirs[near_mask]
            # Pick the nearby segment minimizing |angle diff|.
            diffs = np.array(
                [abs(_angle_diff(state.heading, float(d))) for d in near_dirs],
                dtype=np.float32,
            )
            best_diff = float(np.min(diffs))

        wrong_way[agent.agent_id] = float(best_diff / np.pi)

    return wrong_way


def compute_ttc(scenario: Scenario, t: int) -> dict[int, float]:
    """Compute time-to-collision for all agent pairs at timestep t.

    Returns dict mapping agent_id -> minimum TTC in seconds (inf = no collision risk).
    Uses linear projection of current velocities.
    """
    active = scenario.agents_at(t)
    ttc: dict[int, float] = {}

    for i, (agent_i, state_i) in enumerate(active):
        min_ttc = float("inf")

        for j, (agent_j, state_j) in enumerate(active):
            if i == j:
                continue

            t_col = _compute_pairwise_ttc(state_i, state_j)
            min_ttc = min(min_ttc, t_col)

        ttc[agent_i.agent_id] = min_ttc

    return ttc


def compute_lane_compliance(
    scenario: Scenario, t: int
) -> dict[int, float]:
    """Compute lane compliance score for each agent at timestep t.

    Returns dict mapping agent_id -> compliance score (1.0 = perfect, 0.0 = poor).
    Combines lateral offset from the best-matched (direction-aware) lane center
    with heading alignment against that lane. Pedestrians are excluded (returned
    as 1.0) since lane compliance does not apply to them.
    """
    active = scenario.agents_at(t)
    road_graph = scenario.road_graph
    compliance: dict[int, float] = {}

    # Get lane centers
    lane_mids: list[NDArray[np.float32]] = []
    lane_dirs: list[float] = []
    for lane in road_graph.lanes:
        if lane.lane_type == "center" and len(lane.points) >= 2:
            for k in range(len(lane.points) - 1):
                mid = (lane.points[k] + lane.points[k + 1]) / 2
                direction = float(np.arctan2(
                    lane.points[k + 1][1] - lane.points[k][1],
                    lane.points[k + 1][0] - lane.points[k][0],
                ))
                lane_mids.append(mid)
                lane_dirs.append(direction)

    if not lane_mids:
        return {agent.agent_id: 1.0 for agent, _ in active}

    centers = np.array(lane_mids, dtype=np.float32)
    directions = np.array(lane_dirs, dtype=np.float32)

    for agent, state in active:
        if agent.agent_type == AgentType.PEDESTRIAN:
            compliance[agent.agent_id] = 1.0
            continue

        pos = np.array([state.x, state.y], dtype=np.float32)
        dists = np.linalg.norm(centers - pos, axis=1)

        near_mask = dists <= _LANE_MATCH_RADIUS
        if near_mask.any():
            near_idx = np.nonzero(near_mask)[0]
            # Pick the nearby segment minimizing heading diff (direction-aware).
            near_dirs = directions[near_idx]
            diffs = np.array(
                [abs(_angle_diff(state.heading, float(d))) for d in near_dirs],
                dtype=np.float32,
            )
            best_local = int(np.argmin(diffs))
            chosen_idx = int(near_idx[best_local])
        else:
            chosen_idx = int(np.argmin(dists))

        lateral_offset = float(dists[chosen_idx])
        heading_diff = abs(_angle_diff(state.heading, float(directions[chosen_idx])))

        # Lateral score: 1.0 within 0.5m, decays to 0.0 at 3.0m
        lateral_score = max(0.0, 1.0 - max(0.0, lateral_offset - 0.5) / 2.5)

        # Heading score: 1.0 within 5deg, decays to 0.0 at 45deg
        heading_score = max(0.0, 1.0 - max(0.0, heading_diff - np.radians(5)) / np.radians(40))

        compliance[agent.agent_id] = 0.6 * lateral_score + 0.4 * heading_score

    return compliance


def compute_accel(scenario: Scenario, t: int) -> dict[int, float]:
    """Compute longitudinal acceleration for each valid agent at timestep t.

    Uses ``(speed[t] - speed[t-1]) / dt`` per agent. At t == 0 the value is
    ``0.0``. If the agent was not valid at t-1 the value is also ``0.0``.

    Returns dict mapping agent_id -> acceleration in m/s^2 (negative = braking).
    """
    active = scenario.agents_at(t)
    dt = scenario.timestep_duration
    result: dict[int, float] = {}

    for agent, _state in active:
        if t <= 0:
            result[agent.agent_id] = 0.0
            continue
        if t - 1 >= agent.num_timesteps or not bool(agent.valid[t - 1]):
            result[agent.agent_id] = 0.0
            continue
        v_now = float(np.hypot(agent.vx[t], agent.vy[t]))
        v_prev = float(np.hypot(agent.vx[t - 1], agent.vy[t - 1]))
        result[agent.agent_id] = (v_now - v_prev) / dt

    return result


def compute_vru_distance(scenario: Scenario, t: int) -> dict[int, float]:
    """Compute distance from each vehicle to the nearest VRU at timestep t.

    VRUs are pedestrians and cyclists. Returns a dict keyed by *vehicle*
    agent_id -> minimum center-to-center distance in meters (``inf`` if no
    VRUs are active at this timestep). Pedestrian / cyclist agent_ids are
    intentionally not present in the result.
    """
    active = scenario.agents_at(t)

    vrus: list[tuple[float, float]] = []
    vehicles: list[tuple[int, float, float]] = []

    for agent, state in active:
        if agent.agent_type in (AgentType.PEDESTRIAN, AgentType.CYCLIST):
            vrus.append((state.x, state.y))
        if agent.agent_type == AgentType.VEHICLE:
            vehicles.append((agent.agent_id, state.x, state.y))

    result: dict[int, float] = {}
    if not vrus:
        for agent_id, _, _ in vehicles:
            result[agent_id] = float("inf")
        return result

    vru_arr = np.array(vrus, dtype=np.float32)
    for agent_id, vx, vy in vehicles:
        pos = np.array([vx, vy], dtype=np.float32)
        d = float(np.min(np.linalg.norm(vru_arr - pos, axis=1)))
        result[agent_id] = d

    return result


def _get_corners(state: AgentState) -> NDArray[np.float32]:
    """Get the 4 corners of an agent's oriented bounding box."""
    cos_h = np.cos(state.heading)
    sin_h = np.sin(state.heading)

    half_l = state.length / 2
    half_w = state.width / 2

    # Corners in local frame: front-left, front-right, rear-right, rear-left
    local = np.array([
        [half_l, half_w],
        [half_l, -half_w],
        [-half_l, -half_w],
        [-half_l, half_w],
    ], dtype=np.float32)

    rot = np.array([[cos_h, -sin_h], [sin_h, cos_h]], dtype=np.float32)
    world = local @ rot.T + np.array([state.x, state.y], dtype=np.float32)
    return world


def _bbox_overlap(
    corners_a: NDArray[np.float32], corners_b: NDArray[np.float32]
) -> float:
    """Approximate overlap between two oriented bounding boxes using SAT.

    Returns overlap ratio from 0.0 (no overlap) to 1.0 (significant overlap).
    """
    # Use Separating Axis Theorem (simplified)
    for corners in [corners_a, corners_b]:
        for i in range(4):
            edge = corners[(i + 1) % 4] - corners[i]
            axis = np.array([-edge[1], edge[0]], dtype=np.float32)
            norm = np.linalg.norm(axis)
            if norm < 1e-8:
                continue
            axis /= norm

            proj_a = corners_a @ axis
            proj_b = corners_b @ axis

            min_a, max_a = proj_a.min(), proj_a.max()
            min_b, max_b = proj_b.min(), proj_b.max()

            if max_a < min_b or max_b < min_a:
                return 0.0  # separating axis found

    # Overlapping — estimate overlap magnitude by center distance
    center_a = corners_a.mean(axis=0)
    center_b = corners_b.mean(axis=0)
    dist = np.linalg.norm(center_a - center_b)
    # Rough: full overlap when dist=0, diminishes with distance
    avg_size = (np.linalg.norm(corners_a[0] - corners_a[2])
                + np.linalg.norm(corners_b[0] - corners_b[2])) / 2
    if avg_size < 1e-8:
        return 1.0
    return float(max(0.0, min(1.0, 1.0 - dist / avg_size)))


def _compute_pairwise_ttc(
    state_a: AgentState, state_b: AgentState
) -> float:
    """Compute time-to-collision between two agents using linear projection.

    Projects both agents forward in time and finds when their bounding circles
    would intersect. Returns time in seconds, or inf if no collision expected.
    """
    dx = state_b.x - state_a.x
    dy = state_b.y - state_a.y
    dvx = state_b.vx - state_a.vx
    dvy = state_b.vy - state_a.vy

    # Collision radius: sum of half-diagonals
    r_a = np.sqrt(state_a.length**2 + state_a.width**2) / 2
    r_b = np.sqrt(state_b.length**2 + state_b.width**2) / 2
    r = r_a + r_b

    # Solve |p + v*t|^2 = r^2 for minimum positive t
    a = dvx**2 + dvy**2
    b = 2 * (dx * dvx + dy * dvy)
    c = dx**2 + dy**2 - r**2

    if c <= 0:
        return 0.0  # already overlapping

    if abs(a) < 1e-10:
        # Constant relative velocity — check if closing
        if abs(b) < 1e-10:
            return float("inf")
        t = -c / b
        return float(t) if t > 0 else float("inf")

    discriminant = b**2 - 4 * a * c
    if discriminant < 0:
        return float("inf")

    sqrt_disc = np.sqrt(discriminant)
    t1 = (-b - sqrt_disc) / (2 * a)
    t2 = (-b + sqrt_disc) / (2 * a)

    # Return smallest positive time
    candidates = [t for t in [t1, t2] if t > 0]
    return float(min(candidates)) if candidates else float("inf")


def _angle_diff(a: float, b: float) -> float:
    """Compute signed angle difference, wrapped to [-pi, pi]."""
    diff = a - b
    return float((diff + np.pi) % (2 * np.pi) - np.pi)
