"""Tests for the bus-bar constraint solver."""

from nexus.arbitration import SystemState
from nexus.bus_bar import ActuatorLimits, BusBarConstraint


def test_within_limits_passes_through():
    bb = BusBarConstraint(ActuatorLimits(max_power=100, max_temperature=85))
    state, sat = bb.apply(SystemState.NOMINAL, current_power=50, current_temp=40)
    assert state == SystemState.NOMINAL
    assert sat is False


def test_over_temp_forces_fault():
    bb = BusBarConstraint(ActuatorLimits(max_temperature=85))
    state, sat = bb.apply(SystemState.NOMINAL, current_power=50, current_temp=90)
    assert state == SystemState.FAULT
    assert sat is True


def test_over_power_forces_fault():
    bb = BusBarConstraint(ActuatorLimits(max_power=100))
    state, sat = bb.apply(SystemState.NOMINAL, current_power=120, current_temp=40)
    assert state == SystemState.FAULT
    assert sat is True


def test_near_temp_limit_degrades_to_invalid():
    bb = BusBarConstraint(ActuatorLimits(max_temperature=85))
    # 90% of 85 = 76.5; 80 is above that but below 85.
    state, sat = bb.apply(SystemState.NOMINAL, current_power=50, current_temp=80)
    assert state == SystemState.INVALID
    assert sat is True


def test_near_power_limit_degrades_to_invalid():
    bb = BusBarConstraint(ActuatorLimits(max_power=100))
    state, sat = bb.apply(SystemState.NOMINAL, current_power=95, current_temp=40)
    assert state == SystemState.INVALID
    assert sat is True
