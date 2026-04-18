name: Bug Report
description: Report a bug or issue with NEXUS
labels: ['bug', 'needs-triage']

body:
  - type: markdown
    attributes:
      value: |
        Thank you for reporting a bug! Please provide as much detail as possible.

  - type: input
    id: environment
    attributes:
      label: Environment
      description: Your hardware, OS, Python version
      placeholder: "e.g., Dell PowerEdge R7615, Ubuntu 22.04, Python 3.8"
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Description
      description: What's the issue?
      placeholder: "Expected X, but got Y..."
    validations:
      required: true

  - type: textarea
    id: reproduction
    attributes:
      label: Steps to Reproduce
      description: Clear steps to reproduce
      placeholder: |
        1. Run `python tools/validate_v4.py --target 192.168.1.100`
        2. Wait for 30 seconds
        3. See timeout error
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Logs or Error Output
      description: Paste full error message or logs
      render: bash
    validations:
      required: false

  - type: textarea
    id: attempted_fix
    attributes:
      label: What you've tried
      description: Any workarounds or fixes you've attempted
      placeholder: "I tried X, which temporarily resolved it. I also checked Y."
    validations:
      required: false

  - type: dropdown
    id: severity
    attributes:
      label: Severity
      options:
        - 'Low (cosmetic, no functionality impact)'
        - 'Medium (feature not working, workaround exists)'
        - 'High (feature broken, no workaround)'
        - 'Critical (data loss, security issue)'
    validations:
      required: true
