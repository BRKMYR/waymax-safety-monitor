"""Tests for safety metrics and composite risk scoring."""

import numpy as np

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import AgentState, AgentTrajectory, AgentType, LaneLine, RoadGraph, Scenario
from src.metrics.composite import (
    AgentRisk,
    RiskConfig,
    RiskLevel,
    classify_risk,
    compute_composite_risk,
)
from src.metrics.safety import (
    compute_lane_compliance,
    compute_offroad,
    compute_overlap,
    compute_ttc,
    compute_wrong_way,
    _angle_diff,
    _compute_pairwise_ttc,
    _get_corners,
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
        # Closing at 20 m/s, ~30m apart, collision radius ~sqrt(20)/2*2 ≈ 4.5
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


class TestWrongWay:
    def test_aligned(self):
        scenario = load_demo_scenario("intersection_conflict")
        wrong_way = compute_wrong_way(scenario, 0)
        # Ego heading should be roughly aligned with its lane
        assert wrong_way[0] < 0.5


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
