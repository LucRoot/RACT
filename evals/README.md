# RACT Evaluations

Reproducible tasks for measuring RACT across providers.

## Leaderboard

| Task | Provider | Seed | Passed | Run |
|------|----------|------|--------|-----|
| refactor-function | mock | 42 | ✅ | [run](runs/2026-07-22-refactor-function-mock) |
| fastapi-validation | mock | 42 | ✅ | [run](runs/2026-07-22-fastapi-validation-mock) |
| file-watcher | mock | 42 | ✅ | [run](runs/2026-07-22-file-watcher-mock) |

## Tasks

- `tasks/refactor-function/` — split a 200-line function into testable units.
- `tasks/fastapi-validation/` — add input validation to a FastAPI endpoint.
- `tasks/file-watcher/` — implement a file watcher that rebuilds on change.

## Running evals

```bash
python -m rootact.eval.runner evals/tasks/refactor-function --provider mock --seed 42
python -m rootact.eval.runner evals/tasks/fastapi-validation --provider mock --seed 42
python -m rootact.eval.runner evals/tasks/file-watcher --provider mock --seed 42
```
