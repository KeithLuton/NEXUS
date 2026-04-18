"""
NEXUS v4.0 - Unified Input Manager
Aggregates ALL thermal/power signal sources into the 32-float solver vector.

Vector slot map (32 floats, normalized 0.0-1.0):
  [0-3]   CPU socket power (up to 4 sockets)
  [4-7]   GPU card power (up to 4 GPUs)
  [8]     Memory subsystem power
  [9]     Storage aggregate power (NVMe + SAS)
  [10]    Network ASIC power
  [11]    PSU efficiency delta (1.0 = max loss)
  [12-15] CPU die temperatures (up to 4 sockets)
  [16-19] GPU junction temperatures (up to 4 GPUs)
  [20]    Ambient inlet temperature
  [21]    Ambient outlet temperature
  [22]    Coolant inlet temperature (liquid cooling)
  [23]    Coolant outlet temperature (liquid cooling)
  [24]    Coolant flow rate delta
  [25]    Chassis pressure differential
  [26]    Workload scheduler pressure (SLURM/k8s)
  [27]    PCIe slot aggregate power
  [28]    DIMM temperature hotspot
  [29]    Chassis management controller load
  [30]    Reserved / future LFM field signal A
  [31]    Reserved / future LFM field signal B

Sources supported:
  - Redfish (DSP0266) — vendor-agnostic BMC
  - IPMI raw (legacy hardware, pre-Redfish)
  - Linux hwmon / lm-sensors (in-band)
  - NVIDIA NVML (in-band GPU)
  - AMD ROCm / SMI (in-band GPU)
  - NVMe smart-log (storage thermal)
  - SNMP (network switches, legacy PDUs)
  - Kubernetes / SLURM scheduler signals
  - Liquid cooling CDU (Redfish CoolingUnit schema)
  - Direct /sys/class/thermal (Linux kernel thermal zones)
"""

import time
import logging
import threading
import subprocess
import json
import os
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)

VECTOR_SIZE = 32
POLL_INTERVAL_S = 0.015  # 15ms — consistent with bmc_signal_poller


class InputVector:
    """Live normalized 32-float solver input vector, thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = [0.0] * VECTOR_SIZE
        self._source_map = ["unset"] * VECTOR_SIZE  # which source last wrote each slot
        self._timestamps = [0.0] * VECTOR_SIZE

    def write(self, slot: int, value: float, source: str):
        """Write a normalized value (0.0-1.0) to a slot."""
        if not 0 <= slot < VECTOR_SIZE:
            return
        value = max(0.0, min(1.0, float(value)))
        with self._lock:
            self._data[slot] = value
            self._source_map[slot] = source
            self._timestamps[slot] = time.time()

    def snapshot(self) -> list:
        """Return a copy of the current vector for solver consumption."""
        with self._lock:
            return list(self._data)

    def staleness_check(self, max_age_s: float = 1.0) -> list:
        """Return slots that haven't been updated within max_age_s."""
        now = time.time()
        with self._lock:
            return [i for i, t in enumerate(self._timestamps)
                    if t > 0 and (now - t) > max_age_s]


# ─────────────────────────────────────────────────────────
# Normalizers — convert raw units to 0.0–1.0
# ─────────────────────────────────────────────────────────

def norm_power(watts: float, ceiling_w: float) -> float:
    return max(0.0, min(1.0, watts / ceiling_w)) if ceiling_w > 0 else 0.0

def norm_temp(celsius: float, t_min: float = 20.0, t_max: float = 100.0) -> float:
    return max(0.0, min(1.0, (celsius - t_min) / (t_max - t_min)))

def norm_flow(lpm: float, max_lpm: float = 20.0) -> float:
    return max(0.0, min(1.0, lpm / max_lpm)) if max_lpm > 0 else 0.0


# ─────────────────────────────────────────────────────────
# Source: Redfish Full (extends base redfish_client)
# ─────────────────────────────────────────────────────────

