- The checklist, the approval prompts, `/help`, `/cost`, `/mode`, `/settings` and
  `/model` fold to the terminal width, down to 40 columns. The 40 and 60 column
  checks are in `docs/ux/ux_bar_check.md`.
- The `/ask` reply prints a `Plan: 1 step` line before the answer, and `/help` says
  `/ask` makes no plan, so one of the two is wrong. Reported as a FOUND for the BUILDER.
- The `/ask` error says "returned an empty answer instead of a answer". The
  article is wrong. Reported as a FOUND.
- Whether the empty reply is a scenario mismatch or a defect is not checked.
  The capture does not show it.
- The `/resume` summary now wraps at word boundaries at 80 columns
  (`docs/ux/c_journeys/resume_80.txt`).
