#!/usr/bin/env bash
# Run mutation tests for RACT's four core engine files under WSL.
#
# mutmut does not support native Windows execution (see
# https://github.com/boxed/mutmut/issues/397). This script is the fallback for
# Windows ARM64/x64 hosts that have WSL2 with a Python 3 venv available.
#
# Usage from PowerShell or CMD (adjust the WSL path to your repo location):
#   wsl -d Ubuntu-24.04 -e bash /mnt/c/<user>/<repo>/scripts/run_mutation_tests_wsl.sh
#
# The script creates a temporary venv inside WSL, installs the project in
# editable mode, runs mutmut against the core files, and prints the mutation
# score.
#
# Environment variables:
#   RACT_MUTATION_TARGETS  comma-separated paths to mutate (default: four core files)
#   RACT_TEST_RUNNER       command used by mutmut to check each mutant (default: auto)
#
# When RACT_TEST_RUNNER is not set, the script tries to run only the test file
# that matches a single mutation target (src/rootact/foo.py -> tests/test_foo.py)
# to keep mutant checking fast. For multiple targets it falls back to the full
# suite, which is slow but safe.

set -uo pipefail

# Derive the repository root from the script's location so the runner is
# portable across WSL mounts and machines.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Keep the WSL venv outside the repository so it is never scanned by RACT's
# own file walkers (symbol graph, novelty detector, dead-code auction).
VENV_DIR="${HOME}/.cache/ract-mutmut-venv"
# Work on a clean copy of the repo inside WSL-native /tmp. This avoids SQLite
# cache corruption on the Windows 9P mount and prevents mutmut's source-mtime
# checks from clearing the cache between "run" and "results".
WORK_DIR="/tmp/ract-mutmut-src"

MUTATION_TARGETS="${RACT_MUTATION_TARGETS:-src/rootact/executor.py,src/rootact/loop_controller.py,src/rootact/harness.py,src/rootact/cli.py}"

# Determine the test runner. Prefer a user override, then a single matching
# test file, then fall back to the full suite.
if [[ -n "${RACT_TEST_RUNNER:-}" ]]; then
    TEST_RUNNER="$RACT_TEST_RUNNER"
else
    # Count targets by checking for commas.
    if [[ "$MUTATION_TARGETS" != *,* ]]; then
        target_basename="$(basename "$MUTATION_TARGETS" .py)"
        matching_test="tests/test_${target_basename}.py"
        if [[ -f "$matching_test" ]]; then
            TEST_RUNNER="python3 -m pytest ${matching_test} -q"
        else
            TEST_RUNNER="python3 -m pytest tests/ -q"
        fi
    else
        TEST_RUNNER="python3 -m pytest tests/ -q"
    fi
fi

cd "$REPO_ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
fi

# Export a clean, committed snapshot of the repo to the WSL work directory.
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$WORK_DIR"

cd "$WORK_DIR"

source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
# Remove any stale editable install so the fresh install cannot inherit old
# metadata or source paths from previous runs.
pip uninstall -y rootact >/dev/null 2>&1 || true
pip install --quiet --force-reinstall --no-deps -e "$WORK_DIR[dev]"
# Pin to mutmut 2.x because 3.x removed the --paths-to-mutate and --runner CLI
# flags and requires pyproject.toml configuration. The 2.x CLI is easier to
# drive from a standalone shell script.
pip install --quiet "mutmut==2.4.5"

export PYTHONUNBUFFERED=1

echo ""
echo "=== Running mutation tests on: $MUTATION_TARGETS ==="
echo "=== Test runner: $TEST_RUNNER ==="
echo ""

python3 -m mutmut run \
    --paths-to-mutate "$MUTATION_TARGETS" \
    --runner "$TEST_RUNNER" || true

echo ""
echo "=== Mutation testing complete ==="
python3 -m mutmut results
# RACT 0.1.1 - Trust and Tooling
