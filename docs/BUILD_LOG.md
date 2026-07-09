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
- Fix the symbol graph prefix mismatch that caused the dead-code auction to flag 76 of 77 modules as dead.

## 2026-07-09 — Loop pass: fix symbol graph prefix mismatch and auction calibration

**What changed**
- Fixed `SymbolGraph._detect_package_root` so it recognizes when `project_dir` is already inside `src/<pkg>` (or a flat `<pkg>` layout), not only when `project_dir` is the repo root containing `src/<pkg>`.
- Added `SymbolGraph.module_id_for_path()` and updated `DeadCodeAuction._module_for_file()` to use the graph's own module namespace. This keeps file paths and graph module ids consistent.
- Replaced the package-stripping `_relative_module_from_import` with `_resolve_imported_module` and `_is_project_import` that accept both package-prefixed absolute imports and relative imports inside the package.
- Added `test_src_layout_cross_module_reference`, `test_ract_repo_has_cross_module_edges`, and `test_auction_discriminates_dead_from_live_in_src_layout` to prevent regression.
- Fixed the contradictory novelty assumption string in `executor.py`: it now says the artifact is "not structurally novel" and a "near-duplicate" instead of "structurally novel."
- Ran `ruff format` to clean the format regression.

**Why**
- Claude's re-audit found the symbol graph produced only **3 cross-module edges** in RACT instead of hundreds. Node keys were `src.rootact.X` while import resolution returned `rootact.X` or `providers.X`, so `_is_project_import` returned False for every real internal import. The auction then flagged 76 of 77 source modules as dead code, including `executor.py` and `providers/router.py`.

**Test/lint/type result**
- `pytest tests/`: 876 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy`: passed on changed files.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: 85 of 175 files still scored `low` because existing files compress well against the codebase dictionary. This remains a known limitation; leave-one-out training is the proper fix.
- `rootact auction list`: **0 dead-code candidates** on RACT itself.
- Injected-dead-module probe (via new unit test): flags only the dead module, not the live one.

**Next action**
- Fix `rootact novelty scan` false positives with leave-one-out dictionary training, then continue the launch-gap backlog (demo asciicast, HF Space page, mutation-testing gate).

## 2026-07-09 — Loop pass: real static page for Hugging Face Space

**What changed**
- Created `hf-space/index.html`: a dark-themed landing page with the Dr. Root logo, the GitClear 623-million-commit hook, install commands, a Root-Knot-anchored loop example, the anti-rot verifier arsenal, a signed-receipt example, and links to GitHub + the AI Agent Playbook mailing list.
- Created `hf-space/README.md`: Space description with license and links.
- Verified the page renders without broken asset links and that all documented CLI snippets match the current `rootact` interface.

**Why**
- DeepSeek audit flagged the HF Space as a dead discovery surface. A public release needs every entry point to tell the same story.

**Test/lint/type result**
- `pytest tests/`: 876 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact --config rootact.yaml doctor`: all checks passed.
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 85 of 175 files scored `low`. This is a known false-positive pattern: the dictionary is trained on the whole codebase, so existing files compress well against it. Leave-one-out training is the planned fix.

**Next action**
- Implement leave-one-out dictionary training for `compression_novelty_detector` to eliminate the `low` false positives on existing files.

## 2026-07-09 — Loop pass: leave-one-out dictionary training for novelty scan

**What changed**
- Implemented leave-one-out dictionary training in `compression_novelty_detector.py`:
  - `_collect_samples` now tracks which chunks came from which file.
  - `_train_dictionary` accepts an optional `exclude_path` to omit a file's own chunks.
  - `_score_with_dict`, `_assess_with_dict`, `_conditional_ratio`, and `_nearest_similar_artifact_with_ratio` accept a dictionary argument so the leave-one-out dictionary can be threaded through scoring.
  - Added `score_artifact_leave_one_out` and updated `scan_project` to use it.
- Changed the guard in `_assess_with_dict` from `dictionary is None or nn_ratio is None` to `nn_ratio is None` so a missing dictionary does not suppress the nearest-neighbor signal.
- Added `test_scan_project_uses_leave_one_out_for_existing_files` and `test_scan_project_still_flags_verbatim_duplicates`.

**Why**
- `rootact novelty scan` reported 85 of 175 existing files as `low` because the dictionary was trained on the files it was scoring. Leave-one-out removes that self-bias.

**Test/lint/type result**
- `pytest tests/`: 878 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/compression_novelty_detector.py tests/test_compression_novelty_detector.py`: passed.

**Self-audit result**
- `rootact --config rootact.yaml doctor`: failed with HTTP 401 from the local provider (Internal/llama-server auth issue, not a RACT bug).
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 80 `low`, 35 `high`, 60 `nominal` out of 175 files. Leave-one-out eliminated self-bias (verified on synthetic data: a unique file went from ratio 0.212/`low` to 0.818/`high`), but RACT's own codebase retains a lot of genuine structural similarity across files, so many still compress well against the rest of the project.

**Next action**
- Set up cla-assistant.io for the repository so external PRs can land under the CLA.

# RACT 0.1.0 - Initial Public Release
