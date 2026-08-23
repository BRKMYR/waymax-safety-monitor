"""Agent rendering — vehicles, pedestrians, cyclists with risk halos."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pygame

from src.data.scenario import AgentState, AgentTrajectory, AgentType
from src.metrics.composite import AgentRisk, RiskLevel
from src.renderer.colors import Colors

if TYPE_CHECKING:
    from src.renderer.map_renderer import Viewport


def _safe_sysfont(name: str, size: int, bold: bool = False) -> pygame.font.Font:
    """SysFont with a Font(None, ...) fallback for minimal environments."""
    try:
        return pygame.font.SysFont(name, size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


class AgentRenderer:
    """Renders agents as oriented bounding boxes with heading indicators and risk halos."""

    def __init__(self, surface: pygame.Surface, viewport: "Viewport"):
        self.surface = surface
        self.viewport = viewport
        # Cached label font (avoid re-creating per label per frame).
        self._label_font = _safe_sysfont("monospace", 10)

    def draw_agent(
        self,
        agent: AgentTrajectory,
        state: AgentState,
        is_ego: bool = False,
        risk: AgentRisk | None = None,
        show_trail: bool = True,
        trail_timesteps: int = 10,
        current_timestep: int = 0,
    ) -> None:
        """Draw a single agent with bounding box, heading, and risk halo."""
        if not state.valid:
            return

        # Draw trajectory trail
        if show_trail:
            self._draw_trail(agent, current_timestep, trail_timesteps, is_ego)

        # Draw risk halo
        if risk is not None:
            self._draw_halo(state, risk)

        # Draw bounding box
        self._draw_bbox(agent, state, is_ego)

        # Draw heading arrow
        self._draw_heading(state, is_ego)

        # Draw agent ID label
        self._draw_label(agent, state, is_ego)

    def _draw_bbox(
        self,
        agent: AgentTrajectory,
        state: AgentState,
        is_ego: bool,
    ) -> None:
        """Draw oriented bounding box."""
        corners = self._get_screen_corners(state)

        if agent.agent_type == AgentType.PEDESTRIAN:
            # Draw pedestrians as circles
            center = self.viewport.world_to_screen(
                np.array([state.x, state.y], dtype=np.float32)
            )
            radius = max(3, int(state.width * self.viewport.scale / 2))
            pygame.draw.circle(self.surface, Colors.PEDESTRIAN, center, radius)
            pygame.draw.circle(self.surface, Colors.BG_DARK, center, radius, 1)
        elif agent.agent_type == AgentType.CYCLIST:
            # Draw cyclists as diamonds
            color = Colors.CYCLIST
            pygame.draw.polygon(self.surface, color, corners)
            pygame.draw.polygon(self.surface, Colors.BG_DARK, corners, 1)
        else:
            # Draw vehicles as rectangles
            color = Colors.EGO_VEHICLE if is_ego else Colors.OTHER_VEHICLE
            pygame.draw.polygon(self.surface, color, corners)
            pygame.draw.polygon(self.surface, Colors.BG_DARK, corners, 1)

    def _draw_heading(self, state: AgentState, is_ego: bool) -> None:
        """Draw heading arrow from center of agent."""
        center = np.array([state.x, state.y], dtype=np.float32)
        arrow_length = max(state.length * 0.6, 1.5)
        tip = center + arrow_length * np.array(
            [np.cos(state.heading), np.sin(state.heading)], dtype=np.float32
        )

        s_center = self.viewport.world_to_screen(center)
        s_tip = self.viewport.world_to_screen(tip)

        color = Colors.EGO_VEHICLE if is_ego else Colors.HEADING_ARROW
        pygame.draw.line(self.surface, color, s_center, s_tip, 2)

        # Arrow head
        angle = np.arctan2(s_tip[1] - s_center[1], s_tip[0] - s_center[0])
        head_len = 6
        for da in [2.5, -2.5]:
            hx = int(s_tip[0] - head_len * np.cos(angle + da))
            hy = int(s_tip[1] - head_len * np.sin(angle + da))
            pygame.draw.line(self.surface, color, s_tip, (hx, hy), 2)

    def _draw_halo(self, state: AgentState, risk: AgentRisk) -> None:
        """Draw semi-transparent risk halo around the agent."""
        center = self.viewport.world_to_screen(
            np.array([state.x, state.y], dtype=np.float32)
        )

        base_radius = max(
            state.length, state.width
        ) * self.viewport.scale / 2 + 4

        color_map = {
            RiskLevel.GREEN: Colors.HALO_GREEN,
            RiskLevel.AMBER: Colors.HALO_AMBER,
            RiskLevel.RED: Colors.HALO_RED,
        }
        color = color_map.get(risk.risk_level, Colors.HALO_GREEN)

        # Draw multiple rings with decreasing opacity for glow effect
        intensity = max(0.3, risk.composite_score)
        n_rings = 3
        for i in range(n_rings):
            radius = int(base_radius + i * 3)
            alpha = int(180 * intensity * (1 - i / n_rings))
            if alpha < 10:
                continue

            # Create a temporary surface for alpha blending
            temp = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(
                temp,
                (*color, alpha),
                (radius + 1, radius + 1),
                radius,
                max(1, 3 - i),
            )
            self.surface.blit(
                temp,
                (center[0] - radius - 1, center[1] - radius - 1),
            )

    def _draw_trail(
        self,
        agent: AgentTrajectory,
        current_t: int,
        trail_length: int,
        is_ego: bool,
    ) -> None:
        """Draw trajectory trail behind the agent.

        Renders all segments onto a single small alpha surface bounding
        the trail points, then blits it once (avoids a full-screen alpha
        allocation per segment).
        """
        start_t = max(0, current_t - trail_length)
        points: list[tuple[int, int]] = []

        for t in range(start_t, current_t + 1):
            if t < agent.num_timesteps and agent.valid[t]:
                pt = self.viewport.world_to_screen(
                    np.array([float(agent.x[t]), float(agent.y[t])], dtype=np.float32)
                )
                points.append((int(pt[0]), int(pt[1])))

        if len(points) < 2:
            return

        base_color = Colors.EGO_VEHICLE if is_ego else Colors.TEXT_MUTED

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        pad = 2
        min_x = min(xs) - pad
        min_y = min(ys) - pad
        max_x = max(xs) + pad
        max_y = max(ys) + pad
        w = max(1, max_x - min_x)
        h = max(1, max_y - min_y)

        temp = pygame.Surface((w, h), pygame.SRCALPHA)
        local = [(p[0] - min_x, p[1] - min_y) for p in points]

        n = len(local)
        for i in range(n - 1):
            alpha = int(60 * (i + 1) / n)
            pygame.draw.line(temp, (*base_color, alpha), local[i], local[i + 1], 1)
        self.surface.blit(temp, (min_x, min_y))

    def _draw_label(
        self,
        agent: AgentTrajectory,
        state: AgentState,
        is_ego: bool,
    ) -> None:
        """Draw agent ID label."""
        center = self.viewport.world_to_screen(
            np.array([state.x, state.y], dtype=np.float32)
        )

        label = "EGO" if is_ego else f"V{agent.agent_id}"
        if agent.agent_type == AgentType.PEDESTRIAN:
            label = f"P{agent.agent_id}"
        elif agent.agent_type == AgentType.CYCLIST:
            label = f"C{agent.agent_id}"

        text = self._label_font.render(label, True, Colors.TEXT_PRIMARY)
        text_rect = text.get_rect(center=(center[0], center[1] - 15))
        self.surface.blit(text, text_rect)

    def _get_screen_corners(self, state: AgentState) -> list[tuple[int, int]]:
        """Get screen coordinates of bounding box corners."""
        cos_h = np.cos(state.heading)
        sin_h = np.sin(state.heading)

        half_l = state.length / 2
        half_w = state.width / 2

        local = [
            (half_l, half_w),
            (half_l, -half_w),
            (-half_l, -half_w),
            (-half_l, half_w),
        ]

        corners = []
        for lx, ly in local:
            wx = state.x + lx * cos_h - ly * sin_h
            wy = state.y + lx * sin_h + ly * cos_h
            corners.append(
                self.viewport.world_to_screen(
                    np.array([wx, wy], dtype=np.float32)
                )
            )
        return corners
