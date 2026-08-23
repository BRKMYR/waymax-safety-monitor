"""Tests for safety metrics and composite risk scoring."""

import numpy as np

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import (
    AgentState,
    AgentTrajectory,
    AgentType,
    LaneLine,
    RoadGraph,
    Scenario,
)
from src.metrics.composite import (
    AgentRisk,
    RiskConfig,
    RiskLevel,
    classify_risk,
    compute_composite_risk,
)
from src.metrics.safety import (
    _angle_diff,
    _compute_pairwise_ttc,
    _get_corners,
    compute_accel,
    compute_lane_compliance,
    compute_offroad,
    compute_overlap,
    compute_ttc,
    compute_vru_distance,
    compute_wrong_way,
)


class TestAngleDiff:
    def test_zero(self):
        assert abs(_angle_diff(0.0, 0.0)) < 1e-6

    def test_small_positive(self):
        diff = _angle_diff(0.1, 0.0)
        assert abs(diff - 0.1) < 1e-6

    def test_wrap_around(self):
        diff = _angle_diff(3.0, -3.0)
        assert abs(diff) < 1.0  # should wrap, not be 6.0


class TestGetCorners:
    def test_axis_aligned(self):
        state = AgentState(x=0, y=0, heading=0, vx=0, vy=0, length=4, width=2)
        corners = _get_corners(state)
        assert corners.shape == (4, 2)
        # Front-left should be at (2, 1)
        np.testing.assert_allclose(corners[0], [2.0, 1.0], atol=1e-5)

    def test_rotated(self):
        state = AgentState(
            x=0, y=0, heading=np.pi / 2, vx=0, vy=0, length=4, width=2
        )
        corners = _get_corners(state)
        # After 90 degree rotation, front-left should be at (-1, 2)
        np.testing.assert_allclose(corners[0], [-1.0, 2.0], atol=1e-5)


class TestPairwiseTTC:
    def test_head_on_collision(self):
        a = AgentState(x=0, y=0, heading=0, vx=10, vy=0, length=4, width=2)
        b = AgentState(x=30, y=0, heading=np.pi, vx=-10, vy=0, length=4, width=2)
        ttc = _compute_pairwise_ttc(a, b)
        # Closing at 20 m/s, ~30m apart, collision radius ~sqrt(20)/2*2 ~ 4.5
        assert 0 < ttc < 2.0

    def test_parallel_no_collision(self):
        a = AgentState(x=0, y=0, heading=0, vx=10, vy=0, length=4, width=2)
        b = AgentState(x=0, y=20, heading=0, vx=10, vy=0, length=4, width=2)
        ttc = _compute_pairwise_ttc(a, b)
        assert ttc == float("inf")

    def test_already_overlapping(self):
        a = AgentState(x=0, y=0, heading=0, vx=0, vy=0, length=4, width=2)
        b = AgentState(x=1, y=0, heading=0, vx=0, vy=0, length=4, width=2)
        ttc = _compute_pairwise_ttc(a, b)
        assert ttc == 0.0

    def test_stationary_diverging(self):
        a = AgentState(x=0, y=0, heading=0, vx=-5, vy=0, length=4, width=2)
        b = AgentState(x=20, y=0, heading=0, vx=5, vy=0, length=4, width=2)
        ttc = _compute_pairwise_ttc(a, b)
        assert ttc == float("inf")

    def test_exact_head_on_linear(self):
        # r_a = sqrt(4+0)/2 = 1, r_b = 1, r = 2. Center gap 22, closing 10 m/s
        # bounding-circle gap = 20 -> ttc = 2.0s exactly.
        a = AgentState(x=0, y=0, heading=0, vx=10, vy=0, length=2, width=0)
        b = AgentState(x=22, y=0, heading=0, vx=0, vy=0, length=2, width=0)
        ttc = _compute_pairwise_ttc(a, b)
        assert abs(ttc - 2.0) < 1e-6


class TestOverlap:
    def test_no_overlap(self):
        scenario = _make_two_agent_scenario(
            (0, 0, 0), (50, 50, 0),  # far apart
        )
        overlaps = compute_overlap(scenario, 0)
        assert overlaps[0] == 0.0
        assert overlaps[1] == 0.0

    def test_overlapping(self):
        scenario = _make_two_agent_scenario(
            (0, 0, 0), (2, 0, 0),  # very close, overlapping
        )
        overlaps = compute_overlap(scenario, 0)
        assert overlaps[0] > 0.0
        assert overlaps[1] > 0.0


