# Vector Slot Map

NEXUS reserves 32 parallel workload slots per orchestrator instance.
This document describes how those slots are allocated and what each
category is for.

## Slot layout

| Range     | Count | Purpose                                          |
|-----------|-------|--------------------------------------------------|
| 0 – 3     | 4     | Reserved: control plane (no tenant workloads)    |
| 4 – 7     | 4     | Reserved: BMC / CDU telemetry polling            |
| 8 – 23    | 16    | General workload placement                       |
| 24 – 29   | 6     | GPU / accelerator workload placement             |
| 30 – 31   | 2     | Overflow / burst scheduling                      |

## Why 32?

32 is a compromise between two pressures:

- **Latency.** Evaluating placement candidates in parallel keeps
  end-to-end placement latency roughly constant as the fleet grows.
- **BMC load.** Every active slot translates to read traffic against
  a BMC. 32 concurrent readers is a load most BMCs can sustain; doubling
  it starts to matter for single-core BMC silicon.

Operators running very small fleets (< 16 chassis) will typically see
slots 8–23 sit idle. Operators running very large fleets should run
multiple orchestrator instances, each with its own 32-slot pool,
partitioned by rack or row.

## Reserved slots

Slots 0–7 are off-limits to tenant scheduling. Control-plane work
(config reload, health checks, metric emission) and BMC telemetry
polling live there so they cannot be starved by a burst of tenant
placements.

## Thermal profiles

Each slot inherits its target chassis's thermal profile:

- **balanced** — default; aim for comfortable headroom on all zones.
- **aggressive** — willing to run zones hotter in exchange for packing
  more workload per chassis. Typical for GPU training workloads.
- **quiet** — prioritize low fan speed / noise over packing density.
  Typical for edge or office-adjacent deployments.
