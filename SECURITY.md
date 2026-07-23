:warning: This file is project documentation, not part of the source code.

# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅         |
| 0.1.x   | ❌         |

## Reporting a vulnerability

RACT executes user-provided intents, writes files, and can run shell commands. We take security seriously.

If you discover a security vulnerability — including prompt injection, arbitrary file write/escape, sandbox escape, credential leakage, MCP tool abuse, or any issue that could compromise a user's machine or data — please report it privately.

- **Email:** security@lucasroot.com
- **Subject:** `[RACT Security] <short description>`
- **PGP:** `security@lucasroot.com` key fingerprint is published at `https://lucasroot.com/pgp/security.asc`. Please encrypt sensitive details.

Please include:
- A clear description of the vulnerability.
- Steps to reproduce, if applicable.
- The version of RACT you are using.
- Any suggested mitigation or fix.

We will acknowledge receipt within 72 hours and share a timeline for a fix. We will publicly disclose the issue with appropriate credit once a patch is available, unless you request otherwise.

## Security-related design notes

- RACT classifies every action into a capability tier (T0–T3) and refuses T3 actions by default.
- RACT writes artifacts only within the configured project directory; absolute paths and paths resolving outside the workspace are refused.
- RACT refuses reads of sensitive files (`.env`, `*.pem`, `*.key`, `~/.ssh/**`, etc.).
- RACT refuses package-registry publishes, `rm -rf` on untracked paths, and full-workspace uploads above the chunk threshold.
- The `--yolo` and `--allow-tier-3` flags disable safety checks. Use them only in trusted environments.
- Provider API keys should be provided via environment variables or secure config, never committed to version control.
- The `SafetyGuardrail` blocks known dangerous patterns, but it is not a substitute for reviewing generated code before execution.

## License

RACT is licensed under the PolyForm Noncommercial License 1.0.0.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.2.0 -->
