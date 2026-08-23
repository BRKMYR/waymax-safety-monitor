"""Main dashboard application — pygame event loop, layout, headless mode."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

import pygame

from src.data.demo_loader import load_demo_scenario
from src.data.scenario import Scenario
from src.dashboard.state import DashboardState
from src.metrics.composite import RiskConfig
from src.renderer.agent_renderer import AgentRenderer
from src.renderer.colors import Colors
from src.renderer.map_renderer import MapRenderer, Viewport
from src.renderer.panel_renderer import PanelRenderer, playback_bar_rect
from src.triggers.config import TriggerConfig
from src.triggers.engine import TriggerEvent


# Layout constants
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
RIGHT_PANEL_WIDTH = 300
PLAYBACK_BAR_HEIGHT = 44
MIN_VIEWER_WIDTH = 600

# Panel vertical layout (right side)
FLEET_PANEL_HEIGHT = 280
TRIGGER_PANEL_RATIO = 0.55  # of remaining height

SCENARIO_CHOICES = (
    "intersection_conflict",
    "highway_merge",
    "pedestrian_crossing",
    "hard_brake",
    "stalled_ego",
)

_RISK_CONFIG_FIELDS = {f.name for f in dataclasses.fields(RiskConfig)}
_TRIGGER_CONFIG_FIELDS = {f.name for f in dataclasses.fields(TriggerConfig)}
_ALLOWED_CONFIG_KEYS = {
    "scenario", "seed", "trigger_policy", "risk_config", "trigger_overrides",
}


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

        # Precompute the full trigger timeline once. The (edge-triggered)
        # engine requires strictly-increasing timesteps; DashboardState.reset()
        # deliberately does NOT wipe the precomputed timeline.
        self.state.precompute_all()

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

        all_x: list[float] = []
        all_y: list[float] = []

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
        """Main interactive event loop."""
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
            pygame.display.flip()
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
        elif event.key == pygame.K_4:
            self._load_scenario("hard_brake")
        elif event.key == pygame.K_5:
            self._load_scenario("stalled_ego")
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
        bar = playback_bar_rect(self.playback_rect)
        if bar.width <= 0:
            return

        progress = (mouse_x - bar.x) / bar.width
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
        self._fit_viewport()

    def _draw(self) -> None:
        """Draw the full dashboard onto self.screen."""
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
        title = self.panel_renderer.font_body.render(
            f"Scenario: {self.state.scenario.scenario_id}",
            True, Colors.TEXT_SECONDARY,
        )
        self.screen.blit(title, (8, 4))

        dt = self.state.scenario.timestep_duration

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
            self.state.events_up_to(self.state.current_timestep),
            self.state.trigger_scroll,
        )

        self.panel_renderer.draw_timeline(
            self.timeline_rect,
            self.state.events,
            self.state.current_timestep,
            self.state.scenario.num_timesteps,
            self.state.timeline_scroll,
            timestep_duration=dt,
        )

        self.panel_renderer.draw_playback_bar(
            self.playback_rect,
            self.state.current_timestep,
            self.state.scenario.num_timesteps,
            self.state.playing,
            self.state.playback_speed,
            timestep_duration=dt,
        )


def _load_run_config(path: str | Path) -> tuple[str, int, TriggerConfig, RiskConfig]:
    """Load a scenarios/*.json run config.

    Returns ``(scenario_name, seed, trigger_config, risk_config)``. Missing
    ``trigger_policy`` or ``risk_config`` fall back to defaults. Unknown top-
    level keys raise ``ValueError`` naming the offending key.
    """
    with open(path, "r") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Config {path} must be a JSON object, got {type(data).__name__}")

    unknown = set(data.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"Unknown top-level key(s) in {path}: {sorted(unknown)!r}. "
            f"Allowed: {sorted(_ALLOWED_CONFIG_KEYS)!r}"
        )

    scenario_name = data.get("scenario", "intersection_conflict")
    seed = int(data.get("seed", 42))

    policy = data.get("trigger_policy", "default")
    if policy == "conservative":
        trigger_config = TriggerConfig.conservative()
    elif policy == "permissive":
        trigger_config = TriggerConfig.permissive()
    elif policy == "default":
        trigger_config = TriggerConfig()
    else:
        raise ValueError(
            f"Unknown trigger_policy '{policy}' in {path}. "
            "Allowed: 'default', 'conservative', 'permissive'."
        )

    overrides = data.get("trigger_overrides", {})
    if overrides:
        if not isinstance(overrides, dict):
            raise ValueError(f"trigger_overrides in {path} must be an object")
        bad = set(overrides.keys()) - _TRIGGER_CONFIG_FIELDS
        if bad:
            raise ValueError(
                f"Unknown trigger_overrides key(s) in {path}: {sorted(bad)!r}"
            )
        trigger_config = dataclasses.replace(trigger_config, **overrides)

    risk_raw = data.get("risk_config", {})
    if not isinstance(risk_raw, dict):
        raise ValueError(f"risk_config in {path} must be an object")
    bad = set(risk_raw.keys()) - _RISK_CONFIG_FIELDS
    if bad:
        raise ValueError(
            f"Unknown risk_config key(s) in {path}: {sorted(bad)!r}"
        )
    risk_config = RiskConfig(**risk_raw)

    return scenario_name, seed, trigger_config, risk_config


def _event_to_json(event: TriggerEvent) -> dict:
    """Serialize a TriggerEvent to the JSON shape documented in Section 5.4."""
    return {
        "agent_id": int(event.agent_id),
        "agent_type": event.agent_type.name,
        "timestep": int(event.timestep),
        "time_seconds": float(event.time_seconds),
        "severity": event.severity_name,
        "kind": str(event.kind),
        "reason": str(event.reason),
        "metric_value": float(event.metric_value),
    }


def _write_events_json(events: list[TriggerEvent], out_path: Path) -> None:
    """Write events to JSON, sorted by (timestep, agent_id, kind)."""
    sorted_events = sorted(
        events,
        key=lambda e: (e.timestep, e.agent_id, e.kind),
    )
    payload = [_event_to_json(e) for e in sorted_events]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def run_headless(
    app: DashboardApp,
    frames_out: Path,
    events_out: Path,
    frame_stride: int = 1,
) -> tuple[int, int]:
    """Run the dashboard headless: dump frames + events.json.

    Returns ``(num_frames_written, num_events)``.
    """
    frames_out = Path(frames_out)
    frames_out.mkdir(parents=True, exist_ok=True)

    n_frames = 0
    for t in range(0, app.state.scenario.num_timesteps, max(1, frame_stride)):
        app.state.set_timestep(t)
        app._draw()
        frame_path = frames_out / f"frame_{t:03d}.png"
        pygame.image.save(app.screen, str(frame_path))
        n_frames += 1

    _write_events_json(app.state.events, Path(events_out))
    return n_frames, len(app.state.events)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Waymax Safety Monitor: real-time safety monitoring dashboard",
    )
    parser.add_argument(
        "--scenario", "-s",
        default="intersection_conflict",
        choices=list(SCENARIO_CHOICES),
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
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a run-config JSON (scenarios/*.json). CLI flags win over config values.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Headless mode: dump PNG frames and events.json, then exit.",
    )
    parser.add_argument(
        "--frames-out",
        default=None,
        help="Directory to write PNG frames (default: docs/screenshots/<scenario_id>/).",
    )
    parser.add_argument(
        "--events-out",
        default=None,
        help="Path to write events.json (default: <frames-out>/events.json).",
    )
    parser.add_argument(
        "--frame-stride",
        type=int,
        default=1,
        help="Emit every Nth frame (default: 1).",
    )
    args = parser.parse_args()

    # Ensure SDL uses the dummy driver in headless mode BEFORE pygame.init.
    if args.headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    # Resolve config file first, then let CLI flags override.
    cfg_scenario: str | None = None
    cfg_seed: int | None = None
    cfg_trigger: TriggerConfig | None = None
    cfg_risk: RiskConfig | None = None
    if args.config:
        try:
            cfg_scenario, cfg_seed, cfg_trigger, cfg_risk = _load_run_config(args.config)
        except ValueError as e:
            print(f"Config error: {e}", file=sys.stderr)
            sys.exit(2)

    # Scenario selection: explicit CLI value wins if it differs from default.
    # We treat the arg as "user-supplied" if it deviates from the default
    # or the parser sees it on argv.
    explicit_scenario = "--scenario" in sys.argv or "-s" in sys.argv
    scenario_name = args.scenario if (explicit_scenario or cfg_scenario is None) else cfg_scenario

    explicit_seed = "--seed" in sys.argv
    seed = args.seed if (explicit_seed or cfg_seed is None) else cfg_seed

    explicit_policy = "--policy" in sys.argv
    if explicit_policy or cfg_trigger is None:
        if args.policy == "conservative":
            trigger_config = TriggerConfig.conservative()
        elif args.policy == "permissive":
            trigger_config = TriggerConfig.permissive()
        else:
            trigger_config = TriggerConfig()
    else:
        trigger_config = cfg_trigger

    risk_config = cfg_risk if cfg_risk is not None else RiskConfig()

    # Load scenario
    if args.womd_path:
        from src.data.waymax_loader import load_womd_scenario
        scenario = load_womd_scenario(args.womd_path, args.womd_index)
    else:
        scenario = load_demo_scenario(scenario_name, seed=seed)

    app = DashboardApp(
        scenario=scenario,
        risk_config=risk_config,
        trigger_config=trigger_config,
    )

    if args.headless:
        frames_out = Path(args.frames_out) if args.frames_out else Path("docs/screenshots") / scenario.scenario_id
        events_out = Path(args.events_out) if args.events_out else frames_out / "events.json"
        n_frames, n_events = run_headless(app, frames_out, events_out, args.frame_stride)
        red = sum(1 for e in app.state.events if e.severity_name == "RED")
        print(f"{n_frames} frames, {n_events} events ({red} RED) -> {frames_out}")
        pygame.quit()
        sys.exit(0)

    app.run()


if __name__ == "__main__":
    main()
