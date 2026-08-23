"""Teleoperation trigger detection engine.

Evaluates safety metrics at each timestep and fires trigger events when
thresholds are exceeded. The engine is edge-triggered: a given (agent, kind)
combination fires once when the condition transitions from inactive to
active. While the condition persists the engine stays silent. An escalation
AMBER -> RED emits a new RED event. Once the condition has cleared for
``config.rearm_clear_steps`` consecutive steps the (agent, kind) key
re-arms and may fire again.

``evaluate`` must be called with strictly increasing ``timestep`` values,
otherwise the internal edge / dwell state is meaningless. The dashboard
guarantees this via ``DashboardState.precompute_all``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from src.data.scenario import AgentType, Scenario
from src.metrics.composite import AgentRisk
from src.metrics.safety import compute_accel, compute_vru_distance
from src.triggers.config import TriggerConfig


# The closed set of trigger kinds; see docs/ARCHITECTURE.md Section 5.4.
TRIGGER_KINDS: frozenset[str] = frozenset({
    "ttc",
    "overlap",
    "offroad",
    "wrong_way",
    "lane_compliance",
    "composite",
    "hard_brake",
    "stalled",
    "vru_proximity",
})


class TriggerSeverity(enum.IntEnum):
    AMBER = 1
    RED = 2


@dataclass
class TriggerEvent:
    """A teleoperation trigger event."""

    agent_id: int
    agent_type: AgentType
    timestep: int
    time_seconds: float
    severity: TriggerSeverity
    reason: str
    metric_value: float
    kind: str = "composite"

    @property
    def severity_name(self) -> str:
        return "RED" if self.severity == TriggerSeverity.RED else "AMBER"


class TriggerEngine:
    """Evaluates safety metrics and fires edge-triggered trigger events."""

    def __init__(self, config: TriggerConfig | None = None):
        self.config = config or TriggerConfig()
        self.events: list[TriggerEvent] = []
        # Per (agent_id, kind): current active severity.
        self._active: dict[tuple[int, str], TriggerSeverity] = {}
        # Per (agent_id, kind): consecutive clear-step counter.
        self._clear_count: dict[tuple[int, str], int] = {}
        # Per agent_id: consecutive sub-stall_speed steps.
        self._stall_dwell: dict[int, int] = {}

    def reset(self) -> None:
        self.events.clear()
        self._active.clear()
        self._clear_count.clear()
        self._stall_dwell.clear()

    def evaluate(
        self,
        scenario: Scenario,
        timestep: int,
        risks: dict[int, AgentRisk],
    ) -> list[TriggerEvent]:
        """Evaluate all agents at a timestep and return new trigger events.

        Must be called with strictly increasing ``timestep`` values.
        """
        new_events: list[TriggerEvent] = []
        time_s = timestep * scenario.timestep_duration

        # Build a per-agent metric snapshot including the added metrics.
        accels = compute_accel(scenario, timestep)
        vru_dists = compute_vru_distance(scenario, timestep)

        # Track (agent_id, kind) pairs that were tripped this step so we can
        # increment clear counters for all other keys afterwards.
        tripped_keys: set[tuple[int, str]] = set()

        # Index agents by id for type lookup.
        agent_lookup = {a.agent_id: a for a in scenario.agents}

        # Update stall dwell counters for every valid vehicle first.
        for agent, state in scenario.agents_at(timestep):
            if agent.agent_type != AgentType.VEHICLE:
                continue
            speed = (state.vx * state.vx + state.vy * state.vy) ** 0.5
            if speed < self.config.stall_speed:
                self._stall_dwell[agent.agent_id] = self._stall_dwell.get(agent.agent_id, 0) + 1
            else:
                self._stall_dwell[agent.agent_id] = 0

        for agent_id, risk in risks.items():
            agent = agent_lookup.get(agent_id)
            if agent is None:
                continue
            agent_type = agent.agent_type

            # ---- TTC ----
            ttc_sev: TriggerSeverity | None = None
            ttc_reason = ""
            if risk.ttc < float("inf"):
                if risk.ttc <= self.config.ttc_red:
                    ttc_sev = TriggerSeverity.RED
                    ttc_reason = f"TTC {risk.ttc:.1f}s — collision imminent"
                elif risk.ttc <= self.config.ttc_amber:
                    ttc_sev = TriggerSeverity.AMBER
                    ttc_reason = f"TTC {risk.ttc:.1f}s — closing distance"
            self._handle_condition(
                agent_id, agent_type, "ttc", ttc_sev, ttc_reason,
                risk.ttc, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Overlap ----
            ov_sev: TriggerSeverity | None = None
            ov_reason = ""
            if risk.overlap >= self.config.overlap_red:
                ov_sev = TriggerSeverity.RED
                ov_reason = f"Bounding box overlap {risk.overlap:.0%}"
            elif risk.overlap >= self.config.overlap_amber:
                ov_sev = TriggerSeverity.AMBER
                ov_reason = f"Near-miss overlap {risk.overlap:.0%}"
            self._handle_condition(
                agent_id, agent_type, "overlap", ov_sev, ov_reason,
                risk.overlap, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Off-road ----
            off_sev: TriggerSeverity | None = None
            off_reason = ""
            if risk.offroad >= self.config.offroad_red:
                off_sev = TriggerSeverity.RED
                off_reason = "Off-road excursion"
            elif risk.offroad >= self.config.offroad_amber:
                off_sev = TriggerSeverity.AMBER
                off_reason = "Approaching road boundary"
            self._handle_condition(
                agent_id, agent_type, "offroad", off_sev, off_reason,
                risk.offroad, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Wrong-way ----
            ww_sev: TriggerSeverity | None = None
            ww_reason = ""
            if risk.wrong_way >= self.config.wrong_way_red:
                ww_sev = TriggerSeverity.RED
                ww_reason = "Wrong-way heading"
            elif risk.wrong_way >= self.config.wrong_way_amber:
                ww_sev = TriggerSeverity.AMBER
                ww_reason = "Heading misalignment"
            self._handle_condition(
                agent_id, agent_type, "wrong_way", ww_sev, ww_reason,
                risk.wrong_way, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Lane compliance ----
            lc_sev: TriggerSeverity | None = None
            lc_reason = ""
            if risk.lane_compliance <= self.config.lane_compliance_red:
                lc_sev = TriggerSeverity.RED
                lc_reason = f"Lane compliance {risk.lane_compliance:.0%}"
            elif risk.lane_compliance <= self.config.lane_compliance_amber:
                lc_sev = TriggerSeverity.AMBER
                lc_reason = f"Lane compliance {risk.lane_compliance:.0%}"
            self._handle_condition(
                agent_id, agent_type, "lane_compliance", lc_sev, lc_reason,
                risk.lane_compliance, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Composite ----
            comp_sev: TriggerSeverity | None = None
            comp_reason = ""
            if risk.composite_score >= self.config.composite_red:
                comp_sev = TriggerSeverity.RED
                comp_reason = f"Composite risk {risk.composite_score:.0%}"
            elif risk.composite_score >= self.config.composite_amber:
                comp_sev = TriggerSeverity.AMBER
                comp_reason = f"Composite risk {risk.composite_score:.0%}"
            self._handle_condition(
                agent_id, agent_type, "composite", comp_sev, comp_reason,
                risk.composite_score, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Hard-brake (vehicles only) ----
            hb_sev: TriggerSeverity | None = None
            hb_reason = ""
            hb_value = accels.get(agent_id, 0.0)
            if agent_type == AgentType.VEHICLE and hb_value <= self.config.hard_brake_accel:
                hb_sev = TriggerSeverity.RED
                hb_reason = f"Hard brake {hb_value:.1f} m/s2"
            self._handle_condition(
                agent_id, agent_type, "hard_brake", hb_sev, hb_reason,
                hb_value, timestep, time_s, new_events, tripped_keys,
            )

            # ---- Stalled (vehicles only) ----
            st_sev: TriggerSeverity | None = None
            st_reason = ""
            st_value = float(self._stall_dwell.get(agent_id, 0))
            if (
                agent_type == AgentType.VEHICLE
                and self._stall_dwell.get(agent_id, 0) >= self.config.stall_dwell_steps
            ):
                is_ego = agent_id == scenario.ego_agent_id
                st_sev = TriggerSeverity.RED if is_ego else TriggerSeverity.AMBER
                st_reason = "Stalled in lane"
            self._handle_condition(
                agent_id, agent_type, "stalled", st_sev, st_reason,
                st_value, timestep, time_s, new_events, tripped_keys,
            )

            # ---- VRU proximity (vehicles only) ----
            vru_sev: TriggerSeverity | None = None
            vru_reason = ""
            vru_value = vru_dists.get(agent_id, float("inf"))
            if agent_type == AgentType.VEHICLE and vru_value < float("inf"):
                speed = (
                    (agent.vx[timestep] ** 2 + agent.vy[timestep] ** 2) ** 0.5
                    if timestep < agent.num_timesteps
                    else 0.0
                )
                if speed >= self.config.vru_min_vehicle_speed:
                    if vru_value <= self.config.vru_distance_red:
                        vru_sev = TriggerSeverity.RED
                        vru_reason = f"VRU within {vru_value:.1f} m"
                    elif vru_value <= self.config.vru_distance_amber:
                        vru_sev = TriggerSeverity.AMBER
                        vru_reason = f"VRU within {vru_value:.1f} m"
            self._handle_condition(
                agent_id, agent_type, "vru_proximity", vru_sev, vru_reason,
                vru_value, timestep, time_s, new_events, tripped_keys,
            )

        # Increment clear-step counters for every active key not tripped this
        # step; re-arm those that clear for long enough.
        stale_keys = []
        for key in list(self._active.keys()):
            if key in tripped_keys:
                self._clear_count[key] = 0
                continue
            self._clear_count[key] = self._clear_count.get(key, 0) + 1
            if self._clear_count[key] >= self.config.rearm_clear_steps:
                stale_keys.append(key)
        for key in stale_keys:
            self._active.pop(key, None)
            self._clear_count.pop(key, None)

        return new_events

    def _handle_condition(
        self,
        agent_id: int,
        agent_type: AgentType,
        kind: str,
        severity: TriggerSeverity | None,
        reason: str,
        metric_value: float,
        timestep: int,
        time_s: float,
        new_events: list[TriggerEvent],
        tripped_keys: set[tuple[int, str]],
    ) -> None:
        """Apply edge-triggered firing logic for one (agent, kind) condition."""
        key = (agent_id, kind)
        if severity is None:
            # Condition not tripped. Nothing to add to tripped_keys; the
            # outer loop will handle clear-count increment / re-arm.
            return

        tripped_keys.add(key)
        prev = self._active.get(key)
        if prev is None:
            # Edge inactive -> active: fire.
            self._active[key] = severity
            self._clear_count[key] = 0
            new_events.append(self._make_event(
                agent_id, agent_type, timestep, time_s, severity, reason,
                metric_value, kind,
            ))
        elif prev == TriggerSeverity.AMBER and severity == TriggerSeverity.RED:
            # Escalation AMBER -> RED: fire again.
            self._active[key] = severity
            self._clear_count[key] = 0
            new_events.append(self._make_event(
                agent_id, agent_type, timestep, time_s, severity, reason,
                metric_value, kind,
            ))
        else:
            # Same or de-escalating severity: stay silent, remain active.
            self._clear_count[key] = 0

    def _make_event(
        self,
        agent_id: int,
        agent_type: AgentType,
        timestep: int,
        time_s: float,
        severity: TriggerSeverity,
        reason: str,
        metric_value: float,
        kind: str,
    ) -> TriggerEvent:
        event = TriggerEvent(
            agent_id=agent_id,
            agent_type=agent_type,
            timestep=timestep,
            time_seconds=time_s,
            severity=severity,
            reason=reason,
            metric_value=float(metric_value),
            kind=kind,
        )
        self.events.append(event)
        return event

    @property
    def red_events(self) -> list[TriggerEvent]:
        return [e for e in self.events if e.severity == TriggerSeverity.RED]

    @property
    def amber_events(self) -> list[TriggerEvent]:
        return [e for e in self.events if e.severity == TriggerSeverity.AMBER]

    def events_at(self, timestep: int) -> list[TriggerEvent]:
        return [e for e in self.events if e.timestep == timestep]

    def events_up_to(self, timestep: int) -> list[TriggerEvent]:
        return [e for e in self.events if e.timestep <= timestep]
