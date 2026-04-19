# Liquid Cooling Integration

NEXUS discovers liquid cooling infrastructure through the Redfish
`ThermalEquipment` endpoint (DMTF Redfish 2023.1 and later). Any CDU
that exposes this endpoint is supported out of the box; vendor-specific
integration is only required when the CDU uses a proprietary API
instead of Redfish.

## Discovery

When `tools/validate_v4.py` runs, it probes:

```
GET /redfish/v1/ThermalEquipment
```

If the endpoint exists, NEXUS enumerates any `CoolingLoops` and
`CDUs` collections beneath it. This works uniformly across vendors
that have adopted the standard endpoint.

## Tested integration paths

| CDU family                          | Integration path       |
|-------------------------------------|------------------------|
| Generic Redfish `ThermalEquipment`  | Native (no plugin)     |
| Vendor CDUs with proprietary APIs   | Plugin (planned)       |

Vendor-specific plugins (Asetek, CoolIT, IceOtope, etc.) live under
`integrations/cdu/` and wrap the vendor's API to expose the same shape
the orchestrator core expects. Adding one is a contribution-friendly
task; open an issue with the vendor's API docs to start.

## Configuration

In your `chassis_map_template.json`, reference the CDU by its
`ThermalEquipment` URI:

```json
{
  "chassis_id": "rack01-chassis01",
  "bmc_host": "192.168.1.100",
  "bmc_user": "root",
  "cooling_loop": "/redfish/v1/ThermalEquipment/CoolingLoops/Primary",
  "thermal_zones": [ ... ]
}
```

If `cooling_loop` is omitted, NEXUS treats the chassis as air-cooled.
