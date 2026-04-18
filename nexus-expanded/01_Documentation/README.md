# NEXUS Trial Package v3.0
## Predictive Thermal Management System

**Version:** 3.0 (15-Day Trial Edition)  
**Kernel:** SPIGOT_TORCH v3.0 (Proprietary LFM Physics Engine)  
**Release Date:** April 15, 2026  
**Trial Duration:** 15 days from first execution (runtime-based license)  
**License Location:** `~/.nexus_trial` (Linux/Mac) or `%APPDATA%\nexus_trial.dat` (Windows)  

---

## Package Contents

### 02_Proprietary_Engine/
The deterministic physics kernel in three platform formats:
- **spigot_torch_LINUX_x86_64**: For standard Linux rack managers and servers
- **spigot_torch_BMC_ARM64**: For OpenBMC / ASPEED AST2600+ hardware (BMCs)
- **spigot_torch_WINDOWS_x64.exe**: For Windows-based Redfish hosts

All binaries are statically linked, optimized for <15ms solve time, and symbol-stripped for IP protection.

### 03_Core_Logic/
Open-source Python orchestration layer (full source available for inspection):
- `nexus_orchestrator.py`: Central control loop (Intent → Solve → Actuate)
- `solver_wrapper.py`: Binary interface for the proprietary kernel

### 04_Infrastructure/
Standard Redfish protocol implementation:
- `redfish_client.py`: Vendor-agnostic Redfish 1.6+ communication layer

### 05_Testing_Tools/
Workload generation and validation:
- `workload_proxy_ingress.py`: FastAPI ingress endpoint for OS workload intent
- `mock_workload_generator.py`: Stress test generator (CPU, GPU, mixed workloads)

### 06_Configuration/
Hardware-specific mapping:
- `chassis_map.json`: Maps 32 zones to your Redfish fan/pump control IDs

---

## Quick Start

### 1. Prepare Hardware
Edit `06_Configuration/chassis_map.json` to map your Redfish control IDs:
```json
{
  "chassis_id": "Self",
  "zones": [
    {
      "zone_id": 0,
      "name": "CPU_Zone_A",
      "actuators": [
        {
          "redfish_id": "Fan1",
          "type": "Fan"
        }
      ]
    }
  ]
}
```

### 2. Start the Orchestrator
```bash
python 03_Core_Logic/nexus_orchestrator.py \
  --config 06_Configuration/chassis_map.json \
  --binary 02_Proprietary_Engine/spigot_torch_LINUX_x86_64 \
  --bmc-host 192.168.1.100 \
  --bmc-user root \
  --bmc-pass <password>
```

### 3. Run a Workload Test
In another terminal:
```bash
python 05_Testing_Tools/mock_workload_generator.py \
  --url http://localhost:8000/predict \
  --test mixed \
  --duration 30
```

### 4. Observe Results
The orchestrator will:
1. Receive workload intent via HTTP POST to `/predict`
2. Execute the proprietary solver (<15ms)
3. Send Redfish PATCH commands to update fan setpoints (predictive)
4. Print latency and actuation stats

**Expected Behavior:**  
Fan speeds update **within 25ms** of receiving workload intent, **before** thermal sensors spike.

---

## Validation Protocol (Smoking Gun Test)

### Objective
Prove that the thermal control loop responds to **predicted** workload rather than **observed** temperature.

### Setup
1. Boot your test system (OCP, x86 server, or OpenBMC host)
2. Map your fans in `chassis_map.json`
3. Start `nexus_orchestrator.py`
4. Start `mock_workload_generator.py` in a separate terminal

### Test Sequence
```bash
# Phase 1: Baseline (30s, low load)
python mock_workload_generator.py --test cpu --intensity 0.1 --duration 30

# Phase 2: Sudden GPU burst (10s, 99% GPU load)
python mock_workload_generator.py --test gpu --intensity 0.99 --duration 10

# Observation Point (< 25ms after Phase 2 starts)
# Check Redfish logs: Did Fan setpoints change BEFORE temperature sensors report heat?
```

