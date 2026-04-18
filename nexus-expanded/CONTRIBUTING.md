# Contributing to NEXUS

Thank you for helping grow hardware support for the NEXUS thermal engine.

## The fastest way to contribute

The most valuable contributions are **vendor configuration files** — JSON files that  
map your specific hardware's Redfish fan IDs and constraints so others with the same  
server don't have to figure it out.

### Adding a vendor config

1. **Find your Redfish fan IDs:**
   ```bash
   curl -sk -u admin:password https://<bmc-ip>/redfish/v1/Chassis/Self/Controls | python3 -m json.tool
   ```
   Look for `Members` — those are your fan control IDs.

2. **Copy the template:**
   ```bash
   cp config/chassis_map_template.json config/vendors/yourvendor_model.json
   ```

3. **Edit the fan IDs** — replace `Fan1`, `Fan2` etc. with what your BMC actually uses.

4. **Run the validator:**
   ```bash
   python3 tools/validate_v4.py --bmc-host <your-bmc> --config config/vendors/yourvendor_model.json
   ```

5. **Open a pull request** with:
   - Your new JSON file in `config/vendors/`
   - A one-line addition to the supported hardware table in `README.md`
   - The output of `validate_v4.py` in your PR description

### Naming convention

`{vendor}_{bmc_or_model}.json`

Examples:
- `dell_idrac9.json`
- `hpe_ilo5.json`  
- `supermicro_x12.json`
- `openbmc_ast2600.json`

---

## Other contributions

- **Bug fixes** — PRs welcome. Include the validate_v4.py output in your PR.
- **New input sources** — add to `infrastructure/nexus_input_manager.py`
- **New output/actuator types** — add to `infrastructure/nexus_output_manager.py`
- **Liquid cooling configs** — add to `liquid-cooling/configs/`
- **Documentation** — especially for integration guides

## What we don't accept

- Modifications to `solver_wrapper.py` that change the binary interface
- Any attempt to reverse-engineer the SPIGOT_TORCH kernel
- Changes to the 32-float vector slot assignments without opening an issue first  
  (slot changes break binary compatibility)

---

## Code style

- Python: PEP 8, docstrings on all public classes and methods
- JSON configs: 2-space indent, `_vendor` and `_notes` fields required
- No external dependencies beyond `requirements.txt` for core files