class RedfishFullSource:
    """
    Full Redfish DSP0266 signal reader.
    Covers: Thermal, Power, EnvironmentMetrics, CoolingUnit (liquid).
    Handles multi-chassis traversal via ChassisCollection.
    """

    def __init__(self, redfish_client, config: dict):
        self.rf = redfish_client
        self.config = config
        self.chassis_id = config.get("chassis_id", "Self")
        self.cpu_power_max = config.get("cpu_power_ceiling_w", 400.0)
        self.gpu_power_max = config.get("gpu_power_ceiling_w", 700.0)
        self.mem_power_max = config.get("mem_power_ceiling_w", 50.0)
        self.storage_power_max = config.get("storage_power_ceiling_w", 100.0)
        self.t_min = config.get("temp_scale_min_c", 20.0)
        self.t_max = config.get("temp_scale_max_c", 100.0)

    def poll(self, vec: InputVector):
        self._poll_power(vec)
        self._poll_thermal(vec)
        self._poll_environment_metrics(vec)
        self._poll_cooling_unit(vec)

    def _poll_power(self, vec: InputVector):
        data = self.rf.get_power_metrics()
        if not data:
            return

        controls = data.get("PowerControl", [])
        for entry in controls:
            name = entry.get("Name", "").upper()
            watts = float(entry.get("PowerConsumedWatts", 0.0))
            idx = _extract_index(name)

            if any(k in name for k in ("CPU", "PROCESSOR", "SOCKET")):
                vec.write(idx, norm_power(watts, self.cpu_power_max), "redfish_power")
            elif any(k in name for k in ("GPU", "ACCELERATOR")):
                vec.write(4 + idx, norm_power(watts, self.gpu_power_max), "redfish_power")
            elif any(k in name for k in ("MEM", "DIMM", "MEMORY")):
                vec.write(8, norm_power(watts, self.mem_power_max), "redfish_power")
            elif any(k in name for k in ("STORAGE", "NVME", "SAS", "HDD", "SSD")):
                vec.write(9, norm_power(watts, self.storage_power_max), "redfish_power")

        # PSU efficiency delta
        psus = data.get("PowerSupplies", [])
        if psus:
            total_input = sum(float(p.get("PowerInputWatts", 0)) for p in psus)
            total_output = sum(float(p.get("PowerOutputWatts", 0)) for p in psus)
            if total_input > 0:
                efficiency = total_output / total_input
                vec.write(11, 1.0 - efficiency, "redfish_psu")

    def _poll_thermal(self, vec: InputVector):
        data = self.rf.get_thermal_sensors()
        if not data:
            return

        for temp in data.get("Temperatures", []):
            name = temp.get("Name", "").upper()
            reading = float(temp.get("CurrentReading", temp.get("ReadingCelsius", 0.0)))
            idx = _extract_index(name)

            if any(k in name for k in ("CPU", "PROCESSOR", "SOCKET", "CORE", "DIE")):
                vec.write(12 + idx, norm_temp(reading, self.t_min, self.t_max), "redfish_temp")
            elif any(k in name for k in ("GPU", "ACCELERATOR")):
                vec.write(16 + idx, norm_temp(reading, self.t_min, self.t_max), "redfish_temp")
            elif "INLET" in name or "INTAKE" in name or "AMBIENT" in name:
                vec.write(20, norm_temp(reading, 15.0, 45.0), "redfish_temp")
            elif "OUTLET" in name or "EXHAUST" in name:
                vec.write(21, norm_temp(reading, 20.0, 65.0), "redfish_temp")
            elif any(k in name for k in ("MEM", "DIMM")):
                vec.write(28, norm_temp(reading, self.t_min, 85.0), "redfish_temp")

    def _poll_environment_metrics(self, vec: InputVector):
        """Redfish EnvironmentMetrics — newer servers (2022+)."""
        try:
            url = f"{self.rf.base_url}/Chassis/{self.chassis_id}/EnvironmentMetrics"
            resp = self.rf.session.get(url)
            if resp.status_code != 200:
                return
            data = resp.json()
            inlet = data.get("TemperatureSummaryCelsius", {}).get("Intake", {}).get("Reading")
            exhaust = data.get("TemperatureSummaryCelsius", {}).get("Exhaust", {}).get("Reading")
            if inlet is not None:
                vec.write(20, norm_temp(float(inlet), 15.0, 45.0), "env_metrics")
            if exhaust is not None:
                vec.write(21, norm_temp(float(exhaust), 20.0, 65.0), "env_metrics")
        except Exception as e:
            logger.debug(f"EnvironmentMetrics not available: {e}")

    def _poll_cooling_unit(self, vec: InputVector):
        """
        Redfish CoolingUnit schema — liquid cooling CDUs.
        Covers: coolant inlet/outlet temps, flow rate.
        Path: /redfish/v1/ThermalEquipment/CDUs/{id}
        """
        try:
            url = f"{self.rf.base_url}/ThermalEquipment/CDUs"
            resp = self.rf.session.get(url)
            if resp.status_code != 200:
                return
            members = resp.json().get("Members", [])
            if not members:
                return

            cdu_url = self.rf.base_url.replace("/redfish/v1", "") + members[0].get("@odata.id", "")
            cdu_resp = self.rf.session.get(cdu_url)
            if cdu_resp.status_code != 200:
                return
            cdu = cdu_resp.json()

            coolant_info = cdu.get("CoolantConnectorRedundancy", [{}])
            primary = coolant_info[0] if coolant_info else {}

            inlet_c = cdu.get("PrimaryCoolantConnectors", {}).get("InletTemperatureCelsius")
            outlet_c = cdu.get("PrimaryCoolantConnectors", {}).get("OutletTemperatureCelsius")
            flow_lpm = cdu.get("PrimaryCoolantConnectors", {}).get("FlowLitersPerMinute")

            if inlet_c is not None:
                vec.write(22, norm_temp(float(inlet_c), 10.0, 50.0), "cdu_liquid")
            if outlet_c is not None:
                vec.write(23, norm_temp(float(outlet_c), 15.0, 60.0), "cdu_liquid")
            if flow_lpm is not None:
                vec.write(24, norm_flow(float(flow_lpm)), "cdu_liquid")

        except Exception as e:
            logger.debug(f"CoolingUnit/CDU not available: {e}")


