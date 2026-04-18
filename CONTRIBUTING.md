# Contributing to NEXUS

NEXUS is a community-powered thermal orchestration engine. Every hardware vendor config, integration hook, and solver optimization comes from real deployment experience.

## How to Contribute

### 1. Add Your Hardware Configuration (Most Common)

**For: "My server isn't on the list"**

#### Step 1: Validate Your Hardware
```bash
python tools/validate_v4.py \
  --target 192.168.1.100 \
  --user root \
  --pass your_password \
  --output my_hardware_redfish.txt
```

#### Step 2: Create Your Vendor Config

Copy `config/chassis_map_template.json` and fill in your details:

```bash
cp config/chassis_map_template.json config/vendors/acme_thermalserver_2024.json
```

Edit the file:

```json
{
  "vendor": "ACME Corporation",
  "model": "ThermalServer 2024",
  "release_date": "2024-01",
  "bmc_type": "redfish",
  "api_version": "1.8.0",
  "form_factor": "2U",
  "max_processors": 2,
  "max_memory_gb": 1024,
  "max_gpus": 8,
  "psu_count": 4,
  "fan_count": 12,

  "chassis_info": {
    "redfish_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1",
    "thermal_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Thermal"
  },

  "thermal_zones": [
    {
      "zone_id": "cpu0",
      "zone_name": "Processor 0 Zone",
      "sensor_type": "temperature",
      "sensor_paths": [
        "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/CPU0_Temp_CPU1",
        "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/CPU0_Temp_CPU2"
      ],
      "alert_threshold_c": 85,
      "critical_threshold_c": 95,
      "pwm_control_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/CPU0_PWM",
      "pwm_min_percent": 20,
      "pwm_max_percent": 100,
      "thermal_profile": "dynamic",
      "solver_slot": 0
    },
    {
      "zone_id": "gpu0",
      "zone_name": "GPU 0 (NVIDIA A100)",
      "sensor_type": "temperature",
      "sensor_paths": [
        "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/GPU0_Memory_Temp",
        "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/GPU0_GPU_Temp"
      ],
      "alert_threshold_c": 80,
      "critical_threshold_c": 90,
      "pwm_control_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/GPU0_PWM",
      "pwm_min_percent": 30,
      "pwm_max_percent": 100,
      "thermal_profile": "aggressive",
      "solver_slot": 1
    },
    {
      "zone_id": "memory",
      "zone_name": "Memory Thermal Zone",
      "sensor_type": "temperature",
      "sensor_paths": [
        "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/DIMM_Temp_Zone"
      ],
      "alert_threshold_c": 75,
      "critical_threshold_c": 85,
      "pwm_control_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/Sensors/Memory_PWM",
      "pwm_min_percent": 15,
      "pwm_max_percent": 80,
      "thermal_profile": "conservative",
      "solver_slot": 2
    }
  ],

  "power_supplies": {
    "sensor_path": "/redfish/v1/Chassis/System.Embedded.1-Chassis-1/PowerSupplies",
    "redundancy_required": true
  },

  "liquid_cooling": {
    "enabled": false,
    "cdu_type": "none"
  },

  "network_interfaces": {
    "bmc_speed_mbps": 1000,
    "data_speed_mbps": 25000
  },

  "validated_with": {
    "nexus_version": "4.0.0",
    "validated_date": "2024-01-15",
    "contributed_by": "your_github_username"
  }
}
```

#### Step 3: Validate Your Config

```bash
python tools/validate_v4.py --config config/vendors/acme_thermalserver_2024.json
```

Expected output:
```
[✓] JSON schema valid
[✓] 3 thermal zones mapped
[✓] All Redfish paths accessible
[✓] PWM control endpoints verified
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Ready for deployment
```

#### Step 4: Submit Your PR

```bash
git checkout -b add/acme-thermalserver-2024
git add config/vendors/acme_thermalserver_2024.json
git commit -m "Add support for ACME ThermalServer 2024 (iDRAC 9)"
git push origin add/acme-thermalserver-2024
```

**In your PR description, include:**
- Hardware model and generation
- BMC type and firmware version
- Your `my_hardware_redfish.txt` validation output
- Any custom tuning you've done (optional)

