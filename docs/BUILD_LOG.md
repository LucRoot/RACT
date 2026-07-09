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
- Add a "Why RACT" comparison table to README; then fix Internal/local-model provider auth.

## 2026-07-09 — Loop pass: Why RACT comparison table

**What changed**
- Replaced the numbered "Why RACT" list in `README.md` with a comparison table: rows are dimensions (pricing, lock-in, loop logic, continuity guard, anti-rot tooling, oversight, auditability, execution model, diff strategy, local data); columns are RACT, Cursor, Claude Code, and Lovable.
- Added a one-paragraph summary explaining who RACT is for versus the incumbents.

**Why**
- DeepSeek audit flagged the lack of a comparison table as a gap: visitors need to see the trade-offs at a glance.
- The table format surfaces RACT's actual wedge (sovereignty, model economics, anti-rot, CLI-first) without burying it in prose.

**Test/lint/type result**
- `pytest tests/`: 873 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: 85 of 175 files scored `low`. This is a false-positive pattern for existing files: the detector's dictionary is trained on the entire codebase, so files already in the codebase compress well against it. The `assess_new_artifact` API excludes the target file's nearest neighbor but still falls back to the global dictionary ratio, so existing files remain flagged.
- `rootact auction list`: 0 dead-code candidates.
- `rootact fence inspect`: still blocked by local provider HTTP 401.

**Next action**
- Fix `rootact novelty scan` to use leave-one-out dictionary training (or otherwise distinguish existing files from proposed duplicates). Then diagnose Internal/local auth so fence/whisper can complete end-to-end.

# RACT 0.1.0 - Initial Public Release
