"""Tests for the rate-limited actuator. Uses injected `now` for determinism (no sleeps)."""

from unittest.mock import Mock

from nexus.actuator import Actuator
from nexus.arbitration import SystemState


def _make_actuator(dwell=5.0, fan_ok=True):
    reader = Mock()
    reader.set_fan_pwm.return_value = fan_ok
    return reader, Actuator(reader, min_dwell_seconds=dwell)


def test_first_commit_writes_immediately():
    reader, act = _make_actuator()
    assert act.commit(SystemState.FAULT, "/fan", now=1000.0) is True
    assert act.last_state == SystemState.FAULT
    reader.set_fan_pwm.assert_called_once_with("/fan", 100)  # FAULT → 100%


def test_same_state_is_a_noop():
    reader, act = _make_actuator()
    act.commit(SystemState.FAULT, "/fan", now=1000.0)
    reader.set_fan_pwm.reset_mock()
    assert act.commit(SystemState.FAULT, "/fan", now=1000.1) is True
    reader.set_fan_pwm.assert_not_called()


def test_state_change_within_dwell_is_deferred():
    reader, act = _make_actuator(dwell=5.0)
    act.commit(SystemState.FAULT, "/fan", now=1000.0)
    reader.set_fan_pwm.reset_mock()

    # Too soon — must defer, must not call the BMC.
    assert act.commit(SystemState.NOMINAL, "/fan", now=1001.0) is False
    reader.set_fan_pwm.assert_not_called()
    assert act.pending_state == SystemState.NOMINAL
    # last_state is unchanged until the commit actually lands.
    assert act.last_state == SystemState.FAULT


def test_state_change_after_dwell_is_committed():
    reader, act = _make_actuator(dwell=5.0)
    act.commit(SystemState.FAULT, "/fan", now=1000.0)
    reader.set_fan_pwm.reset_mock()

    # Dwell elapsed — must write.
    assert act.commit(SystemState.NOMINAL, "/fan", now=1006.0) is True
    assert act.last_state == SystemState.NOMINAL
    reader.set_fan_pwm.assert_called_once_with("/fan", 30)  # NOMINAL → 30%


def test_try_flush_pending_applies_deferred_state():
    reader, act = _make_actuator(dwell=5.0)
    act.commit(SystemState.FAULT, "/fan", now=1000.0)

    # Defer a NOMINAL.
    act.commit(SystemState.NOMINAL, "/fan", now=1001.0)
    assert act.pending_state == SystemState.NOMINAL

    # Flush too early → still deferred.
    assert act.try_flush_pending("/fan", now=1002.0) is False
    assert act.pending_state == SystemState.NOMINAL

    # Flush after dwell → committed.
    assert act.try_flush_pending("/fan", now=1006.0) is True
    assert act.last_state == SystemState.NOMINAL
    assert act.pending_state is None


def test_failed_pwm_write_does_not_update_state():
    reader = Mock()
    reader.set_fan_pwm.return_value = False
    act = Actuator(reader, min_dwell_seconds=5.0)
    assert act.commit(SystemState.FAULT, "/fan", now=1000.0) is False
    assert act.last_state is None   # still unset
    assert act.last_commit_time == 0.0
