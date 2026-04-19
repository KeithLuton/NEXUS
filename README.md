# NEXUS v4.0 — Intelligent Thermal Orchestration Engine

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org/downloads/)
[![Redfish Certified](https://img.shields.io/badge/Redfish-Certified-orange.svg)](docs/redfish_compatibility.md)
[![Community Configs: 8/50](https://img.shields.io/badge/Community%20Configs-8%2F50-brightgreen.svg)](config/vendors/)
[![Kubernetes Ready](https://img.shields.io/badge/Kubernetes-Ready-blueviolet.svg)](integrations/kubernetes/)

Intelligent thermal orchestration for hyperscale, HPC, and liquid-cooled infrastructure. Dynamically optimizes server cooling strategies across 32 simultaneous workload vectors, integrates with Kubernetes/SLURM, and ships with an open hardware configuration database.

## What NEXUS Does

- **Real-time Thermal Routing** — Assigns workloads to chassis based on predictive thermal models
- **Multi-Vendor BMC Support** — Works with iDRAC 9, iLO 5, XCC, OpenBMC, MegaRAC, and more (Redfish-native)
- **Liquid Cooling Integration** — Native support for Asetek CDU, IceOtope KU, CoolIT, and generic Redfish CDUs
- **32-Slot Solver Engine** — Parallel workload optimization with vector-based scheduling
- **Kubernetes Native** — DaemonSet deployment, automatic node thermal profiling
- **SLURM Aware** — Prolog/epilog hooks for HPC workload placement
- **Community Hardware Configs** — Open database of server/cooling configurations (submit a PR to add yours)

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/KeithLuton/NEXUS.git
cd NEXUS
./setup.sh  # Linux/macOS
# OR
setup.bat   # Windows
```

### 2. Validate Your Hardware
```bash
python tools/validate_v4.py --target 192.168.1.100 --user root --pass password
```

**Example output:**
```
[✓] iDRAC 9 detected (Dell PowerEdge R7615)
[✓] 32x thermal sensors mapped
[✓] GPU thermal zones identified (3x A100)
[✓] Liquid cooling: Asetek CDU v2.1
[✓] Network: 1Gbps BMC, 25Gbps data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Ready for deployment
```

### 3. Deploy (Choose Your Platform)

**Kubernetes:**
```bash
helm install nexus ./integrations/kubernetes/helm/ \
  --set bmc.target=192.168.1.100 \
  --set bmc.username=root
```

**SLURM:**
```bash
cp integrations/slurm/nexus_slurm_prolog.sh /etc/slurm/prolog.d/
systemctl restart slurmctld
```

**Standalone:**
```bash
python core/nexus_orchestrator_v4.py --config config/chassis_map_template.json
```

## Hardware Support

NEXUS ships with **8 verified vendor configurations** and accepts community submissions.

| Vendor | Model | BMC | Status | Config |
|--------|-------|-----|--------|--------|
| Dell | PowerEdge R7615/R6715 | iDRAC 9 | ✓ Tested | [`dell_idrac9.json`](config/vendors/dell_idrac9.json) |
| HPE | ProLiant DL380 Gen11 | iLO 5 | ✓ Tested | [`hpe_ilo5.json`](config/vendors/hpe_ilo5.json) |
| Supermicro | A+ 2214S-TN10RT | XCC | ✓ Tested | [`supermicro_x12.json`](config/vendors/supermicro_x12.json) |
| Lenovo | ThinkSystem SR950 | XCC2 | ✓ Tested | [`lenovo_xcc2.json`](config/vendors/lenovo_xcc2.json) |
| OpenBMC | Insyde OpenEdition | OpenBMC | ✓ Tested | [`openbmc_ast2600.json`](config/vendors/openbmc_ast2600.json) |
| Insyde | Custom OEM | Insyde | ✓ Tested | [`insyde_openedition.json`](config/vendors/insyde_openedition.json) |
| AMI | MegaRAC SP-X | MegaRAC | ✓ Tested | [`ami_megarac.json`](config/vendors/ami_megarac.json) |
| Generic | Redfish 1.0+ | Redfish | ⚠ Fallback | [`generic_redfish.json`](config/vendors/generic_redfish.json) |

**Don't see your hardware?** [Open a vendor support request](https://github.com/KeithLuton/NEXUS/issues/new?template=vendor_support_request.md) — provide your Redfish output and we'll add it.

## Documentation

- **[Architecture Guide](docs/architecture.md)** — How the 32-slot solver engine works
- **[Vector Slot Map](docs/vector_slot_map.md)** — All 32 solver slots explained
- **[Redfish Compatibility](docs/redfish_compatibility.md)** — BMC support matrix
- **[Liquid Cooling Integration](docs/liquid_cooling.md)** — CDU setup and configs
- **[IP & Licensing Notice](docs/ip_notice.md)** — FreewareLayer™ & community terms

## Community Contributing

### Add Your Hardware Config (5 minutes)

1. Run validation:
   ```bash
   python tools/validate_v4.py --target YOUR_BMC_IP > your_redfish_dump.txt
   ```

2. Create `config/vendors/your_vendor_model.json`:
   ```json
   {
     "vendor": "Your Company",
     "model": "ServerX-2024",
     "bmc_type": "redfish",
     "api_version": "1.8.0",
     "thermal_zones": [
       {
         "zone_id": "cpu0_zone",
         "sensor_paths": ["/redfish/v1/Chassis/1/Sensors/CPU0_Temp"],
         "pwm_path": "/redfish/v1/Chassis/1/Sensors/CPU0_PWM",
         "thermal_profile": "aggressive"
       }
     ]
   }
   ```

3. Submit a PR to `config/vendors/` with your config + Redfish validation output.

**[Full contributing guide →](CONTRIBUTING.md)**

## Licensing

- **FreewareLayer™** (MIT): Core orchestrator, Python SDK, community configs
- **Commercial License**: Enterprise deployment, priority vendor support, SLA-backed integrations
- **[Apache 2.0](LICENSE)** for all open-source components

See [IP Notice](docs/ip_notice.md) for full licensing terms.

## Citation & Credits

NEXUS v4.0 Built to integrate with :
- iDRAC team (thermal modeling)
- Redfish Consortium (standard compliance)
- OpenBMC community (generic BMC support)
- IceOtope Engineering (liquid cooling integration)

## Support

- **Community Issues**: [GitHub Issues](https://github.com/KeithLuton/NEXUS/issues)
- **Security Vulnerabilities**: [security@nexus-orchestration.io](mailto:security@nexus-orchestration.io)
- **Commercial Support**: [nexus-enterprise.io](https://nexus-enterprise.io)

---

**NEXUS v4.0** — Where thermal orchestration meets open infrastructure. [Deploy now →](docs/architecture.md)
