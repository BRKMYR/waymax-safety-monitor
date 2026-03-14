"""Safety metrics for driving scenarios.

Computes per-agent, per-timestep safety metrics including overlap detection,
off-road detection, wrong-way detection, time-to-collision, and lane compliance.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from src.data.scenario import AgentState, AgentTrajectory, RoadGraph, Scenario


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
    Uses distance to nearest road edge/lane as a proxy.
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
    """
    active = scenario.agents_at(t)
    road_graph = scenario.road_graph
    wrong_way: dict[int, float] = {}

    # Compute lane directions from center lane polylines
    lane_segments = []
    for lane in road_graph.lanes:
        if lane.lane_type == "center" and len(lane.points) >= 2:
            for k in range(len(lane.points) - 1):
                p1 = lane.points[k]
                p2 = lane.points[k + 1]
                mid = (p1 + p2) / 2
                direction = np.arctan2(p2[1] - p1[1], p2[0] - p1[0])
                lane_segments.append((mid, direction))

    if not lane_segments:
        return {agent.agent_id: 0.0 for agent, _ in active}

    seg_mids = np.array([s[0] for s in lane_segments], dtype=np.float32)
    seg_dirs = np.array([s[1] for s in lane_segments], dtype=np.float32)

    for agent, state in active:
        pos = np.array([state.x, state.y], dtype=np.float32)
        dists = np.linalg.norm(seg_mids - pos, axis=1)
        nearest_idx = int(np.argmin(dists))

        # Only check wrong-way if reasonably close to a lane
        if dists[nearest_idx] > 5.0:
            wrong_way[agent.agent_id] = 0.0
            continue

        lane_dir = seg_dirs[nearest_idx]
        heading_diff = _angle_diff(state.heading, lane_dir)

        # Score based on how far heading deviates from lane direction
        # 0 = aligned, pi = opposite direction
        wrong_way[agent.agent_id] = float(abs(heading_diff) / np.pi)

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
    Combines lateral offset from lane center and heading alignment.
    """
    active = scenario.agents_at(t)
    road_graph = scenario.road_graph
    compliance: dict[int, float] = {}

    # Get lane centers
    lane_centers = []
    lane_directions = []
    for lane in road_graph.lanes:
        if lane.lane_type == "center" and len(lane.points) >= 2:
            for k in range(len(lane.points) - 1):
                mid = (lane.points[k] + lane.points[k + 1]) / 2
                direction = np.arctan2(
                    lane.points[k + 1][1] - lane.points[k][1],
                    lane.points[k + 1][0] - lane.points[k][0],
                )
                lane_centers.append(mid)
                lane_directions.append(direction)

    if not lane_centers:
        return {agent.agent_id: 1.0 for agent, _ in active}

    centers = np.array(lane_centers, dtype=np.float32)
    directions = np.array(lane_directions, dtype=np.float32)

    for agent, state in active:
        pos = np.array([state.x, state.y], dtype=np.float32)
        dists = np.linalg.norm(centers - pos, axis=1)
        nearest_idx = int(np.argmin(dists))

        lateral_offset = float(dists[nearest_idx])
        heading_diff = abs(_angle_diff(state.heading, directions[nearest_idx]))

        # Lateral score: 1.0 within 0.5m, decays to 0.0 at 3.0m
        lateral_score = max(0.0, 1.0 - max(0.0, lateral_offset - 0.5) / 2.5)

        # Heading score: 1.0 within 5deg, decays to 0.0 at 45deg
        heading_score = max(0.0, 1.0 - max(0.0, heading_diff - np.radians(5)) / np.radians(40))

        compliance[agent.agent_id] = 0.6 * lateral_score + 0.4 * heading_score

    return compliance


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
