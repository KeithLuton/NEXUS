#!/usr/bin/env python3
"""
NEXUS v4.0 — Thermal Orchestrator (standalone entry point)

Loads a chassis map, polls BMC thermal sensors at an interval, and logs
workload-placement decisions based on per-zone thermal headroom.

This is the standalone runner. Kubernetes/SLURM integrations wrap this
same core loop via the integrations/ directory.

Usage:
    python core/nexus_orchestrator_v4.py --config config/chassis_map_template.json
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("nexus")


# -------- Data model -------------------------------------------------------

@dataclass
class ThermalZone:
    zone_id: str
    sensor_paths: list[str]
    pwm_path: str | None = None
    thermal_profile: str = "balanced"   # balanced | aggressive | quiet
    last_temp_c: float | None = None


@dataclass
class Chassis:
    chassis_id: str
    bmc_host: str
    bmc_user: str
    zones: list[ThermalZone] = field(default_factory=list)


@dataclass
class OrchestratorConfig:
    poll_interval_s: int
    chassis: list[Chassis]

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
                zones=zones,
            ))
        return cls(
            poll_interval_s=int(raw.get("poll_interval_s", 30)),
            chassis=chassis_list,
        )


# -------- Orchestrator loop ------------------------------------------------

class Orchestrator:
    """Minimal orchestration loop.

    This scaffold is intentionally simple. It polls each configured chassis,
    records thermal state, and emits structured log lines. Real placement
    decisions are made by plug-in scheduler hooks (Kubernetes, SLURM) that
    consume these log events.
    """

    def __init__(self, cfg: OrchestratorConfig):
        self.cfg = cfg
        self._running = False

    def poll_chassis(self, chassis: Chassis) -> dict[str, Any]:
        """Return a snapshot dict for this chassis. Stub reader for now."""
        # TODO: wire to Redfish client in tools/validate_v4.py style.
        # For the moment we emit zone metadata so operators can verify their
        # config before live polling is enabled.
        return {
            "chassis_id": chassis.chassis_id,
            "bmc_host": chassis.bmc_host,
            "zones": [
                {
                    "zone_id": z.zone_id,
                    "profile": z.thermal_profile,
                    "sensor_count": len(z.sensor_paths),
                }
                for z in chassis.zones
            ],
        }

    def run(self) -> None:
        self._running = True
        logger.info(
            "NEXUS orchestrator starting: %d chassis, poll interval %ds",
            len(self.cfg.chassis),
            self.cfg.poll_interval_s,
        )
        while self._running:
            for chassis in self.cfg.chassis:
                snapshot = self.poll_chassis(chassis)
                logger.info("snapshot %s", json.dumps(snapshot))
            time.sleep(self.cfg.poll_interval_s)

    def stop(self, *_: Any) -> None:
        logger.info("NEXUS orchestrator shutting down.")
        self._running = False


# -------- Main -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="NEXUS v4.0 orchestrator")
    ap.add_argument("--config", required=True, help="Path to chassis map JSON")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

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
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        logger.error("Invalid config: %s", e)
        return 2

    if not cfg.chassis:
        logger.error("Config loaded but contains no chassis entries.")
        return 2

    orch = Orchestrator(cfg)
    signal.signal(signal.SIGINT, orch.stop)
    signal.signal(signal.SIGTERM, orch.stop)
    orch.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
