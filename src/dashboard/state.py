"""Dashboard state management — playback controls and scenario state."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.data.scenario import Scenario
from src.metrics.composite import AgentRisk, RiskConfig, compute_composite_risk
from src.triggers.config import TriggerConfig
from src.triggers.engine import TriggerEngine, TriggerEvent


@dataclass
class DashboardState:
    """Central state for the dashboard application.

    The trigger engine is edge-triggered and requires strictly-increasing
    timesteps. To make scrubbing / random-access consistent, the timeline
    is precomputed once via ``precompute_all`` and cached in
    ``precomputed_events``. The interactive playback loop then only
    refreshes the per-timestep risk snapshot (``current_risks``); it does
    not re-run the engine (which would corrupt the dwell / edge state).
    """

    scenario: Scenario
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    trigger_config: TriggerConfig = field(default_factory=TriggerConfig)
    trigger_engine: TriggerEngine = field(init=False)

    # Playback state
    current_timestep: int = 0
    playing: bool = False
    playback_speed: float = 1.0
    _accumulator: float = 0.0

    # Cached per-timestep data
    current_risks: dict[int, AgentRisk] = field(default_factory=dict)
    precomputed_events: list[TriggerEvent] = field(default_factory=list)

    # Panel scroll state
    trigger_scroll: int = 0
    timeline_scroll: int = 0

    def __post_init__(self) -> None:
        self.trigger_engine = TriggerEngine(self.trigger_config)
        self._update_risks()

    def _update_risks(self) -> None:
        """Refresh only the risk snapshot; do NOT re-run the trigger engine."""
        self.current_risks = compute_composite_risk(
            self.scenario, self.current_timestep, self.risk_config
        )

    def set_timestep(self, t: int) -> None:
        t = max(0, min(t, self.scenario.num_timesteps - 1))
        if t != self.current_timestep:
            self.current_timestep = t
            self._update_risks()

    def step_forward(self) -> None:
        self.set_timestep(self.current_timestep + 1)

    def step_backward(self) -> None:
        self.set_timestep(self.current_timestep - 1)

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self._accumulator = 0.0

    def update(self, dt: float) -> None:
        """Update playback state. dt is real-world seconds since last frame."""
        if not self.playing:
            return

        self._accumulator += dt * self.playback_speed
        step_interval = self.scenario.timestep_duration

        while self._accumulator >= step_interval:
            self._accumulator -= step_interval
            if self.current_timestep < self.scenario.num_timesteps - 1:
                self.step_forward()
            else:
                self.playing = False
                break

    def reset(self) -> None:
        """Rewind playback to t=0. Does NOT clear the precomputed timeline."""
        self.playing = False
        self._accumulator = 0.0
        self.set_timestep(0)

    def change_speed(self, delta: float) -> None:
        self.playback_speed = max(0.1, min(5.0, self.playback_speed + delta))

    def precompute_all(self) -> None:
        """Pre-compute the entire trigger timeline once, in order.

        Runs the (edge-triggered) engine over t = 0..N-1 with strictly
        increasing timesteps, then caches the resulting events in
        ``precomputed_events``. Idempotent: multiple calls produce the
        same list.
        """
        self.trigger_engine.reset()
        for t in range(self.scenario.num_timesteps):
            risks = compute_composite_risk(self.scenario, t, self.risk_config)
            self.trigger_engine.evaluate(self.scenario, t, risks)
        self.precomputed_events = list(self.trigger_engine.events)
        # Refresh the current-timestep risk snapshot.
        self._update_risks()

    @property
    def events(self) -> list[TriggerEvent]:
        """The precomputed event timeline (empty until precompute_all runs)."""
        return self.precomputed_events

    def events_up_to(self, t: int) -> list[TriggerEvent]:
        """Filter the precomputed timeline to events with timestep <= t."""
        return [e for e in self.precomputed_events if e.timestep <= t]

    @property
    def current_time_seconds(self) -> float:
        return self.current_timestep * self.scenario.timestep_duration
