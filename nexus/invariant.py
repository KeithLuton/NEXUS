"""Invariant layer: pure predicates plus the state transition that composes them.

Dependency order: this sits above arbitration, telemetry, and history.
Nothing in those three modules imports from this file — breaks the cycle.
"""

from __future__ import annotations

from typing import List, Tuple

from nexus.arbitration import (
    ArbitrationConfig, HardwareSafetyFlags, PolicyConfig,
    StateChangeCause, SystemState,
)
from nexus.history import History
from nexus.telemetry import Telemetry


def is_divergence_detected(tele: Telemetry, threshold: float) -> bool:
    return tele.divergence.combined() > threshold


def is_gradient_valid(tele: Telemetry, min_grad: float) -> bool:
    return tele.gradient >= min_grad


def get_confidence(tele: Telemetry) -> float:
    return tele.confidence


def is_reentry_allowed(tele: Telemetry, policy: PolicyConfig, hist: History) -> bool:
    if not policy.allow_predictive_recovery:
        return False
    if tele.prediction <= 0.5:
        hist.reentry_consecutive_valid = 0
        return False
    hist.reentry_consecutive_valid += 1
    return hist.reentry_consecutive_valid >= policy.reentry_required_valid_ticks


def detect_oscillation(history_window: List[float]) -> bool:
    """Detect control-output oscillation.

    An oscillation is defined as alternation between two distinct values
    over a window. We check the last N samples (N = len, minimum 4) and
    count "alternating" pairs where x[i] != x[i-1] AND x[i] == x[i-2].
    If more than half the eligible positions alternate, we flag it.

    This replaces the old sign-change heuristic, which only worked for
    signed data centered on zero. SystemState values are 0..3, so the
    old check could never detect the actual oscillation shape the
    project cares about (e.g. [NOMINAL, FAULT, NOMINAL, FAULT, ...]).
    """
    n = len(history_window)
    if n < 4:
        return False
    alternations = 0
    eligible = 0
    for i in range(2, n):
        eligible += 1
        if history_window[i] != history_window[i - 1] and history_window[i] == history_window[i - 2]:
            alternations += 1
    return alternations > eligible // 2


def critical_fault_trigger(hist: History, hw_flags: HardwareSafetyFlags,
                           tele: Telemetry, policy: PolicyConfig) -> Tuple[bool, str]:
    """Any-of-these triggers an immediate forced FAULT."""
    if hw_flags.thermal_runaway or hw_flags.voltage_instability or hw_flags.fan_nonresponse:
        return True, "Hardware fault"
    if hist.divergence_streak >= policy.divergence_streak_threshold:
        return True, "Persistent divergence"
    if hist.checksum_mismatch_count > 0:
        return True, "History checksum mismatch"
    if hist.oscillation_detected:
        return True, "Control oscillation"
    return False, ""


def spigot_transition(current_state: SystemState, tele: Telemetry,
                      cfg: ArbitrationConfig, hist: History) -> Tuple[SystemState, StateChangeCause]:
    """Decide the next state from telemetry and policy. Ordered by priority."""
    if cfg.hardware_override_active:
        return cfg.forced_state, StateChangeCause.HARDWARE_OVERRIDE

    if is_divergence_detected(tele, cfg.policy.divergence_threshold):
        return SystemState.FAULT, StateChangeCause.DIVERGENCE

    if not is_gradient_valid(tele, cfg.policy.gradient_min) and get_confidence(tele) < cfg.policy.confidence_min:
        return SystemState.INVALID, StateChangeCause.GRADIENT_LOSS

    if is_reentry_allowed(tele, cfg.policy, hist):
        return SystemState.NOMINAL, StateChangeCause.REENTRY

    return current_state, StateChangeCause.NONE
