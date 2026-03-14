"""Composite risk scoring and risk level classification."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from src.data.scenario import Scenario
from src.metrics.safety import (
    compute_lane_compliance,
    compute_offroad,
    compute_overlap,
    compute_ttc,
    compute_wrong_way,
)


class RiskLevel(enum.IntEnum):
    GREEN = 0   # Nominal
    AMBER = 1   # Elevated risk
    RED = 2     # Critical — teleoperation trigger


@dataclass
class RiskConfig:
    """Configurable weights and thresholds for risk scoring."""

    # Metric weights (must sum to 1.0)
    weight_overlap: float = 0.25
    weight_offroad: float = 0.15
    weight_wrong_way: float = 0.15
    weight_ttc: float = 0.25
    weight_lane_compliance: float = 0.20

    # TTC normalization: scores go from 0 at ttc_safe to 1 at ttc=0
    ttc_safe: float = 6.0  # seconds — TTC above this is "no concern"

    # Risk level thresholds
    amber_threshold: float = 0.3
    red_threshold: float = 0.6


DEFAULT_RISK_CONFIG = RiskConfig()


@dataclass
class AgentRisk:
    """Risk assessment for a single agent at a single timestep."""

    agent_id: int
    overlap: float = 0.0
    offroad: float = 0.0
    wrong_way: float = 0.0
    ttc: float = float("inf")
    lane_compliance: float = 1.0
    composite_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.GREEN


def compute_composite_risk(
    scenario: Scenario,
    t: int,
    config: RiskConfig | None = None,
) -> dict[int, AgentRisk]:
    """Compute composite risk score for all agents at timestep t.

    Returns dict mapping agent_id -> AgentRisk.
    """
    if config is None:
        config = DEFAULT_RISK_CONFIG

    overlaps = compute_overlap(scenario, t)
    offroads = compute_offroad(scenario, t)
    wrong_ways = compute_wrong_way(scenario, t)
    ttcs = compute_ttc(scenario, t)
    compliances = compute_lane_compliance(scenario, t)

    risks: dict[int, AgentRisk] = {}

    all_ids = set(overlaps) | set(offroads) | set(wrong_ways) | set(ttcs) | set(compliances)

    for agent_id in all_ids:
        overlap_score = overlaps.get(agent_id, 0.0)
        offroad_score = offroads.get(agent_id, 0.0)
        wrong_way_score = wrong_ways.get(agent_id, 0.0)

        raw_ttc = ttcs.get(agent_id, float("inf"))
        # Normalize TTC: 1.0 at ttc=0, 0.0 at ttc>=ttc_safe
        if raw_ttc >= config.ttc_safe:
            ttc_score = 0.0
        elif raw_ttc <= 0:
            ttc_score = 1.0
        else:
            ttc_score = 1.0 - raw_ttc / config.ttc_safe

        compliance = compliances.get(agent_id, 1.0)
        # Invert: low compliance = high risk
        compliance_risk = 1.0 - compliance

        composite = (
            config.weight_overlap * overlap_score
            + config.weight_offroad * offroad_score
            + config.weight_wrong_way * wrong_way_score
            + config.weight_ttc * ttc_score
            + config.weight_lane_compliance * compliance_risk
        )

        risk_level = classify_risk(composite, config)

        risks[agent_id] = AgentRisk(
            agent_id=agent_id,
            overlap=overlap_score,
            offroad=offroad_score,
            wrong_way=wrong_way_score,
            ttc=raw_ttc,
            lane_compliance=compliance,
            composite_score=composite,
            risk_level=risk_level,
        )

    return risks


def classify_risk(score: float, config: RiskConfig | None = None) -> RiskLevel:
    """Classify a composite score into a risk level."""
    if config is None:
        config = DEFAULT_RISK_CONFIG
    if score >= config.red_threshold:
        return RiskLevel.RED
    elif score >= config.amber_threshold:
        return RiskLevel.AMBER
    return RiskLevel.GREEN
