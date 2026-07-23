# RACT Troubleshooting Guide

Common problems and how to fix them.

## Installation issues

**Symptom:** `ModuleNotFoundError: No module named 'ract'` after install.  
**Cause:** The package was installed into a different Python environment or the editable install was not performed from the repo root.  
**Fix:** Activate the correct virtual environment and reinstall from the project root:

```bash
.venv/Scripts/python -m pip install -e .
```

## Provider connection failures

**Symptom:** `ract doctor` reports a provider as unreachable or every plan fails with a timeout.  
**Cause:** The provider endpoint in `ract.yaml` is wrong, the local model server is not running, or a firewall is blocking the port.  
**Fix:** Check the endpoint with curl and verify the model server is healthy:

```bash
curl http://127.0.0.1:11435/v1/health
```

Then update `ract.yaml` so the provider URL matches the running server.

## Thermal throttling during long runs

**Symptom:** Model calls slow to a crawl or the host becomes unresponsive during a council run.  
**Cause:** The local model servers are pushing the CPU/GPU past its thermal ceiling and the OS is throttling.  
**Fix:** Check `max_temp_c` from the health endpoint. If it is near 96 °C, stop the council and let the machine cool, or reduce concurrency by running one model stream at a time.

```bash
curl -s http://127.0.0.1:11435/v1/health | python -c "import sys,json; print(json.load(sys.stdin)['thermal']['max_temp_c'])"
```

## Git push failures

**Symptom:** `ract release` or a manual `git push` is rejected with a permission error.  
**Cause:** GitHub authentication is missing or the remote URL uses HTTPS without a token.  
**Fix:** Ensure `gh auth status` shows an authenticated user, or switch the remote to SSH:

```bash
git remote set-url origin git@github.com:LucRoot/RACT.git
```

## No consolidation candidates found

**Symptom:** `ract consolidate scan --json` returns an empty `issues` list.  
**Cause:** The scanned modules are not similar enough to meet the default similarity threshold.  
**Fix:** Lower the thresholds or restrict the scan to a smaller set of files:

```bash
ract consolidate scan --similarity-threshold 0.7 --merge-threshold 0.6 --paths src/ract
```
