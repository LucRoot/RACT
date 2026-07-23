# Eval Task: FastAPI Input Validation

Add Pydantic input validation to the `create_user` endpoint in `src/main.py` so invalid inputs return HTTP 400.

## Success criteria

- New tests in `tests/test_validation.py` pass.
- Invalid inputs return 400.
- Existing tests still pass.

## Run

```bash
python -m rootact.eval.runner evals/tasks/fastapi-validation --provider mock
```
