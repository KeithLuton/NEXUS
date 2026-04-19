"""History persistence with monotonic tick, checksum tracking, and safe JSON round-trip."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nexus.arbitration import SystemState, StateChangeCause

logger = logging.getLogger("nexus")


@dataclass
class History:
    """Persistent per-chassis history used by the invariant and arbitration layers."""
    last_committed_state: SystemState = SystemState.NOMINAL
    last_tick: int = 0
    valid_entry_count: int = 0
    history_checksum: int = 0
    reentry_consecutive_valid: int = 0
    divergence_streak: int = 0
    last_state_change_cause: StateChangeCause = StateChangeCause.NONE
    cause_history: List[Tuple[int, StateChangeCause]] = field(default_factory=list)
    control_output_history: List[float] = field(default_factory=list)
    oscillation_detected: bool = False
    checksum_mismatch_count: int = 0
    # Path is not part of the persisted state itself. `repr=False` and `compare=False`
    # keep it out of __repr__ and equality checks; `to_dict` explicitly pops it.
    _persist_path: Optional[Path] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_persist_path", None)
        d["last_committed_state"] = self.last_committed_state.name
        d["last_state_change_cause"] = self.last_state_change_cause.name
        d["cause_history"] = [(t, c.name) for t, c in self.cause_history]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "History":
        h = cls()
        h.last_committed_state = SystemState[data["last_committed_state"]]
        h.last_tick = int(data["last_tick"])
        h.valid_entry_count = int(data["valid_entry_count"])
        h.history_checksum = int(data["history_checksum"])
        h.reentry_consecutive_valid = int(data["reentry_consecutive_valid"])
        h.divergence_streak = int(data["divergence_streak"])
        h.last_state_change_cause = StateChangeCause[data["last_state_change_cause"]]
        h.cause_history = [(int(t), StateChangeCause[name]) for t, name in data["cause_history"]]
        h.control_output_history = list(data["control_output_history"])
        h.oscillation_detected = bool(data["oscillation_detected"])
        h.checksum_mismatch_count = int(data["checksum_mismatch_count"])
        return h

    def save(self) -> None:
        """Persist to disk. No-op if no _persist_path was set. Atomic via temp-file + rename."""
        if not self._persist_path:
            return
        tmp = self._persist_path.with_suffix(self._persist_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2))
        tmp.replace(self._persist_path)

    @classmethod
    def load_or_default(cls, persist_path: Path) -> "History":
        """Load from disk if a valid file exists, else return a fresh History bound to the path."""
        if persist_path.exists():
            try:
                data = json.loads(persist_path.read_text())
                h = cls.from_dict(data)
                h._persist_path = persist_path
                return h
            except Exception as e:
                logger.warning("Failed to load history from %s: %s — starting fresh", persist_path, e)
        return cls(_persist_path=persist_path)
