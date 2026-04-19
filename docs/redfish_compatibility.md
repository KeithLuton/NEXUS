# Redfish Compatibility

NEXUS speaks Redfish (DMTF standard) to BMCs. It does not rely on
vendor-specific APIs. The compatibility matrix below reflects what the
orchestrator expects from the BMC, not certification from any vendor.

## Minimum Redfish surface required

NEXUS needs read access to:

| Endpoint                                    | Purpose                          |
|---------------------------------------------|----------------------------------|
| `/redfish/v1/`                              | Service root / vendor detection  |
| `/redfish/v1/Chassis`                       | Chassis inventory                |
| `/redfish/v1/Chassis/{id}/Thermal`          | Temperature / fan readings       |
| `/redfish/v1/Systems`                       | Processor inventory              |
| `/redfish/v1/Systems/{id}/Processors`       | GPU / accelerator detection      |
| `/redfish/v1/Managers`                      | BMC identity / network info      |

Optional (used if present):

| Endpoint                                    | Purpose                          |
|---------------------------------------------|----------------------------------|
| `/redfish/v1/ThermalEquipment`              | CDU / liquid-cooling integration |
| `/redfish/v1/Chassis/{id}/EnvironmentMetrics` | Redfish 2023.1+ metrics        |

## BMC family support

| BMC family       | Redfish version | Config template                     |
|------------------|-----------------|-------------------------------------|
| Dell iDRAC 9     | 1.8+            | `config/vendors/dell_idrac9.json`   |
| HPE iLO 5        | 1.6+            | `config/vendors/hpe_ilo5.json`      |
| OpenBMC AST2600  | 1.9+            | `config/vendors/openbmc_ast2600.json` |
| Any Redfish 1.0+ | 1.0+            | `config/vendors/generic_redfish.json` |

Vendor templates are starting points. Sensor path names differ between
firmware revisions and specific models — always run
`python tools/validate_v4.py` against your hardware first and adjust the
template to match.

## Contributing a new BMC family

See the "Add Your Hardware Config" section in the root README.
