# RACT 0.1.1 Release Notes

## Summary

This release hardens RACT's anti-rot tooling, expands provider and marketplace support, and adds the `ract audit` meta-command. It also fixes the symbol-graph prefix bug that made the dead-code auction unreliable on its own repository.

## What's New

### Commands & UX
- **`ract audit`** — single-command health check running `doctor`, `dead_code_auction`, and (with `--deep`) `consolidate scan`.
- **`ract audit --deep`** — surfaces merge proposals from `consolidate scan` in a unified pass/fail table or JSON.
- **`ract consolidate scan|apply|rollback`** — find near-duplicate modules, preview merges as unified diffs, and roll back if needed.
- **`ract mcp invoke`** — call configured MCP tools directly from the CLI.
- **`ract skills marketplace list|install`** — install skills from a catalog by name.

### Anti-rot improvements
- **AST-normalized structural similarity** in `consolidate` and the novelty detector catches copy-and-rename clones that byte-level compression misses.
- **Symbol graph prefix fix** — cross-module edges went from 3 to ~375, making `dead_code_auction`, `load_bearing_guard`, and `duplication_guard` trustworthy on real `src/` layouts.
- **Compression-novelty detector** now strips prose before training and uses nearest-neighbor scoring.

### Providers
- **Local provider** accepts `base_url` alias.

### Quality gates
- Earned-coverage gate with per-file floors, dynamic badge JSON, and `baseline|status|badge|delta` CLI verbs.
- Mutation-score gate with per-file floors and README badge.
- CI enforces `ruff`, `mypy`, and 90% aggregate coverage.

### Docs & discovery
- Public quality leaderboard (`docs/PUBLIC_LEADERBOARD.md`).
- Hugging Face Space static landing page.
- Demo asciicast (`assets/demo.cast`).

## Quality metrics

| Metric | Value |
|---|---|
| Tests | 1079 passed, 1 skipped |
| Line coverage | 91.30% |
| `src/ract/cli.py` coverage | 76% |
| `src/ract/executor.py` coverage | 100% |
| Dead-code auction on RACT | 0 candidates |
| `ract doctor` | 7/7 |
| `ract audit --deep` | 9/9 |

## Known limitations

- `ract novelty scan` is accurate but slow on large codebases (>60s on RACT itself), so it is not currently included in `audit --deep`.
- `consolidate scan` is practical (~10s on RACT) but limited to the 50 largest modules by default.

## Installation

```bash
pip install git+https://github.com/LucRoot/RACT.git@v0.1.1
```

## Verification

```bash
ract doctor
ract audit --deep
ract auction list
```
<!-- RACT 0.1.1 - Trust and Tooling -->
