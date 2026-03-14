"""Road graph and map rendering for the top-down scenario viewer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pygame

from src.data.scenario import RoadGraph, SignalState
from src.renderer.colors import Colors

if TYPE_CHECKING:
    from src.data.scenario import Scenario


class MapRenderer:
    """Renders the road graph as a 2D tactical map."""

    def __init__(self, surface: pygame.Surface, viewport: "Viewport"):
        self.surface = surface
        self.viewport = viewport

    def draw(self, scenario: "Scenario", timestep: int = 0) -> None:
        """Draw the full road graph."""
        road_graph = scenario.road_graph

        self._draw_road_edges(road_graph)
        self._draw_crosswalks(road_graph)
        self._draw_lanes(road_graph)
        self._draw_stop_signs(road_graph)
        self._draw_speed_bumps(road_graph)
        self._draw_traffic_signals(scenario, timestep)

    def _draw_lanes(self, road_graph: RoadGraph) -> None:
        for lane in road_graph.lanes:
            if len(lane.points) < 2:
                continue

            screen_points = [self.viewport.world_to_screen(p) for p in lane.points]

            if lane.lane_type == "center":
                # Dashed center line
                for i in range(0, len(screen_points) - 1, 2):
                    if i + 1 < len(screen_points):
                        pygame.draw.line(
                            self.surface, Colors.LANE_CENTER,
                            screen_points[i], screen_points[i + 1], 1,
                        )
            else:
                # Solid boundary line
                pygame.draw.lines(
                    self.surface, Colors.LANE_BOUNDARY, False, screen_points, 1,
                )

    def _draw_road_edges(self, road_graph: RoadGraph) -> None:
        for edge in road_graph.road_edges:
            if len(edge.points) < 2:
                continue
            screen_points = [self.viewport.world_to_screen(p) for p in edge.points]
            pygame.draw.lines(
                self.surface, Colors.ROAD_EDGE, False, screen_points, 2,
            )

    def _draw_crosswalks(self, road_graph: RoadGraph) -> None:
        for crosswalk in road_graph.crosswalks:
            if len(crosswalk.polygon) < 3:
                continue
            screen_points = [
                self.viewport.world_to_screen(p) for p in crosswalk.polygon
            ]
            # Draw striped crosswalk
            pygame.draw.polygon(self.surface, Colors.CROSSWALK, screen_points, 1)

            # Draw internal stripes
            if len(crosswalk.polygon) >= 4:
                self._draw_crosswalk_stripes(crosswalk.polygon)

    def _draw_crosswalk_stripes(self, polygon: np.ndarray) -> None:
        """Draw zebra stripes inside a crosswalk polygon."""
        p0, p1, p2, p3 = polygon[:4]
        n_stripes = 6

        for i in range(n_stripes):
            t = (i + 0.5) / n_stripes
            start = p0 + t * (p3 - p0)
            end = p1 + t * (p2 - p1)
            s_start = self.viewport.world_to_screen(start)
            s_end = self.viewport.world_to_screen(end)
            pygame.draw.line(self.surface, Colors.CROSSWALK, s_start, s_end, 1)

    def _draw_stop_signs(self, road_graph: RoadGraph) -> None:
        for pos in road_graph.stop_signs:
            screen_pos = self.viewport.world_to_screen(pos)
            pygame.draw.circle(self.surface, Colors.STOP_SIGN, screen_pos, 4)
            pygame.draw.circle(self.surface, Colors.STOP_SIGN, screen_pos, 6, 1)

    def _draw_speed_bumps(self, road_graph: RoadGraph) -> None:
        for pos in road_graph.speed_bumps:
            screen_pos = self.viewport.world_to_screen(pos)
            pygame.draw.circle(self.surface, Colors.SPEED_BUMP, screen_pos, 3)

    def _draw_traffic_signals(self, scenario: "Scenario", timestep: int) -> None:
        for signal in scenario.traffic_signals:
            screen_pos = self.viewport.world_to_screen(signal.position)

            state = SignalState(int(signal.states[min(timestep, len(signal.states) - 1)]))
            color = {
                SignalState.GREEN: Colors.SIGNAL_GREEN,
                SignalState.YELLOW: Colors.SIGNAL_YELLOW,
                SignalState.RED: Colors.SIGNAL_RED,
            }.get(state, Colors.SIGNAL_UNKNOWN)

            pygame.draw.circle(self.surface, color, screen_pos, 5)
            pygame.draw.circle(self.surface, Colors.BG_DARK, screen_pos, 5, 1)


class Viewport:
    """Transforms between world coordinates and screen coordinates."""

    def __init__(
        self,
        screen_rect: pygame.Rect,
        center: tuple[float, float] = (0.0, 0.0),
        scale: float = 5.0,  # pixels per meter
    ):
        self.screen_rect = screen_rect
        self.center_x, self.center_y = center
        self.scale = scale

    def world_to_screen(
        self, point: np.ndarray | tuple[float, float]
    ) -> tuple[int, int]:
        if isinstance(point, np.ndarray):
            wx, wy = float(point[0]), float(point[1])
        else:
            wx, wy = point

        sx = int(self.screen_rect.centerx + (wx - self.center_x) * self.scale)
        # Flip Y axis (world Y-up -> screen Y-down)
        sy = int(self.screen_rect.centery - (wy - self.center_y) * self.scale)
        return (sx, sy)

    def screen_to_world(self, sx: int, sy: int) -> tuple[float, float]:
        wx = (sx - self.screen_rect.centerx) / self.scale + self.center_x
        wy = -(sy - self.screen_rect.centery) / self.scale + self.center_y
        return (wx, wy)

    def zoom(self, factor: float) -> None:
        self.scale = max(1.0, min(50.0, self.scale * factor))

    def pan(self, dx_screen: int, dy_screen: int) -> None:
        self.center_x -= dx_screen / self.scale
        self.center_y += dy_screen / self.scale

    def fit_to_bounds(
        self,
        min_x: float, max_x: float,
        min_y: float, max_y: float,
        margin: float = 10.0,
    ) -> None:
        """Fit the viewport to show the given world bounds."""
        self.center_x = (min_x + max_x) / 2
        self.center_y = (min_y + max_y) / 2

        world_w = max_x - min_x + 2 * margin
        world_h = max_y - min_y + 2 * margin

        if world_w > 0 and world_h > 0:
            scale_x = self.screen_rect.width / world_w
            scale_y = self.screen_rect.height / world_h
            self.scale = min(scale_x, scale_y)
