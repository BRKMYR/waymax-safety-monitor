"""Tests for the teleoperation trigger engine."""

import numpy as np

from src.data.demo_loader import load_demo_scenario
from src.metrics.composite import RiskConfig, compute_composite_risk
from src.triggers.config import TriggerConfig
from src.triggers.engine import TriggerEngine, TriggerSeverity


class TestTriggerConfig:
    def test_default_config(self):
        config = TriggerConfig()
        assert config.ttc_red == 2.0
        assert config.ttc_amber == 4.0

    def test_conservative_policy(self):
        config = TriggerConfig.conservative()
        assert config.ttc_red > TriggerConfig().ttc_red  # Triggers earlier
        assert config.composite_red < TriggerConfig().composite_red

    def test_permissive_policy(self):
        config = TriggerConfig.permissive()
        assert config.ttc_red < TriggerConfig().ttc_red  # Triggers later
        assert config.composite_red > TriggerConfig().composite_red


class TestTriggerEngine:
    def test_evaluate_returns_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        risks = compute_composite_risk(scenario, 0)
        events = engine.evaluate(scenario, 0, risks)
        # Events list should be a list (may be empty at t=0)
        assert isinstance(events, list)

    def test_no_duplicate_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        risks = compute_composite_risk(scenario, 0)
        events1 = engine.evaluate(scenario, 0, risks)
        events2 = engine.evaluate(scenario, 0, risks)
        # Second call should not produce duplicates
        assert len(events2) == 0

    def test_full_scenario_produces_events(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        for t in range(scenario.num_timesteps):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        # Over 91 timesteps with multiple agents, we expect some triggers
        assert len(engine.events) > 0

    def test_events_have_correct_fields(self):
        scenario = load_demo_scenario("intersection_conflict")
        engine = TriggerEngine()

        for t in range(scenario.num_timesteps):
            risks = compute_composite_risk(scenario, t)
            engine.evaluate(scenario, t, risks)

        if engine.events:
            event = engine.events[0]
            assert event.timestep >= 0
            assert event.time_seconds >= 0
            assert event.severity in (TriggerSeverity.AMBER, TriggerSeverity.RED)
            assert len(event.reason) > 0
            assert event.severity_name in ("AMBER", "RED")

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

        # events_at should filter correctly
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

    def test_conservative_triggers_more(self):
        scenario = load_demo_scenario("intersection_conflict")

        engine_default = TriggerEngine(TriggerConfig())
        engine_conservative = TriggerEngine(TriggerConfig.conservative())

        for t in range(scenario.num_timesteps):
            risks = compute_composite_risk(scenario, t)
            engine_default.evaluate(scenario, t, risks)
            engine_conservative.evaluate(scenario, t, risks)

        # Conservative should trigger at least as many events
        assert len(engine_conservative.events) >= len(engine_default.events)
