"""Constraint solver: enforces power and thermal limits (bus bar)."""

from dataclasses import dataclass
from typing import Tuple

from nexus.arbitration import SystemState


@dataclass
class ActuatorLimits:
    max_power: float = 100.0       # watts
    max_current: float = 20.0      # amps
    max_temperature: float = 85.0  # Celsius


class BusBarConstraint:
    """Overrides the arbitration layer when physical limits are violated.

    Returns (constrained_state, saturated_flag). When saturated_flag is True,
    the caller should treat the state change cause as CONSTRAINT_SATURATION.
    """

    def __init__(self, limits: ActuatorLimits):
        self.limits = limits

    def apply(self, desired_state: SystemState, current_power: float,
              current_temp: float) -> Tuple[SystemState, bool]:
        if current_power > self.limits.max_power or current_temp > self.limits.max_temperature:
            return SystemState.FAULT, True
        if (current_power > 0.9 * self.limits.max_power
                or current_temp > 0.9 * self.limits.max_temperature):
            return SystemState.INVALID, True
        return desired_state, False
