:warning: This file is project documentation, not part of the source code.

# Contributing to RACT

Thank you for considering a contribution to RACT.

## Quick guidelines

1. **Open an issue first** for substantial changes so we can align on direction.
2. **Keep changes focused.** One concern per pull request.
3. **Prefer depth over surface area.** New features must justify themselves against the claim-and-verify genre. Load-bearing invariants need property tests.
4. **Run the gate** before submitting:
   ```bash
   ruff check src tests scripts
   ruff format --check src tests scripts
   mypy src tests
   pytest -q -o addopts="" --cov=src/ract/core --cov-report=term-missing
   python -m ract.eval.runner evals/tasks/refactor-function --provider mock
   python -m ract.eval.runner evals/tasks/fastapi-validation --provider mock
   python -m ract.eval.runner evals/tasks/file-watcher --provider mock
   ```
5. **Update tests and docs** for any new behavior.
6. **Write an ADR** for any architectural decision. ADRs live in `docs/ADRs/` and follow the standard shape: Context, Decision, Consequences, Alternatives Considered, Status.
7. **Add property tests** for every load-bearing invariant. See `tests/property/` for examples.
8. **No proprietary IP.** RACT must remain independent of the author's proprietary internal tooling.

## Contributor License Agreement

Before we can merge your pull request, you must sign the Contributor License Agreement (CLA). The CLA ensures that contributions can be distributed under RACT's license.

- **Read the CLA:** [`CLA.md`](CLA.md)
- **Sign the CLA:** https://cla-assistant.io/LucRoot/RACT

If you have questions about the CLA, email info@lucasroot.com.

When configuring cla-assistant.io, use the raw URL of `CLA.md`:
`https://raw.githubusercontent.com/LucRoot/RACT/main/CLA.md`

## License

By contributing, you agree that your contributions will be licensed under the PolyForm Noncommercial License 1.0.0.

<!-- RACT 0.2.0 -->
