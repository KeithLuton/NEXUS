"""
NEXUS v4.0 - Unified Output Manager
Routes solver predictions to ALL actuator types.

Prediction vector slot assignments (mirrors input map):
  [0-3]   CPU zone cooling targets (fan or liquid cold plate)
  [4-7]   GPU zone cooling targets
  [8]     Memory zone cooling target
  [9]     Storage zone cooling target
  [10]    Network zone cooling target
  [11]    System/chassis exhaust target
  [12-15] Spare zone targets
  [16+]   Reserved

Supported actuator types:
  - Redfish Fan (PWM % via PATCH /Controls)
  - Redfish CoolingUnit pump (via CoolingUnit schema)
  - IPMI raw fan control (ipmitool raw 0x30 commands)
  - Linux PWM via sysfs (/sys/class/hwmon/hwmonX/pwmN)
  - OCP Rack Management Interface (RMI) fan bus
  - TEC (thermoelectric cooler) setpoint
  - Liquid cooling pump (0-100% via Redfish or direct)
  - CDU valve position (0-100% via Redfish CoolingUnit)
  - Prometheus/OpenTelemetry metrics push
  - Webhook event notifications
"""

import time
import logging
import subprocess
import json
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# PWM mapping helpers
# ─────────────────────────────────────────────────────────

def prediction_to_pwm(predicted: float, min_pwm: int = 20, max_pwm: int = 100) -> int:
    """
    Convert normalized solver prediction (0.0-1.0) to PWM setpoint (min_pwm-max_pwm).
    Non-linear mapping: aggressive at high temps, conservative at low.
    """
    clamped = max(0.0, min(1.0, float(predicted)))
    # Quadratic curve — more aggressive response as prediction approaches 1.0
    curved = clamped ** 0.75
    return int(min_pwm + curved * (max_pwm - min_pwm))

def prediction_to_pump_pct(predicted: float, min_pct: int = 30, max_pct: int = 100) -> int:
    """Convert prediction to liquid pump speed %. Higher floor than fans for liquid."""
    clamped = max(0.0, min(1.0, float(predicted)))
    return int(min_pct + clamped * (max_pct - min_pct))

def prediction_to_valve_pct(predicted: float) -> int:
    """CDU bypass valve: 0 = fully closed (all flow to load), 100 = fully open (bypass)."""
    # As thermal load rises, close bypass valve to maximize cold plate flow
    return int((1.0 - min(1.0, float(predicted))) * 100)


# ─────────────────────────────────────────────────────────
# Actuator: Redfish Fan (base + extended)
# ─────────────────────────────────────────────────────────

class RedfishFanActuator:
    """
    Standard Redfish fan/pump control via PATCH /Controls/{id}.
    Vendor-agnostic: iDRAC, iLO, OpenBMC, AMI, Insyde.
    """

    def __init__(self, redfish_client, chassis_id: str, config: dict):
        self.rf = redfish_client
        self.chassis_id = chassis_id
        self.min_pwm = config.get("min_fan_pwm", 20)
        self.max_pwm = config.get("max_fan_pwm", 100)

    def actuate(self, control_id: str, prediction: float) -> bool:
        pwm = prediction_to_pwm(prediction, self.min_pwm, self.max_pwm)
        result = self.rf.patch_control(self.chassis_id, control_id, pwm)
        return result is not None

    def actuate_all(self, zones: list, predictions: list) -> int:
        """Actuate all zones. Returns count of successful actuations."""
        count = 0
        for zone in zones:
            zone_id = zone.get("zone_id", 0)
            if zone_id >= len(predictions):
                continue
            prediction = predictions[zone_id]
            for actuator in zone.get("actuators", []):
                if actuator.get("type") in ("Fan", "fan"):
                    if self.actuate(actuator["redfish_id"], prediction):
                        count += 1
        return count


# ─────────────────────────────────────────────────────────
# Actuator: Redfish CoolingUnit (liquid CDU pump + valve)
# ─────────────────────────────────────────────────────────

