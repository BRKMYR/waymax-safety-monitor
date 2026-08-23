"""Tests for headless rendering, config loading, and determinism.

Run headless: SDL uses the dummy video driver so no display is required.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# SDL must be set to dummy before pygame is imported anywhere.
os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame  # noqa: E402

from src.dashboard.app import (  # noqa: E402
    DashboardApp,
    _load_run_config,
    _write_events_json,
    run_headless,
)
from src.data.demo_loader import load_demo_scenario  # noqa: E402
from src.metrics.composite import RiskConfig  # noqa: E402
from src.triggers.config import TriggerConfig  # noqa: E402


def _new_app(scenario_name: str = "hard_brake") -> DashboardApp:
    scenario = load_demo_scenario(scenario_name)
    return DashboardApp(scenario=scenario)


class TestHeadlessFrameDump:
    def test_dumps_all_frames(self, tmp_path: Path):
        app = _new_app("hard_brake")
        try:
            frames_out = tmp_path / "frames"
            events_out = tmp_path / "events.json"
            n_frames, n_events = run_headless(
                app, frames_out, events_out, frame_stride=1
            )
            assert n_frames == app.state.scenario.num_timesteps == 91
            pngs = sorted(frames_out.glob("frame_*.png"))
            assert len(pngs) == 91
            # Names go frame_000.png .. frame_090.png.
            assert pngs[0].name == "frame_000.png"
            assert pngs[-1].name == "frame_090.png"
            assert events_out.exists()
            payload = json.loads(events_out.read_text())
            assert n_events == len(payload)
        finally:
            pygame.quit()

    def test_frame_geometry_and_non_blank(self, tmp_path: Path):
        """Criterion 4: frame_045.png is 1400x900 and has >=1000 non-bg pixels."""
        app = _new_app("hard_brake")
        try:
            frames_out = tmp_path / "frames"
            events_out = tmp_path / "events.json"
            run_headless(app, frames_out, events_out, frame_stride=1)
            frame = frames_out / "frame_045.png"
            assert frame.exists()

            surf = pygame.image.load(str(frame))
            assert surf.get_size() == (1400, 900)

            # Count pixels differing from the background (12, 12, 18).
            arr = pygame.surfarray.array3d(surf)  # (w, h, 3)
            bg = (12, 12, 18)
            diff = (
                (arr[..., 0] != bg[0])
                | (arr[..., 1] != bg[1])
                | (arr[..., 2] != bg[2])
            )
            assert int(diff.sum()) >= 1000
        finally:
            pygame.quit()

    def test_frame_stride(self, tmp_path: Path):
        app = _new_app("hard_brake")
        try:
            frames_out = tmp_path / "frames"
            events_out = tmp_path / "events.json"
            n_frames, _ = run_headless(app, frames_out, events_out, frame_stride=10)
            # timesteps 0, 10, 20, ..., 90 -> 10 frames
            expected = len(range(0, app.state.scenario.num_timesteps, 10))
            assert n_frames == expected
        finally:
            pygame.quit()

    def test_events_json_shape(self, tmp_path: Path):
        app = _new_app("hard_brake")
        try:
            frames_out = tmp_path / "frames"
            events_out = tmp_path / "events.json"
            run_headless(app, frames_out, events_out, frame_stride=91)
            payload = json.loads(events_out.read_text())
            assert isinstance(payload, list)
            required = {
                "agent_id", "agent_type", "timestep", "time_seconds",
                "severity", "kind", "reason", "metric_value",
            }
            for entry in payload:
                assert required.issubset(entry.keys())
                assert entry["severity"] in ("AMBER", "RED")
        finally:
            pygame.quit()

    def test_events_json_sorted(self, tmp_path: Path):
        app = _new_app("intersection_conflict")
        try:
            frames_out = tmp_path / "frames"
            events_out = tmp_path / "events.json"
            run_headless(app, frames_out, events_out, frame_stride=91)
            payload = json.loads(events_out.read_text())
            keys = [
                (e["timestep"], e["agent_id"], e["kind"]) for e in payload
            ]
            assert keys == sorted(keys)
        finally:
            pygame.quit()


class TestDeterminism:
    def test_two_runs_produce_identical_events_json(self, tmp_path: Path):
        """Two independent headless runs produce byte-identical events.json."""
        digests: list[str] = []
        for i in range(2):
            app = _new_app("hard_brake")
            try:
                frames_out = tmp_path / f"run{i}" / "frames"
                events_out = tmp_path / f"run{i}" / "events.json"
                run_headless(app, frames_out, events_out, frame_stride=91)
                digests.append(
                    hashlib.sha256(events_out.read_bytes()).hexdigest()
                )
            finally:
                pygame.quit()
        assert digests[0] == digests[1]

    def test_two_runs_produce_identical_last_frame(self, tmp_path: Path):
        """Frame bytes are stable across runs (dummy SDL driver + fixed data)."""
        digests: list[str] = []
        for i in range(2):
            app = _new_app("hard_brake")
            try:
                frames_out = tmp_path / f"run{i}"
                events_out = tmp_path / f"run{i}" / "events.json"
                run_headless(app, frames_out, events_out, frame_stride=1)
                last = frames_out / "frame_090.png"
                assert last.exists()
                digests.append(hashlib.sha256(last.read_bytes()).hexdigest())
            finally:
                pygame.quit()
        assert digests[0] == digests[1]


class TestPrecomputeSurvivesReset:
    def test_reset_preserves_precomputed_events(self):
        app = _new_app("intersection_conflict")
        try:
            before = list(app.state.events)
            assert before, "expected non-empty precomputed timeline"
            app.state.set_timestep(50)
            app.state.reset()
            after = list(app.state.events)
            assert after == before
            assert app.state.current_timestep == 0
        finally:
            pygame.quit()

    def test_precompute_is_idempotent(self):
        app = _new_app("hard_brake")
        try:
            first = list(app.state.events)
            app.state.precompute_all()
            second = list(app.state.events)
            assert len(first) == len(second)
            for a, b in zip(first, second):
                assert a.agent_id == b.agent_id
                assert a.timestep == b.timestep
                assert a.kind == b.kind
                assert a.severity == b.severity
        finally:
            pygame.quit()


class TestConfigLoading:
    def test_default_config_loads(self):
        cfg_path = Path("scenarios/default.json")
        name, seed, trigger_cfg, risk_cfg = _load_run_config(cfg_path)
        assert name == "intersection_conflict"
        assert seed == 42
        assert isinstance(trigger_cfg, TriggerConfig)
        assert isinstance(risk_cfg, RiskConfig)

    def test_unknown_top_level_key_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({
            "scenario": "hard_brake",
            "nonsense_key": 123,
        }))
        try:
            _load_run_config(bad)
        except ValueError as e:
            assert "nonsense_key" in str(e)
        else:
            raise AssertionError("expected ValueError for unknown key")

    def test_unknown_trigger_override_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({
            "scenario": "hard_brake",
            "trigger_overrides": {"not_a_real_threshold": 1.0},
        }))
        try:
            _load_run_config(bad)
        except ValueError as e:
            assert "not_a_real_threshold" in str(e)
        else:
            raise AssertionError("expected ValueError for unknown override")

    def test_policy_conservative_loads(self, tmp_path: Path):
        cfg = tmp_path / "cons.json"
        cfg.write_text(json.dumps({
            "scenario": "intersection_conflict",
            "trigger_policy": "conservative",
        }))
        _, _, trigger_cfg, _ = _load_run_config(cfg)
        # Conservative shifts TTC RED threshold higher (fires earlier).
        assert trigger_cfg.ttc_red > TriggerConfig().ttc_red

    def test_unknown_policy_raises(self, tmp_path: Path):
        cfg = tmp_path / "bad.json"
        cfg.write_text(json.dumps({
            "scenario": "intersection_conflict",
            "trigger_policy": "aggressive",
        }))
        try:
            _load_run_config(cfg)
        except ValueError as e:
            assert "aggressive" in str(e)
        else:
            raise AssertionError("expected ValueError for unknown policy")


class TestEventsJsonHelper:
    def test_write_events_json_creates_dirs(self, tmp_path: Path):
        app = _new_app("hard_brake")
        try:
            out = tmp_path / "nested" / "path" / "events.json"
            _write_events_json(app.state.events, out)
            assert out.exists()
            data = json.loads(out.read_text())
            assert isinstance(data, list)
        finally:
            pygame.quit()