class TestOffroad:
    def test_on_road(self):
        scenario = load_demo_scenario("intersection_conflict")
        offroad = compute_offroad(scenario, 0)
        # Ego should start on the road
        assert offroad[0] < 0.5

    def test_off_road(self):
        scenario = _make_single_agent_scenario((100, 100, 0))
        offroad = compute_offroad(scenario, 0)
        assert offroad[0] > 0.0

    def test_pedestrian_excluded(self):
        # Pedestrian far off the drivable surface -> still 0.0.
        scenario = _make_single_pedestrian_scenario((100.0, 100.0, 0.0))
        offroad = compute_offroad(scenario, 0)
        assert offroad[0] == 0.0


class TestWrongWay:
    def test_aligned(self):
        scenario = load_demo_scenario("intersection_conflict")
        wrong_way = compute_wrong_way(scenario, 0)
        # Ego heading should be roughly aligned with its lane
        assert wrong_way[0] < 0.5

    def test_pedestrian_excluded(self):
        scenario = _make_single_pedestrian_scenario((0.0, 0.0, np.pi / 2))
        ww = compute_wrong_way(scenario, 0)
        assert ww[0] == 0.0

    def test_direction_aware_westbound(self):
        # Eastbound lane at y=-1.75 (points west->east) and westbound at
        # y=+1.75 (points east->west). Vehicle at (0, 1.75) heading pi is
        # aligned with the westbound lane despite the eastbound one being
        # within the 6 m match radius.
        rg = RoadGraph(lanes=[
            LaneLine(points=np.array([[-30, -1.75], [30, -1.75]], dtype=np.float32),
                     lane_type="center", lane_id=0),
            LaneLine(points=np.array([[30, 1.75], [-30, 1.75]], dtype=np.float32),
                     lane_type="center", lane_id=1),
        ])
        scenario = _one_vehicle_with_graph(rg, x=0.0, y=1.75, heading=np.pi)
        ww = compute_wrong_way(scenario, 0)
        assert ww[0] < 0.1

    def test_direction_aware_eastbound(self):
        rg = RoadGraph(lanes=[
            LaneLine(points=np.array([[-30, -1.75], [30, -1.75]], dtype=np.float32),
                     lane_type="center", lane_id=0),
            LaneLine(points=np.array([[30, 1.75], [-30, 1.75]], dtype=np.float32),
                     lane_type="center", lane_id=1),
        ])
        # Vehicle at y = -1.75 heading east - eastbound lane matches.
        scenario = _one_vehicle_with_graph(rg, x=0.0, y=-1.75, heading=0.0)
        ww = compute_wrong_way(scenario, 0)
        assert ww[0] < 0.1

    def test_no_matching_direction_flags_wrong_way(self):
        # Only an east-west lane; vehicle heading north (pi/2) at that
        # location has no direction-compatible lane -> non-trivial score.
        rg = RoadGraph(lanes=[
            LaneLine(points=np.array([[-30, 1.75], [30, 1.75]], dtype=np.float32),
                     lane_type="center", lane_id=0),
        ])
        scenario = _one_vehicle_with_graph(rg, x=0.0, y=1.75, heading=np.pi / 2)
        ww = compute_wrong_way(scenario, 0)
        assert ww[0] >= 0.4


class TestTTC:
    def test_demo_scenario(self):
        scenario = load_demo_scenario("intersection_conflict")
        ttc = compute_ttc(scenario, 0)
        # Should have TTC values for all valid agents
        assert len(ttc) > 0
        for agent_id, value in ttc.items():
            assert value >= 0


class TestLaneCompliance:
    def test_demo_scenario(self):
        scenario = load_demo_scenario("intersection_conflict")
        compliance = compute_lane_compliance(scenario, 0)
        assert len(compliance) > 0
        for agent_id, score in compliance.items():
            assert 0.0 <= score <= 1.0

    def test_pedestrian_excluded(self):
        scenario = _make_single_pedestrian_scenario((100.0, 100.0, 0.0))
        compliance = compute_lane_compliance(scenario, 0)
        assert compliance[0] == 1.0


