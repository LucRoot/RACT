:warning: This file is project documentation, not part of the source code.

# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅         |

## Reporting a vulnerability

RACT executes user-provided intents, writes files, and can run shell commands. We take security seriously.

If you discover a security vulnerability — including prompt injection, arbitrary file write/escape, credential leakage, or any issue that could compromise a user's machine or data — please report it privately.

- **Email:** info@lucasroot.com
- **Subject:** `[RACT Security] <short description>`

Please include:
- A clear description of the vulnerability.
- Steps to reproduce, if applicable.
- The version of RACT you are using.
- Any suggested mitigation or fix.

We will acknowledge receipt within 72 hours and share a timeline for a fix. We will publicly disclose the issue with appropriate credit once a patch is available, unless you request otherwise.

## Security-related design notes

- RACT writes artifacts only within the configured project directory; absolute paths are rejected.
- The `--yolo` flag disables approval prompts. Use it only in trusted environments.
- Provider API keys should be provided via environment variables or secure config, never committed to version control.
- The `SafetyGuardrail` blocks known dangerous patterns, but it is not a substitute for reviewing generated code before execution.

## License

RACT is licensed under the PolyForm Noncommercial License 1.0.0.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.1.0 - Initial Public Release -->
