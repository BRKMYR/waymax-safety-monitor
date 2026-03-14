"""Framework-agnostic data classes for driving scenarios.

These mirror the structure of Waymax/WOMD data but use pure numpy,
so the renderer and metrics don't depend on JAX or TensorFlow.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


class AgentType(enum.IntEnum):
    VEHICLE = 0
    PEDESTRIAN = 1
    CYCLIST = 2


class SignalState(enum.IntEnum):
    UNKNOWN = 0
    GREEN = 1
    YELLOW = 2
    RED = 3


@dataclass
class AgentState:
    """State of a single agent at a single timestep."""

    x: float
    y: float
    heading: float  # radians
    vx: float
    vy: float
    length: float
    width: float
    valid: bool = True


@dataclass
class AgentTrajectory:
    """Full trajectory of a single agent across all timesteps."""

    agent_id: int
    agent_type: AgentType
    # Arrays of shape (num_timesteps,)
    x: NDArray[np.float32]
    y: NDArray[np.float32]
    heading: NDArray[np.float32]
    vx: NDArray[np.float32]
    vy: NDArray[np.float32]
    length: float
    width: float
    valid: NDArray[np.bool_]

    @property
    def num_timesteps(self) -> int:
        return len(self.x)

    def state_at(self, t: int) -> AgentState:
        return AgentState(
            x=float(self.x[t]),
            y=float(self.y[t]),
            heading=float(self.heading[t]),
            vx=float(self.vx[t]),
            vy=float(self.vy[t]),
            length=self.length,
            width=self.width,
            valid=bool(self.valid[t]),
        )

    @property
    def speed(self) -> NDArray[np.float32]:
        return np.sqrt(self.vx**2 + self.vy**2)


@dataclass
class LaneLine:
    """A lane center or boundary polyline."""

    points: NDArray[np.float32]  # (N, 2) xy coordinates
    lane_type: str = "center"  # "center", "left_boundary", "right_boundary"
    lane_id: int = 0


@dataclass
class RoadEdge:
    """A road boundary polyline."""

    points: NDArray[np.float32]  # (N, 2) xy coordinates
    edge_type: str = "boundary"  # "boundary", "curb"


@dataclass
class Crosswalk:
    """A crosswalk polygon."""

    polygon: NDArray[np.float32]  # (N, 2) xy coordinates


@dataclass
class TrafficSignal:
    """A traffic signal with state over time."""

    position: NDArray[np.float32]  # (2,) xy
    states: NDArray[np.int32]  # (num_timesteps,) SignalState values
    lane_id: int = 0


@dataclass
class RoadGraph:
    """Full road graph for a scenario."""

    lanes: list[LaneLine] = field(default_factory=list)
    road_edges: list[RoadEdge] = field(default_factory=list)
    crosswalks: list[Crosswalk] = field(default_factory=list)
    stop_signs: NDArray[np.float32] = field(
        default_factory=lambda: np.empty((0, 2), dtype=np.float32)
    )
    speed_bumps: NDArray[np.float32] = field(
        default_factory=lambda: np.empty((0, 2), dtype=np.float32)
    )


@dataclass
class Scenario:
    """A complete driving scenario."""

    scenario_id: str
    num_timesteps: int  # typically 91 (9.1s at 10Hz)
    timestep_duration: float  # typically 0.1s
    agents: list[AgentTrajectory]
    road_graph: RoadGraph
    traffic_signals: list[TrafficSignal] = field(default_factory=list)
    ego_agent_id: int = 0

    @property
    def duration(self) -> float:
        return self.num_timesteps * self.timestep_duration

    @property
    def ego(self) -> AgentTrajectory:
        for agent in self.agents:
            if agent.agent_id == self.ego_agent_id:
                return agent
        return self.agents[0]

    def agents_at(self, t: int) -> list[tuple[AgentTrajectory, AgentState]]:
        """Return all valid agents and their states at timestep t."""
        result = []
        for agent in self.agents:
            if 0 <= t < agent.num_timesteps and agent.valid[t]:
                result.append((agent, agent.state_at(t)))
        return result
