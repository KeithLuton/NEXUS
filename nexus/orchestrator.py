"""Main orchestrator: polls sensors, runs safety core, actuates fans."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from nexus.actuator import Actuator
from nexus.arbitration import (
    ArbitrationConfig, HardwareSafetyFlags, PolicyConfig,
    StateChangeCause, SystemState,
)
from nexus.bus_bar import ActuatorLimits, BusBarConstraint
from nexus.history import History
from nexus.invariant import (
    critical_fault_trigger, detect_oscillation,
    is_divergence_detected, spigot_transition,
)
from nexus.telemetry import (
    DivergenceMetrics, SensorReader, SimplePredictor, Telemetry,
)

logger = logging.getLogger("nexus")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ThermalZone:
    zone_id: str
    sensor_paths: List[str]
    pwm_path: Optional[str] = None
    thermal_profile: str = "balanced"
    last_temp_c: Optional[float] = None
    prev_temp_c: Optional[float] = None


@dataclass
class Chassis:
    chassis_id: str
    bmc_host: str
    bmc_user: str
    bmc_password: str
    zones: List[ThermalZone]


@dataclass
class OrchestratorConfig:
    poll_interval_s: float
    chassis: List[Chassis]

    @classmethod
    def from_json(cls, path: Path) -> "OrchestratorConfig":
        raw = json.loads(path.read_text())
        chassis_list = []
        for c in raw.get("chassis", []):
            zones = [
                ThermalZone(
                    zone_id=z["zone_id"],
                    sensor_paths=z.get("sensor_paths", []),
                    pwm_path=z.get("pwm_path"),
                    thermal_profile=z.get("thermal_profile", "balanced"),
                )
                for z in c.get("thermal_zones", [])
            ]
            chassis_list.append(Chassis(
                chassis_id=c["chassis_id"],
                bmc_host=c["bmc_host"],
                bmc_user=c.get("bmc_user", "root"),
                bmc_password=c.get("bmc_password", ""),
                zones=zones,
            ))
        return cls(
            poll_interval_s=float(raw.get("poll_interval_s", 30)),
            chassis=chassis_list,
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class NexusOrchestrator:
    """Per-chassis poll loop: read sensors → compute telemetry → run safety core → actuate."""

    def __init__(self, cfg: OrchestratorConfig, state_dir: Path):
        self.cfg = cfg
        self._stop_event = threading.Event()
        self.tick = 0

        self.readers: Dict[str, SensorReader] = {}
        self.predictors: Dict[str, SimplePredictor] = {}
        self.histories: Dict[str, History] = {}
        self.actuators: Dict[str, Actuator] = {}

        self.bus_bar = BusBarConstraint(ActuatorLimits())
        self.hw_flags = HardwareSafetyFlags()
        self.policy = PolicyConfig()
        self.arb_cfg = ArbitrationConfig(policy=self.policy)

        state_dir.mkdir(parents=True, exist_ok=True)
        for chassis in self.cfg.chassis:
            reader = SensorReader(chassis.bmc_host, chassis.bmc_user, chassis.bmc_password)
            self.readers[chassis.chassis_id] = reader
            self.predictors[chassis.chassis_id] = SimplePredictor()
            hist_path = state_dir / f"{chassis.chassis_id}_history.json"
            self.histories[chassis.chassis_id] = History.load_or_default(hist_path)
            self.actuators[chassis.chassis_id] = Actuator(reader)

        # Resume from the highest persisted tick across all chassis so the
        # monotonic-tick check does not trip on restart. valid_entry_count > 0
        # indicates history was actually persisted (not a fresh default).
        persisted_histories = [h for h in self.histories.values() if h.valid_entry_count > 0]
        if persisted_histories:
            max_persisted = max(h.last_tick for h in persisted_histories)
            self.tick = max_persisted + 1
            logger.info("Resuming from tick %d (max persisted + 1)", self.tick)

    # ------------------------------------------------------------------
    # Per-tick work
    # ------------------------------------------------------------------

    def _gather_zone_temps(self, chassis: Chassis) -> Dict[str, Optional[float]]:
        reader = self.readers[chassis.chassis_id]
        reader.set_mock_tick(self.tick)
        zone_temps: Dict[str, Optional[float]] = {}
        for zone in chassis.zones:
            temps = []
            for sensor_path in zone.sensor_paths:
                t = reader.get_temperature(sensor_path)
                if t is not None:
                    temps.append(t)
            if temps:
                avg = sum(temps) / len(temps)
                zone_temps[zone.zone_id] = avg
                zone.prev_temp_c = zone.last_temp_c
                zone.last_temp_c = avg
            else:
                zone_temps[zone.zone_id] = None
        return zone_temps

    def _build_telemetry(self, chassis: Chassis,
                         zone_temps: Dict[str, Optional[float]]) -> Telemetry:
        predictor = self.predictors[chassis.chassis_id]
        primary = chassis.zones[0] if chassis.zones else None

        if primary is not None and primary.last_temp_c is not None:
            observed = primary.last_temp_c
            predicted = predictor.predict(observed)
            divergence_value = abs(observed - predicted)
            if primary.prev_temp_c is not None:
                gradient = abs(observed - primary.prev_temp_c)
            else:
                gradient = 0.0
            confidence = 0.9 if divergence_value < 2.0 else max(0.1, 0.9 - divergence_value / 10.0)
            prediction_score = 0.8 if divergence_value < 1.0 else 0.2
        else:
            divergence_value = 0.0
            gradient = 0.0
            confidence = 0.9
            prediction_score = 0.5

        div = DivergenceMetrics(spatial_rms=divergence_value, temporal_lag_ms=0.0,
                                gradient_norm=gradient)
        runaway = any(t is not None and t > 85 for t in zone_temps.values())
        return Telemetry(
            tick=self.tick,
            divergence=div,
            gradient=gradient,
            confidence=confidence,
            prediction=prediction_score,
            thermal_runaway=runaway,
            voltage_instability=False,
        )

    def poll_chassis(self, chassis: Chassis) -> Dict[str, Any]:
        hist = self.histories[chassis.chassis_id]
        actuator = self.actuators[chassis.chassis_id]

        zone_temps = self._gather_zone_temps(chassis)
        tele = self._build_telemetry(chassis, zone_temps)

        # Divergence streak tracking.
        if is_divergence_detected(tele, self.policy.divergence_threshold):
            hist.divergence_streak += 1
        else:
            hist.divergence_streak = 0

        # Monotonic tick guard.
        trigger_fault = False
        if self.tick <= hist.last_tick and hist.last_tick > 0:
            logger.error("Monotonic tick violation on %s: %d <= %d",
                         chassis.chassis_id, self.tick, hist.last_tick)
            hist.checksum_mismatch_count += 1
            constrained_state = SystemState.FAULT
            cause = StateChangeCause.CRITICAL_FAULT
            trigger_fault = True
        else:
            # Arbitration.
            next_state, cause = spigot_transition(
                hist.last_committed_state, tele, self.arb_cfg, hist)

            # Bus bar.
            primary = chassis.zones[0] if chassis.zones else None
            current_power = 50.0  # placeholder until PSU telemetry is wired in
            current_temp = primary.last_temp_c if primary and primary.last_temp_c else 40.0
            constrained_state, saturated = self.bus_bar.apply(
                next_state, current_power, current_temp)
            if saturated:
                cause = StateChangeCause.CONSTRAINT_SATURATION

            # Critical fault trigger — can override the above.
            triggered, reason = critical_fault_trigger(
                hist, self.hw_flags, tele, self.policy)
            if triggered:
                logger.critical("Critical fault on %s: %s", chassis.chassis_id, reason)
                constrained_state = SystemState.FAULT
                cause = StateChangeCause.CRITICAL_FAULT
                trigger_fault = True

        # Actuate.
        primary = chassis.zones[0] if chassis.zones else None
        if primary and primary.pwm_path:
            actuator.commit(constrained_state, primary.pwm_path)

        # Update history.
        hist.last_committed_state = constrained_state
        hist.last_tick = self.tick
        hist.valid_entry_count += 1
        hist.last_state_change_cause = cause
        if cause != StateChangeCause.NONE:
            hist.cause_history.append((self.tick, cause))
            # Trim cause history to keep file size bounded.
            if len(hist.cause_history) > 200:
                hist.cause_history = hist.cause_history[-200:]

        hist.control_output_history.append(float(constrained_state.value))
        if len(hist.control_output_history) > 20:
            hist.control_output_history.pop(0)
        hist.oscillation_detected = detect_oscillation(hist.control_output_history)

        hist.save()

        return {
            "tick": self.tick,
            "chassis_id": chassis.chassis_id,
            "state": constrained_state.name,
            "cause": cause.name,
            "temperatures_c": zone_temps,
            "divergence": tele.divergence.spatial_rms,
            "confidence": tele.confidence,
            "oscillation": hist.oscillation_detected,
            "critical_fault": trigger_fault,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, max_ticks: Optional[int] = None) -> None:
        logger.info("NEXUS orchestrator starting: %d chassis, poll interval %.1fs",
                    len(self.cfg.chassis), self.cfg.poll_interval_s)
        while not self._stop_event.is_set():
            for chassis in self.cfg.chassis:
                snapshot = self.poll_chassis(chassis)
                logger.info("snapshot %s", json.dumps(snapshot))
            self.tick += 1
            if max_ticks is not None and self.tick >= max_ticks:
                break
            self._stop_event.wait(self.cfg.poll_interval_s)
        logger.info("NEXUS orchestrator stopped.")

    def stop(self, *_: Any) -> None:
        logger.info("Shutdown requested.")
        self._stop_event.set()
        for reader in self.readers.values():
            reader.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NEXUS v5.1 thermal orchestrator")
    parser.add_argument("--config", required=True, help="Path to chassis map JSON")
    parser.add_argument("--state-dir", default="./nexus_state",
                        help="Directory for persisted history (default: ./nexus_state)")
    parser.add_argument("--log-level", default="INFO",
                        help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--max-ticks", type=int, default=None,
                        help="Stop after N ticks. Useful for smoke tests.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        logger.error("Config file not found: %s", cfg_path)
        return 2

    try:
        cfg = OrchestratorConfig.from_json(cfg_path)
    except Exception as e:
        logger.error("Invalid config: %s", e)
        return 2

    if not cfg.chassis:
        logger.error("Config loaded but contains no chassis entries.")
        return 2

    state_dir = Path(args.state_dir)
    orch = NexusOrchestrator(cfg, state_dir)
    signal.signal(signal.SIGINT, orch.stop)
    signal.signal(signal.SIGTERM, orch.stop)
    orch.run(max_ticks=args.max_ticks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
