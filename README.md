# NEXUS v4.0 — Intelligent Thermal Orchestration Engine

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org/downloads/)
[![Redfish](https://img.shields.io/badge/Redfish-native-orange.svg)](docs/redfish_compatibility.md)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-ready-blueviolet.svg)](integrations/kubernetes/helm)

Intelligent thermal orchestration for hyperscale, HPC, and liquid-cooled
infrastructure. NEXUS reads BMC thermal telemetry over Redfish, maintains
a live view of per-zone thermal headroom across a fleet, and feeds
placement decisions to Kubernetes, SLURM, or a standalone scheduler.

> **Status:** early. The Redfish validator and orchestrator core are
> working skeletons. Scheduler adapters and predictive thermal modeling
> are in progress. Contributions welcome.

## What NEXUS does

- **Redfish-native BMC reads** — Works with any BMC exposing Redfish 1.0+
  (iDRAC 9, iLO 5, XCC/XCC2, OpenBMC, MegaRAC, Insyde OpenEdition, and
  generic Redfish).
- **Thermal routing** — Assigns workloads to chassis based on per-zone
  thermal headroom.
- **Liquid cooling aware** — Discovers CDUs via the Redfish
  `ThermalEquipment` endpoint (Redfish 2023.1+).
- **32-slot solver engine** — Parallel workload placement with bounded
  latency. See [vector slot map](docs/vector_slot_map.md).
- **Kubernetes & SLURM adapters** — DaemonSet + Helm chart, SLURM prolog.
- **Open hardware config database** — Contribute your BMC/model as a
  simple JSON file.

## Quick start

### 1. Clone & install

```bash
git clone https://github.com/KeithLuton/NEXUS.git
cd NEXUS
./setup.sh  # Linux/macOS
# OR
setup.bat   # Windows
```

### 2. Validate your hardware

```bash
source .venv/bin/activate
python tools/validate_v4.py --target 192.168.1.100 --user root --pass password
```

Example output against an iDRAC-based Dell PowerEdge:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 NEXUS v4.0 — Validating 192.168.1.100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[✓] BMC detected: iDRAC (PowerEdge)
[✓] 32 thermal sensors mapped
[✓] GPU/accelerator thermal zones identified: 3
[✓] BMC network interfaces: 1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[✓] Ready for deployment
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 3. Deploy

**Standalone (simplest):**

```bash
python core/nexus_orchestrator_v4.py --config config/chassis_map_template.json
```

**Kubernetes:**

```bash
helm install nexus ./integrations/kubernetes/helm/ \
  --set bmc.target=192.168.1.100 \
  --set bmc.username=root \
  --set bmc.password=<password>
```

**SLURM:**

```bash
cp integrations/slurm/nexus_slurm_prolog.sh /etc/slurm/prolog.d/
systemctl restart slurmctld
```

## Hardware support

NEXUS ships vendor config **templates** for common BMC families. These
are starting points — sensor path names differ between firmware revisions
and specific models, so always run `validate_v4.py` against your
hardware first and adjust the template to match. Once you have a
working config, a PR to `config/vendors/` is appreciated.

| BMC family       | Config template                                    | Status   |
|------------------|----------------------------------------------------|----------|
| Dell iDRAC 9     | [`dell_idrac9.json`](config/vendors/dell_idrac9.json) | template |
| HPE iLO 5        | [`hpe_ilo5.json`](config/vendors/hpe_ilo5.json)    | template |
| Supermicro X12/X13 | [`supermicro_x12.json`](config/vendors/supermicro_x12.json) | template |
| Lenovo XCC2      | [`lenovo_xcc2.json`](config/vendors/lenovo_xcc2.json) | template |
| OpenBMC AST2600  | [`openbmc_ast2600.json`](config/vendors/openbmc_ast2600.json) | template |
| Insyde OpenEdition | [`insyde_openedition.json`](config/vendors/insyde_openedition.json) | template |
| AMI MegaRAC SP-X | [`ami_megarac.json`](config/vendors/ami_megarac.json) | template |
| Generic Redfish 1.0+ | [`generic_redfish.json`](config/vendors/generic_redfish.json) | fallback |

**Don't see your hardware?** [Open a vendor support request](../../issues/new?template=vendor_support_request.md)
with your Redfish output and we'll add a template for it.

## Documentation

- [Architecture](docs/architecture.md) — How the pieces fit together
- [Vector slot map](docs/vector_slot_map.md) — What the 32 solver slots are for
- [Redfish compatibility](docs/redfish_compatibility.md) — Which endpoints NEXUS reads
- [Liquid cooling](docs/liquid_cooling.md) — CDU setup
- [IP & licensing notice](docs/ip_notice.md) — License details

## Contributing a hardware config (5 minutes)

1. Run validation and save the output:

   ```bash
   python tools/validate_v4.py --target YOUR_BMC_IP --user root --pass password --json > your_redfish_dump.json
   ```

2. Create `config/vendors/your_vendor_model.json`:

   ```json
   {
     "vendor": "Your Company",
     "model": "ServerX-2024",
     "bmc_type": "redfish",
     "api_version": "1.8.0",
     "status": "verified",
     "thermal_zones": [
       {
         "zone_id": "cpu_zone",
         "sensor_paths": ["/redfish/v1/Chassis/1/Sensors/CPU0_Temp"],
         "pwm_path": "/redfish/v1/Chassis/1/Sensors/CPU0_PWM",
         "thermal_profile": "balanced"
       }
     ]
   }
   ```

3. Open a PR including your JSON and the Redfish dump from step 1.

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

## Licensing

All open-source components are [Apache 2.0](LICENSE). See the
[IP notice](docs/ip_notice.md) for details on the "FreewareLayer"
terminology and the optional commercial license.

## Trademarks

Redfish is a trademark of the Distributed Management Task Force (DMTF).
Dell, iDRAC, HPE, iLO, Lenovo, XCC, Supermicro, AMI, MegaRAC, Asetek,
CoolIT, and IceOtope are trademarks of their respective owners. Their
mention in this project describes BMC / hardware compatibility and does
not imply endorsement.

## Support

- **Bugs & feature requests:** [GitHub Issues](../../issues)
- **Security:** open a GitHub security advisory on this repo
- **Commercial inquiries:** open an issue tagged `commercial`

---

**NEXUS v4.0** — Open thermal orchestration for open infrastructure.
