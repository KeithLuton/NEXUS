# NEXUS Architecture

NEXUS is a buildable, Redfish-compatible thermal orchestrator. It operates
standalone on any Redfish 1.0+ BMC and scales with the zones and actuators
a deployment defines. When upgraded with SPIGOT_TORCH, it gains
leading-signal inputs and the performance profile described below.

## Inputs

- Scheduler mapping signal (SPIGOT_TORCH; SLURM / Kubernetes compatible)
- Bus-bar current sensors (SPIGOT_TORCH)
- CPU / GPU thermal diodes (Redfish)
- DIMM thermal sensors (Redfish)
- PSU temperature sensors (Redfish)
- Chassis inlet / outlet air temperature (Redfish)
- Fan tachometers (Redfish)
- Coolant supply / return temperatures (Redfish, when present)
- Flow and pressure sensors (Redfish, when present)
- Voltage rail monitors (Redfish)

## Outputs

- Fan PWM (Redfish)
- Pump flow (Redfish)
- Valve position (Redfish)
- Power cap (Redfish)
- Scalable routing controlled by the scheduler — fine-tune existing
  actuators or extend to new ones without changing the solver
  (SPIGOT_TORCH)

## Performance (with SPIGOT_TORCH)

- Input-to-actuation latency: ~15 ms
- 32 inputs mapped to 32 outputs per cycle
- Continuous operation; no batching or queueing
- Scales by running multiple instances, one per bus bar —
  safer and serviceable per unit

## Numbers (with SPIGOT_TORCH)

- Input vector: 32 slots
- Output vector: 32 slots
- Addressable actuators: 32 control addresses per bus bar, addressing
  up to 42 physical actuators (pairs where outputs are physically coupled)

## Numbers (NEXUS standalone)

- Zones per chassis: configurable (no fixed vector width)
- Poll interval: configurable (default 30 s)
- Actuator dwell minimum: 5 s
- Divergence tolerance: 3 °C
- Confidence threshold: 0.85
- Confidence hysteresis: 0.05
