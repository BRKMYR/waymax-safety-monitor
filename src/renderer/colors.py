"""Color scheme for the safety monitoring dashboard.

Dark theme, high contrast — air traffic control aesthetic.
"""

from __future__ import annotations


class Colors:
    """Dashboard color palette."""

    # Background
    BG_DARK = (12, 12, 18)
    BG_PANEL = (18, 18, 26)
    BG_PANEL_HEADER = (25, 25, 38)

    # Road graph
    ROAD_SURFACE = (28, 28, 38)
    LANE_CENTER = (55, 55, 72)
    LANE_BOUNDARY = (40, 40, 55)
    ROAD_EDGE = (70, 70, 85)
    CROSSWALK = (60, 60, 80)
    STOP_SIGN = (180, 60, 60)
    SPEED_BUMP = (120, 100, 60)

    # Traffic signals
    SIGNAL_GREEN = (40, 200, 80)
    SIGNAL_YELLOW = (220, 200, 40)
    SIGNAL_RED = (220, 50, 50)
    SIGNAL_UNKNOWN = (100, 100, 100)

    # Agents
    EGO_VEHICLE = (60, 160, 255)
    OTHER_VEHICLE = (180, 180, 200)
    PEDESTRIAN = (255, 200, 60)
    CYCLIST = (100, 220, 160)
    HEADING_ARROW = (255, 255, 255)

    # Risk halos
    HALO_GREEN = (40, 200, 80)
    HALO_AMBER = (255, 180, 40)
    HALO_RED = (255, 50, 50)

    # UI text
    TEXT_PRIMARY = (220, 220, 230)
    TEXT_SECONDARY = (140, 140, 160)
    TEXT_MUTED = (90, 90, 110)

    # Panel elements
    DIVIDER = (40, 40, 55)
    HIGHLIGHT = (60, 160, 255)
    TIMELINE_BG = (22, 22, 32)
    TIMELINE_MARKER = (60, 160, 255)
    PLAYBACK_BAR = (45, 45, 60)
    PLAYBACK_PROGRESS = (60, 160, 255)

    # Severity badges
    BADGE_GREEN = (30, 140, 60)
    BADGE_AMBER = (200, 140, 30)
    BADGE_RED = (200, 40, 40)

    @staticmethod
    def with_alpha(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
        return (*color, alpha)
