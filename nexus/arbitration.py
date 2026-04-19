"""State machine data types.

This module has zero dependencies on other nexus modules — it sits at the
bottom of the dependency stack so everything else can import from it
without risking cycles.
"""

from dataclasses import dataclass, field
from enum import Enum


class SystemState(Enum):
    """Runtime state of the orchestrator for a given chassis."""
    NOMINAL = 0   # all invariants healthy, operating within policy
    FAULT = 1    # safety invariant tripped, forced to safe cooling
    INVALID = 2  # sensor trust degraded, running in cautious mode
    RECOVERY = 3  # transitioning back toward NOMINAL after a fault


class StateChangeCause(Enum):
    """Why the state machine changed state. Logged with every transition."""
    NONE = 0
    DIVERGENCE = 1
    GRADIENT_LOSS = 2
    REENTRY = 3
    HARDWARE_OVERRIDE = 4
    CRITICAL_FAULT = 5
    OSCILLATION = 6
    CONSTRAINT_SATURATION = 7


@dataclass
class PolicyConfig:
    """Tunable thresholds for the invariant / arbitration layers."""
    divergence_threshold: float = 5.0
    gradient_min: float = 0.5
    confidence_min: float = 0.8
    allow_predictive_recovery: bool = True
    reentry_required_valid_ticks: int = 3
    divergence_streak_threshold: int = 3


@dataclass
class HardwareSafetyFlags:
    """Hardware-level safety signals, typically fed from BMC alerts or PSU monitors."""
    thermal_runaway: bool = False
    voltage_instability: bool = False
    fan_nonresponse: bool = False


@dataclass
class ArbitrationConfig:
    """Runtime arbitration configuration (policy + hardware override state)."""
    hardware_override_active: bool = False
    forced_state: SystemState = SystemState.NOMINAL
    policy: PolicyConfig = field(default_factory=PolicyConfig)
