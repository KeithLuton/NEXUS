#!/usr/bin/env python3
"""
NEXUS v4.0 - System Validator
Auto-detects what signal sources and actuators are available on this system.
Run this before deployment to know exactly what will and won't work.

Usage:
  python3 validate_v4.py
  python3 validate_v4.py --bmc-host 192.168.1.100 --bmc-user admin --bmc-pass password
  python3 validate_v4.py --full   (runs all checks including network)
"""

import os
import sys
import json
import argparse
import subprocess
import platform
import struct
import socket
import time

# ── ANSI colors (works on Linux/macOS/Windows 10+) ───────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {BLUE}→{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}{msg}{RESET}")


# ─────────────────────────────────────────────────────────
# Section 1: Platform
# ─────────────────────────────────────────────────────────

def check_platform():
    header("Platform")
    os_name = platform.system()
    arch = platform.machine()
    ok(f"OS: {os_name} {platform.release()} ({arch})")

    if os_name == "Linux":
        ok("Linux — full feature set available")
        return "linux"
    elif os_name == "Windows":
        warn("Windows — hwmon, sysfs PWM, and IPMI raw commands unavailable")
        return "windows"
    elif os_name == "Darwin":
        warn("macOS — development/testing only, not for production deployment")
        return "macos"
    else:
        warn(f"Unknown OS: {os_name}")
        return "unknown"


# ─────────────────────────────────────────────────────────
# Section 2: Python & dependencies
# ─────────────────────────────────────────────────────────

def check_python():
    header("Python environment")
    major, minor = sys.version_info[:2]
    if major >= 3 and minor >= 8:
        ok(f"Python {major}.{minor} (3.8+ required)")
    else:
        fail(f"Python {major}.{minor} — 3.8+ required. Please upgrade.")
        return False

    required = ["fastapi", "uvicorn", "pydantic", "httpx", "requests"]
    optional = {
        "pynvml":   "NVIDIA GPU telemetry",
        "pysnmp":   "SNMP trap sending (alternative to snmptrap CLI)",
    }

    all_ok = True
    for pkg in required:
        try:
            __import__(pkg)
            ok(f"{pkg}")
        except ImportError:
            fail(f"{pkg} — run: pip install {pkg}")
            all_ok = False

    for pkg, desc in optional.items():
        try:
            __import__(pkg)
            ok(f"{pkg} ({desc})")
        except ImportError:
            warn(f"{pkg} not installed — {desc} unavailable (optional)")

    return all_ok


# ─────────────────────────────────────────────────────────
# Section 3: Proprietary engine (spigot_torch)
# ─────────────────────────────────────────────────────────

def check_binaries():
    header("Proprietary engine (spigot_torch)")

    os_name = platform.system()
    arch = platform.machine()

    candidates = {
        ("Linux",   "x86_64"):  "02_Proprietary_Engine/spigot_torch_LINUX_x86_64",
        ("Linux",   "aarch64"): "02_Proprietary_Engine/spigot_torch_BMC_ARM64",
        ("Windows", "AMD64"):   "02_Proprietary_Engine/spigot_torch_WINDOWS_x64.exe",
    }

    expected = candidates.get((os_name, arch))
    if not expected:
        fail(f"No binary for {os_name}/{arch}")
        return None

    if not os.path.exists(expected):
        fail(f"Binary not found: {expected}")
        info("Download the trial package from https://github.com/KeithLuton/NEXUS")
        info("Place spigot_torch binaries in 02_Proprietary_Engine/")
        return None

    os.chmod(expected, 0o755)

    # Smoke test: send 32 zero floats, expect 128 bytes back (or license message)
    try:
        test_input = struct.pack("f" * 32, *([0.0] * 32))
        result = subprocess.run(
            [expected], input=test_input,
            capture_output=True, timeout=3
        )
        if result.returncode == 1 and b"expired" in result.stderr.lower():
            fail("Trial license EXPIRED — delete ~/.nexus_trial to reset")
            return None
        elif len(result.stdout) == 128:
            ok(f"Binary functional: {expected}")
            _check_trial_license(expected)
            return expected
        else:
            warn(f"Binary returned unexpected output ({len(result.stdout)} bytes) — "
                 "may be first run (license activating)")
            return expected
    except subprocess.TimeoutExpired:
        fail("Binary timed out — check executable permissions")
        return None
    except Exception as e:
        fail(f"Binary test failed: {e}")
        return None


