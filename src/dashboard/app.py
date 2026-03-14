"""Main dashboard application — pygame event loop and layout."""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pygame

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import Scenario
from src.dashboard.state import DashboardState
from src.metrics.composite import RiskConfig
from src.renderer.agent_renderer import AgentRenderer
from src.renderer.colors import Colors
from src.renderer.map_renderer import MapRenderer, Viewport
from src.renderer.panel_renderer import PanelRenderer
from src.triggers.config import TriggerConfig


# Layout constants
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
RIGHT_PANEL_WIDTH = 300
PLAYBACK_BAR_HEIGHT = 44
MIN_VIEWER_WIDTH = 600

# Panel vertical layout (right side)
FLEET_PANEL_HEIGHT = 280
TRIGGER_PANEL_RATIO = 0.55  # of remaining height


class DashboardApp:
    """Main dashboard application."""

    def __init__(
        self,
        scenario: Scenario,
        risk_config: RiskConfig | None = None,
        trigger_config: TriggerConfig | None = None,
    ):
        pygame.init()
        pygame.display.set_caption("Waymax Safety Monitor")

        self.screen = pygame.display.set_mode(
            (WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE
        )
        self.clock = pygame.time.Clock()

        self.state = DashboardState(
            scenario=scenario,
            risk_config=risk_config or RiskConfig(),
            trigger_config=trigger_config or TriggerConfig(),
        )

        # Pre-compute all triggers for the timeline
        self.state.precompute_all()
        self.state.reset()

        # Layout rects (computed on resize)
        self._compute_layout()

        # Renderers
        self.viewport = Viewport(self.viewer_rect)
        self._fit_viewport()
        self.map_renderer = MapRenderer(self.screen, self.viewport)
        self.agent_renderer = AgentRenderer(self.screen, self.viewport)
        self.panel_renderer = PanelRenderer(self.screen)

        # Interaction state
        self._dragging = False
        self._drag_start = (0, 0)

    def _compute_layout(self) -> None:
        """Compute layout rectangles based on current window size."""
        w, h = self.screen.get_size()

        self.viewer_rect = pygame.Rect(
            0, 0,
            w - RIGHT_PANEL_WIDTH, h - PLAYBACK_BAR_HEIGHT,
        )
        self.playback_rect = pygame.Rect(
            0, h - PLAYBACK_BAR_HEIGHT,
            w, PLAYBACK_BAR_HEIGHT,
        )

        panel_x = w - RIGHT_PANEL_WIDTH
        panel_h = h - PLAYBACK_BAR_HEIGHT

        self.fleet_rect = pygame.Rect(
            panel_x, 0,
            RIGHT_PANEL_WIDTH, FLEET_PANEL_HEIGHT,
        )

        remaining = panel_h - FLEET_PANEL_HEIGHT
        trigger_h = int(remaining * TRIGGER_PANEL_RATIO)
        timeline_h = remaining - trigger_h

        self.trigger_rect = pygame.Rect(
            panel_x, FLEET_PANEL_HEIGHT,
            RIGHT_PANEL_WIDTH, trigger_h,
        )
        self.timeline_rect = pygame.Rect(
            panel_x, FLEET_PANEL_HEIGHT + trigger_h,
            RIGHT_PANEL_WIDTH, timeline_h,
        )

    def _fit_viewport(self) -> None:
        """Fit the viewport to show all agents and road geometry."""
        scenario = self.state.scenario

        all_x = []
        all_y = []

        for agent in scenario.agents:
            valid_mask = agent.valid
            if valid_mask.any():
                all_x.extend(agent.x[valid_mask].tolist())
                all_y.extend(agent.y[valid_mask].tolist())

        for lane in scenario.road_graph.lanes:
            all_x.extend(lane.points[:, 0].tolist())
            all_y.extend(lane.points[:, 1].tolist())

        if all_x and all_y:
            self.viewport.fit_to_bounds(
                min(all_x), max(all_x),
                min(all_y), max(all_y),
                margin=15.0,
            )

    def run(self) -> None:
        """Main event loop."""
        running = True
        last_time = time.time()

        while running:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(
                        (event.w, event.h), pygame.RESIZABLE,
                    )
                    self._compute_layout()
                    self.viewport.screen_rect = self.viewer_rect
                    self._fit_viewport()
                elif event.type == pygame.KEYDOWN:
                    running = self._handle_key(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self._handle_mouse_down(event)
                elif event.type == pygame.MOUSEBUTTONUP:
                    self._handle_mouse_up(event)
                elif event.type == pygame.MOUSEMOTION:
                    self._handle_mouse_motion(event)
                elif event.type == pygame.MOUSEWHEEL:
                    self._handle_scroll(event)

            self.state.update(dt)
            self._draw()
            self.clock.tick(60)

        pygame.quit()

    def _handle_key(self, event: pygame.event.Event) -> bool:
        """Handle keyboard input. Returns False to quit."""
        if event.key in (pygame.K_ESCAPE, pygame.K_q):
            return False
        elif event.key == pygame.K_SPACE:
            self.state.toggle_play()
        elif event.key == pygame.K_RIGHT:
            self.state.step_forward()
        elif event.key == pygame.K_LEFT:
            self.state.step_backward()
        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.state.change_speed(0.25)
        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.state.change_speed(-0.25)
        elif event.key == pygame.K_f:
            self._fit_viewport()
        elif event.key == pygame.K_r:
            self.state.precompute_all()
            self.state.reset()
        elif event.key == pygame.K_HOME:
            self.state.set_timestep(0)
        elif event.key == pygame.K_END:
            self.state.set_timestep(self.state.scenario.num_timesteps - 1)
        elif event.key == pygame.K_1:
            self._load_scenario("intersection_conflict")
        elif event.key == pygame.K_2:
            self._load_scenario("highway_merge")
        elif event.key == pygame.K_3:
            self._load_scenario("pedestrian_crossing")
        return True

    def _handle_mouse_down(self, event: pygame.event.Event) -> None:
        if event.button == 1:  # Left click
            # Check if clicking on playback bar for scrubbing
            if self.playback_rect.collidepoint(event.pos):
                self._scrub_playback(event.pos[0])
            elif self.viewer_rect.collidepoint(event.pos):
                self._dragging = True
                self._drag_start = event.pos
            # Check if clicking on timeline for timestep jump
            elif self.timeline_rect.collidepoint(event.pos):
                self._click_timeline(event.pos)

    def _handle_mouse_up(self, event: pygame.event.Event) -> None:
        if event.button == 1:
            self._dragging = False

    def _handle_mouse_motion(self, event: pygame.event.Event) -> None:
        if self._dragging:
            dx = event.pos[0] - self._drag_start[0]
            dy = event.pos[1] - self._drag_start[1]
            self.viewport.pan(dx, dy)
            self._drag_start = event.pos

        # Scrub while dragging on playback bar
        if event.buttons[0] and self.playback_rect.collidepoint(event.pos):
            self._scrub_playback(event.pos[0])

    def _handle_scroll(self, event: pygame.event.Event) -> None:
        mouse_pos = pygame.mouse.get_pos()

        if self.viewer_rect.collidepoint(mouse_pos):
            factor = 1.1 if event.y > 0 else 0.9
            self.viewport.zoom(factor)
        elif self.trigger_rect.collidepoint(mouse_pos):
            self.state.trigger_scroll = max(
                0, self.state.trigger_scroll - event.y * 20
            )
        elif self.timeline_rect.collidepoint(mouse_pos):
            self.state.timeline_scroll = max(
                0, self.state.timeline_scroll - event.y * 20
            )

    def _scrub_playback(self, mouse_x: int) -> None:
        """Scrub to a position in the playback bar."""
        bar_x = 42  # Approximate bar start (after play button)
        bar_w = self.playback_rect.width - 200
        if bar_w <= 0:
            return

        progress = (mouse_x - bar_x) / bar_w
        progress = max(0.0, min(1.0, progress))
        t = int(progress * (self.state.scenario.num_timesteps - 1))
        self.state.set_timestep(t)

    def _click_timeline(self, pos: tuple[int, int]) -> None:
        """Jump to timestep by clicking on the timeline bar."""
        bar_x = self.timeline_rect.x + 8
        bar_w = self.timeline_rect.width - 16
        bar_y = self.timeline_rect.y + 32

        if bar_y <= pos[1] <= bar_y + 16 and bar_w > 0:
            progress = (pos[0] - bar_x) / bar_w
            progress = max(0.0, min(1.0, progress))
            t = int(progress * (self.state.scenario.num_timesteps - 1))
            self.state.set_timestep(t)

    def _load_scenario(self, name: str) -> None:
        """Load a different demo scenario."""
        scenario = load_demo_scenario(name)
        self.state = DashboardState(
            scenario=scenario,
            risk_config=self.state.risk_config,
            trigger_config=self.state.trigger_config,
        )
        self.state.precompute_all()
        self.state.reset()
        self._fit_viewport()

    def _draw(self) -> None:
        """Draw the full dashboard."""
        self.screen.fill(Colors.BG_DARK)

        # Draw viewer area
        viewer_surface = self.screen.subsurface(self.viewer_rect)
        viewer_surface.fill(Colors.BG_DARK)

        # Draw map
        self.map_renderer.surface = self.screen
        self.map_renderer.draw(self.state.scenario, self.state.current_timestep)

        # Draw agents
        self.agent_renderer.surface = self.screen
        active_agents = self.state.scenario.agents_at(self.state.current_timestep)
        for agent, agent_state in active_agents:
            is_ego = agent.agent_id == self.state.scenario.ego_agent_id
            risk = self.state.current_risks.get(agent.agent_id)
            self.agent_renderer.draw_agent(
                agent, agent_state,
                is_ego=is_ego,
                risk=risk,
                current_timestep=self.state.current_timestep,
            )

        # Draw scenario title
        font = pygame.font.SysFont("monospace", 12)
        title = font.render(
            f"Scenario: {self.state.scenario.scenario_id}",
            True, Colors.TEXT_SECONDARY,
        )
        self.screen.blit(title, (8, 4))

        # Draw panels
        self.panel_renderer.draw_fleet_panel(
            self.fleet_rect,
            self.state.scenario,
            self.state.current_risks,
            self.state.events,
            self.state.current_timestep,
        )

        self.panel_renderer.draw_trigger_panel(
            self.trigger_rect,
            self.state.trigger_engine.events_up_to(self.state.current_timestep),
            self.state.trigger_scroll,
        )

        self.panel_renderer.draw_timeline(
            self.timeline_rect,
            self.state.events,
            self.state.current_timestep,
            self.state.scenario.num_timesteps,
            self.state.timeline_scroll,
        )

        self.panel_renderer.draw_playback_bar(
            self.playback_rect,
            self.state.current_timestep,
            self.state.scenario.num_timesteps,
            self.state.playing,
            self.state.playback_speed,
        )

        pygame.display.flip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Waymax Safety Monitor — real-time safety monitoring dashboard",
    )
    parser.add_argument(
        "--scenario", "-s",
        default="intersection_conflict",
        choices=["intersection_conflict", "highway_merge", "pedestrian_crossing"],
        help="Demo scenario to load (default: intersection_conflict)",
    )
    parser.add_argument(
        "--womd-path",
        default=None,
        help="Path to WOMD TFRecord file (requires waymax install)",
    )
    parser.add_argument(
        "--womd-index",
        type=int,
        default=0,
        help="Scenario index within WOMD file",
    )
    parser.add_argument(
        "--policy",
        default="default",
        choices=["default", "conservative", "permissive"],
        help="Trigger policy preset",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for demo scenarios",
    )
    args = parser.parse_args()

    # Load scenario
    if args.womd_path:
        from src.data.waymax_loader import load_womd_scenario
        scenario = load_womd_scenario(args.womd_path, args.womd_index)
    else:
        scenario = load_demo_scenario(args.scenario, seed=args.seed)

    # Configure trigger policy
    if args.policy == "conservative":
        trigger_config = TriggerConfig.conservative()
    elif args.policy == "permissive":
        trigger_config = TriggerConfig.permissive()
    else:
        trigger_config = TriggerConfig()

    app = DashboardApp(
        scenario=scenario,
        trigger_config=trigger_config,
    )
    app.run()


if __name__ == "__main__":
    main()
