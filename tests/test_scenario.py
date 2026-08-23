"""Tests for scenario data classes and demo data loading."""

import numpy as np
import pytest

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import AgentType, Scenario


class TestScenarioDataClasses:
    def test_agent_trajectory_state_at(self):
        from src.data.scenario import AgentTrajectory

        traj = AgentTrajectory(
            agent_id=0,
            agent_type=AgentType.VEHICLE,
            x=np.array([1.0, 2.0, 3.0], dtype=np.float32),
            y=np.array([4.0, 5.0, 6.0], dtype=np.float32),
            heading=np.array([0.0, 0.1, 0.2], dtype=np.float32),
            vx=np.array([10.0, 10.0, 10.0], dtype=np.float32),
            vy=np.array([0.0, 0.0, 0.0], dtype=np.float32),
            length=4.5,
            width=2.0,
            valid=np.array([True, True, False], dtype=bool),
        )

        state = traj.state_at(1)
        assert state.x == 2.0
        assert state.y == 5.0
        assert state.valid is True

        state = traj.state_at(2)
        assert state.valid is False

    def test_agent_trajectory_speed(self):
        from src.data.scenario import AgentTrajectory

        traj = AgentTrajectory(
            agent_id=0,
            agent_type=AgentType.VEHICLE,
            x=np.zeros(3, dtype=np.float32),
            y=np.zeros(3, dtype=np.float32),
            heading=np.zeros(3, dtype=np.float32),
            vx=np.array([3.0, 0.0, 4.0], dtype=np.float32),
            vy=np.array([4.0, 0.0, 3.0], dtype=np.float32),
            length=4.5,
            width=2.0,
            valid=np.ones(3, dtype=bool),
        )

        speeds = traj.speed
        np.testing.assert_allclose(speeds, [5.0, 0.0, 5.0])

    def test_scenario_agents_at(self):
        scenario = load_demo_scenario("intersection_conflict")

        agents_t0 = scenario.agents_at(0)
        # At least some agents should be valid at t=0
        assert len(agents_t0) > 0

        # All returned agents should be valid
        for agent, state in agents_t0:
            assert state.valid

    def test_scenario_ego(self):
        scenario = load_demo_scenario("intersection_conflict")
        ego = scenario.ego
        assert ego.agent_id == scenario.ego_agent_id


class TestDemoLoader:
    def test_load_intersection_conflict(self):
        scenario = load_demo_scenario("intersection_conflict")
        assert isinstance(scenario, Scenario)
        assert scenario.num_timesteps == 91
        assert scenario.timestep_duration == 0.1
        assert len(scenario.agents) >= 4
        assert len(scenario.road_graph.lanes) > 0
        assert len(scenario.road_graph.crosswalks) > 0

    def test_load_highway_merge(self):
        scenario = load_demo_scenario("highway_merge")
        assert isinstance(scenario, Scenario)
        assert scenario.num_timesteps == 91
        assert len(scenario.agents) >= 3

    def test_load_pedestrian_crossing(self):
        scenario = load_demo_scenario("pedestrian_crossing")
        assert isinstance(scenario, Scenario)
        assert any(
            a.agent_type == AgentType.PEDESTRIAN for a in scenario.agents
        )
        assert len(scenario.road_graph.crosswalks) > 0

    def test_demo_deterministic_with_seed(self):
        s1 = load_demo_scenario("intersection_conflict", seed=42)
        s2 = load_demo_scenario("intersection_conflict", seed=42)
        np.testing.assert_array_equal(s1.agents[0].x, s2.agents[0].x)

    def test_different_seeds_differ(self):
        s1 = load_demo_scenario("intersection_conflict", seed=42)
        s2 = load_demo_scenario("intersection_conflict", seed=99)
        assert not np.array_equal(s1.agents[0].x, s2.agents[0].x)

    def test_all_agents_have_correct_timesteps(self):
        scenario = load_demo_scenario("intersection_conflict")
        for agent in scenario.agents:
            assert agent.num_timesteps == scenario.num_timesteps
            assert len(agent.x) == scenario.num_timesteps
            assert len(agent.valid) == scenario.num_timesteps

    def test_load_hard_brake(self):
        scenario = load_demo_scenario("hard_brake")
        assert scenario.num_timesteps == 91
        assert scenario.timestep_duration == 0.1
        assert len(scenario.agents) >= 2

    def test_load_stalled_ego(self):
        scenario = load_demo_scenario("stalled_ego")
        assert scenario.num_timesteps == 91
        assert scenario.timestep_duration == 0.1
        assert any(
            a.agent_type == AgentType.VEHICLE for a in scenario.agents
        )

    def test_hard_brake_deterministic_regardless_of_seed(self):
        # Noise-free scenario -> byte-identical trajectory across seeds.
        s1 = load_demo_scenario("hard_brake", seed=42)
        s2 = load_demo_scenario("hard_brake", seed=99)
        for a1, a2 in zip(s1.agents, s2.agents):
            np.testing.assert_array_equal(a1.x, a2.x)
            np.testing.assert_array_equal(a1.y, a2.y)
            np.testing.assert_array_equal(a1.vx, a2.vx)

    def test_stalled_ego_deterministic_regardless_of_seed(self):
        s1 = load_demo_scenario("stalled_ego", seed=42)
        s2 = load_demo_scenario("stalled_ego", seed=99)
        for a1, a2 in zip(s1.agents, s2.agents):
            np.testing.assert_array_equal(a1.x, a2.x)
            np.testing.assert_array_equal(a1.y, a2.y)
            np.testing.assert_array_equal(a1.vx, a2.vx)

    def test_hard_brake_lead_speed_profile(self):
        scenario = load_demo_scenario("hard_brake")
        lead = scenario.agents[1]
        # v[30] = 15.0, v[31] = 14.4 -> accel[31] = -6.0 m/s^2
        assert abs(float(lead.vx[30]) - 15.0) < 1e-4
        assert abs(float(lead.vx[31]) - 14.4) < 1e-4

    def test_stalled_ego_speed_profile(self):
        scenario = load_demo_scenario("stalled_ego")
        ego = scenario.agents[0]
        # First timestep with speed < 0.3 must be t=49 (v=0.2).
        speeds = np.hypot(ego.vx, ego.vy)
        # 0.3 boundary
        below = np.where(speeds < 0.3)[0]
        assert below.size > 0
        assert int(below[0]) == 49

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            load_demo_scenario("does_not_exist")
