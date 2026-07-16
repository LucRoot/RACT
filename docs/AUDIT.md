# Rooted by Dr. Lucas Root, Ph.D.

# RootAct (RACT) Codebase Audit

**Date:** 2026-07-16
**Scope:** RACT source, tests, docs, and build artifacts intended for public release.
**Auditor:** Kimi Code CLI
**Methodology:** `ruff check`, `ruff format --check`, `pytest -q --cov=rootact`, `mypy src tests`, manual boundary review.

---

## Executive Summary

RootAct (public name: **RACT**) is a standalone, model-agnostic Agentic Coding Tool built around the `Rooted[T]` assumption-driven programming quirk. The codebase is lint-clean, fully formatted, type-clean, and the test suite is green. It remains independent of the author's proprietary internal tooling and contains no proprietary code, training artifacts, or management-layer concepts.

**Snapshot (after 2026-07-15 hygiene and council-driven fixes):**

- **Source modules:** 97 Python files under `src/rootact/`
- **Test files:** 115 test files under `tests/`
- **pytest:** 1160 passed, 0 failed, 1 skipped
- **Coverage:** 90% (9,954 statements, 961 missed)
- **Static analysis:** `ruff check`, `ruff format --check`, and `mypy src tests` all pass
- **Known failures:** None
- **Public-copy drift:** Working copy has 8 extra modules vs the public GitHub mirror

This audit reflects the current public-release candidate after a focused build-and-repair wave that fixed import conflicts, added an inverted-index API to the retrieval adapter, and hardened the `consolidate apply` round-trip by storing structured proposal metadata in the handshake registry.

---

## Test Results

| Suite | Result |
|-------|--------|
| `pytest -q --cov=rootact` | 1160 passed, 0 failed, 1 skipped |
| `tests/test_consolidate.py` | 17 passed (round-trip + metadata storage covered) |
| `tests/test_retrieval_adapter.py` | 17 passed (index + keyword search covered) |

The single skipped test is platform-specific and unrelated to core functionality.

---

## Coverage Summary

- **Overall coverage:** 90%
- **Total statements:** 9,960
- **Missed statements:** 961
- **All core modules exercised:** provider routing, harness integration, executor, manager/planner, loop controller, session store/rollback, project documents, CLI toggles, self-test benchmark, code-review mode, memory arena, quality scorecard, artifact provenance, built-in skills, provider presets, operator handshakes, run reports, MCP adapter, DiffApplier, retrieval adapter, error-mask detection, symbol graph, codebase historian, duplication guard, lint/format repair, and the Root-Knot-anchored self-recursing build loop.

---

## Static Analysis

| Tool | Command | Result |
|------|---------|--------|
| `ruff` | `ruff check src tests scripts` | All checks passed |
| `ruff format` | `ruff format --check src tests scripts` | Already formatted |
| `mypy` | `mypy src tests` | Success: no issues found in 212 source files |

**Root Knot compliance:**

- `__root_author__ = "Dr. Lucas Root, Ph.D."` is present in every `.py` file.
- `__ract_name__ = "RACT"` is present in every non-`__init__.py` source and test file.
- `_ROOT_KNOT = object()` is present in every non-`__init__.py` source and test file.
- `E402` is intentionally disabled project-wide so authorship/sentinel markers can sit before imports.

---

## Public-Copy Drift

The working copy currently contains **8 additional modules** compared to the public GitHub mirror. These additions are local-only capabilities and tooling modules; none contain proprietary internal code. The drift should be reviewed before the next public release to decide which modules to promote, consolidate, or remove.

---

## Known Issues

- **None.** The previously failing `test_cli_consolidate_scan_apply_rollback_round_trip` was fixed by serializing `MergeProposal` metadata into the handshake registry and preferring that metadata over brittle free-text description parsing.
- The single `mypy` note in `test_github_release_script.py` is silenced with a `# type: ignore[import-not-found]` because the test intentionally mutates `sys.path` to import a helper script.

---

## Next Steps

1. **Council-driven improvements:** Continue the [REDACTED] council loop on additional RACT hygiene and capability tasks, keeping Qwen3.6 for deep-reasoning passes while thermals are managed.
2. **Public-copy reconciliation:** Review the 8 extra working-copy modules and either promote them to the public mirror or archive them.
3. **Coverage gaps:** Target the 961 uncovered statements for incremental test additions, prioritizing CLI edge cases and provider-fallback paths.
4. **Thermal governance:** Monitor SoC temperatures during council runs; the [REDACTED] allocator now disables cross-surface concurrency above 70 °C and defaults to the safe (non-concurrent) state if thermal sensors are unreadable.

---

# RACT 0.1.1 - Trust and Tooling