def _check_trial_license(binary_path):
    license_paths = {
        "Linux":   os.path.expanduser("~/.nexus_trial"),
        "Darwin":  os.path.expanduser("~/.nexus_trial"),
        "Windows": os.path.join(os.environ.get("APPDATA", ""), "nexus_trial.dat"),
    }
    lpath = license_paths.get(platform.system(), "")
    if lpath and os.path.exists(lpath):
        mtime = os.path.getmtime(lpath)
        days_used = (time.time() - mtime) / 86400
        days_left = max(0, 15 - days_used)
        if days_left > 3:
            ok(f"Trial license: {days_left:.1f} days remaining")
        elif days_left > 0:
            warn(f"Trial license: {days_left:.1f} days remaining — contact licensing@nexus-thermal.io")
        else:
            fail("Trial license expired")
    else:
        info("Trial license: not yet activated (will activate on first run)")


# ─────────────────────────────────────────────────────────
# Section 4: Redfish (BMC)
# ─────────────────────────────────────────────────────────

def check_redfish(bmc_host, bmc_user, bmc_pass):
    header("Redfish / BMC")

    if not bmc_host:
        warn("No --bmc-host provided — skipping live Redfish checks")
        info("Re-run with: python3 validate_v4.py --bmc-host <IP> --bmc-user <user> --bmc-pass <pass>")
        return False

    try:
        import httpx
    except ImportError:
        fail("httpx not installed — run: pip install httpx")
        return False

    base = f"https://{bmc_host}/redfish/v1"
    session = httpx.Client(verify=False, auth=(bmc_user, bmc_pass), timeout=5.0)

    # Base connectivity
    try:
        resp = session.get(base)
        if resp.status_code == 200:
            data = resp.json()
            rf_version = data.get("RedfishVersion", "unknown")
            vendor = data.get("Vendor", data.get("Name", "unknown"))
            ok(f"Redfish {rf_version} reachable — {vendor} ({bmc_host})")
        else:
            fail(f"Redfish returned HTTP {resp.status_code}")
            return False
    except Exception as e:
        fail(f"Cannot reach BMC at {bmc_host}: {e}")
        return False

    results = {}

    # Thermal endpoint
    _check_endpoint(session, f"{base}/Chassis/Self/Thermal",
                    "Thermal sensors (GET)", results)

    # Power endpoint
    _check_endpoint(session, f"{base}/Chassis/Self/Power",
                    "Power metrics (GET)", results)

    # Controls endpoint (fan actuation)
    _check_endpoint(session, f"{base}/Chassis/Self/Controls",
                    "Fan controls (PATCH target)", results)

    # EnvironmentMetrics (newer servers)
    _check_endpoint(session, f"{base}/Chassis/Self/EnvironmentMetrics",
                    "EnvironmentMetrics (Redfish 2022+)", results)

    # ThermalSubsystem (newest schema)
    _check_endpoint(session, f"{base}/Chassis/Self/ThermalSubsystem",
                    "ThermalSubsystem (newest schema)", results)

    # CoolingUnit / CDU
    _check_endpoint(session, f"{base}/ThermalEquipment/CDUs",
                    "CoolingUnit CDU (liquid cooling)", results)

    # EventService
    _check_endpoint(session, f"{base}/EventService",
                    "EventService (push subscriptions)", results)

    # Multi-chassis
    _check_endpoint(session, f"{base}/Chassis",
                    "ChassisCollection (multi-chassis)", results)

    # Detect vendor from OEM data
    try:
        chassis_resp = session.get(f"{base}/Chassis/Self")
        if chassis_resp.status_code == 200:
            chassis_data = chassis_resp.json()
            manufacturer = chassis_data.get("Manufacturer", "")
            model = chassis_data.get("Model", "")
            if manufacturer or model:
                info(f"Hardware: {manufacturer} {model}")
                _suggest_vendor_config(manufacturer)
    except Exception:
        pass

    return True


