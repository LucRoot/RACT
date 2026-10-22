# Release checklist

Work through this list before a release is cut. Each item names the command
or the file that shows the result.

## Release gate

The release gate checks the severity-1 journey defects. A severity-1 defect
blocks the journey, loses data or loses trust.

Run the gate from the repository root:

```bash
python scripts/release_gate.py
```

The script reads every `docs/ux/*/defects.md` table. It lists each
severity-1 row that is not closed, with its id and its journey. It exits 0
only when every severity-1 row has one of these statuses:

- `fixed (<commit subject or card id>)`, with the commit or card that fixed it
- `accepted (OPERATOR)`, when the OPERATOR accepts the defect for this release

Every other status holds the gate. These are `open`, `blocked (<card id>, gated)`
and `not testable today (<card id>)`. A table with a missing or unknown status
also fails the gate, and the message names the row.

A `fixed` status needs evidence. Name a commit or a card that has a test for
the defect. Do not mark a row fixed without a test.

The gate reads files only. Pass `--root <path>` to check another tree.
