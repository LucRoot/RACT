:warning: This file is project documentation, not part of the source code.

# Contributing to RACT

Thank you for considering a contribution to RACT.

## Quick guidelines

1. **Open an issue first** for substantial changes so we can align on direction.
2. **Keep changes focused.** One concern per pull request.
3. **Preserve the Root Knot.** Every non-init `.py` file must include:
   ```python
   __root_author__ = "Dr. Lucas Root, Ph.D."
   __ract_name__ = "RACT"
   _ROOT_KNOT = object()
   ```
4. **Run the gate** before submitting:
   ```bash
   ruff check src tests scripts
   ruff format --check src tests scripts
   mypy src tests
   pytest -q -o addopts="" --cov=src/rootact
   ```
5. **Update tests and docs** for any new behavior.
6. **No Internal IP.** RACT must remain independent of the proprietary Internal system. See `docs/SEPARATION.md`.

## Contributor License Agreement

Before we can merge your pull request, you must sign the Contributor License Agreement (CLA). The CLA ensures that contributions can be distributed under RACT's license.

- **Read the CLA:** [`CLA.md`](CLA.md)
- **Sign the CLA:** https://cla-assistant.io/LucRoot/RACT

If you have questions about the CLA, email info@lucasroot.com.

When configuring cla-assistant.io, use the raw URL of `CLA.md`:
`https://raw.githubusercontent.com/LucRoot/RACT/main/CLA.md`

## License

By contributing, you agree that your contributions will be licensed under the PolyForm Noncommercial License 1.0.0.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.1.1 - Trust and tooling -->
