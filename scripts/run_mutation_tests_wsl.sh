#!/usr/bin/env bash
# Run mutation tests for RACT's four core engine files under WSL.
#
# mutmut does not support native Windows execution (see
# https://github.com/boxed/mutmut/issues/397). This script is the fallback for
# Windows ARM64/x64 hosts that have WSL2 with a Python 3 venv available.
#
# Usage from PowerShell or CMD:
#   wsl -d Ubuntu-24.04 -e bash /mnt/c/Users/rootl/ract-work/scripts/run_mutation_tests_wsl.sh
#
# The script creates a temporary venv inside WSL, installs the project in
# editable mode, runs mutmut against the core files, and prints the mutation
# score.

set -euo pipefail

REPO_ROOT="/mnt/c/Users/rootl/ract-work"
VENV_DIR="$REPO_ROOT/.venv-wsl-mutmut"

cd "$REPO_ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"
pip install --quiet mutmut

# Clear previous run state so the report is fresh.
rm -f .mutmut-cache

python3 -m mutmut run \
    --paths-to-mutate "src/rootact/executor.py,src/rootact/loop_controller.py,src/rootact/harness.py,src/rootact/cli.py" \
    --runner "python3 -m pytest tests/ -q"

echo ""
echo "=== Mutation testing complete ==="
python3 -m mutmut results
