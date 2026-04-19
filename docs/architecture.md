# NEXUS v4.0 Architecture

NEXUS is a thermal orchestration engine. It observes the thermal state of a
fleet of servers, predicts where workloads will fit without violating
thermal constraints, and emits placement decisions that schedulers
(Kubernetes, SLURM, or a standalone loop) can act on.

## Components

```
┌─────────────────────────────────────────────────────────┐
│                   Scheduler Adapters                    │
│   (kubernetes/ DaemonSet, slurm/ prolog, standalone)    │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────▼─────────────┐
              │   Orchestrator Core      │
              │   core/nexus_orchestra…  │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │   Solver Engine          │
              │   (32 workload vectors)  │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │   BMC / Redfish Client   │
              │   tools/validate_v4.py   │
              └────────────┬─────────────┘
                           │
                  ┌────────▼────────┐
                  │   Server BMCs   │
                  │ iDRAC/iLO/XCC   │
                  │ OpenBMC/MegaRAC │
                  └─────────────────┘
```

## Data flow

1. **Discovery.** `tools/validate_v4.py` probes each BMC over Redfish and
   produces a per-chassis inventory of thermal zones, sensors, and (where
   present) GPU/accelerator zones and CDU endpoints.
2. **Config.** The inventory is reconciled against a vendor template in
   `config/vendors/` to produce a concrete chassis map
   (`config/chassis_map_template.json` is the starting shape).
3. **Polling.** The orchestrator core polls each chassis on an interval
   and maintains per-zone thermal headroom estimates.
4. **Solving.** The solver engine distributes pending workload vectors
   across available zones, respecting per-zone thermal profile
   (balanced / aggressive / quiet).
5. **Emitting.** Placement decisions are logged as structured events that
   scheduler adapters consume.

## 32-slot solver engine

The solver engine reserves 32 parallel workload slots per orchestrator
instance. Each slot holds a single placement candidate (a workload vector
matched against a thermal zone). Slots are evaluated in parallel rather
than serially so that placement latency stays bounded even as the fleet
grows. See [vector_slot_map.md](vector_slot_map.md) for the slot layout
and reserved-vs-tenant semantics.

## Scope of this release (v4.0)

- Redfish-native BMC reads.
- Standalone polling loop with structured log output.
- Vendor config templates for the most common BMC families.
- Kubernetes and SLURM adapter stubs under `integrations/`.

Active scheduling decisions, predictive thermal modeling, and the
liquid-cooling CDU control plane are in progress; see the repo issues for
current status.
