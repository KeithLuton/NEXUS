# Contributing to NEXUS

Thanks for considering a contribution. The project is small enough that your
patch will actually get read.

## Ground rules

- By submitting a pull request, you agree your contribution is licensed under
  Apache 2.0 (same as the project).
- **Tests must pass.** Run `pytest` before opening a PR. The CI workflow will
  also run them across Python 3.9, 3.10, 3.11, and 3.12.
- **Add tests for new behavior.** Every bug fix gets a regression test.
- Keep changes focused — one logical change per PR.

## What we especially want

1. **Real-hardware reports.** If you run NEXUS against an actual BMC, open an
   issue with the model, firmware version, and a snippet of Redfish output.
   That alone is a genuine contribution.
2. **BMC-specific config templates.** If your BMC exposes sensor paths that
   aren't in `examples/`, submit a PR adding a template under `examples/`.
3. **Vendor-specific quirks.** Some BMCs need flags, pre-auth steps, or
   expose slightly non-standard Redfish shapes. Document these in
   `docs/redfish_compatibility.md` or open an issue.

## Running locally

```bash
git clone https://github.com/KeithLuton/NEXUS.git
cd NEXUS
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest
```

Then try the mock end-to-end:

```bash
python -m nexus.orchestrator --config examples/mock-chassis.json \
  --state-dir ./nexus_state --max-ticks 5
```

## Code style

- Python 3.9+ syntax.
- Prefer dataclasses for data types, pure functions for logic that can be
  pure.
- Module boundaries matter: look at the import graph before adding a new
  cross-module import. If you'd introduce a cycle, rethink where the code
  belongs (see the note at the top of `nexus/arbitration.py`).

## Reporting bugs

Open an issue. Include:

- What you ran (command line, config excerpt with credentials redacted).
- What you expected.
- What happened instead (log output, stack trace).

For security-sensitive reports, see [SECURITY.md](SECURITY.md).
