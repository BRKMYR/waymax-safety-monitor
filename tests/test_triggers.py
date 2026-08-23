"""Tests for the teleoperation trigger engine."""

import numpy as np

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import (
    AgentTrajectory,
    AgentType,
    RoadGraph,
    Scenario,
)
from src.metrics.composite import compute_composite_risk
from src.metrics.safety import _angle_diff  # noqa: F401  (import test)
from src.triggers.config import TriggerConfig
from src.triggers.engine import (
    TRIGGER_KINDS,
    TriggerEngine,
    TriggerEvent,
    TriggerSeverity,
)


def _run_full(scenario: Scenario, engine: TriggerEngine) -> list[TriggerEvent]:
    for t in range(scenario.num_timesteps):
        risks = compute_composite_risk(scenario, t)
        engine.evaluate(scenario, t, risks)
    return list(engine.events)


class TestTriggerConfig:
    def test_default_config(self):
        config = TriggerConfig()
        assert config.ttc_red == 2.0
        assert config.ttc_amber == 4.0

    def test_conservative_policy(self):
        config = TriggerConfig.conservative()
        assert config.ttc_red > TriggerConfig().ttc_red
        assert config.composite_red < TriggerConfig().composite_red

    def test_permissive_policy(self):
        config = TriggerConfig.permissive()
        assert config.ttc_red < TriggerConfig().ttc_red
        assert config.composite_red > TriggerConfig().composite_red

    def test_new_thresholds_present(self):
        config = TriggerConfig()
        assert config.hard_brake_accel <= -3.0
        assert config.stall_speed > 0.0
        assert config.stall_dwell_steps >= 1
        assert config.vru_distance_red < config.vru_distance_amber
        assert config.vru_min_vehicle_speed >= 0.0
        assert config.rearm_clear_steps >= 1


