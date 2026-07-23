# Eval Task: Refactor a 200-line Function

Split the monolithic `process_order` function in `src/orders.py` into three testable units while preserving behavior.

## Success criteria

- Existing tests in `tests/test_orders.py` still pass.
- Each new unit has cyclomatic complexity below 8.
- No Rootknot violations in the workspace.

## Run

```bash
python -m ract.eval.runner evals/tasks/refactor-function --provider mock
```
