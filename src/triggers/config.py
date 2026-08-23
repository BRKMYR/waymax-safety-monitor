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

    # Hard-brake threshold (longitudinal accel, m/s^2). Accel <= this fires RED.
    hard_brake_accel: float = -4.0

    # Stalled thresholds
    stall_speed: float = 0.3          # m/s
    stall_dwell_steps: int = 20       # timesteps of continuous sub-stall_speed

    # VRU (pedestrian / cyclist) proximity thresholds (meters)
    vru_distance_red: float = 3.0
    vru_distance_amber: float = 6.0
    vru_min_vehicle_speed: float = 1.0  # only evaluate for vehicles moving at least this fast

    # Edge-triggered re-arm: consecutive clear timesteps required before the
    # same (agent, kind) may re-fire.
    rearm_clear_steps: int = 10

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
            hard_brake_accel=-3.0,
            stall_speed=0.5,
            stall_dwell_steps=15,
            vru_distance_red=4.0,
            vru_distance_amber=8.0,
            vru_min_vehicle_speed=0.5,
            rearm_clear_steps=5,
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
            hard_brake_accel=-6.0,
            stall_speed=0.2,
            stall_dwell_steps=30,
            vru_distance_red=2.0,
            vru_distance_amber=4.0,
            vru_min_vehicle_speed=2.0,
            rearm_clear_steps=8,
        )