class RedfishCoolingUnitActuator:
    """
    Liquid cooling CDU control via Redfish CoolingUnit schema.
    Controls pump speed and bypass valve position.
    Path: /redfish/v1/ThermalEquipment/CDUs/{id}/CoolantConnectors
    """

    def __init__(self, redfish_client, config: dict):
        self.rf = redfish_client
        self.min_pump = config.get("min_pump_pct", 30)
        self.max_pump = config.get("max_pump_pct", 100)
        self._cdu_url = None
        self._discover_cdu()

    def _discover_cdu(self):
        try:
            url = f"{self.rf.base_url}/ThermalEquipment/CDUs"
            resp = self.rf.session.get(url)
            if resp.status_code == 200:
                members = resp.json().get("Members", [])
                if members:
                    path = members[0].get("@odata.id", "")
                    host = self.rf.base_url.split("/redfish")[0]
                    self._cdu_url = host + path
                    logger.info(f"CDU discovered at {self._cdu_url}")
        except Exception as e:
            logger.debug(f"CDU discovery failed: {e}")

    def actuate_pump(self, prediction: float) -> bool:
        if not self._cdu_url:
            return False
        pump_pct = prediction_to_pump_pct(prediction, self.min_pump, self.max_pump)
        try:
            resp = self.rf.session.patch(
                f"{self._cdu_url}/PrimaryCoolantConnectors",
                json={"PumpSpeedPercent": pump_pct}
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"CDU pump actuate failed: {e}")
            return False

    def actuate_valve(self, prediction: float) -> bool:
        if not self._cdu_url:
            return False
        valve_pct = prediction_to_valve_pct(prediction)
        try:
            resp = self.rf.session.patch(
                f"{self._cdu_url}",
                json={"BypassValvePosition": valve_pct}
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"CDU valve actuate failed: {e}")
            return False


# ─────────────────────────────────────────────────────────
# Actuator: IPMI raw fan control
# ─────────────────────────────────────────────────────────

class IPMIFanActuator:
    """
    Direct IPMI fan control via ipmitool raw commands.
    Fallback for servers without Redfish Controls endpoint.
    Supports Dell iDRAC, HPE iLO, Supermicro, and generic IPMI 2.0.
    """

    # Raw IPMI commands by vendor — add new vendors here
    VENDOR_COMMANDS = {
        "dell": {
            "manual_mode": ["ipmitool", "raw", "0x30", "0x30", "0x01", "0x00"],
            "set_fan": lambda pct: ["ipmitool", "raw", "0x30", "0x30", "0x02",
                                    "0xff", hex(pct)],
        },
        "supermicro": {
            "manual_mode": ["ipmitool", "raw", "0x30", "0x45", "0x01", "0x01"],
            "set_fan": lambda pct: ["ipmitool", "raw", "0x30", "0x70", "0x66",
                                    "0x01", "0x00", hex(pct)],
        },
        "hpe": {
            # iLO uses Redfish for fan control — IPMI path not recommended
            "manual_mode": None,
            "set_fan": None,
        },
        "generic": {
            # Standard IPMI fan control (not all BMCs support raw fan commands)
            "manual_mode": None,
            "set_fan": lambda pct: ["ipmitool", "raw", "0x30", "0x30", "0x02",
                                    "0xff", hex(pct)],
        }
    }

    def __init__(self, config: dict):
        self.vendor = config.get("ipmi_vendor", "generic").lower()
        self.host = config.get("ipmi_host", "")
        self.user = config.get("ipmi_user", "admin")
        self.password = config.get("ipmi_password", "")
        self.min_pwm = config.get("min_fan_pwm", 20)
        self.max_pwm = config.get("max_fan_pwm", 100)
        self._available = self._check_and_init()

    def _run(self, cmd: list) -> bool:
        if self.host:
            cmd = cmd[:1] + ["-I", "lanplus", "-H", self.host,
                             "-U", self.user, "-P", self.password] + cmd[1:]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"IPMI command failed: {e}")
            return False

    def _check_and_init(self) -> bool:
        try:
            subprocess.run(["ipmitool", "--version"], capture_output=True, timeout=3)
        except FileNotFoundError:
            return False

        vendor_cmds = self.VENDOR_COMMANDS.get(self.vendor,
                                                self.VENDOR_COMMANDS["generic"])
        manual_cmd = vendor_cmds.get("manual_mode")
        if manual_cmd:
            success = self._run(manual_cmd)
            if success:
                logger.info(f"IPMI fan control: {self.vendor} manual mode enabled")
            return success
        return True

    def actuate(self, prediction: float) -> bool:
        if not self._available:
            return False
        pwm = prediction_to_pwm(prediction, self.min_pwm, self.max_pwm)
        vendor_cmds = self.VENDOR_COMMANDS.get(self.vendor,
                                                self.VENDOR_COMMANDS["generic"])
        set_fn = vendor_cmds.get("set_fan")
        if not set_fn:
            return False
        return self._run(set_fn(pwm))


