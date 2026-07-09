# RACT Build Log

This log records each loop pass through the RACT codebase. It exists because context compacts and the written record is the remedy.

## 2026-07-09 — Loop pass: README/CI badges and self-audit

**What changed**
- Added status badges to `README.md`: CI (GitHub Actions), coverage (~93%), license (PolyForm Noncommercial), and Python versions (3.11 | 3.12).
- Updated `.github/workflows/ci.yml` to emit `coverage.xml` and upload it as a per-matrix artifact.
- Reinstalled the package in editable mode so `rootact` CLI commands use the current source tree instead of a stale site-packages copy.

**Why**
- DeepSeek audit flagged "no CI/CD badges" and "no test coverage reporting" as the single biggest credibility gap for a public visitor.
- The stale install surfaced a real deployment risk: local fixes can look shipped while the installed CLI still carries the old bug.

**Test/lint/type result**
- `pytest tests/`: 873 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/executor.py src/rootact/harness.py tests/test_compression_novelty_detector.py`: passed.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: all files scored `nominal`; no low-novelty duplicates detected.
- `rootact auction list`: 0 dead-code candidates.
- `rootact fence inspect --file src/rootact/executor.py`: relative-path crash remains fixed in source; completion blocked because the configured local provider endpoint returns HTTP 401 (Internal/local model auth issue, not a RACT bug).

**Next action**
- Fix Internal/local-model provider auth so RACT's own fence/whisper/consolidate verbs can run end-to-end, then tackle the next launch-gap item (demo asciicast or Why RACT comparison table).

# RACT 0.1.0 - Initial Public Release