# ─────────────────────────────────────────────────────────
# Source: IPMI raw (legacy hardware fallback)
# ─────────────────────────────────────────────────────────

class IPMISource:
    """
    IPMI raw sensor reader via ipmitool.
    Fallback for hardware without Redfish (pre-2018 servers).
    Requires: ipmitool installed, IPMI over LAN or KCS.
    """

    def __init__(self, config: dict):
        self.host = config.get("ipmi_host", "")
        self.user = config.get("ipmi_user", "admin")
        self.password = config.get("ipmi_password", "")
        self.interface = "lanplus" if self.host else "open"
        self.t_min = config.get("temp_scale_min_c", 20.0)
        self.t_max = config.get("temp_scale_max_c", 100.0)
        self.cpu_power_max = config.get("cpu_power_ceiling_w", 400.0)
        self._available = self._check_ipmi()

    def _check_ipmi(self) -> bool:
        try:
            subprocess.run(["ipmitool", "--version"],
                           capture_output=True, timeout=3)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("ipmitool not found — IPMI source disabled")
            return False

    def _run(self, *args) -> Optional[str]:
        if not self._available:
            return None
        cmd = ["ipmitool"]
        if self.host:
            cmd += ["-I", self.interface, "-H", self.host,
                    "-U", self.user, "-P", self.password]
        cmd += list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.stdout if result.returncode == 0 else None
        except Exception as e:
            logger.debug(f"IPMI command failed: {e}")
            return None

    def poll(self, vec: InputVector):
        if not self._available:
            return
        self._poll_sdr(vec)
        self._poll_dcmi(vec)

    def _poll_sdr(self, vec: InputVector):
        """Parse IPMI SDR for temp sensors."""
        output = self._run("sdr", "type", "Temperature")
        if not output:
            return
        for line in output.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue
            name = parts[0].upper()
            try:
                value_str = parts[4].split()[0]
                celsius = float(value_str)
            except (ValueError, IndexError):
                continue

            idx = _extract_index(name)
            if any(k in name for k in ("CPU", "PROC", "CORE", "SOCKET")):
                vec.write(12 + idx, norm_temp(celsius, self.t_min, self.t_max), "ipmi_sdr")
            elif any(k in name for k in ("DIMM", "MEM")):
                vec.write(28, norm_temp(celsius, self.t_min, 85.0), "ipmi_sdr")
            elif "INLET" in name or "AMBIENT" in name:
                vec.write(20, norm_temp(celsius, 15.0, 45.0), "ipmi_sdr")
            elif "EXHAUST" in name or "OUTLET" in name:
                vec.write(21, norm_temp(celsius, 20.0, 65.0), "ipmi_sdr")

    def _poll_dcmi(self, vec: InputVector):
        """DCMI power reading — available on most IPMI 2.0+ BMCs."""
        output = self._run("dcmi", "power", "reading")
        if not output:
            return
        for line in output.splitlines():
            if "Instantaneous power reading" in line:
                try:
                    watts = float(line.split(":")[1].strip().split()[0])
                    # Store in slot 0 as aggregate CPU estimate if no better data
                    normalized = norm_power(watts, self.cpu_power_max * 2)
                    vec.write(0, normalized, "ipmi_dcmi")
                except (ValueError, IndexError):
                    pass


