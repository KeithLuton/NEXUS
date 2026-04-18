"""
NEXUS v4.0 - Expanded Orchestrator
Wires InputManager + SolverWrapper + OutputManager + Metrics + Events.
Replaces nexus_orchestrator.py for full-scale deployments.
Trial binary (spigot_torch) is unchanged — black box is still proprietary.
"""

import json
import time
import logging
import threading
import sys
import os
import signal

from solver_wrapper import SpigotTorchWrapper
from redfish_client import RedfishInterface

sys.path.insert(0, os.path.dirname(__file__) + "/../04_Infrastructure")
sys.path.insert(0, os.path.dirname(__file__) + "/../07_Metrics")

from nexus_input_manager import NexusInputManager
from nexus_output_manager import NexusOutputManager
from nexus_metrics import NexusMetricsExporter, NexusEventBus, SNMPTrapSender
from redfish_extended import (
    RedfishEventSubscriber, RedfishMultiChassis, RedfishThermalSubsystem
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S"
)


class NexusOrchestratorV4:
    """
    Full-scale NEXUS orchestrator.
    All signal sources → unified 32-float vector → spigot_torch → all actuators.
    """

    THERMAL_WARNING_THRESHOLD = 0.75   # normalized
    THERMAL_CRITICAL_THRESHOLD = 0.90  # normalized

    def __init__(self, config_path: str, binary_path: str,
                 bmc_host: str, bmc_user: str, bmc_pass: str):

        with open(config_path) as f:
            self.config = json.load(f)

        # Core components
        self.solver = SpigotTorchWrapper(binary_path)
        self.redfish = RedfishInterface(bmc_host, bmc_user, bmc_pass)

        # Input / output managers
        self.inputs = NexusInputManager(self.config, self.redfish)
        self.outputs = NexusOutputManager(self.config, self.redfish)

        # Metrics + events
        metrics_cfg = self.config.get("metrics", {})
        self.metrics = NexusMetricsExporter(metrics_cfg)
        self.events = NexusEventBus({**metrics_cfg,
                                     "hostname": self.config.get("hostname", "")})

        # Optional SNMP
        snmp_cfg = self.config.get("snmp", {})
        self.snmp = SNMPTrapSender(snmp_cfg) if snmp_cfg.get("enabled") else None

        # Optional extended Redfish
        self.thermal_subsystem = RedfishThermalSubsystem(
            self.redfish, self.config.get("chassis_id", "Self"))
        self.multi_chassis = None
        self.event_subscriber = None

        # Redfish event subscriptions
        rf_events = self.config.get("redfish_events", {})
        if rf_events.get("subscribe_push") or rf_events.get("subscribe_sse"):
            self.event_subscriber = RedfishEventSubscriber(
                self.redfish, rf_events,
                on_event=self._handle_redfish_event
            )

        # State
        self._loop_times = []
        self._running = False
        self._control_thread = None
        self._last_predictions = [0.0] * 32

    def start(self):
        """Start all subsystems and the control loop."""
        logger.info("NEXUS v4.0 starting...")

        self.inputs.start()

        if self.config.get("metrics", {}).get("enabled", True):
            self.metrics.start()

        if self.event_subscriber:
            rf_events = self.config.get("redfish_events", {})
            if rf_events.get("subscribe_sse"):
                self.event_subscriber.subscribe_sse()
            if rf_events.get("subscribe_push"):
                wh_host = rf_events.get("webhook_host", "")
                if wh_host:
                    self.event_subscriber.subscribe_push(wh_host)

        self._running = True
        self._control_thread = threading.Thread(
            target=self._control_loop, daemon=True, name="nexus-control")
        self._control_thread.start()

        logger.info("NEXUS v4.0 operational")

    def stop(self):
        """Graceful shutdown."""
        logger.info("NEXUS shutting down...")
        self._running = False
        self.inputs.stop()
        self.outputs.safe_shutdown()
        self.metrics.stop()
        if self.event_subscriber:
            self.event_subscriber.unsubscribe()
        if self._control_thread:
            self._control_thread.join(timeout=3)
        logger.info("NEXUS stopped")

    def _control_loop(self):
        """Main 15-25ms control loop."""
        target_interval = self.config.get("constraints", {}).get(
            "control_loop_target_ms", 25) / 1000.0

        while self._running:
            t0 = time.time()
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Control loop error: {e}")
                self.events.fire("ACTUATION_FAILURE", str(e))

            elapsed = time.time() - t0
            sleep_time = max(0.0, target_interval - elapsed)
            time.sleep(sleep_time)

    def _tick(self):
        """Single control loop iteration."""
        loop_start = time.time()

        # 1. Get unified input vector
        input_vector = self.inputs.get_vector()

        # 2. Check for stale inputs
        stale = self.inputs.vector.staleness_check(max_age_s=2.0)
        if stale:
            self.events.fire("INPUT_STALE",
                             f"Stale input slots: {stale[:5]}",
                             {"slots": stale})

        # 3. Solve — proprietary spigot_torch kernel
        solver_start = time.time()
        predictions = self.solver.solve(input_vector)
        solver_ms = (time.time() - solver_start) * 1000

        if not predictions:
            self.events.fire("SOLVER_TIMEOUT",
                             "spigot_torch returned None — check trial license")
            return

        self._last_predictions = list(predictions)

        # 4. Thermal threshold checks + events
        self._check_thresholds(predictions, input_vector)

        # 5. Actuate all outputs
        actuation_result = self.outputs.actuate(list(predictions))

        # 6. Metrics update
        loop_ms = (time.time() - loop_start) * 1000
        self._loop_times.append(loop_ms)

        zone_setpoints = {}
        for i in range(min(8, len(predictions))):
            from nexus_output_manager import prediction_to_pwm
            zone_setpoints[i] = prediction_to_pwm(predictions[i])

        self.metrics.update_from_loop(
            input_vector, list(predictions),
            solver_ms, loop_ms, actuation_result, zone_setpoints
        )

        # SNMP trap if enabled and threshold exceeded
        if self.snmp:
            for i, p in enumerate(predictions[:8]):
                if p >= self.THERMAL_WARNING_THRESHOLD:
                    self.snmp.send_thermal_trap(i, p)

        logger.debug(
            f"Tick: solver={solver_ms:.1f}ms loop={loop_ms:.1f}ms "
            f"acts={actuation_result.get('actuations', 0)}"
        )

    def _check_thresholds(self, predictions: list, input_vector: list):
        max_pred = max(predictions[:12]) if predictions else 0.0

        if max_pred >= self.THERMAL_CRITICAL_THRESHOLD:
            hottest_zone = predictions[:12].index(max_pred)
            self.events.fire(
                "THERMAL_CRITICAL",
                f"Zone {hottest_zone} prediction {max_pred:.2f} >= critical threshold",
                {"zone": hottest_zone, "prediction": max_pred,
                 "cpu_temp": input_vector[12], "gpu_temp": input_vector[16]}
            )
        elif max_pred >= self.THERMAL_WARNING_THRESHOLD:
            hottest_zone = predictions[:12].index(max_pred)
            self.events.fire(
                "THERMAL_WARNING",
                f"Zone {hottest_zone} prediction {max_pred:.2f} >= warning threshold",
                {"zone": hottest_zone, "prediction": max_pred}
            )

    def _handle_redfish_event(self, event: dict):
        """Handle push events from Redfish EventService."""
        msg_id = event.get("MessageId", "")
        severity = event.get("Severity", "").lower()

        if "overtemperature" in msg_id.lower() or severity == "critical":
            logger.warning(f"BMC thermal event: {event.get('Message', '')}")
            # Trigger an immediate tick at elevated response
            self.events.fire("THERMAL_CRITICAL",
                             f"BMC push event: {msg_id}",
                             event)

    def process_intent(self, intent_data: dict) -> dict:
        """
        HTTP API compatibility shim — accepts workload intent from
        workload_proxy_ingress.py and injects into input vector.
        Supplements automatic polling; does not replace it.
        """
        vec = self.inputs.vector

        cpu_zones = intent_data.get("cpu_zones", [0.0] * 4)
        for i, val in enumerate(cpu_zones[:4]):
            current = vec._data[i]
            # Blend: take max of polled vs. reported intent
            vec.write(i, max(float(val), current), "intent_api")

        gpu_zones = intent_data.get("gpu_zones", [0.0] * 4)
        for i, val in enumerate(gpu_zones[:4]):
            current = vec._data[4 + i]
            vec.write(4 + i, max(float(val), current), "intent_api")

        mem = float(intent_data.get("mem_load", 0.0))
        vec.write(8, max(mem, vec._data[8]), "intent_api")

        return {"status": "intent_blended", "deterministic_gap": "closing"}

    def get_stats(self) -> dict:
        if not self._loop_times:
            return {"loops": 0, "min_ms": 0, "max_ms": 0, "avg_ms": 0}
        return {
            "loops": len(self._loop_times),
            "min_ms": round(min(self._loop_times), 2),
            "max_ms": round(max(self._loop_times), 2),
            "avg_ms": round(sum(self._loop_times) / len(self._loop_times), 2),
            "input_diagnostics": self.inputs.get_diagnostics(),
            "output_stats": self.outputs.get_stats(),
        }


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="NEXUS v4.0 Thermal Engine")
    parser.add_argument("--bmc-host",    required=True)
    parser.add_argument("--bmc-user",    default="admin")
    parser.add_argument("--bmc-pass",    required=True)
    parser.add_argument("--config",      default="06_Configuration/chassis_map.json")
    parser.add_argument("--binary",      default="02_Proprietary_Engine/spigot_torch_LINUX_x86_64")
    parser.add_argument("--api-port",    type=int, default=8000)
    args = parser.parse_args()

    orchestrator = NexusOrchestratorV4(
        config_path=args.config,
        binary_path=args.binary,
        bmc_host=args.bmc_host,
        bmc_user=args.bmc_user,
        bmc_pass=args.bmc_pass,
    )

    def shutdown(sig, frame):
        logger.info(f"Signal {sig} received")
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    orchestrator.start()

    # Start HTTP API on top of v4 orchestrator
    from workload_proxy_ingress import start_ingress
    start_ingress(orchestrator, port=args.api_port)


if __name__ == "__main__":
    main()
