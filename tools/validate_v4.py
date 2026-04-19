#!/usr/bin/env python3
"""
NEXUS v4.0 — Hardware Validation Tool

Probes a target BMC via Redfish and reports what NEXUS can detect:
 - BMC vendor / firmware
 - Thermal sensor inventory
 - GPU thermal zones (if present)
 - Liquid cooling / CDU presence
 - Network interfaces

Usage:
    python tools/validate_v4.py --target 192.168.1.100 --user root --pass password

This tool makes read-only Redfish queries. It does not modify BMC state.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    import requests
    from requests.auth import HTTPBasicAuth
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # type: ignore
except ImportError:
    print("[X] Missing dependency: requests")
    print("    Run ./setup.sh (or setup.bat on Windows) first.")
    sys.exit(1)


# -------- Output helpers ---------------------------------------------------

def ok(msg: str) -> None:
    print(f"[\u2713] {msg}")


def warn(msg: str) -> None:
    print(f"[!] {msg}")


def fail(msg: str) -> None:
    print(f"[\u2717] {msg}")


def divider() -> None:
    print("\u2501" * 40)


# -------- Redfish client ---------------------------------------------------

class Redfish:
    def __init__(self, host: str, user: str, password: str, verify_tls: bool = False):
        self.base = f"https://{host}"
        self.auth = HTTPBasicAuth(user, password)
        self.verify = verify_tls
        self.session = requests.Session()

    def get(self, path: str) -> dict[str, Any] | None:
        url = self.base + path if path.startswith("/") else f"{self.base}/{path}"
        try:
            r = self.session.get(url, auth=self.auth, verify=self.verify, timeout=10)
        except requests.exceptions.RequestException as e:
            fail(f"Network error fetching {path}: {e}")
            return None
        if r.status_code == 401:
            fail("Authentication failed (401). Check --user / --pass.")
            return None
        if r.status_code >= 400:
            warn(f"{path} returned HTTP {r.status_code}")
            return None
        try:
            return r.json()
        except ValueError:
            warn(f"{path} did not return JSON")
            return None


# -------- Probes -----------------------------------------------------------

def detect_bmc(rf: Redfish) -> str | None:
    """Return a human-friendly BMC label, or None if Redfish is unreachable."""
    root = rf.get("/redfish/v1/")
    if root is None:
        fail("Redfish endpoint unreachable (/redfish/v1/).")
        return None

    vendor = (root.get("Oem") or {})
    product = root.get("Product") or ""
    name = root.get("Name") or ""

    label_parts = [p for p in (product, name) if p]
    label = " ".join(label_parts) if label_parts else "Generic Redfish"

    # Heuristic vendor hints
    oem_keys = list(vendor.keys()) if isinstance(vendor, dict) else []
    for key in oem_keys:
        k = key.lower()
        if "dell" in k:
            label = f"iDRAC ({label})"
        elif "hpe" in k or "hp" in k:
            label = f"iLO ({label})"
        elif "lenovo" in k:
            label = f"XCC ({label})"
        elif "supermicro" in k:
            label = f"XCC/BMC ({label})"

    ok(f"BMC detected: {label}")
    return label


def inventory_thermal(rf: Redfish) -> int:
    """Count thermal sensors across all chassis."""
    chassis_col = rf.get("/redfish/v1/Chassis")
    if not chassis_col or "Members" not in chassis_col:
        warn("No Chassis collection found.")
        return 0

    total = 0
    for member in chassis_col["Members"]:
        odata = member.get("@odata.id")
        if not odata:
            continue
        thermal = rf.get(f"{odata}/Thermal")
        if thermal and "Temperatures" in thermal:
            total += len(thermal["Temperatures"])

    if total > 0:
        ok(f"{total} thermal sensors mapped")
    else:
        warn("No thermal sensors reported (BMC may not expose /Thermal).")
    return total


def detect_gpu_zones(rf: Redfish) -> int:
    """Best-effort GPU thermal-zone detection via /Systems/*/Processors."""
    systems_col = rf.get("/redfish/v1/Systems")
    if not systems_col or "Members" not in systems_col:
        return 0

    gpu_count = 0
    for sysmember in systems_col["Members"]:
        odata = sysmember.get("@odata.id")
        if not odata:
            continue
        procs = rf.get(f"{odata}/Processors")
        if not procs or "Members" not in procs:
            continue
        for p in procs["Members"]:
            p_odata = p.get("@odata.id")
            if not p_odata:
                continue
            pdata = rf.get(p_odata)
            if not pdata:
                continue
            ptype = (pdata.get("ProcessorType") or "").lower()
            if "gpu" in ptype or "accelerator" in ptype:
                gpu_count += 1

    if gpu_count:
        ok(f"GPU/accelerator thermal zones identified: {gpu_count}")
    return gpu_count


def detect_liquid_cooling(rf: Redfish) -> bool:
    """Check for ThermalEquipment / CoolingLoops (Redfish 2023.1+)."""
    te = rf.get("/redfish/v1/ThermalEquipment")
    if te:
        ok("Liquid cooling: ThermalEquipment endpoint present")
        return True
    return False


def summarize_network(rf: Redfish) -> None:
    """Report managers' network interfaces, if available."""
    mgrs = rf.get("/redfish/v1/Managers")
    if not mgrs or "Members" not in mgrs:
        return
    for m in mgrs["Members"]:
        odata = m.get("@odata.id")
        if not odata:
            continue
        enet = rf.get(f"{odata}/EthernetInterfaces")
        if enet and "Members@odata.count" in enet:
            ok(f"BMC network interfaces: {enet['Members@odata.count']}")
            return


# -------- Main -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="NEXUS v4.0 hardware validator")
    ap.add_argument("--target", required=True, help="BMC host or IP address")
    ap.add_argument("--user", required=True, help="BMC username")
    ap.add_argument(
        "--pass",
        dest="password",
        required=True,
        help="BMC password",
    )
    ap.add_argument(
        "--verify-tls",
        action="store_true",
        help="Verify BMC TLS certificate (default: off, most BMCs ship self-signed)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human text",
    )
    args = ap.parse_args()

    rf = Redfish(args.target, args.user, args.password, verify_tls=args.verify_tls)

    divider()
    print(f" NEXUS v4.0 — Validating {args.target}")
    divider()

    bmc = detect_bmc(rf)
    if bmc is None:
        fail("Validation aborted: could not reach Redfish.")
        return 2

    sensors = inventory_thermal(rf)
    gpus = detect_gpu_zones(rf)
    liquid = detect_liquid_cooling(rf)
    summarize_network(rf)

    divider()
    if sensors > 0:
        ok("Ready for deployment")
        rc = 0
    else:
        warn("Partial support: no thermal sensors exposed.")
        rc = 1
    divider()

    if args.json:
        print(json.dumps({
            "target": args.target,
            "bmc": bmc,
            "thermal_sensors": sensors,
            "gpu_zones": gpus,
            "liquid_cooling": liquid,
            "ready": rc == 0,
        }, indent=2))

    return rc


if __name__ == "__main__":
    sys.exit(main())