# ─────────────────────────────────────────────────────────
# Actuator: Linux sysfs PWM (in-band)
# ─────────────────────────────────────────────────────────

class LinuxSysfsPWMActuator:
    """
    Direct Linux hwmon PWM control via /sys/class/hwmon.
    Works in-band without BMC. Useful for embedded or DIY cooling systems.
    Requires: pwmX_enable set to 1 (manual control).
    """

    def __init__(self, config: dict):
        self.hwmon_path = config.get("hwmon_path", "/sys/class/hwmon/hwmon0")
        self.pwm_channels = config.get("pwm_channels", [1, 2, 3, 4])
        self.min_pwm = config.get("min_fan_pwm", 50)   # 0-255 scale for sysfs
        self.max_pwm = 255
        self._available = os.path.exists(self.hwmon_path)
        if self._available:
            self._enable_manual_mode()

    def _enable_manual_mode(self):
        for ch in self.pwm_channels:
            enable_path = f"{self.hwmon_path}/pwm{ch}_enable"
            if os.path.exists(enable_path):
                try:
                    with open(enable_path, "w") as f:
                        f.write("1")  # 1 = manual
                except OSError as e:
                    logger.warning(f"Could not enable manual PWM on channel {ch}: {e}")

    def actuate(self, channel: int, prediction: float) -> bool:
        if not self._available:
            return False
        pwm_path = f"{self.hwmon_path}/pwm{channel}"
        if not os.path.exists(pwm_path):
            return False
        # Scale: sysfs PWM is 0-255
        min_raw = int(self.min_pwm * 255 / 100)
        pwm_raw = int(min_raw + prediction * (255 - min_raw))
        pwm_raw = max(0, min(255, pwm_raw))
        try:
            with open(pwm_path, "w") as f:
                f.write(str(pwm_raw))
            return True
        except OSError as e:
            logger.error(f"sysfs PWM write error on channel {channel}: {e}")
            return False

    def actuate_all_zones(self, predictions: list) -> int:
        count = 0
        for i, ch in enumerate(self.pwm_channels):
            if i < len(predictions):
                if self.actuate(ch, predictions[i]):
                    count += 1
        return count


# ─────────────────────────────────────────────────────────
# Actuator: OCP RMI (rack-level fan bus)
# ─────────────────────────────────────────────────────────

class OCPRackFanActuator:
    """
    OCP Rack Management Interface fan control.
    Sends zone-level PWM commands to the OCP rack fan bus controller.
    Uses HTTP REST to OCP shelf manager.
    """

    def __init__(self, config: dict):
        self.shelf_manager_url = config.get("ocp_shelf_manager_url", "")
        self.rack_id = config.get("ocp_rack_id", "1")
        self.min_pwm = config.get("min_fan_pwm", 20)
        self.max_pwm = config.get("max_fan_pwm", 100)
        self._available = bool(self.shelf_manager_url)

    def actuate_zone(self, zone_id: int, prediction: float,
                     session) -> bool:
        if not self._available:
            return False
        pwm = prediction_to_pwm(prediction, self.min_pwm, self.max_pwm)
        try:
            url = (f"{self.shelf_manager_url}/api/v1/racks/{self.rack_id}"
                   f"/fans/zones/{zone_id}/setpoint")
            resp = session.patch(url, json={"pwm_percent": pwm}, timeout=0.05)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"OCP RMI zone {zone_id} actuate failed: {e}")
            return False


# ─────────────────────────────────────────────────────────
# Master Output Manager
# ─────────────────────────────────────────────────────────

