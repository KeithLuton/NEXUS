"""End-to-end smoke tests for the orchestrator using the deterministic mock sensor."""

import json
import tempfile
from pathlib import Path

from nexus.arbitration import SystemState
from nexus.orchestrator import NexusOrchestrator, OrchestratorConfig


def _write_config(tmpdir: Path, chassis_id: str = "mock-chassis-01") -> Path:
    cfg = {
        "poll_interval_s": 0,  # no sleeping in tests
        "chassis": [{
            "chassis_id": chassis_id,
            "bmc_host": "mock",
            "bmc_user": "root",
            "bmc_password": "",
            "thermal_zones": [{
                "zone_id": "primary",
                "sensor_paths": ["/mock/temp"],
                "pwm_path": "/mock/pwm",
                "thermal_profile": "balanced"
            }]
        }]
    }
    path = tmpdir / "config.json"
    path.write_text(json.dumps(cfg))
    return path


def test_fresh_orchestrator_starts_at_tick_zero():
    """Regression: a fresh orchestrator with no state dir must start at tick 0, not 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = _write_config(tmp)
        state_dir = tmp / "state"  # does not exist yet
        cfg = OrchestratorConfig.from_json(cfg_path)

        orch = NexusOrchestrator(cfg, state_dir)
        assert orch.tick == 0, f"Fresh orchestrator should start at tick 0, got {orch.tick}"


def test_orchestrator_runs_without_crashing():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = _write_config(tmp)
        state_dir = tmp / "state"
        cfg = OrchestratorConfig.from_json(cfg_path)
        orch = NexusOrchestrator(cfg, state_dir)
        # Run a fixed number of ticks.
        orch.run(max_ticks=5)
        # History file must have been written.
        hist_file = state_dir / "mock-chassis-01_history.json"
        assert hist_file.exists()
        data = json.loads(hist_file.read_text())
        assert data["last_tick"] >= 4  # 0..4 over 5 ticks


def test_orchestrator_persists_across_restart():
    """A fresh orchestrator should resume at last_tick + 1, not 0."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = _write_config(tmp)
        state_dir = tmp / "state"
        cfg = OrchestratorConfig.from_json(cfg_path)

        orch1 = NexusOrchestrator(cfg, state_dir)
        orch1.run(max_ticks=3)
        persisted_last = orch1.histories["mock-chassis-01"].last_tick

        # New orchestrator instance, same state dir. tick must resume past the persisted value.
        orch2 = NexusOrchestrator(cfg, state_dir)
        assert orch2.histories["mock-chassis-01"].last_tick == persisted_last
        assert orch2.tick == persisted_last + 1


def test_restart_does_not_trip_monotonic_fault_cascade():
    """Regression: a restart must not force every chassis into FAULT on the first tick."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = _write_config(tmp)
        state_dir = tmp / "state"
        cfg = OrchestratorConfig.from_json(cfg_path)

        # Seed some persisted history.
        NexusOrchestrator(cfg, state_dir).run(max_ticks=3)

        # Restart — first poll must NOT be a CRITICAL_FAULT from a monotonic-tick violation.
        orch = NexusOrchestrator(cfg, state_dir)
        snapshot = orch.poll_chassis(cfg.chassis[0])
        assert snapshot["state"] != "FAULT" or snapshot["cause"] != "CRITICAL_FAULT", \
            f"Restart tripped monotonic fault: {snapshot}"


def test_orchestrator_produces_valid_json_snapshots():
    """The snapshot dict must be JSON-serializable — it's written to logs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = _write_config(tmp)
        cfg = OrchestratorConfig.from_json(cfg_path)
        orch = NexusOrchestrator(cfg, tmp / "state")
        chassis = cfg.chassis[0]
        snapshot = orch.poll_chassis(chassis)
        # Round-trip through JSON must work.
        as_json = json.dumps(snapshot)
        parsed = json.loads(as_json)
        assert parsed["chassis_id"] == "mock-chassis-01"
        assert parsed["state"] in [s.name for s in SystemState]
        assert isinstance(parsed["temperatures_c"], dict)