def _check_endpoint(session, url, label, results):
    try:
        resp = session.get(url)
        if resp.status_code == 200:
            ok(label)
            results[label] = True
        elif resp.status_code == 404:
            warn(f"{label} — not available on this BMC")
            results[label] = False
        elif resp.status_code == 401:
            fail(f"{label} — authentication failed")
            results[label] = False
        else:
            warn(f"{label} — HTTP {resp.status_code}")
            results[label] = False
    except Exception as e:
        warn(f"{label} — {e}")
        results[label] = False


def _suggest_vendor_config(manufacturer: str):
    m = manufacturer.lower()
    vendor_configs = {
        "dell":        "config/vendors/dell_idrac9.json",
        "hp":          "config/vendors/hpe_ilo5.json",
        "hpe":         "config/vendors/hpe_ilo5.json",
        "supermicro":  "config/vendors/supermicro_x12.json",
        "lenovo":      "config/vendors/lenovo_xcc2.json",
        "insyde":      "config/vendors/insyde_openedition.json",
        "ami":         "config/vendors/ami_megarac.json",
    }
    for key, path in vendor_configs.items():
        if key in m:
            if os.path.exists(path):
                info(f"Vendor config available: {path} — use as your chassis_map.json base")
            else:
                info(f"Vendor detected: {manufacturer} — "
                     f"contribute config at github.com/KeithLuton/NEXUS/config/vendors/")
            return
    info(f"Unknown vendor: {manufacturer} — use config/chassis_map_template.json as base")


# ─────────────────────────────────────────────────────────
# Section 5: IPMI
# ─────────────────────────────────────────────────────────

def check_ipmi():
    header("IPMI (legacy fallback)")
    try:
        result = subprocess.run(["ipmitool", "--version"],
                                capture_output=True, text=True, timeout=3)
        version = result.stdout.strip().split("\n")[0]
        ok(f"ipmitool found: {version}")

        # Test local KCS interface
        kcs = subprocess.run(["ipmitool", "mc", "info"],
                             capture_output=True, timeout=5)
        if kcs.returncode == 0:
            ok("Local KCS IPMI interface accessible")
        else:
            warn("Local KCS not accessible (normal if BMC is remote-only)")
        return True
    except FileNotFoundError:
        warn("ipmitool not installed — IPMI fallback unavailable")
        info("Install: apt install ipmitool  /  yum install ipmitool")
        return False
    except subprocess.TimeoutExpired:
        warn("ipmitool timed out")
        return False


# ─────────────────────────────────────────────────────────
# Section 6: GPU telemetry
# ─────────────────────────────────────────────────────────