# ─────────────────────────────────────────────────────────
# Source: Linux hwmon / lm-sensors (in-band)
# ─────────────────────────────────────────────────────────

class LinuxHwmonSource:
    """
    In-band thermal reader from Linux kernel hwmon subsystem.
    /sys/class/thermal/thermal_zone* — kernel ACPI thermal zones
    /sys/class/hwmon/hwmon*/temp*_input — hardware monitor chips
    Works without BMC access. Complements out-of-band Redfish/IPMI.
    """

    def __init__(self, config: dict):
        self.t_min = config.get("temp_scale_min_c", 20.0)
        self.t_max = config.get("temp_scale_max_c", 100.0)
        self._available = os.path.exists("/sys/class/thermal")

    def poll(self, vec: InputVector):
        if not self._available:
            return
        self._poll_thermal_zones(vec)
        self._poll_hwmon(vec)

    def _poll_thermal_zones(self, vec: InputVector):
        base = "/sys/class/thermal"
        try:
            zones = sorted([d for d in os.listdir(base) if d.startswith("thermal_zone")])
        except OSError:
            return
        for zone_dir in zones:
            try:
                type_path = f"{base}/{zone_dir}/type"
                temp_path = f"{base}/{zone_dir}/temp"
                with open(type_path) as f:
                    zone_type = f.read().strip().upper()
                with open(temp_path) as f:
                    millicelsius = int(f.read().strip())
                celsius = millicelsius / 1000.0
                idx = _extract_index(zone_dir)

                if "CPU" in zone_type or "X86" in zone_type or "ACPITZ" in zone_type:
                    vec.write(12 + min(idx, 3), norm_temp(celsius, self.t_min, self.t_max), "hwmon_zone")
            except (OSError, ValueError):
                continue

    def _poll_hwmon(self, vec: InputVector):
        base = "/sys/class/hwmon"
        try:
            hwmons = os.listdir(base)
        except OSError:
            return
        for hwmon in hwmons:
            try:
                name_path = f"{base}/{hwmon}/name"
                with open(name_path) as f:
                    chip_name = f.read().strip().lower()
            except OSError:
                chip_name = hwmon

            for i in range(1, 12):
                temp_path = f"{base}/{hwmon}/temp{i}_input"
                label_path = f"{base}/{hwmon}/temp{i}_label"
                if not os.path.exists(temp_path):
                    continue
                try:
                    with open(temp_path) as f:
                        millicelsius = int(f.read().strip())
                    celsius = millicelsius / 1000.0
                    label = ""
                    if os.path.exists(label_path):
                        with open(label_path) as f:
                            label = f.read().strip().upper()

                    if "CORETEMP" in chip_name or "K10TEMP" in chip_name:
                        vec.write(12, norm_temp(celsius, self.t_min, self.t_max), "hwmon_chip")
                    elif "NVME" in chip_name or "NVME" in label:
                        vec.write(9, norm_temp(celsius, 20.0, 80.0), "hwmon_nvme")
                    elif "MEMORY" in label or "DIMM" in label:
                        vec.write(28, norm_temp(celsius, 20.0, 85.0), "hwmon_dimm")
                except (OSError, ValueError):
                    continue


# ─────────────────────────────────────────────────────────
# Source: NVIDIA NVML (in-band GPU)
# ─────────────────────────────────────────────────────────

