# assets/

Static assets bundled with the RACT project docs and CLI demos.

## Files

- **`DrLucasRoot-Logo.png`** — project author logo, referenced from top-level docs.
- **`demo.cast`** — asciinema recording used by README/onboarding to demo
  `ract doctor`. NOTE (2026-07-27): this cast was recorded on an operator
  workstation and bakes absolute operator-side paths (`C:\Users\...`) into
  the on-screen output at lines 53 and 76. The recording is otherwise
  representative but should be re-recorded from a clean path before the
  `v0.4.0` final tag. Tracked as a known gap in the v0.4.0-rc1 [REDACTED]-
  leakage audit.
- **`hf-space/`** — HuggingFace Space bundle for the public demo.
- **`marketplace/`** — skills marketplace assets.