---

### 2. Add Liquid Cooling Support

**For: "My CDU isn't supported"**

Create `liquid-cooling/configs/your_cdu_model.json`:

```json
{
  "cdu_vendor": "YourCooling Corp",
  "cdu_model": "CoolTech-5000",
  "api_type": "proprietary",
  "api_endpoint": "https://cdu-api.yourcooling.com",
  "authentication": "bearer_token",
  
  "operational_zones": [
    {
      "loop_id": "cpu_loop",
      "inlet_temp_sensor": "/api/v1/sensors/inlet_cpu",
      "outlet_temp_sensor": "/api/v1/sensors/outlet_cpu",
      "flowrate_sensor": "/api/v1/sensors/flowrate_cpu",
      "pump_speed_control": "/api/v1/actuators/pump_speed_cpu",
      "alert_threshold_c": 45,
      "max_flow_lpm": 50
    }
  ],

  "safety_interlocks": {
    "min_flowrate_lpm": 5,
    "max_inlet_temp_c": 50,
    "pump_failure_action": "escalate_to_air_cooling"
  },

  "documentation": {
    "datasheet_url": "https://...",
    "api_docs_url": "https://...",
    "tested_with_nexus": "4.0.0"
  }
}
```

Submit as a PR to `liquid-cooling/configs/`.

---

### 3. Fix a Bug or Improve Code

**For: "I found an issue" or "I have an optimization"**

1. Fork and create a feature branch:
   ```bash
   git checkout -b fix/thermal-zone-timeout
   ```

2. Write tests (if applicable):
   ```bash
   python -m pytest tests/test_your_fix.py -v
   ```

3. Commit with clear messages:
   ```bash
   git commit -m "Fix thermal zone timeout in nexus_orchestrator_v4.py

   - Increased redfish_client timeout from 5s to 30s
   - Added exponential backoff for BMC connection retries
   - Fixes #123"
   ```

4. Push and open a PR with context.

---

### 4. Add Integration Documentation

**For: "I integrated NEXUS into our system"**

Create `integrations/your_platform/README.md` with:
- Step-by-step setup
- Configuration examples
- Troubleshooting section
- Your company/name as the maintainer

Example:
```markdown
# NEXUS Integration: Proxmox VE

## Overview
This integration hooks NEXUS into Proxmox VE's VM scheduling engine...

## Setup
1. Install NEXUS on Proxmox host
2. Deploy the Proxmox agent: `./setup_proxmox.sh`
3. Configure VM thermal profiles...

## Troubleshooting
**Issue: VMs won't migrate**
- Check NEXUS daemon: `systemctl status nexus`
- View logs: `journalctl -u nexus -n 50`
```

---

## Code Style & Standards

- **Python**: Follow [PEP 8](https://pep8.org/). Use `black` for formatting.
- **JSON**: 2-space indentation, sorted keys where applicable.
- **Commits**: Clear, descriptive messages. Reference issues: "Fixes #123"
- **Tests**: All code changes should include tests.

### Quick Format Check
```bash
python -m black core/ infrastructure/ metrics/
python -m flake8 core/ --max-line-length=100
```

---

## Code of Conduct

We're committed to providing a welcoming, inclusive community.

- **Be respectful** — Different perspectives drive better solutions.
- **Give credit** — Acknowledge prior art and community contributors.
- **Help others** — Answer questions, review PRs, share knowledge.
- **No harassment** — See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details.

---

## Getting Help

**Questions?**
- Check [existing issues](https://github.com/KeithLuton/NEXUS/issues)
- Read [Architecture Guide](docs/architecture.md)
- Ask in [GitHub Discussions](https://github.com/KeithLuton/NEXUS/discussions)

**Found a vulnerability?**
- Email: [security@nexus-orchestration.io](mailto:security@nexus-orchestration.io)
- Don't open a public issue

---

## Recognition

Every contributor is recognized in:
- **CONTRIBUTORS.md** (automatic on first merged PR)
- **GitHub Contributors page**
- **Release notes** (for major contributions)

Thank you for making NEXUS better! 🚀
