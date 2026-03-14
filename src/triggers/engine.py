"""Teleoperation trigger detection engine.

Evaluates safety metrics at each timestep and fires trigger events
when thresholds are exceeded.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from src.data.scenario import AgentType, Scenario
from src.metrics.composite import AgentRisk
from src.triggers.config import TriggerConfig


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

    @property
    def severity_name(self) -> str:
        return "RED" if self.severity == TriggerSeverity.RED else "AMBER"


class TriggerEngine:
    """Evaluates safety metrics and fires trigger events."""

    def __init__(self, config: TriggerConfig | None = None):
        self.config = config or TriggerConfig()
        self.events: list[TriggerEvent] = []
        self._fired: set[tuple[int, int, str]] = set()  # (agent_id, timestep, reason)

    def reset(self) -> None:
        self.events.clear()
        self._fired.clear()

    def evaluate(
        self,
        scenario: Scenario,
        timestep: int,
        risks: dict[int, AgentRisk],
    ) -> list[TriggerEvent]:
        """Evaluate all agents at a timestep and return new trigger events."""
        new_events: list[TriggerEvent] = []
        time_s = timestep * scenario.timestep_duration

        for agent_id, risk in risks.items():
            agent = None
            for a in scenario.agents:
                if a.agent_id == agent_id:
                    agent = a
                    break
            if agent is None:
                continue

            agent_type = agent.agent_type

            # Check TTC
            if risk.ttc < float("inf"):
                if risk.ttc <= self.config.ttc_red:
                    new_events.extend(
                        self._fire(
                            agent_id, agent_type, timestep, time_s,
                            TriggerSeverity.RED,
                            f"TTC {risk.ttc:.1f}s — collision imminent",
                            risk.ttc,
                        )
                    )
                elif risk.ttc <= self.config.ttc_amber:
                    new_events.extend(
                        self._fire(
                            agent_id, agent_type, timestep, time_s,
                            TriggerSeverity.AMBER,
                            f"TTC {risk.ttc:.1f}s — closing distance",
                            risk.ttc,
                        )
                    )

            # Check overlap
            if risk.overlap >= self.config.overlap_red:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.RED,
                        f"Bounding box overlap {risk.overlap:.0%}",
                        risk.overlap,
                    )
                )
            elif risk.overlap >= self.config.overlap_amber:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.AMBER,
                        f"Near-miss overlap {risk.overlap:.0%}",
                        risk.overlap,
                    )
                )

            # Check off-road
            if risk.offroad >= self.config.offroad_red:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.RED,
                        "Off-road excursion",
                        risk.offroad,
                    )
                )
            elif risk.offroad >= self.config.offroad_amber:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.AMBER,
                        "Approaching road boundary",
                        risk.offroad,
                    )
                )

            # Check wrong-way
            if risk.wrong_way >= self.config.wrong_way_red:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.RED,
                        "Wrong-way heading",
                        risk.wrong_way,
                    )
                )
            elif risk.wrong_way >= self.config.wrong_way_amber:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.AMBER,
                        "Heading misalignment",
                        risk.wrong_way,
                    )
                )

            # Check lane compliance
            if risk.lane_compliance <= self.config.lane_compliance_red:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.RED,
                        f"Lane compliance {risk.lane_compliance:.0%}",
                        risk.lane_compliance,
                    )
                )
            elif risk.lane_compliance <= self.config.lane_compliance_amber:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.AMBER,
                        f"Lane compliance {risk.lane_compliance:.0%}",
                        risk.lane_compliance,
                    )
                )

            # Check composite score
            if risk.composite_score >= self.config.composite_red:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.RED,
                        f"Composite risk {risk.composite_score:.0%}",
                        risk.composite_score,
                    )
                )
            elif risk.composite_score >= self.config.composite_amber:
                new_events.extend(
                    self._fire(
                        agent_id, agent_type, timestep, time_s,
                        TriggerSeverity.AMBER,
                        f"Composite risk {risk.composite_score:.0%}",
                        risk.composite_score,
                    )
                )

        return new_events

    def _fire(
        self,
        agent_id: int,
        agent_type: AgentType,
        timestep: int,
        time_s: float,
        severity: TriggerSeverity,
        reason: str,
        metric_value: float,
    ) -> list[TriggerEvent]:
        """Fire a trigger event if not already fired for this agent/timestep/reason."""
        # Deduplicate by base reason (strip numeric details)
        base_reason = reason.split(" — ")[0].split(" ")[0]  # e.g., "TTC", "Bounding", etc.
        key = (agent_id, timestep, base_reason)
        if key in self._fired:
            return []
        self._fired.add(key)

        event = TriggerEvent(
            agent_id=agent_id,
            agent_type=agent_type,
            timestep=timestep,
            time_seconds=time_s,
            severity=severity,
            reason=reason,
            metric_value=metric_value,
        )
        self.events.append(event)
        return [event]

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
