# Security Policy

## Supported versions

NEXUS is in active development. Security fixes are provided for the most
recent minor release only. Pin to a specific version if you need stability.

## Reporting a vulnerability

Please **do not** open a public issue for security-sensitive reports.
Instead, open a
[GitHub Security Advisory](https://github.com/KeithLuton/NEXUS/security/advisories/new)
on this repository. This keeps the report private until a fix is ready.

Initial response: within 7 days.

## Threat model

NEXUS runs as a privileged daemon that holds BMC credentials and issues
fan-control commands. The following are in scope for security review:

- **BMC credential handling.** NEXUS accepts credentials via the config file.
  The config file should be mode 0600 and owned by the NEXUS service account.
  Credentials must never appear in log output — if you see credentials in a
  log line, that is a bug; please report it.
- **Input validation.** The orchestrator parses a JSON config at startup.
  Malformed JSON is rejected with a clear error and non-zero exit.
- **State file integrity.** History is saved atomically (temp-file + rename).
  A corrupted state file is detected on load and the orchestrator starts
  fresh with a warning rather than crashing.

The following are **out of scope**:

- Transport-layer attacks on the Redfish connection. NEXUS delegates TLS
  verification to the underlying `redfish` library. If your BMCs use
  self-signed certs, you are operating on a trusted management network.
- Host-OS hardening. NEXUS assumes it is running as a dedicated service
  account on a hardened host.

## Known limitations

- Credentials in the config file are stored in plaintext. Using Kubernetes
  Secrets, HashiCorp Vault, or similar is recommended for production.
- The deterministic mock sensor is for development and testing only —
  do not deploy a production orchestrator that has no real BMC to control.
