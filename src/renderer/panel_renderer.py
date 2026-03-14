"""Side panel rendering — trigger panel, incident timeline, fleet stats."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.data.scenario import AgentType, Scenario
from src.metrics.composite import AgentRisk, RiskLevel
from src.renderer.colors import Colors
from src.triggers.engine import TriggerEvent, TriggerSeverity

if TYPE_CHECKING:
    pass


class PanelRenderer:
    """Renders dashboard side panels."""

    def __init__(self, surface: pygame.Surface):
        self.surface = surface
        self._font_title: pygame.font.Font | None = None
        self._font_body: pygame.font.Font | None = None
        self._font_small: pygame.font.Font | None = None

    @property
    def font_title(self) -> pygame.font.Font:
        if self._font_title is None:
            self._font_title = pygame.font.SysFont("monospace", 14, bold=True)
        return self._font_title

    @property
    def font_body(self) -> pygame.font.Font:
        if self._font_body is None:
            self._font_body = pygame.font.SysFont("monospace", 11)
        return self._font_body

    @property
    def font_small(self) -> pygame.font.Font:
        if self._font_small is None:
            self._font_small = pygame.font.SysFont("monospace", 10)
        return self._font_small

    def draw_trigger_panel(
        self,
        rect: pygame.Rect,
        events: list[TriggerEvent],
        scroll_offset: int = 0,
    ) -> None:
        """Draw the teleoperation trigger panel."""
        # Panel background
        pygame.draw.rect(self.surface, Colors.BG_PANEL, rect)
        pygame.draw.rect(self.surface, Colors.DIVIDER, rect, 1)

        # Header
        header_rect = pygame.Rect(rect.x, rect.y, rect.width, 28)
        pygame.draw.rect(self.surface, Colors.BG_PANEL_HEADER, header_rect)
        title = self.font_title.render("TELEOP TRIGGERS", True, Colors.TEXT_PRIMARY)
        self.surface.blit(title, (rect.x + 8, rect.y + 6))

        # Count badge
        red_count = sum(1 for e in events if e.severity == TriggerSeverity.RED)
        amber_count = sum(1 for e in events if e.severity == TriggerSeverity.AMBER)
        if red_count > 0:
            badge = self.font_small.render(f" {red_count} ", True, (255, 255, 255))
            badge_rect = badge.get_rect(right=rect.right - 8, centery=rect.y + 14)
            pygame.draw.rect(self.surface, Colors.BADGE_RED, badge_rect.inflate(4, 2))
            self.surface.blit(badge, badge_rect)

        # Events list
        y = rect.y + 32 - scroll_offset
        clip = self.surface.get_clip()
        self.surface.set_clip(
            pygame.Rect(rect.x, rect.y + 30, rect.width, rect.height - 30)
        )

        for event in reversed(events[-50:]):  # Show most recent first
            if y > rect.bottom:
                break
            if y + 40 >= rect.y + 30:
                self._draw_trigger_entry(rect.x + 4, y, rect.width - 8, event)
            y += 42

        self.surface.set_clip(clip)

    def _draw_trigger_entry(
        self, x: int, y: int, width: int, event: TriggerEvent
    ) -> None:
        """Draw a single trigger event entry."""
        # Severity indicator
        sev_color = Colors.BADGE_RED if event.severity == TriggerSeverity.RED else Colors.BADGE_AMBER
        pygame.draw.rect(self.surface, sev_color, (x, y, 3, 38))

        # Agent ID
        agent_label = self._agent_label(event.agent_id, event.agent_type)
        text = self.font_body.render(agent_label, True, Colors.TEXT_PRIMARY)
        self.surface.blit(text, (x + 8, y + 2))

        # Timestamp
        ts = self.font_small.render(f"{event.time_seconds:.1f}s", True, Colors.TEXT_SECONDARY)
        self.surface.blit(ts, (x + width - ts.get_width() - 4, y + 2))

        # Reason
        reason = self.font_small.render(event.reason[:40], True, Colors.TEXT_SECONDARY)
        self.surface.blit(reason, (x + 8, y + 18))

        # Divider
        pygame.draw.line(
            self.surface, Colors.DIVIDER,
            (x, y + 40), (x + width, y + 40), 1,
        )

    def draw_timeline(
        self,
        rect: pygame.Rect,
        events: list[TriggerEvent],
        current_timestep: int,
        total_timesteps: int,
        scroll_offset: int = 0,
    ) -> None:
        """Draw the incident timeline panel."""
        pygame.draw.rect(self.surface, Colors.BG_PANEL, rect)
        pygame.draw.rect(self.surface, Colors.DIVIDER, rect, 1)

        # Header
        header_rect = pygame.Rect(rect.x, rect.y, rect.width, 28)
        pygame.draw.rect(self.surface, Colors.BG_PANEL_HEADER, header_rect)
        title = self.font_title.render("INCIDENT TIMELINE", True, Colors.TEXT_PRIMARY)
        self.surface.blit(title, (rect.x + 8, rect.y + 6))

        # Timeline bar
        bar_y = rect.y + 32
        bar_rect = pygame.Rect(rect.x + 8, bar_y, rect.width - 16, 16)
        pygame.draw.rect(self.surface, Colors.TIMELINE_BG, bar_rect)

        # Progress marker
        if total_timesteps > 0:
            progress = current_timestep / max(1, total_timesteps - 1)
            marker_x = int(bar_rect.x + progress * bar_rect.width)
            pygame.draw.line(
                self.surface, Colors.TIMELINE_MARKER,
                (marker_x, bar_y), (marker_x, bar_y + 16), 2,
            )

            # Event markers on the timeline bar
            for event in events:
                ep = event.timestep / max(1, total_timesteps - 1)
                ex = int(bar_rect.x + ep * bar_rect.width)
                color = Colors.BADGE_RED if event.severity == TriggerSeverity.RED else Colors.BADGE_AMBER
                pygame.draw.line(
                    self.surface, color,
                    (ex, bar_y + 12), (ex, bar_y + 16), 2,
                )

        # Time labels
        t_start = self.font_small.render("0.0s", True, Colors.TEXT_MUTED)
        self.surface.blit(t_start, (bar_rect.x, bar_y + 18))
        t_current = self.font_small.render(
            f"{current_timestep * 0.1:.1f}s", True, Colors.TEXT_PRIMARY
        )
        self.surface.blit(
            t_current, (bar_rect.centerx - t_current.get_width() // 2, bar_y + 18)
        )
        t_end = self.font_small.render(
            f"{(total_timesteps - 1) * 0.1:.1f}s", True, Colors.TEXT_MUTED
        )
        self.surface.blit(t_end, (bar_rect.right - t_end.get_width(), bar_y + 18))

        # Event log entries below timeline
        log_y = bar_y + 38
        clip = self.surface.get_clip()
        self.surface.set_clip(
            pygame.Rect(rect.x, log_y, rect.width, rect.bottom - log_y)
        )

        y = log_y - scroll_offset
        # Filter events up to current timestep, sorted by time
        visible_events = sorted(
            [e for e in events if e.timestep <= current_timestep],
            key=lambda e: e.timestep,
            reverse=True,
        )

        for event in visible_events[:30]:
            if y > rect.bottom:
                break
            if y + 18 >= log_y:
                sev_color = (
                    Colors.BADGE_RED
                    if event.severity == TriggerSeverity.RED
                    else Colors.BADGE_AMBER
                )
                pygame.draw.rect(self.surface, sev_color, (rect.x + 8, y + 2, 6, 6))

                label = f"{event.time_seconds:5.1f}s  {self._agent_label(event.agent_id, event.agent_type):4s}  {event.reason[:30]}"
                text = self.font_small.render(label, True, Colors.TEXT_SECONDARY)
                self.surface.blit(text, (rect.x + 20, y))
            y += 16

        self.surface.set_clip(clip)

    def draw_fleet_panel(
        self,
        rect: pygame.Rect,
        scenario: Scenario,
        risks: dict[int, AgentRisk],
        events: list[TriggerEvent],
        current_timestep: int,
    ) -> None:
        """Draw the fleet aggregate statistics panel."""
        pygame.draw.rect(self.surface, Colors.BG_PANEL, rect)
        pygame.draw.rect(self.surface, Colors.DIVIDER, rect, 1)

        # Header
        header_rect = pygame.Rect(rect.x, rect.y, rect.width, 28)
        pygame.draw.rect(self.surface, Colors.BG_PANEL_HEADER, header_rect)
        title = self.font_title.render("FLEET STATUS", True, Colors.TEXT_PRIMARY)
        self.surface.blit(title, (rect.x + 8, rect.y + 6))

        y = rect.y + 34

        # Fleet safety score
        if risks:
            scores = [r.composite_score for r in risks.values()]
            fleet_score = 1.0 - (sum(scores) / len(scores))
            score_color = Colors.HALO_GREEN
            if fleet_score < 0.5:
                score_color = Colors.HALO_RED
            elif fleet_score < 0.75:
                score_color = Colors.HALO_AMBER

            label = self.font_body.render("Fleet Safety Score", True, Colors.TEXT_SECONDARY)
            self.surface.blit(label, (rect.x + 8, y))
            value = self.font_title.render(f"{fleet_score:.0%}", True, score_color)
            self.surface.blit(value, (rect.right - value.get_width() - 8, y))
            y += 22

        # Divider
        pygame.draw.line(
            self.surface, Colors.DIVIDER,
            (rect.x + 8, y), (rect.right - 8, y), 1,
        )
        y += 6

        # Agent counts
        vehicles = sum(1 for a in scenario.agents if a.agent_type == AgentType.VEHICLE)
        pedestrians = sum(1 for a in scenario.agents if a.agent_type == AgentType.PEDESTRIAN)
        cyclists = sum(1 for a in scenario.agents if a.agent_type == AgentType.CYCLIST)

        for label, count, color in [
            ("Vehicles", vehicles, Colors.OTHER_VEHICLE),
            ("Pedestrians", pedestrians, Colors.PEDESTRIAN),
            ("Cyclists", cyclists, Colors.CYCLIST),
        ]:
            text = self.font_small.render(label, True, Colors.TEXT_SECONDARY)
            self.surface.blit(text, (rect.x + 8, y))
            val = self.font_small.render(str(count), True, color)
            self.surface.blit(val, (rect.right - val.get_width() - 8, y))
            y += 16

        y += 4
        pygame.draw.line(
            self.surface, Colors.DIVIDER,
            (rect.x + 8, y), (rect.right - 8, y), 1,
        )
        y += 6

        # Risk distribution
        green_count = sum(1 for r in risks.values() if r.risk_level == RiskLevel.GREEN)
        amber_count = sum(1 for r in risks.values() if r.risk_level == RiskLevel.AMBER)
        red_count = sum(1 for r in risks.values() if r.risk_level == RiskLevel.RED)

        for label, count, color in [
            ("GREEN", green_count, Colors.HALO_GREEN),
            ("AMBER", amber_count, Colors.HALO_AMBER),
            ("RED", red_count, Colors.HALO_RED),
        ]:
            pygame.draw.rect(self.surface, color, (rect.x + 8, y + 2, 8, 8))
            text = self.font_small.render(f"{label}: {count}", True, Colors.TEXT_SECONDARY)
            self.surface.blit(text, (rect.x + 22, y))
            y += 16

        y += 4
        pygame.draw.line(
            self.surface, Colors.DIVIDER,
            (rect.x + 8, y), (rect.right - 8, y), 1,
        )
        y += 6

        # Trigger counts
        events_so_far = [e for e in events if e.timestep <= current_timestep]
        red_triggers = sum(1 for e in events_so_far if e.severity == TriggerSeverity.RED)
        amber_triggers = sum(1 for e in events_so_far if e.severity == TriggerSeverity.AMBER)

        text = self.font_small.render("Total Triggers", True, Colors.TEXT_SECONDARY)
        self.surface.blit(text, (rect.x + 8, y))
        val = self.font_small.render(str(len(events_so_far)), True, Colors.TEXT_PRIMARY)
        self.surface.blit(val, (rect.right - val.get_width() - 8, y))
        y += 16

        text = self.font_small.render("  RED", True, Colors.HALO_RED)
        self.surface.blit(text, (rect.x + 8, y))
        val = self.font_small.render(str(red_triggers), True, Colors.HALO_RED)
        self.surface.blit(val, (rect.right - val.get_width() - 8, y))
        y += 16

        text = self.font_small.render("  AMBER", True, Colors.HALO_AMBER)
        self.surface.blit(text, (rect.x + 8, y))
        val = self.font_small.render(str(amber_triggers), True, Colors.HALO_AMBER)
        self.surface.blit(val, (rect.right - val.get_width() - 8, y))
        y += 20

        # Worst-case vehicle
        if risks:
            worst_id = max(risks, key=lambda k: risks[k].composite_score)
            worst = risks[worst_id]
            worst_agent = None
            for a in scenario.agents:
                if a.agent_id == worst_id:
                    worst_agent = a
                    break
            agent_label = self._agent_label(worst_id, worst_agent.agent_type if worst_agent else AgentType.VEHICLE)

            pygame.draw.line(
                self.surface, Colors.DIVIDER,
                (rect.x + 8, y), (rect.right - 8, y), 1,
            )
            y += 6

            text = self.font_small.render("Worst Agent", True, Colors.TEXT_SECONDARY)
            self.surface.blit(text, (rect.x + 8, y))
            val = self.font_body.render(
                f"{agent_label} ({worst.composite_score:.0%})", True, Colors.HALO_RED
            )
            self.surface.blit(val, (rect.right - val.get_width() - 8, y))

    def draw_playback_bar(
        self,
        rect: pygame.Rect,
        current_timestep: int,
        total_timesteps: int,
        playing: bool,
        speed: float = 1.0,
    ) -> None:
        """Draw the playback control bar at the bottom."""
        pygame.draw.rect(self.surface, Colors.BG_PANEL, rect)
        pygame.draw.line(
            self.surface, Colors.DIVIDER,
            (rect.x, rect.y), (rect.right, rect.y), 1,
        )

        # Play/pause button
        btn_x = rect.x + 12
        btn_y = rect.centery
        if playing:
            # Pause icon
            pygame.draw.rect(self.surface, Colors.TEXT_PRIMARY, (btn_x, btn_y - 6, 4, 12))
            pygame.draw.rect(self.surface, Colors.TEXT_PRIMARY, (btn_x + 7, btn_y - 6, 4, 12))
        else:
            # Play icon
            pygame.draw.polygon(
                self.surface, Colors.TEXT_PRIMARY,
                [(btn_x, btn_y - 7), (btn_x, btn_y + 7), (btn_x + 12, btn_y)],
            )

        # Progress bar
        bar_x = btn_x + 30
        bar_w = rect.width - 200
        bar_rect = pygame.Rect(bar_x, rect.centery - 3, bar_w, 6)
        pygame.draw.rect(self.surface, Colors.PLAYBACK_BAR, bar_rect, border_radius=3)

        if total_timesteps > 0:
            progress = current_timestep / max(1, total_timesteps - 1)
            fill_w = int(bar_w * progress)
            fill_rect = pygame.Rect(bar_x, rect.centery - 3, fill_w, 6)
            pygame.draw.rect(
                self.surface, Colors.PLAYBACK_PROGRESS, fill_rect, border_radius=3,
            )
            # Scrubber handle
            handle_x = bar_x + fill_w
            pygame.draw.circle(
                self.surface, Colors.TEXT_PRIMARY, (handle_x, rect.centery), 6,
            )

        # Time display
        time_s = current_timestep * 0.1
        total_s = (total_timesteps - 1) * 0.1
        time_text = self.font_body.render(
            f"{time_s:.1f}s / {total_s:.1f}s", True, Colors.TEXT_PRIMARY
        )
        self.surface.blit(
            time_text,
            (bar_x + bar_w + 12, rect.centery - time_text.get_height() // 2),
        )

        # Speed indicator
        speed_text = self.font_small.render(f"{speed:.1f}x", True, Colors.TEXT_SECONDARY)
        self.surface.blit(
            speed_text,
            (rect.right - speed_text.get_width() - 12, rect.centery - speed_text.get_height() // 2),
        )

        # Keyboard hints
        hints = self.font_small.render(
            "SPACE:play  ←→:step  +/-:speed  F:fit  R:reset  1/2/3:scenario",
            True, Colors.TEXT_MUTED,
        )
        self.surface.blit(hints, (bar_x, rect.y + 3))

    def _agent_label(self, agent_id: int, agent_type: AgentType) -> str:
        if agent_type == AgentType.PEDESTRIAN:
            return f"P{agent_id}"
        elif agent_type == AgentType.CYCLIST:
            return f"C{agent_id}"
        return f"V{agent_id}"
