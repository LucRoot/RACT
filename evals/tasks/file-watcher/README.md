# Eval Task: File Watcher

Implement a file watcher that rebuilds a static site when `src/` changes.

## Success criteria

- Watcher detects file changes within 500ms.
- Rebuild produces a Rootknot-valid artifact.
- Exits cleanly on SIGINT.

## Run

```bash
python -m rootact.eval.runner evals/tasks/file-watcher --provider mock
```
