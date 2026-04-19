"""Actuator layer: rate-limited fan PWM commits via the SensorReader."""

from __future__ import annotations

import logging
import time
from typing import Optional

from nexus.arbitration import SystemState
from nexus.telemetry import SensorReader

logger = logging.getLogger("nexus")


class Actuator:
    """Rate-limited fan control.

    - If the desired state equals the last committed state, do nothing.
    - If enough dwell time has passed, write immediately.
    - Otherwise, store as pending_state. The caller (or next commit call)
      will retry once dwell has elapsed.

    This matters because thrashing fan commands hurts fan lifetime and
    generates BMC load. A minimum dwell of a few seconds is a standard
    enterprise practice.
    """

    # Maps each state to a fan PWM percentage. Tunable at construction.
    DEFAULT_PWM_MAP = {
        SystemState.NOMINAL: 30,
        SystemState.INVALID: 50,
        SystemState.RECOVERY: 40,
        SystemState.FAULT: 100,
    }

    def __init__(self, reader: SensorReader, min_dwell_seconds: float = 5.0,
                 pwm_map: Optional[dict] = None):
        self.reader = reader
        self.min_dwell = min_dwell_seconds
        self.pwm_map = dict(pwm_map) if pwm_map else dict(self.DEFAULT_PWM_MAP)
        self.last_commit_time = 0.0
        self.last_state: Optional[SystemState] = None
        self.pending_state: Optional[SystemState] = None

    def _write_pwm(self, state: SystemState, pwm_path: str) -> bool:
        percent = self.pwm_map.get(state, 50)
        return self.reader.set_fan_pwm(pwm_path, percent)

    def commit(self, new_state: SystemState, pwm_path: str,
               now: Optional[float] = None) -> bool:
        """Try to commit new_state. Returns True if written, False if deferred or failed.

        `now` can be supplied by tests; defaults to wall-clock time.
        """
        if now is None:
            now = time.time()

        # No-op: state unchanged.
        if new_state == self.last_state:
            return True

        # Too soon since last commit — defer.
        if self.last_commit_time and (now - self.last_commit_time) < self.min_dwell:
            self.pending_state = new_state
            logger.warning("Deferring %s -> %s (dwell not elapsed, %.1fs of %.1fs)",
                           self.last_state, new_state,
                           now - self.last_commit_time, self.min_dwell)
            return False

        # Write.
        ok = self._write_pwm(new_state, pwm_path)
        if not ok:
            logger.error("PWM write failed for state %s on %s", new_state, pwm_path)
            return False

        self.last_state = new_state
        self.last_commit_time = now
        self.pending_state = None
        return True

    def try_flush_pending(self, pwm_path: str, now: Optional[float] = None) -> bool:
        """If there's a pending state and dwell has elapsed, commit it now."""
        if self.pending_state is None:
            return False
        return self.commit(self.pending_state, pwm_path, now=now)
