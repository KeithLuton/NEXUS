---
name: Vendor support request
about: Request support for a server vendor / BMC family not yet covered
title: "[vendor] <Vendor> <Model> <BMC family>"
labels: vendor-support
assignees: ''
---

## Hardware details

- **Vendor:**
- **Model:**
- **BMC family / firmware version:**
- **Redfish version:** (from `GET /redfish/v1/` — `RedfishVersion` field)

## Redfish output

Please attach the output of:

```
python tools/validate_v4.py --target <BMC_IP> --user <user> --pass <password> --json > redfish_dump.json
```

…or paste it inline if it's short.

## Proposed config

If you already have a vendor config JSON for this hardware, paste it below
or open a PR against `config/vendors/` instead. Otherwise leave this blank
and a maintainer will draft one from your Redfish output.

```json

```

## Anything unusual?

- Does the BMC require enabling Redfish in a web UI before it answers?
- Are there non-standard auth requirements?
- Anything else that would trip up a first-time user?
