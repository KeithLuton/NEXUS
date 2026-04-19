"""Telemetry acquisition: divergence metrics, predictor, sensor reader.

Depends only on arbitration (for data types). The sensor reader uses
the optional `redfish` library when available, and falls back to a
deterministic sine-wave mock otherwise.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nexus")

try:
    from redfish import RedfishClient  # type: ignore
    REDFISH_AVAILABLE = True
except ImportError:
    REDFISH_AVAILABLE = False


@dataclass
class DivergenceMetrics:
    """Breakdown of how the observed state diverged from the predicted state."""
    spatial_rms: float = 0.0       # |observed - predicted|, primary signal
    temporal_lag_ms: float = 0.0   # how far the prediction is lagging
    gradient_norm: float = 0.0     # magnitude of the rate of change

    def combined(self) -> float:
        """Weighted combination used by the divergence predicate."""
        return (0.6 * self.spatial_rms
                + 0.2 * self.temporal_lag_ms / 10.0
                + 0.2 * self.gradient_norm)


@dataclass
class Telemetry:
    """Snapshot of invariant inputs for one tick on one chassis."""
    tick: int
    divergence: DivergenceMetrics
    gradient: float
    confidence: float
    prediction: float
    thermal_runaway: bool = False
    voltage_instability: bool = False

    def checksum(self) -> int:
        data = (self.tick, self.divergence.spatial_rms, self.divergence.temporal_lag_ms,
                self.divergence.gradient_norm, self.gradient, self.confidence, self.prediction)
        return hash(data) & 0xffffffff


class SimplePredictor:
    """Exponential moving average over observed temperatures.

    Deliberately simple: good enough to give the invariant layer a real
    predicted-vs-observed signal without pretending to be a physics model.
    """

    def __init__(self, alpha: float = 0.3):
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = alpha
        self.predicted: Optional[float] = None

    def predict(self, observed: float) -> float:
        if self.predicted is None:
            self.predicted = observed
        else:
            self.predicted = self.alpha * observed + (1 - self.alpha) * self.predicted
        return self.predicted


class SensorReader:
    """Reads temperatures and writes fan PWM. Uses Redfish if available, mock otherwise.

    The mock is a deterministic sine wave (reproducible across runs), with
    an optional tick-based fault injection for tests.
    """

    def __init__(self, bmc_host: str, bmc_user: str, bmc_password: str):
        self.bmc_host = bmc_host
        self.bmc_user = bmc_user
        self.bmc_password = bmc_password
        self.client = None
        if REDFISH_AVAILABLE and bmc_host and bmc_host != "mock":
            try:
                self.client = RedfishClient(bmc_host, bmc_user, bmc_password)
                self.client.login()
                logger.info("Redfish login succeeded: %s", bmc_host)
            except Exception as e:
                logger.warning("Redfish login failed for %s: %s — falling back to mock", bmc_host, e)
                self.client = None
        self._mock_phase = 0.0
        self._mock_tick = 0

    def set_mock_tick(self, tick: int) -> None:
        """Record the orchestrator's current tick so fault injection can align to it."""
        self._mock_tick = tick

    def get_temperature(self, sensor_path: str, fault_tick: int = -1) -> Optional[float]:
        """Return current temperature in °C, or None on failure."""
        if self.client is None:
            self._mock_phase += 0.1
            temp = 60.0 + 20.0 * math.sin(self._mock_phase)
            if fault_tick >= 0 and self._mock_tick == fault_tick:
                temp = 95.0   # injected overheat
            return temp
        try:
            resp = self.client.get(sensor_path)
            if resp.status == 200:
                return resp.dict.get("Reading")
            logger.error("Redfish sensor read %s returned %s", sensor_path, resp.status)
            return None
        except Exception as e:
            logger.error("Redfish exception reading %s: %s", sensor_path, e)
            return None

    def set_fan_pwm(self, pwm_path: str, percent: int) -> bool:
        """Write a PWM setpoint. Returns True on success. Mock always succeeds."""
        if self.client is None:
            logger.debug("mock PWM write: %s -> %d%%", pwm_path, percent)
            return True
        try:
            resp = self.client.patch(pwm_path, body={"SpeedPercent": percent})
            return resp.status == 200
        except Exception as e:
            logger.error("Fan control failed on %s: %s", pwm_path, e)
            return False

    def close(self) -> None:
        if self.client:
            try:
                self.client.logout()
            except Exception:
                pass
