# RACT v0.5.x Wheel Build + GH Release Asset Upload Spec

**Ships as:** post-push follow-on for whatever v0.5.x tag is at HEAD after Pipelines A' + B land.
**Pattern reference:** `_BUILD/ract_v0.4.1_intent_fidelity/HANDSHAKE_PUSH_COMMANDS.md` — v0.4.1's successful pattern.
**Owner:** [REDACTED] Builder
**Authored:** 2026-08-20

## 1. Purpose

Rebuild wheel from the released tag commit and attach to the GitHub Release page so users can install via a single `pip install <URL>` without cloning.

## 2. Scope

Two modules only. Small pipeline.

## 3. Prerequisites

- `git push origin main` and `git push origin <tag>` completed (operator handshake).
- `gh auth status` reports authenticated as `LucRoot`.
- `python -m build` available in venv.
- `gh` CLI available.

## 4. Module map

### module_01 — Wheel build + provenance verify
Checkout the tag commit (detached HEAD). `python -m build --wheel --outdir dist/`. Verify:
- `dist/ract-<version>-py3-none-any.whl` exists
- `pip install dist/ract-*.whl` in a fresh venv succeeds
- `ract --version` in that venv prints `RACT <version>`
- `python -c "import ract; print(ract.__version__)"` matches
- Wheel SHA-256 recorded to `_BUILD/ract_v0.5.x_wheel_gh_release/wheel_sha256.txt`
- SP: reviewer verifies wheel content parity vs sdist (no missing package data, no orphan __init__ imports)

Return to `main` after.

### module_02 — GH Release create + asset upload + verify
- `gh release create <tag> --title "RACT <version>" --notes-file docs/RELEASE_NOTES_<version>.md` if release does not exist; else `gh release edit`
- `gh release upload <tag> dist/ract-<version>-py3-none-any.whl`
- Verify: `gh release view <tag>` shows the asset; `curl -sfIL https://github.com/LucRoot/RACT/releases/download/<tag>/ract-<version>-py3-none-any.whl` returns `HTTP/... 200`
- Update `README.md` install-from-release snippet if URL pattern changed
- Close: `_BUILD/ract_v0.5.x_wheel_gh_release/build_state.md` marks `current_status: shipped`

## 5. Gate matrix

| Gate | When |
|---|---|
| Wheel installs cleanly in fresh venv | module_01 |
| `ract --version` matches tag | module_01 |
| Release page carries asset | module_02 |
| Public download URL returns 200 | module_02 |
| README install snippet current | module_02 |

## 6. Rollback

- module_02: `gh release delete-asset <tag> <asset-name>` if bad asset uploaded
- module_01: no revert needed (dist/ is gitignored)

## 7. No handshake needed

Push happens BEFORE this pipeline. Operator has already authorized the tag being public via the earlier handshake. This pipeline is just release-page publishing, mechanical.