class NexusOutputManager:
    """
    Routes solver prediction vector to all configured actuators.
    Handles priority: Redfish > IPMI > sysfs (in that order, first available wins).
    Safety guard: enforces min PWM floor and thermal cutoff thresholds.
    """

    def __init__(self, config: dict, redfish_client=None):
        self.config = config
        self.zones = config.get("zones", [])
        self.constraints = config.get("constraints", {})
        self.safety_threshold = self.constraints.get("thermal_safety_threshold", 95.0)
        self._actuators = []
        self._redfish_fan = None
        self._cdu = None
        self._ipmi_fan = None
        self._sysfs_pwm = None
        self._ocp_rmi = None
        self._stats = {"total_actuations": 0, "errors": 0, "last_loop_ms": 0.0}

        enabled = config.get("enabled_outputs", {})

        if redfish_client and enabled.get("redfish_fan", True):
            self._redfish_fan = RedfishFanActuator(
                redfish_client, config.get("chassis_id", "Self"), self.constraints)
            logger.info("Output: Redfish fan/pump control")

        if redfish_client and enabled.get("redfish_cdu", False):
            self._cdu = RedfishCoolingUnitActuator(redfish_client, config)
            logger.info("Output: Redfish CoolingUnit (CDU liquid)")

        if enabled.get("ipmi_fan", False):
            self._ipmi_fan = IPMIFanActuator(config)
            logger.info(f"Output: IPMI fan ({config.get('ipmi_vendor', 'generic')})")

        if enabled.get("sysfs_pwm", False):
            self._sysfs_pwm = LinuxSysfsPWMActuator(config)
            logger.info("Output: Linux sysfs PWM")

        if enabled.get("ocp_rmi", False):
            self._ocp_rmi = OCPRackFanActuator(config)
            logger.info("Output: OCP Rack Management Interface")

    def actuate(self, predictions: list) -> dict:
        """
        Route solver predictions to all enabled actuators.
        predictions: 32-float list from solver.
        Returns actuation result dict.
        """
        t0 = time.time()
        total = 0
        errors = 0

        if not predictions or len(predictions) < 12:
            return {"status": "error", "message": "Invalid prediction vector"}

        # Safety gate: if any high-temp zone prediction is maxed, ensure minimum
        # safety floor is met regardless of solver output
        predictions = self._apply_safety_floor(predictions)

        # 1. Redfish fans (primary)
        if self._redfish_fan:
            try:
                count = self._redfish_fan.actuate_all(self.zones, predictions)
                total += count
            except Exception as e:
                logger.error(f"Redfish fan actuate error: {e}")
                errors += 1
                # Fall through to IPMI backup

        # 2. IPMI fan (backup or additional zones)
        if self._ipmi_fan:
            try:
                max_pred = max(predictions[:12])
                if self._ipmi_fan.actuate(max_pred):
                    total += 1
            except Exception as e:
                logger.error(f"IPMI fan actuate error: {e}")
                errors += 1

        # 3. Liquid cooling CDU (parallel with fans)
        if self._cdu:
            try:
                cpu_pred = max(predictions[0:4])
                gpu_pred = max(predictions[4:8])
                combined = max(cpu_pred, gpu_pred)
                self._cdu.actuate_pump(combined)
                self._cdu.actuate_valve(combined)
                total += 1
            except Exception as e:
                logger.error(f"CDU actuate error: {e}")
                errors += 1

        # 4. Linux sysfs PWM (in-band, runs in parallel)
        if self._sysfs_pwm:
            try:
                count = self._sysfs_pwm.actuate_all_zones(predictions)
                total += count
            except Exception as e:
                logger.error(f"sysfs PWM actuate error: {e}")
                errors += 1

        # 5. OCP RMI (rack-level)
        if self._ocp_rmi and hasattr(self._ocp_rmi, '_session'):
            try:
                for i, zone in enumerate(self.zones):
                    if i < len(predictions):
                        self._ocp_rmi.actuate_zone(i, predictions[i],
                                                    self._ocp_rmi._session)
                        total += 1
            except Exception as e:
                logger.error(f"OCP RMI actuate error: {e}")
                errors += 1

        elapsed_ms = (time.time() - t0) * 1000
        self._stats["total_actuations"] += total
        self._stats["errors"] += errors
        self._stats["last_loop_ms"] = elapsed_ms

        return {
            "status": "success" if errors == 0 else "partial",
            "actuations": total,
            "errors": errors,
            "actuation_ms": round(elapsed_ms, 2),
        }

    def _apply_safety_floor(self, predictions: list) -> list:
        """
        Enforce minimum fan speed if any prediction exceeds safety threshold.
        Safety threshold is in normalized units (0.0-1.0).
        """
        safety_norm = self.safety_threshold / 100.0
        result = list(predictions)
        if any(p >= safety_norm for p in predictions[:12]):
            floor = self.constraints.get("min_fan_pwm", 20) / 100.0
            result = [max(floor, p) for p in result]
        return result

    def emergency_max(self) -> bool:
        """Drive all actuators to 100% — thermal emergency."""
        logger.critical("THERMAL EMERGENCY: Driving all actuators to 100%")
        max_vector = [1.0] * VECTOR_SIZE
        result = self.actuate(max_vector)
        return result["errors"] == 0

    def safe_shutdown(self) -> bool:
        """Set fans to safe idle before shutdown."""
        idle = [0.2] * VECTOR_SIZE
        return self.actuate(idle)["errors"] == 0

    def get_stats(self) -> dict:
        return dict(self._stats)


VECTOR_SIZE = 32