class TestTriggerEngine:
    def test_evaluate_returns_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        risks = compute_composite_risk(scenario, 0)
        events = engine.evaluate(scenario, 0, risks)
        assert isinstance(events, list)

    def test_no_duplicate_events_same_timestep(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        risks = compute_composite_risk(scenario, 0)
        engine.evaluate(scenario, 0, risks)
        # Re-evaluating with identical conditions must not double-fire the
        # same (agent, kind, severity) tuple. In practice the dashboard
        # advances t monotonically; the edge state protects against re-fires.
        second = engine.evaluate(scenario, 0, risks)
        assert second == []

    def test_full_scenario_produces_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()
        events = _run_full(scenario, engine)
        assert len(events) > 0

    def test_events_have_correct_fields(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()
        events = _run_full(scenario, engine)

        assert events, "expected at least one event"
        event = events[0]
        assert event.timestep >= 0
        assert event.time_seconds >= 0
        assert event.severity in (TriggerSeverity.AMBER, TriggerSeverity.RED)
        assert len(event.reason) > 0
        assert event.severity_name in ("AMBER", "RED")
        assert event.kind in TRIGGER_KINDS

    def test_reset_clears_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        risks = compute_composite_risk(scenario, 0)
        engine.evaluate(scenario, 0, risks)
        engine.reset()
        assert len(engine.events) == 0

    def test_events_at_timestep(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        for t in range(10):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        for t in range(10):
            events_t = engine.events_at(t)
            for e in events_t:
                assert e.timestep == t

    def test_events_up_to(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        for t in range(20):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        events_up_to_10 = engine.events_up_to(10)
        for e in events_up_to_10:
            assert e.timestep <= 10


# -----------------------------------------------------------------------
# Edge-triggered semantics
# -----------------------------------------------------------------------


def _make_two_step_ttc_scenario() -> Scenario:
    """Two closing vehicles with TTC below RED at both t=0 and t=1.

    Ego at (0,0) heading east at 10 m/s. Lead at (12, 0) heading east at
    0 m/s. Bumper gap ~ 12 - 4.5 = 7.5 m, closing at 10 m/s => TTC ~ 0.75s.
    Well below the default TTC RED threshold of 2.0s. The condition
    holds at both timesteps.
    """
    n = 2
    dt = 0.1

    ego = AgentTrajectory(
        agent_id=0,
        agent_type=AgentType.VEHICLE,
        x=np.array([0.0, 1.0], dtype=np.float32),
        y=np.zeros(n, dtype=np.float32),
        heading=np.zeros(n, dtype=np.float32),
        vx=np.array([10.0, 10.0], dtype=np.float32),
        vy=np.zeros(n, dtype=np.float32),
        length=4.5,
        width=2.0,
        valid=np.ones(n, dtype=bool),
    )
    lead = AgentTrajectory(
        agent_id=1,
        agent_type=AgentType.VEHICLE,
        x=np.array([12.0, 12.0], dtype=np.float32),
        y=np.zeros(n, dtype=np.float32),
        heading=np.zeros(n, dtype=np.float32),
        vx=np.zeros(n, dtype=np.float32),
        vy=np.zeros(n, dtype=np.float32),
        length=4.5,
        width=2.0,
        valid=np.ones(n, dtype=bool),
    )
    return Scenario(
        scenario_id="edge_ttc_two_step",
        num_timesteps=n,
        timestep_duration=dt,
        agents=[ego, lead],
        road_graph=RoadGraph(lanes=[], road_edges=[], crosswalks=[]),
        ego_agent_id=0,
    )


class TestEdgeSemantics:
    def test_ttc_condition_edge_fires_once(self):
        scenario = _make_two_step_ttc_scenario()
        engine = TriggerEngine()

        for t in range(scenario.num_timesteps):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        # Exactly one ttc event for the ego across the two timesteps.
        ttc_events = [
            e for e in engine.events
            if e.kind == "ttc" and e.agent_id == 0
        ]
        assert len(ttc_events) == 1
        assert ttc_events[0].timestep == 0

    def test_condition_rearm_after_clear(self):
        """Condition tripped at t=0, clears for rearm_clear_steps, re-trips."""
        config = TriggerConfig(rearm_clear_steps=3)
        engine = TriggerEngine(config)

        # Fabricate a scenario where the ttc condition is on/off/on:
        # t=0: closing (RED)
        # t=1..3: separated (no TTC)
        # t=4: closing again (RED)
        n = 5
        ego = AgentTrajectory(
            agent_id=0,
            agent_type=AgentType.VEHICLE,
            x=np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
            y=np.zeros(n, dtype=np.float32),
            heading=np.zeros(n, dtype=np.float32),
            vx=np.array([10.0, 0.0, 0.0, 0.0, 10.0], dtype=np.float32),
            vy=np.zeros(n, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(n, dtype=bool),
        )
        # Lead nearby only at t=0 and t=4; far away in between.
        lead_x = np.array([12.0, 500.0, 500.0, 500.0, 12.0], dtype=np.float32)
        lead = AgentTrajectory(
            agent_id=1,
            agent_type=AgentType.VEHICLE,
            x=lead_x,
            y=np.zeros(n, dtype=np.float32),
            heading=np.zeros(n, dtype=np.float32),
            vx=np.zeros(n, dtype=np.float32),
            vy=np.zeros(n, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(n, dtype=bool),
        )
        scenario = Scenario(
            scenario_id="rearm_test",
            num_timesteps=n,
            timestep_duration=0.1,
            agents=[ego, lead],
            road_graph=RoadGraph(lanes=[], road_edges=[], crosswalks=[]),
            ego_agent_id=0,
        )

        for t in range(n):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        ttc_events = [e for e in engine.events if e.kind == "ttc" and e.agent_id == 0]
        # One fire at t=0, one after re-arm at t=4.
        assert len(ttc_events) == 2
        assert ttc_events[0].timestep == 0
        assert ttc_events[1].timestep == 4

    def test_escalation_amber_to_red_fires_second_event(self):
        """A condition AMBER at t=0 escalating to RED at t=1 emits 2 events."""
        engine = TriggerEngine()

        n = 2
        # Build closing scenario with two distinct closing rates so that:
        #   t=0: TTC ~ 3.0s (AMBER)
        #   t=1: TTC ~ 1.0s (RED)
        # Ego closes on a stationary lead.
        # Bumper gap g, closing speed c => ttc = g/c.
        # t=0: g=15, c=5  => 3.0
        # t=1: g=5,  c=5  => 1.0
        ego = AgentTrajectory(
            agent_id=0,
            agent_type=AgentType.VEHICLE,
            x=np.array([0.0, 10.0], dtype=np.float32),
            y=np.zeros(n, dtype=np.float32),
            heading=np.zeros(n, dtype=np.float32),
            vx=np.array([5.0, 5.0], dtype=np.float32),
            vy=np.zeros(n, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(n, dtype=bool),
        )
        lead = AgentTrajectory(
            agent_id=1,
            agent_type=AgentType.VEHICLE,
            x=np.array([19.5, 19.5], dtype=np.float32),
            y=np.zeros(n, dtype=np.float32),
            heading=np.zeros(n, dtype=np.float32),
            vx=np.zeros(n, dtype=np.float32),
            vy=np.zeros(n, dtype=np.float32),
            length=4.5, width=2.0,
            valid=np.ones(n, dtype=bool),
        )
        scenario = Scenario(
            scenario_id="escalation",
            num_timesteps=n,
            timestep_duration=0.1,
            agents=[ego, lead],
            road_graph=RoadGraph(lanes=[], road_edges=[], crosswalks=[]),
            ego_agent_id=0,
        )

        for t in range(n):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        ttc_events = [e for e in engine.events if e.kind == "ttc" and e.agent_id == 0]
        assert len(ttc_events) == 2
        assert ttc_events[0].severity == TriggerSeverity.AMBER
        assert ttc_events[1].severity == TriggerSeverity.RED


# -----------------------------------------------------------------------
# Exact analytic scenarios: hard_brake, stalled_ego
# -----------------------------------------------------------------------


class TestExactAnalyticTriggers:
    def test_hard_brake_fires_at_expected_timestep(self):
        scenario = load_demo_scenario("hard_brake")
        engine = TriggerEngine()
        events = _run_full(scenario, engine)

        hb = [e for e in events if e.kind == "hard_brake"]
        assert len(hb) == 1
        e = hb[0]
        assert e.agent_id == 1
        assert e.timestep == 31
        assert e.severity == TriggerSeverity.RED

    def test_stalled_ego_fires_at_expected_timestep(self):
        scenario = load_demo_scenario("stalled_ego")
        engine = TriggerEngine()
        events = _run_full(scenario, engine)

        st = [e for e in events if e.kind == "stalled"]
        assert len(st) == 1
        e = st[0]
        assert e.agent_id == 0
        assert e.timestep == 68
        assert e.severity == TriggerSeverity.RED


# -----------------------------------------------------------------------
# VRU proximity window
# -----------------------------------------------------------------------


class TestVruWindow:
    def test_pedestrian_crossing_produces_vru_event(self):
        scenario = load_demo_scenario("pedestrian_crossing")
        engine = TriggerEngine()
        _run_full(scenario, engine)

        vru = [
            e for e in engine.events
            if e.kind == "vru_proximity" and e.agent_id == 0
        ]
        assert len(vru) >= 1
        # Ego closes on the crosswalk in the later half of the scenario;
        # the first VRU event should land somewhere in that window.
        timesteps = [e.timestep for e in vru]
        assert any(60 <= t <= 90 for t in timesteps)


# -----------------------------------------------------------------------
# Spam ceiling + kind integrity
# -----------------------------------------------------------------------


class TestSpamCeilingAndIntegrity:
    def test_intersection_default_event_count_in_range(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()
        events = _run_full(scenario, engine)
        # Edge-triggered engine must produce a bounded, non-trivial count.
        assert 5 <= len(events) <= 60

    def test_every_event_has_valid_kind(self):
        for name in (
            "intersection_conflict",
            "highway_merge",
            "pedestrian_crossing",
            "hard_brake",
            "stalled_ego",
        ):
            scenario = load_demo_scenario(name)
            engine = TriggerEngine()
            events = _run_full(scenario, engine)
            for e in events:
                assert e.kind in TRIGGER_KINDS, (
                    f"{name}: unexpected kind {e.kind!r}"
                )

    def test_conservative_triggers_more(self):
        scenario = load_demo_scenario("intersection_conflict")

        engine_default = TriggerEngine(TriggerConfig())
        engine_conservative = TriggerEngine(TriggerConfig.conservative())

        _run_full(scenario, engine_default)
        _run_full(scenario, engine_conservative)

        assert len(engine_conservative.events) >= len(engine_default.events)