### Success Criteria
- ✅ Fan setpoints update within 25ms of workload intent POST
- ✅ Temperature sensors remain stable during the first 50ms
- ✅ This proves predictive actuation (not reactive)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ OS / Workload Scheduler                                 │
│ (sends intent via HTTP POST)                            │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ NEXUS Workload Ingress (FastAPI)                        │
│ POST /predict (32 floats: CPU, GPU, Memory load)       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ NEXUS Orchestrator (nexus_orchestrator.py)              │
│ - Packs workload into 128-byte vector                   │
│ - Calls proprietary kernel (stdin/stdout binary bridge) │
│ - Maps thermal predictions to fan zones                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ SPIGOT_TORCH Kernel (proprietary binary)                │
│ - Single-pass LFM viscous relaxation                    │
│ - 32,768-cell 3D thermal topography resolution          │
│ - Output: 32 predicted hotspot temperatures             │
│ - Latency: < 15ms                                       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Redfish Client (redfish_client.py)                      │
│ PATCH /Chassis/Self/Controls/{FanID}                    │
│ SetPoint: PWM % (0-100)                                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ BMC / Rack Manager (Redfish 1.6+)                       │
│ - Updates fan controller                                │
│ - Total latency to actuation: ~25ms                     │
└─────────────────────────────────────────────────────────┘
```

---

## Technical Details

### Proprietary Kernel (SPIGOT_TORCH v3.0)
- **Algorithm:** LFM Viscous Relaxation (Axiom VII: Forces from Gradients)
- **Grid Resolution:** 32×32×32 = 32,768 cells
- **Output Zones:** 32 actuator zones
- **Solve Time:** < 15ms on modern CPUs
- **Cell Update Rate:** 200M+ cells/sec
- **Physics Model:** Single-pass deterministic (no iterative convergence)

### Open Orchestration Layer
- **Language:** Python 3.8+
- **API Server:** FastAPI (async, non-blocking)
- **Redfish Version:** 1.6+ compatible
- **Dependencies:** `httpx`, `fastapi`, `uvicorn`, `pydantic`

### Compatibility
- **OS:** Linux (x86/ARM), Windows
- **Redfish Implementations:** iLO, iDRAC, OpenBMC, ASPEED AST2600+, Proxmox, Kubernetes
- **Network:** Gigabit Ethernet minimum (for <25ms round-trip to BMC)

---

## Performance Targets

| Metric | Target | Typical |
|--------|--------|---------|
| Intent latency (HTTP POST → parsing) | < 5ms | 2-3ms |
| Solver latency (intent → prediction) | < 15ms | 8-12ms |
| Redfish PATCH latency | < 10ms | 5-8ms |
| **Total control loop** | < 25ms | 15-20ms |

---

## Troubleshooting

### Problem: "Proprietary Kernel not found"
- Ensure you're using the correct binary for your platform (x86_64, ARM64, or Windows)
- Check file permissions: `chmod +x spigot_torch_*`

### Problem: Redfish connection refused
- Verify BMC IP address and credentials in `chassis_map.json`
- Confirm Redfish endpoint is accessible: `curl -k https://<bmc-ip>/redfish/v1/`
- Check firewall rules (Redfish uses port 443 HTTPS)

### Problem: "Control loop latency exceeded 25ms"
- Check network latency to BMC: `ping <bmc-ip>`
- Verify orchestrator and FastAPI are running on the same host as BMC
- Monitor host CPU/memory (orchestrator should use <5% CPU)

### Problem: Fans not updating despite orchestrator running
- Verify `chassis_map.json` has correct Redfish control IDs
- Check Redfish logs on BMC for PATCH errors
- Confirm Redfish user has Control write permissions

---

## License & Expiration

The proprietary kernel uses a **runtime-based trial license** that activates on first execution and expires after **15 days** of actual use.

**License Details:**
- **File Location:** `~/.nexus_trial` (Linux/Mac) or `%APPDATA%\nexus_trial.dat` (Windows)
- **Activation:** Automatic on first binary execution
- **Duration:** 15 calendar days from activation
- **Expiration:** Binary refuses to run and returns exit code 1
- **Reset:** Delete the license file to start a fresh 15-day trial

See [TRIAL_LICENSE.md](TRIAL_LICENSE.md) for detailed trial license management.

## Proprietary vs. Open Source

---

## Support & Contact

For technical questions, performance tuning, or production licensing:
- Email: support@nexus-thermal.io
- Technical Documentation: https://docs.nexus-thermal.io

---

**NEXUS™ Predictive Thermal Management System**  
"Closing the Deterministic Gap"
