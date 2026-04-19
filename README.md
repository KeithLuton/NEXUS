# NEXUS v5.1 — Thermal Orchestrator with LFM Safety Core

[![tests](https://github.com/KeithLuton/NEXUS/actions/workflows/tests.yml/badge.svg)](https://github.com/KeithLuton/NEXUS/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/downloads/)

A thermal control orchestrator for Redfish-managed servers. Reads temperatures,
compares observed behavior to a predictor, and drives fan PWM through a
three-layer safety architecture: **invariant → arbitration → actuation**.

> **Project status:** Beta. The safety core, predictor, persistence, rate
> limiting, and mock runtime all work and are covered by 49 unit and
> integration tests. Real-BMC validation against iDRAC / iLO / OpenBMC is in
> progress — see [Hardware status](#hardware-status).

## What it does

- **Polls BMC thermal sensors** over Redfish (DMTF DSP0266). Vendor-agnostic.
- **Predicts** expected temperature using an exponential moving average.
- **Detects divergence** between observed and predicted, with streak tracking
  to avoid tripping on single outliers.
- **Makes a state decision** (NOMINAL / INVALID / FAULT / RECOVERY) using a
  priority-ordered state machine.
- **Enforces physical limits** through a bus-bar constraint solver that can
  override the state machine if power or temperature exceeds configured caps.
- **Drives fan PWM** through a rate-limited actuator with a configurable
  minimum dwell time, so fan settings don't thrash.
- **Persists history** atomically to disk so restarts resume cleanly and
  invariants carry across crashes.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Sensor Reader (Redfish)                 │
│              reads temperatures from BMC sensors           │
└───────────────────────────┬────────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│                       Predictor (EMA)                      │
│          produces expected temperature for comparison      │
└───────────────────────────┬────────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    Invariant Layer (pure)                  │
│   divergence, gradient, confidence, oscillation detect     │
└───────────────────────────┬────────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│                     Arbitration Layer                      │
│     state machine: NOMINAL / INVALID / FAULT / RECOVERY    │
└───────────────────────────┬────────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│                 Bus-Bar Constraint Solver                  │
│      enforces max power and max temperature envelopes      │
└───────────────────────────┬────────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│                 Rate-Limited Actuator                      │
│       writes fan PWM via Redfish, with dwell debounce      │
└────────────────────────────────────────────────────────────┘
```

## Quick start

### Requirements

- Python 3.9+
- (Optional) Access to a Redfish-compliant BMC

### Install

```bash
git clone https://github.com/KeithLuton/NEXUS.git
cd NEXUS
pip install -e ".[test]"
```

The `redfish` extra is optional — if not installed, NEXUS falls back to a
deterministic mock sensor so you can try everything end-to-end without real
hardware:

```bash
pip install -e ".[test,redfish]"   # with Redfish client
```

### Run the tests

```bash
pytest
```

Expected: **49 passed**.

### Run the orchestrator against the mock sensor

```bash
python -m nexus.orchestrator \
  --config examples/mock-chassis.json \
  --state-dir ./nexus_state \
  --max-ticks 5
```

Expected output (one JSON snapshot per tick):

```
2026-04-19 10:15:02,371 INFO nexus: NEXUS orchestrator starting: 1 chassis, poll interval 1.0s
2026-04-19 10:15:02,372 INFO nexus: snapshot {"tick": 0, "chassis_id": "mock-chassis-01", "state": "NOMINAL", ...}
2026-04-19 10:15:03,374 INFO nexus: snapshot {"tick": 1, "chassis_id": "mock-chassis-01", "state": "NOMINAL", ...}
...
```

Stop it any time with `Ctrl+C` — shutdown is graceful and history is saved.

### Point it at a real BMC

1. Create `my-rack.json` from `examples/mock-chassis.json`, replacing `bmc_host`
   with your BMC's IP, and `bmc_user` / `bmc_password` with real credentials.
2. Find your Redfish sensor paths:
   ```bash
   curl -k -u root:yourpass https://<bmc-ip>/redfish/v1/Chassis/1/Thermal
   ```
3. Put those paths into `sensor_paths` / `pwm_path` in your config.
4. Run:
   ```bash
   python -m nexus.orchestrator --config my-rack.json --state-dir /var/lib/nexus
   ```

## Configuration

See `examples/mock-chassis.json`. All fields:

```json
{
  "poll_interval_s": 30,
  "chassis": [
    {
      "chassis_id": "rack01-chassis01",
      "bmc_host": "192.168.1.100",
      "bmc_user": "root",
      "bmc_password": "secret",
      "thermal_zones": [
        {
          "zone_id": "primary",
          "sensor_paths": ["/redfish/v1/Chassis/1/Sensors/CPU0_Temp"],
          "pwm_path": "/redfish/v1/Chassis/1/Sensors/CPU0_PWM",
          "thermal_profile": "balanced"
        }
      ]
    }
  ]
}
```

`thermal_profile` accepts `balanced`, `aggressive`, or `quiet`. See
`docs/vector_slot_map.md` for semantics.

## Hardware status

NEXUS speaks standard Redfish, so it should work against any BMC exposing
Redfish 1.0+. The code has been validated against the following:

| BMC family       | Mock | Real hardware | Notes                       |
|------------------|------|---------------|-----------------------------|
| Deterministic mock | ✓   | n/a           | Ships with the repo         |
| Dell iDRAC 9     | ✓   | in progress   | Report issues with output   |
| HPE iLO 5        | ✓   | not tested    |                             |
| OpenBMC AST2600  | ✓   | not tested    |                             |
| Generic Redfish  | ✓   | not tested    |                             |

Have a BMC to test against? Please
[open an issue](https://github.com/KeithLuton/NEXUS/issues/new) with your
Redfish output so we can confirm and add your hardware to the table.

## Project layout

```
nexus/
├── arbitration.py      # State enums + policy data types. No dependencies.
├── telemetry.py        # DivergenceMetrics, Telemetry, Predictor, SensorReader
├── history.py          # Persistent History with atomic save
├── invariant.py        # Pure predicates + spigot_transition
├── bus_bar.py          # Physical-limit constraint solver
├── actuator.py         # Rate-limited fan PWM writer
└── orchestrator.py     # Main loop (CLI entry point)

tests/
├── test_arbitration.py # covered by test_invariant
├── test_bus_bar.py     # constraint solver
├── test_history.py     # persistence round-trip + corruption recovery
├── test_invariant.py   # every pure predicate + state machine
├── test_actuator.py    # rate limiting + deferred commits
├── test_predictor.py   # EMA correctness
└── test_orchestrator.py # end-to-end smoke + restart regression

examples/
└── mock-chassis.json   # runnable mock config
```

## Licensing

Apache 2.0 — see [LICENSE](LICENSE). Contributions welcome under the same
license by default.

## Acknowledgments

Built against the [DMTF Redfish standard](https://www.dmtf.org/standards/redfish).
No endorsement by DMTF, Dell, HPE, Lenovo, or any other named hardware vendor
is claimed — references in this repo describe technical compatibility only.
