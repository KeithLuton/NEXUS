# NEXUS — Predictive Thermal Engine

**Luton Field Model · Thermal Control · v4.0**

NEXUS uses the proprietary **SPIGOT_TORCH** solver kernel — built on the Luton Field Model (LFM) — to predict thermal load *before* it becomes heat, then actuates cooling systems proactively. The result: lower temperatures, quieter fans, and longer hardware life.

> *"The deterministic gap between workload intent and thermal response — closed."*

---

## How it works

```
All signal sources          Proprietary solver         All actuator types
─────────────────           ──────────────────         ──────────────────
Redfish power/temp    ──┐                         ┌──  Redfish fans/pumps
IPMI sensors          ──┤                         ├──  Liquid CDU pump+valve
NVIDIA NVML           ──┤  32-float input vector  ├──  IPMI raw fan control
AMD ROCm              ──┼─→  SPIGOT_TORCH kernel ─┼──  Linux sysfs PWM
Linux hwmon           ──┤  32-float predictions   ├──  OCP rack fan bus
NVMe SMART            ──┤                         ├──  Prometheus metrics
Kubernetes/SLURM      ──┘                         └──  Webhooks / SNMP
```

The **freeware layer** (this repo) is fully open source.  
The **SPIGOT_TORCH kernel** is proprietary — protected by LFM IP.  
A 15-day trial binary is available at [nexus-thermal.io](mailto:licensing@nexus-thermal.io).

---

## Supported hardware

### BMC / Out-of-band

| Vendor | BMC | Redfish | IPMI | Config |
|--------|-----|---------|------|--------|
| Dell | iDRAC 9/10 | ✓ 1.6+ | ✓ | [dell_idrac9.json](config/vendors/dell_idrac9.json) |
| HPE | iLO 5/6 | ✓ 1.6+ | — | [hpe_ilo5.json](config/vendors/hpe_ilo5.json) |
| Supermicro | IPMI 2.0 + Redfish | ✓ 1.2+ | ✓ | [supermicro_x12.json](config/vendors/supermicro_x12.json) |
| Lenovo | XCC2 | ✓ 1.6+ | ✓ | [lenovo_xcc2.json](config/vendors/lenovo_xcc2.json) |
| OpenBMC | AST2600 | ✓ 1.5+ | ✓ | [openbmc_ast2600.json](config/vendors/openbmc_ast2600.json) |
| AMI | MegaRAC | ✓ 1.4+ | ✓ | [ami_megarac.json](config/vendors/ami_megarac.json) |
| Any | Redfish 1.0+ | ✓ | — | [chassis_map_template.json](config/chassis_map_template.json) |

### Liquid cooling CDUs

| Vendor | Protocol | Config |
|--------|----------|--------|
| Generic Redfish CDU | Redfish CoolingUnit | [generic_redfish_cdu.json](liquid-cooling/configs/generic_redfish_cdu.json) |
| Asetek RackCDU | Redfish | [asetek_cdu.json](liquid-cooling/configs/asetek_cdu.json) |
| Iceotope KU | Redfish | [iceotope_ku.json](liquid-cooling/configs/iceotope_ku.json) |

### In-band signal sources (no BMC required)

| Source | Platform | Notes |
|--------|----------|-------|
| NVIDIA NVML | Linux/Windows | `pip install pynvml` |
| AMD ROCm | Linux | ROCm toolkit required |
| Linux hwmon | Linux | Zero install |
| NVMe SMART | Linux | `nvme-cli` required |

### Workload schedulers

| Scheduler | Notes |
|-----------|-------|
| Kubernetes | kubectl + cluster access |
| SLURM | squeue in PATH |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/KeithLuton/NEXUS.git
cd NEXUS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Get the trial binary (15-day free trial)
#    Place in 02_Proprietary_Engine/ — see email from licensing@nexus-thermal.io

# 4. Pick your vendor config
cp config/vendors/dell_idrac9.json config/my_chassis.json
# Edit Redfish fan IDs for your specific hardware

# 5. Validate your system
python3 tools/validate_v4.py \
  --bmc-host 192.168.1.100 \
  --bmc-user admin \
  --bmc-pass yourpassword \
  --config config/my_chassis.json

# 6. Start the engine
python3 core/nexus_orchestrator_v4.py \
  --bmc-host 192.168.1.100 \
  --bmc-user admin \
  --bmc-pass yourpassword \
  --config config/my_chassis.json

# 7. View metrics
open http://localhost:9090/metrics
```

---

## Solver vector map

The SPIGOT_TORCH kernel consumes and produces 32 normalized floats (0.0–1.0).  
See [docs/vector_slot_map.md](docs/vector_slot_map.md) for the full slot assignment table.

---

## Prometheus / Grafana

NEXUS exposes metrics at `:9090/metrics` in OpenMetrics format. Import the provided  
Grafana dashboard from [docs/grafana_dashboard.json](docs/grafana_dashboard.json).

Key metrics:
- `nexus_loop_latency_ms` — control loop latency (target: <25ms)
- `nexus_prediction{zone}` — per-zone thermal predictions
- `nexus_fan_setpoint_pct{zone}` — current fan setpoints
- `nexus_trial_days_remaining` — trial license status

---

## Contributing a vendor config

Hardware support grows through community contributions.  
If your server isn't listed, open an issue using the  
[Hardware Support Request](https://github.com/KeithLuton/NEXUS/issues/new?template=hardware_support.md) template.

To contribute a config:
1. Copy `config/chassis_map_template.json`
2. Run `python3 tools/validate_v4.py --bmc-host <your_bmc>` to verify
3. Open a PR to `config/vendors/` with your JSON file
4. Add a row to the supported hardware table in this README

---

## IP notice

The **SPIGOT_TORCH kernel binaries** and the **Luton Field Model** are proprietary  
intellectual property of Keith Luton. All rights reserved.  
See [docs/ip_notice.md](docs/ip_notice.md) for licensing terms.

The freeware Python layer in this repository is licensed under **Apache 2.0**.

**Production licensing:** licensing@nexus-thermal.io  
**Technical support:** support@nexus-thermal.io

---

## Performance targets

| Metric | Target | Typical |
|--------|--------|---------|
| Solver latency | <15ms | 8–12ms |
| HTTP overhead | <5ms | 2–3ms |
| Redfish PATCH | <10ms | 5–8ms |
| **Total loop** | **<25ms** | **15–20ms** |

---

*NEXUS v4.0 · Built on the Luton Field Model · © 2026 Keith Luton*
