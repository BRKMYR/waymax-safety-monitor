"""Configurable trigger thresholds for teleoperation intervention."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TriggerConfig:
    """Thresholds that determine when a teleoperation trigger fires.

    Two policy presets are provided:
    - conservative: triggers early, higher operator workload, safer
    - permissive: triggers late, lower operator workload, more autonomy trust
    """

    # TTC thresholds (seconds)
    ttc_red: float = 2.0
    ttc_amber: float = 4.0

    # Overlap thresholds (0-1 ratio)
    overlap_red: float = 0.1
    overlap_amber: float = 0.01

    # Off-road thresholds (0-1 score)
    offroad_red: float = 0.5
    offroad_amber: float = 0.2

    # Wrong-way thresholds (0-1, fraction of pi)
    wrong_way_red: float = 0.6    # ~108 degrees
    wrong_way_amber: float = 0.35  # ~63 degrees

    # Lane compliance thresholds (1.0 = perfect, 0.0 = terrible)
    lane_compliance_red: float = 0.3
    lane_compliance_amber: float = 0.5

    # Composite risk score thresholds
    composite_red: float = 0.6
    composite_amber: float = 0.3

    @classmethod
    def conservative(cls) -> TriggerConfig:
        """Conservative policy: trigger early, safer."""
        return cls(
            ttc_red=3.0,
            ttc_amber=5.0,
            overlap_red=0.05,
            overlap_amber=0.005,
            offroad_red=0.3,
            offroad_amber=0.1,
            wrong_way_red=0.4,
            wrong_way_amber=0.25,
            lane_compliance_red=0.4,
            lane_compliance_amber=0.6,
            composite_red=0.4,
            composite_amber=0.2,
        )

    @classmethod
    def permissive(cls) -> TriggerConfig:
        """Permissive policy: trigger late, more autonomy trust."""
        return cls(
            ttc_red=1.5,
            ttc_amber=3.0,
            overlap_red=0.2,
            overlap_amber=0.05,
            offroad_red=0.7,
            offroad_amber=0.4,
            wrong_way_red=0.75,
            wrong_way_amber=0.5,
            lane_compliance_red=0.2,
            lane_compliance_amber=0.35,
            composite_red=0.7,
            composite_amber=0.4,
        )
