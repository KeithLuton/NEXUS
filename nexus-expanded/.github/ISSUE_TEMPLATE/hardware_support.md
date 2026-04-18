---
name: Hardware support request
about: My server/BMC isn't listed — request vendor config
title: '[HARDWARE] Vendor/Model - BMC type'
labels: hardware-support
---

**Server make and model:**
e.g. Dell PowerEdge R650, HPE ProLiant DL380 Gen11

**BMC type and firmware version:**
e.g. iDRAC 9 firmware 6.10.30.00

**Redfish version:**
Run: `curl -sk -u admin:pass https://<bmc>/redfish/v1 | python3 -m json.tool | grep RedfishVersion`

**Fan control IDs from your BMC:**
Run: `curl -sk -u admin:pass https://<bmc>/redfish/v1/Chassis/Self/Controls | python3 -m json.tool`
Paste output here (redact passwords).

**validate_v4.py output:**
```
paste here
```

**Are you willing to test a config PR?**
[ ] Yes — I have hardware access to test

**Additional context:**
Any notes on quirks, special IPMI commands needed, etc.