def check_gpus():
    header("GPU telemetry")
    found_any = False

    # NVIDIA
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        ok(f"NVIDIA NVML: {count} GPU(s) detected")
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            power_mw = pynvml.nvmlDeviceGetPowerUsage(h)
            ok(f"  GPU {i}: {name} — {temp}°C, {power_mw/1000:.0f}W")
        found_any = True
    except ImportError:
        warn("pynvml not installed — NVIDIA telemetry unavailable")
        info("Install: pip install pynvml")
    except Exception as e:
        warn(f"NVIDIA NVML: {e}")

    # AMD ROCm
    try:
        result = subprocess.run(["rocm-smi", "--showtemp", "--json"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            count = len(data)
            ok(f"AMD ROCm: {count} GPU(s) detected")
            found_any = True
        else:
            warn("AMD ROCm: rocm-smi returned error")
    except FileNotFoundError:
        info("rocm-smi not found — AMD GPU telemetry unavailable (optional)")
    except Exception as e:
        warn(f"AMD ROCm: {e}")

    if not found_any:
        info("No GPU telemetry available — GPU slots in solver vector will be 0.0")

    return found_any


# ─────────────────────────────────────────────────────────
# Section 7: Linux in-band sensors
# ─────────────────────────────────────────────────────────

def check_linux_sensors():
    header("Linux in-band sensors")

    if platform.system() != "Linux":
        warn("Not Linux — hwmon/thermal zones unavailable")
        return

    # Thermal zones
    thermal_base = "/sys/class/thermal"
    if os.path.exists(thermal_base):
        zones = [d for d in os.listdir(thermal_base) if d.startswith("thermal_zone")]
        if zones:
            ok(f"/sys/class/thermal: {len(zones)} thermal zone(s)")
            for z in zones[:4]:
                try:
                    with open(f"{thermal_base}/{z}/type") as f:
                        ztype = f.read().strip()
                    with open(f"{thermal_base}/{z}/temp") as f:
                        temp_mc = int(f.read().strip())
                    ok(f"  {z}: {ztype} — {temp_mc/1000:.1f}°C")
                except Exception:
                    pass
        else:
            warn("No thermal zones found in /sys/class/thermal")
    else:
        warn("/sys/class/thermal not found")

    # hwmon chips
    hwmon_base = "/sys/class/hwmon"
    if os.path.exists(hwmon_base):
        chips = os.listdir(hwmon_base)
        ok(f"/sys/class/hwmon: {len(chips)} chip(s)")
        for chip in chips[:4]:
            name_path = f"{hwmon_base}/{chip}/name"
            try:
                with open(name_path) as f:
                    name = f.read().strip()
                ok(f"  {chip}: {name}")
            except Exception:
                pass
    else:
        warn("/sys/class/hwmon not found")

    # lm-sensors
    try:
        result = subprocess.run(["sensors", "-j"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            ok(f"lm-sensors: {len(data)} chip(s) readable")
        else:
            warn("lm-sensors: sensors command failed")
    except FileNotFoundError:
        info("lm-sensors not installed (optional) — hwmon direct read will be used")


# ─────────────────────────────────────────────────────────
# Section 8: NVMe storage
# ─────────────────────────────────────────────────────────

def check_nvme():
    header("NVMe storage thermal")
    try:
        result = subprocess.run(["nvme", "list", "--output-format=json"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            devices = data.get("Devices", [])
            if devices:
                ok(f"nvme-cli: {len(devices)} NVMe device(s)")
                for d in devices[:4]:
                    ok(f"  {d.get('DevicePath', '')} — {d.get('ModelNumber', '').strip()}")
            else:
                info("nvme-cli available but no NVMe devices found")
        else:
            warn("nvme list failed — may need sudo")
    except FileNotFoundError:
        warn("nvme-cli not installed")
        info("Install: apt install nvme-cli  /  yum install nvme-cli")


# ─────────────────────────────────────────────────────────
# Section 9: Schedulers
# ─────────────────────────────────────────────────────────

def check_schedulers():
    header("Workload schedulers")

    # Kubernetes
    try:
        result = subprocess.run(["kubectl", "version", "--client"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ok("kubectl available — Kubernetes scheduler input supported")
            # Check cluster access
            cluster_check = subprocess.run(
                ["kubectl", "get", "nodes", "--no-headers"],
                capture_output=True, text=True, timeout=5)
            if cluster_check.returncode == 0:
                nodes = len(cluster_check.stdout.strip().splitlines())
                ok(f"Cluster accessible: {nodes} node(s)")
            else:
                warn("kubectl available but no cluster access (check kubeconfig)")
        else:
            info("kubectl not found — Kubernetes scheduler input unavailable (optional)")
    except FileNotFoundError:
        info("kubectl not installed — Kubernetes integration unavailable (optional)")

    # SLURM
    try:
        result = subprocess.run(["squeue", "--version"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ok(f"SLURM squeue available — SLURM scheduler input supported")
        else:
            info("SLURM not available (optional)")
    except FileNotFoundError:
        info("squeue not found — SLURM integration unavailable (optional)")


# ─────────────────────────────────────────────────────────
# Section 10: Config file
# ─────────────────────────────────────────────────────────

def check_config(config_path: str):
    header("Configuration")

    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        info("Copy config/chassis_map_template.json and edit for your hardware")
        return False

    try:
        with open(config_path) as f:
            config = json.load(f)
        ok(f"Config valid JSON: {config_path}")

        zones = config.get("zones", [])
        ok(f"Zones configured: {len(zones)}")

        # Check for placeholder values
        for zone in zones:
            for actuator in zone.get("actuators", []):
                rid = actuator.get("redfish_id", "")
                if not rid or rid == "FanX":
                    warn(f"Zone {zone.get('name')}: placeholder Redfish ID '{rid}' — update for your hardware")

        constraints = config.get("constraints", {})
        if constraints.get("min_fan_pwm", 0) < 10:
            warn("min_fan_pwm < 10 — may cause fan stall on some hardware")
        if constraints.get("thermal_safety_threshold", 100) > 95:
            warn("thermal_safety_threshold > 95°C — consider lowering for safety margin")

        ok(f"Schema version: {config.get('_schema_version', '3.0 (legacy)')}")
        return True

    except json.JSONDecodeError as e:
        fail(f"Config JSON parse error: {e}")
        return False


# ─────────────────────────────────────────────────────────
# Summary + recommended chassis_map settings
# ─────────────────────────────────────────────────────────

def print_summary(results: dict):
    header("=" * 50)
    print(f"{BOLD}Summary{RESET}")
    print("=" * 50)

    enabled_inputs = []
    enabled_outputs = []
    warnings = []

    if results.get("binary"):
        ok("Solver engine ready")
    else:
        fail("Solver engine NOT ready — deployment blocked")
        warnings.append("binary")

    if results.get("redfish"):
        enabled_inputs.append("redfish")
        enabled_outputs.append("redfish_fan")
        ok("Redfish I/O ready")

    if results.get("ipmi"):
        enabled_inputs.append("ipmi")
        enabled_outputs.append("ipmi_fan")

    if results.get("nvidia"):
        enabled_inputs.append("nvidia_nvml")

    if results.get("hwmon") and platform.system() == "Linux":
        enabled_inputs.append("hwmon")

    if results.get("nvme"):
        enabled_inputs.append("nvme")

    if results.get("k8s"):
        enabled_inputs.append("scheduler")

    print(f"\n{BOLD}Recommended enabled_inputs for chassis_map.json:{RESET}")
    rec = {src: (src in enabled_inputs) for src in
           ["redfish", "ipmi", "hwmon", "nvidia_nvml", "amd_rocm", "nvme", "scheduler"]}
    print(json.dumps(rec, indent=4))

    print(f"\n{BOLD}Recommended enabled_outputs for chassis_map.json:{RESET}")
    rec_out = {src: (src in enabled_outputs) for src in
               ["redfish_fan", "redfish_cdu", "ipmi_fan", "sysfs_pwm", "ocp_rmi"]}
    print(json.dumps(rec_out, indent=4))

    if warnings:
        print(f"\n{RED}{BOLD}Deployment BLOCKED — resolve failures above before proceeding{RESET}")
        return False
    else:
        print(f"\n{GREEN}{BOLD}Ready for deployment{RESET}")
        return True


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEXUS v4.0 System Validator")
    parser.add_argument("--bmc-host",  default="", help="BMC IP/hostname")
    parser.add_argument("--bmc-user",  default="admin")
    parser.add_argument("--bmc-pass",  default="")
    parser.add_argument("--config",    default="06_Configuration/chassis_map.json")
    parser.add_argument("--full",      action="store_true",
                        help="Run all checks including slow ones")
    args = parser.parse_args()

    print(f"\n{BOLD}NEXUS v4.0 — System Validator{RESET}")
    print(f"Luton Field Model · Thermal Engine · github.com/KeithLuton/NEXUS")
    print("=" * 60)

    results = {}

    results["platform"] = check_platform()
    results["python"]   = check_python()
    results["binary"]   = bool(check_binaries())
    results["config"]   = check_config(args.config)

    if args.bmc_host or args.full:
        results["redfish"] = check_redfish(args.bmc_host, args.bmc_user, args.bmc_pass)
    else:
        results["redfish"] = False

    results["ipmi"]    = check_ipmi()
    results["nvidia"]  = check_gpus()
    results["nvme"]    = True  # check_nvme prints but always returns
    check_nvme()

    if results["platform"] == "linux":
        check_linux_sensors()
        results["hwmon"] = True
    else:
        results["hwmon"] = False

    check_schedulers()
    results["k8s"] = False  # updated inside check_schedulers if found

    ready = print_summary(results)
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