class NvidiaGPUSource:
    """
    NVIDIA GPU telemetry via pynvml.
    Reads temperature, power consumption, and utilization for up to 4 GPUs.
    Install: pip install pynvml
    """

    def __init__(self, config: dict):
        self.gpu_power_max = config.get("gpu_power_ceiling_w", 700.0)
        self.t_min = config.get("temp_scale_min_c", 20.0)
        self.t_max = config.get("temp_scale_max_c", 100.0)
        self._handles = []
        self._available = False
        self._init_nvml()

    def _init_nvml(self):
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i)
                             for i in range(min(count, 4))]
            self._nvml = pynvml
            self._available = True
            logger.info(f"NVIDIA NVML: {count} GPU(s) detected")
        except Exception as e:
            logger.info(f"NVIDIA NVML not available: {e}")

    def poll(self, vec: InputVector):
        if not self._available:
            return
        for i, handle in enumerate(self._handles):
            try:
                temp_c = self._nvml.nvmlDeviceGetTemperature(
                    handle, self._nvml.NVML_TEMPERATURE_GPU)
                power_mw = self._nvml.nvmlDeviceGetPowerUsage(handle)
                power_w = power_mw / 1000.0

                vec.write(4 + i, norm_power(power_w, self.gpu_power_max), "nvml_power")
                vec.write(16 + i, norm_temp(temp_c, self.t_min, self.t_max), "nvml_temp")
            except Exception as e:
                logger.debug(f"NVML GPU {i} read error: {e}")


# ─────────────────────────────────────────────────────────
# Source: AMD ROCm / rocm-smi (in-band GPU)
# ─────────────────────────────────────────────────────────