class TestAccel:
    def test_at_t_zero(self):
        # Any scenario, t=0 -> 0.0 for every agent.
        scenario = load_demo_scenario("intersection_conflict")
        accels = compute_accel(scenario, 0)
        for aid, a in accels.items():
            assert a == 0.0

    def test_step_change(self):
        # vx = [10, 10, 4, 4] -> accel[2] = -60 m/s^2 (dt = 0.1).
        traj = AgentTrajectory(
            agent_id=0, agent_type=AgentType.VEHICLE,
            x=np.zeros(4, dtype=np.float32),
            y=np.zeros(4, dtype=np.float32),
            heading=np.zeros(4, dtype=np.float32),
            vx=np.array([10.0, 10.0, 4.0, 4.0], dtype=np.float32),
            vy=np.zeros(4, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(4, dtype=bool),
        )
        scenario = Scenario(
            scenario_id="t", num_timesteps=4, timestep_duration=0.1,
            agents=[traj], road_graph=RoadGraph(),
        )
        assert abs(compute_accel(scenario, 2)[0] - (-60.0)) < 1e-4
        assert compute_accel(scenario, 0)[0] == 0.0

    def test_invalid_previous_is_zero(self):
        traj = AgentTrajectory(
            agent_id=0, agent_type=AgentType.VEHICLE,
            x=np.zeros(2, dtype=np.float32),
            y=np.zeros(2, dtype=np.float32),
            heading=np.zeros(2, dtype=np.float32),
            vx=np.array([0.0, 10.0], dtype=np.float32),
            vy=np.zeros(2, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.array([False, True], dtype=bool),
        )
        scenario = Scenario(
            scenario_id="t", num_timesteps=2, timestep_duration=0.1,
            agents=[traj], road_graph=RoadGraph(),
        )
        # Agent not valid at t=0 but valid at t=1; because t-1 was invalid
        # we return 0.0 for t=1.
        assert compute_accel(scenario, 1)[0] == 0.0


class TestVruDistance:
    def test_vehicle_to_pedestrian_exact(self):
        veh = AgentTrajectory(
            agent_id=0, agent_type=AgentType.VEHICLE,
            x=np.zeros(1, dtype=np.float32),
            y=np.zeros(1, dtype=np.float32),
            heading=np.zeros(1, dtype=np.float32),
            vx=np.zeros(1, dtype=np.float32), vy=np.zeros(1, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(1, dtype=bool),
        )
        ped = AgentTrajectory(
            agent_id=1, agent_type=AgentType.PEDESTRIAN,
            x=np.array([3.0], dtype=np.float32),
            y=np.array([4.0], dtype=np.float32),
            heading=np.zeros(1, dtype=np.float32),
            vx=np.zeros(1, dtype=np.float32), vy=np.zeros(1, dtype=np.float32),
            length=0.5, width=0.5,
            valid=np.ones(1, dtype=bool),
        )
        scenario = Scenario(
            scenario_id="t", num_timesteps=1, timestep_duration=0.1,
            agents=[veh, ped], road_graph=RoadGraph(),
        )
        result = compute_vru_distance(scenario, 0)
        assert abs(result[0] - 5.0) < 1e-5
        assert 1 not in result  # pedestrian is not keyed

    def test_no_vrus_is_inf(self):
        v1 = AgentTrajectory(
            agent_id=0, agent_type=AgentType.VEHICLE,
            x=np.zeros(1, dtype=np.float32),
            y=np.zeros(1, dtype=np.float32),
            heading=np.zeros(1, dtype=np.float32),
            vx=np.zeros(1, dtype=np.float32), vy=np.zeros(1, dtype=np.float32),
            length=4.5, width=2.0, valid=np.ones(1, dtype=bool),
        )
        scenario = Scenario(
            scenario_id="t", num_timesteps=1, timestep_duration=0.1,
            agents=[v1], road_graph=RoadGraph(),
        )
        result = compute_vru_distance(scenario, 0)
        assert result[0] == float("inf")


class TestCompositeRisk:
    def test_demo_scenario(self):
        scenario = load_demo_scenario("intersection_conflict")
        risks = compute_composite_risk(scenario, 0)
        assert len(risks) > 0
        for agent_id, risk in risks.items():
            assert isinstance(risk, AgentRisk)
            assert 0.0 <= risk.composite_score <= 1.0
            assert risk.risk_level in (RiskLevel.GREEN, RiskLevel.AMBER, RiskLevel.RED)

    def test_classify_risk_green(self):
        assert classify_risk(0.0) == RiskLevel.GREEN
        assert classify_risk(0.29) == RiskLevel.GREEN

    def test_classify_risk_amber(self):
        assert classify_risk(0.3) == RiskLevel.AMBER
        assert classify_risk(0.59) == RiskLevel.AMBER

    def test_classify_risk_red(self):
        assert classify_risk(0.6) == RiskLevel.RED
        assert classify_risk(1.0) == RiskLevel.RED


def _make_two_agent_scenario(
    agent_a: tuple[float, float, float],
    agent_b: tuple[float, float, float],
) -> Scenario:
    """Create a minimal scenario with two stationary vehicles."""
    agents = []
    for i, (x, y, h) in enumerate([agent_a, agent_b]):
        agents.append(AgentTrajectory(
            agent_id=i,
            agent_type=AgentType.VEHICLE,
            x=np.array([x], dtype=np.float32),
            y=np.array([y], dtype=np.float32),
            heading=np.array([h], dtype=np.float32),
            vx=np.zeros(1, dtype=np.float32),
            vy=np.zeros(1, dtype=np.float32),
            length=4.5,
            width=2.0,
            valid=np.ones(1, dtype=bool),
        ))

    road_graph = RoadGraph(
        lanes=[
            LaneLine(
                points=np.array([[-50, 0], [50, 0]], dtype=np.float32),
                lane_type="center",
            )
        ],
    )

    return Scenario(
        scenario_id="test",
        num_timesteps=1,
        timestep_duration=0.1,
        agents=agents,
        road_graph=road_graph,
    )


def _make_single_agent_scenario(
    pos: tuple[float, float, float],
) -> Scenario:
    """Create a minimal scenario with one vehicle."""
    x, y, h = pos
    agents = [AgentTrajectory(
        agent_id=0,
        agent_type=AgentType.VEHICLE,
        x=np.array([x], dtype=np.float32),
        y=np.array([y], dtype=np.float32),
        heading=np.array([h], dtype=np.float32),
        vx=np.zeros(1, dtype=np.float32),
        vy=np.zeros(1, dtype=np.float32),
        length=4.5,
        width=2.0,
        valid=np.ones(1, dtype=bool),
    )]

    road_graph = RoadGraph(
        lanes=[
            LaneLine(
                points=np.array([[-50, 0], [50, 0]], dtype=np.float32),
                lane_type="center",
            )
        ],
    )

    return Scenario(
        scenario_id="test",
        num_timesteps=1,
        timestep_duration=0.1,
        agents=agents,
        road_graph=road_graph,
    )


def _make_single_pedestrian_scenario(
    pos: tuple[float, float, float],
) -> Scenario:
    x, y, h = pos
    agents = [AgentTrajectory(
        agent_id=0,
        agent_type=AgentType.PEDESTRIAN,
        x=np.array([x], dtype=np.float32),
        y=np.array([y], dtype=np.float32),
        heading=np.array([h], dtype=np.float32),
        vx=np.zeros(1, dtype=np.float32),
        vy=np.zeros(1, dtype=np.float32),
        length=0.5,
        width=0.5,
        valid=np.ones(1, dtype=bool),
    )]
    road_graph = RoadGraph(
        lanes=[
            LaneLine(
                points=np.array([[-50, 0], [50, 0]], dtype=np.float32),
                lane_type="center",
            )
        ],
    )
    return Scenario(
        scenario_id="ped_test",
        num_timesteps=1,
        timestep_duration=0.1,
        agents=agents,
        road_graph=road_graph,
    )


def _one_vehicle_with_graph(
    rg: RoadGraph, x: float, y: float, heading: float,
) -> Scenario:
    veh = AgentTrajectory(
        agent_id=0, agent_type=AgentType.VEHICLE,
        x=np.array([x], dtype=np.float32),
        y=np.array([y], dtype=np.float32),
        heading=np.array([heading], dtype=np.float32),
        vx=np.zeros(1, dtype=np.float32),
        vy=np.zeros(1, dtype=np.float32),
        length=4.5, width=2.0,
        valid=np.ones(1, dtype=bool),
    )
    return Scenario(
        scenario_id="dir",
        num_timesteps=1, timestep_duration=0.1,
        agents=[veh], road_graph=rg,
    )
