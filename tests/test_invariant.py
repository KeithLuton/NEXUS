"""Unit tests for the invariant layer (pure functions)."""

from nexus.arbitration import (
    ArbitrationConfig, HardwareSafetyFlags, PolicyConfig, SystemState,
    StateChangeCause,
)
from nexus.history import History
from nexus.invariant import (
    critical_fault_trigger, detect_oscillation, get_confidence,
    is_divergence_detected, is_gradient_valid, is_reentry_allowed,
    spigot_transition,
)
from nexus.telemetry import DivergenceMetrics, Telemetry


def _tele(spatial=0.0, gradient=1.0, confidence=0.9, prediction=0.5, tick=0):
    return Telemetry(
        tick=tick,
        divergence=DivergenceMetrics(spatial_rms=spatial),
        gradient=gradient,
        confidence=confidence,
        prediction=prediction,
    )


# ---------------- divergence ----------------

def test_divergence_detection_above_threshold():
    assert is_divergence_detected(_tele(spatial=10.0), 5.0) is True


def test_divergence_detection_below_threshold():
    assert is_divergence_detected(_tele(spatial=2.0), 5.0) is False


def test_divergence_exactly_at_threshold_is_not_detected():
    # combined() is weighted; with only spatial=threshold, combined = 0.6*threshold
    # so strictly greater semantics hold
    assert is_divergence_detected(_tele(spatial=5.0), 5.0) is False


# ---------------- gradient ----------------

def test_gradient_valid_true():
    assert is_gradient_valid(_tele(gradient=0.8), 0.5) is True


def test_gradient_valid_false():
    assert is_gradient_valid(_tele(gradient=0.2), 0.5) is False


# ---------------- confidence ----------------

def test_confidence_passthrough():
    assert get_confidence(_tele(confidence=0.75)) == 0.75


# ---------------- reentry ----------------

def test_reentry_requires_consecutive_valid_ticks():
    policy = PolicyConfig(allow_predictive_recovery=True, reentry_required_valid_ticks=3)
    hist = History()
    good = _tele(prediction=0.8)
    # First two calls should not yet allow reentry; third call does.
    assert is_reentry_allowed(good, policy, hist) is False
    assert is_reentry_allowed(good, policy, hist) is False
    assert is_reentry_allowed(good, policy, hist) is True


def test_reentry_resets_on_bad_prediction():
    policy = PolicyConfig(allow_predictive_recovery=True, reentry_required_valid_ticks=3)
    hist = History()
    good = _tele(prediction=0.8)
    bad = _tele(prediction=0.4)
    is_reentry_allowed(good, policy, hist)
    is_reentry_allowed(good, policy, hist)
    is_reentry_allowed(bad, policy, hist)  # should reset counter
    assert hist.reentry_consecutive_valid == 0
    assert is_reentry_allowed(good, policy, hist) is False  # counter had reset


def test_reentry_denied_when_recovery_disabled():
    policy = PolicyConfig(allow_predictive_recovery=False)
    hist = History()
    assert is_reentry_allowed(_tele(prediction=0.9), policy, hist) is False


# ---------------- oscillation ----------------

def test_oscillation_detects_alternating_pattern():
    # This is the case the old implementation missed: all non-negative values.
    assert detect_oscillation([0, 1, 0, 1, 0]) is True


def test_oscillation_detects_signed_alternating():
    assert detect_oscillation([1, -1, 1, -1, 1]) is True


def test_oscillation_rejects_monotonic():
    assert detect_oscillation([1, 2, 3, 4, 5]) is False


def test_oscillation_rejects_constant():
    assert detect_oscillation([1, 1, 1, 1, 1]) is False


def test_oscillation_rejects_too_short():
    assert detect_oscillation([1, 0, 1]) is False


def test_oscillation_detects_state_flipping():
    # The real shape: SystemState.NOMINAL.value = 0, SystemState.FAULT.value = 1
    pattern = [0, 1, 0, 1, 0, 1, 0]
    assert detect_oscillation(pattern) is True


# ---------------- critical fault trigger ----------------

def test_critical_fault_on_hardware_flag():
    hist = History()
    hw = HardwareSafetyFlags(thermal_runaway=True)
    triggered, reason = critical_fault_trigger(hist, hw, _tele(), PolicyConfig())
    assert triggered is True
    assert "Hardware" in reason


def test_critical_fault_on_persistent_divergence():
    hist = History()
    hist.divergence_streak = 3
    triggered, reason = critical_fault_trigger(hist, HardwareSafetyFlags(),
                                                _tele(), PolicyConfig(divergence_streak_threshold=3))
    assert triggered is True
    assert "Persistent divergence" in reason


def test_critical_fault_on_checksum_mismatch():
    hist = History()
    hist.checksum_mismatch_count = 1
    triggered, reason = critical_fault_trigger(hist, HardwareSafetyFlags(),
                                                _tele(), PolicyConfig())
    assert triggered is True
    assert "checksum" in reason.lower()


def test_critical_fault_on_oscillation():
    hist = History()
    hist.oscillation_detected = True
    triggered, reason = critical_fault_trigger(hist, HardwareSafetyFlags(),
                                                _tele(), PolicyConfig())
    assert triggered is True
    assert "oscillation" in reason.lower()


def test_no_critical_fault_when_clean():
    triggered, _ = critical_fault_trigger(History(), HardwareSafetyFlags(),
                                          _tele(), PolicyConfig())
    assert triggered is False


# ---------------- spigot_transition ----------------

def test_spigot_transition_hardware_override():
    cfg = ArbitrationConfig(hardware_override_active=True, forced_state=SystemState.FAULT)
    state, cause = spigot_transition(SystemState.NOMINAL, _tele(), cfg, History())
    assert state == SystemState.FAULT
    assert cause == StateChangeCause.HARDWARE_OVERRIDE


def test_spigot_transition_divergence_triggers_fault():
    cfg = ArbitrationConfig(policy=PolicyConfig(divergence_threshold=5.0))
    tele = _tele(spatial=20.0)  # well above threshold
    state, cause = spigot_transition(SystemState.NOMINAL, tele, cfg, History())
    assert state == SystemState.FAULT
    assert cause == StateChangeCause.DIVERGENCE


def test_spigot_transition_stays_put_when_quiet():
    cfg = ArbitrationConfig(policy=PolicyConfig(allow_predictive_recovery=False))
    state, cause = spigot_transition(SystemState.NOMINAL, _tele(), cfg, History())
    assert state == SystemState.NOMINAL
    assert cause == StateChangeCause.NONE
