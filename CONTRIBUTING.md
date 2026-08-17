:warning: This file is project documentation, not part of the source code.

# Contributing to RACT

Thank you for considering a contribution to RACT.

## Quick guidelines

1. **Open an issue first** for substantial changes so we can align on direction.
2. **Keep changes focused.** One concern per pull request.
3. **Prefer depth over surface area.** New features must justify themselves against the claim-and-verify genre. Load-bearing invariants need property tests.
4. **Run the gate** before submitting:
   ```bash
   ruff check src tests scripts evals
   ruff format --check src tests scripts evals
   mypy src tests
   pytest -q -o addopts="" --cov=src/ract/core --cov-report=term-missing
   python -m ract.eval.runner evals/tasks/refactor-function --provider mock
   python -m ract.eval.runner evals/tasks/fastapi-validation --provider mock
   python -m ract.eval.runner evals/tasks/file-watcher --provider mock
   python evals/benchmarks/refactor-token-usage/report.py
   ```
5. **Update tests and docs** for any new behavior.
6. **Write an ADR** for any architectural decision. ADRs live in `docs/ADRs/` and follow the standard shape: Context, Decision, Consequences, Alternatives Considered, Status.
7. **Add property tests** for every load-bearing invariant. See `tests/property/` for examples.
8. **No proprietary IP.** RACT must remain independent of the author's proprietary internal tooling.

## Repository conventions

- **Fixtures live in `tests/fixtures/`.** Never commit a `*.json` / `*.jsonl` fixture at the repo root. A lint test (`tests/test_repo_hygiene.py`) fails the build if one appears.
- **Runtime state is never committed.** Sessions, the provenance SQLite index (`.rack/`), approval queues, coverage data, and benchmark scratch all live under XDG state/cache or a gitignored `_BUILD/` directory. The `.gitignore` covers `.ract/`, `.ract_sessions/`, `.rack/`, `_BUILD/`, and archived session keys (`*.pem.archived-*`).
- **New third-party dependencies are a conscious act.** Adding an import root not in `tests/test_public_provenance.py::ALLOWED_IMPORT_ROOTS` fails the independence lint. To add a dep: declare it in `pyproject.toml` *and* add its root to the allowlist in the same PR.
- **`docs/USE_CASES.jsonl` is the release-surface record** of accepted goals and refused non-goals. Adding a CLI verb without a matching accepted entry fails CI (see `tests/test_use_cases_catalog.py`). Removing a rejected entry requires an ADR. The verb source of truth is `ract.cli.CLI_VERBS`.

## Branch protection (required GitHub settings)

The `main` branch must be protected so CI is the source of truth, not advisory. These are GitHub repository settings the maintainer applies (a file can only document them):

- **Require a pull request** before merging to `main` (no direct pushes).
- **Require status checks to pass** before merging: `lint-format-type`, `test`, `eval-smoke`, `benchmark`.
- **Require at least one review** approval.
- **Force-push disabled**, and branch deletion disabled.

Without these, the CI gate is bypassable. If any required check is missing from the list above, add it when the job is introduced.

## Contributor License Agreement

Before we can merge your pull request, you must sign the Contributor License Agreement (CLA). The CLA ensures that contributions can be distributed under RACT's license.

- **Read the CLA:** [`CLA.md`](CLA.md)
- **Sign the CLA:** https://cla-assistant.io/LucRoot/RACT

If you have questions about the CLA, email info@lucasroot.com.

When configuring cla-assistant.io, use the raw URL of `CLA.md`:
`https://raw.githubusercontent.com/LucRoot/RACT/main/CLA.md`

## License

By contributing, you agree that your contributions will be licensed under the PolyForm Noncommercial License 1.0.0.

<!-- RACT v0.2.0 - Provenance and Invariants -->
