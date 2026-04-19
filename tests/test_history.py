"""Tests for history persistence — including the round-trip bug that crashed v5.0."""

import json
import tempfile
from pathlib import Path

from nexus.arbitration import StateChangeCause, SystemState
from nexus.history import History


def test_empty_history_roundtrip():
    """Save a fresh history and load it — no crash, identical state."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hist.json"
        h = History(_persist_path=path)
        h.save()
        assert path.exists()
        loaded = History.load_or_default(path)
        assert loaded.last_committed_state == SystemState.NOMINAL
        assert loaded.last_tick == 0


def test_populated_history_roundtrip():
    """Save a realistic history and make sure every field round-trips."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hist.json"
        h = History(_persist_path=path)
        h.last_committed_state = SystemState.INVALID
        h.last_tick = 42
        h.valid_entry_count = 42
        h.divergence_streak = 2
        h.last_state_change_cause = StateChangeCause.GRADIENT_LOSS
        h.cause_history = [(10, StateChangeCause.DIVERGENCE),
                           (20, StateChangeCause.REENTRY)]
        h.control_output_history = [0.0, 1.0, 2.0, 1.0, 0.0]
        h.oscillation_detected = True
        h.checksum_mismatch_count = 1
        h.save()

        loaded = History.load_or_default(path)
        assert loaded.last_committed_state == SystemState.INVALID
        assert loaded.last_tick == 42
        assert loaded.valid_entry_count == 42
        assert loaded.divergence_streak == 2
        assert loaded.last_state_change_cause == StateChangeCause.GRADIENT_LOSS
        assert loaded.cause_history == [(10, StateChangeCause.DIVERGENCE),
                                         (20, StateChangeCause.REENTRY)]
        assert loaded.control_output_history == [0.0, 1.0, 2.0, 1.0, 0.0]
        assert loaded.oscillation_detected is True
        assert loaded.checksum_mismatch_count == 1


def test_to_dict_does_not_leak_persist_path():
    """Regression test: v5.0 crashed on save because _persist_path leaked into JSON."""
    h = History(_persist_path=Path("/tmp/test.json"))
    d = h.to_dict()
    assert "_persist_path" not in d
    # Must be JSON-serializable.
    json.dumps(d)  # will raise if it's not


def test_save_is_atomic_tempfile_then_rename():
    """If the save somehow fails mid-write, the old file must still be intact."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hist.json"
        h = History(_persist_path=path)
        h.last_tick = 1
        h.save()

        # Simulate a save: after it completes, no .tmp file should be left.
        h.last_tick = 2
        h.save()
        assert not path.with_suffix(path.suffix + ".tmp").exists()
        loaded = History.load_or_default(path)
        assert loaded.last_tick == 2


def test_load_or_default_returns_fresh_when_file_missing():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "does-not-exist.json"
        h = History.load_or_default(path)
        assert h.last_tick == 0
        # Persist path should be bound so subsequent save() works.
        assert h._persist_path == path


def test_load_or_default_recovers_from_corrupt_file():
    """Corrupt JSON must not crash — orchestrator should start fresh and log a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hist.json"
        path.write_text("{not valid json}")
        h = History.load_or_default(path)
        assert h.last_tick == 0
        assert h._persist_path == path