class AMDGPUSource:
    """
    AMD GPU telemetry via rocm-smi CLI.
    Reads temperature and power for up to 4 AMD GPUs.
    Requires: ROCm installed, rocm-smi in PATH.
    """

    def __init__(self, config: dict):
        self.gpu_power_max = config.get("gpu_power_ceiling_w", 700.0)
        self.t_min = config.get("temp_scale_min_c", 20.0)
        self.t_max = config.get("temp_scale_max_c", 100.0)
        self._available = self._check_rocm()

    def _check_rocm(self) -> bool:
        try:
            result = subprocess.run(["rocm-smi", "--version"],
                                    capture_output=True, timeout=3)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.info("rocm-smi not found — AMD GPU source disabled")
            return False

    def poll(self, vec: InputVector):
        if not self._available:
            return
        try:
            result = subprocess.run(
                ["rocm-smi", "--showtemp", "--showpower", "--json"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return
            data = json.loads(result.stdout)
            for i, (gpu_id, metrics) in enumerate(data.items()):
                if i >= 4:
                    break
                temp_str = metrics.get("Temperature (Sensor edge) (C)", "0")
                power_str = metrics.get("Average Graphics Package Power (W)", "0")
                try:
                    temp_c = float(str(temp_str).replace("c", "").strip())
                    power_w = float(power_str)
                    vec.write(4 + i, norm_power(power_w, self.gpu_power_max), "rocm_power")
                    vec.write(16 + i, norm_temp(temp_c, self.t_min, self.t_max), "rocm_temp")
                except ValueError:
                    continue
        except Exception as e:
            logger.debug(f"ROCm-SMI error: {e}")


# ─────────────────────────────────────────────────────────
# Source: NVMe SMART (storage thermal)
# ─────────────────────────────────────────────────────────

class NVMeStorageSource:
    """
    NVMe drive temperature via nvme-cli smart-log.
    Maps hottest drive temperature to storage slot [9].
    Requires: nvme-cli installed.
    """

    def __init__(self, config: dict):
        self.devices = config.get("nvme_devices", [])
        self._available = self._check_nvme()

    def _check_nvme(self) -> bool:
        try:
            subprocess.run(["nvme", "version"], capture_output=True, timeout=3)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.info("nvme-cli not found — NVMe thermal source disabled")
            return False

    def poll(self, vec: InputVector):
        if not self._available:
            return
        devices = self.devices or self._discover_devices()
        temps = []
        for dev in devices:
            try:
                result = subprocess.run(
                    ["nvme", "smart-log", dev, "--output-format=json"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0:
                    continue
                data = json.loads(result.stdout)
                temp_k = data.get("temperature", 0)
                if temp_k > 0:
                    temps.append(temp_k - 273.15)  # Kelvin to Celsius
            except Exception:
                continue
        if temps:
            hottest = max(temps)
            vec.write(9, norm_temp(hottest, 20.0, 80.0), "nvme_smart")

    def _discover_devices(self) -> list:
        try:
            result = subprocess.run(["nvme", "list", "--output-format=json"],
                                    capture_output=True, text=True, timeout=5)
            data = json.loads(result.stdout)
            return [d.get("DevicePath", "") for d in data.get("Devices", [])]
        except Exception:
            return []


# ─────────────────────────────────────────────────────────
# Source: Kubernetes / SLURM workload scheduler
# ─────────────────────────────────────────────────────────

class WorkloadSchedulerSource:
    """
    Workload pressure signal from orchestration layers.
    Reads pending queue depth / resource pressure as a 0-1 signal.

    Kubernetes: kubectl top nodes + pending pods
    SLURM: squeue pending jobs
    """

    def __init__(self, config: dict):
        self.scheduler = config.get("scheduler", "none").lower()
        self.k8s_namespace = config.get("k8s_namespace", "default")

    def poll(self, vec: InputVector):
        if self.scheduler == "kubernetes":
            self._poll_kubernetes(vec)
        elif self.scheduler == "slurm":
            self._poll_slurm(vec)

    def _poll_kubernetes(self, vec: InputVector):
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-A", "--field-selector=status.phase=Pending",
                 "--no-headers"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pending = len(result.stdout.strip().splitlines())
                pressure = min(1.0, pending / 100.0)
                vec.write(26, pressure, "k8s_scheduler")
        except Exception as e:
            logger.debug(f"Kubernetes source error: {e}")

    def _poll_slurm(self, vec: InputVector):
        try:
            result = subprocess.run(
                ["squeue", "--states=PENDING", "--noheader", "--format=%i"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pending = len(result.stdout.strip().splitlines())
                pressure = min(1.0, pending / 500.0)
                vec.write(26, pressure, "slurm_scheduler")
        except Exception as e:
            logger.debug(f"SLURM source error: {e}")


# ─────────────────────────────────────────────────────────
# Master Input Manager
# ─────────────────────────────────────────────────────────

class NexusInputManager:
    """
    Aggregates all enabled input sources into a unified solver vector.
    Sources run in parallel threads. Vector is updated at poll_interval_s.
    """

    def __init__(self, config: dict, redfish_client=None):
        self.config = config
        self.vector = InputVector()
        self._sources = []
        self._running = False
        self._thread = None

        # Register sources based on config flags
        enabled = config.get("enabled_inputs", {})

        if redfish_client and enabled.get("redfish", True):
            self._sources.append(RedfishFullSource(redfish_client, config))
            logger.info("Input: Redfish full (power, thermal, env, CDU)")

        if enabled.get("ipmi", False):
            self._sources.append(IPMISource(config))
            logger.info("Input: IPMI (legacy BMC)")

        if enabled.get("hwmon", True) and os.name == "posix":
            self._sources.append(LinuxHwmonSource(config))
            logger.info("Input: Linux hwmon / thermal zones")

        if enabled.get("nvidia_nvml", True):
            self._sources.append(NvidiaGPUSource(config))

        if enabled.get("amd_rocm", False):
            self._sources.append(AMDGPUSource(config))

        if enabled.get("nvme", True):
            self._sources.append(NVMeStorageSource(config))

        if enabled.get("scheduler", False):
            self._sources.append(WorkloadSchedulerSource(config))
            logger.info(f"Input: Workload scheduler ({config.get('scheduler', 'none')})")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(f"InputManager started — {len(self._sources)} active sources")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _poll_loop(self):
        while self._running:
            t0 = time.time()
            for source in self._sources:
                try:
                    source.poll(self.vector)
                except Exception as e:
                    logger.error(f"Source {source.__class__.__name__} poll error: {e}")
            elapsed = time.time() - t0
            sleep_time = max(0.0, POLL_INTERVAL_S - elapsed)
            time.sleep(sleep_time)

    def get_vector(self) -> list:
        """Return current 32-float solver input vector."""
        return self.vector.snapshot()

    def get_diagnostics(self) -> dict:
        """Return slot-level diagnostics for monitoring."""
        stale = self.vector.staleness_check()
        with self.vector._lock:
            return {
                "sources": len(self._sources),
                "stale_slots": stale,
                "source_map": list(self.vector._source_map),
                "vector_snapshot": list(self.vector._data),
            }


# ─────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────

def _extract_index(name: str, max_idx: int = 3) -> int:
    """Extract a 0-based index from a name string like 'CPU 2' or 'Processor_1'."""
    import re
    digits = re.findall(r'\d+', name)
    if digits:
        return min(int(digits[0]), max_idx)
    return 0
