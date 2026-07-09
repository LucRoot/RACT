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
pip install --quiet -e "$WORK_DIR[dev]"
# Pin to mutmut 2.x because 3.x removed the --paths-to-mutate and --runner CLI
# flags and requires pyproject.toml configuration. The 2.x CLI is easier to
# drive from a standalone shell script.
pip install --quiet "mutmut==2.4.5"

python3 -m mutmut run \
    --paths-to-mutate "src/rootact/executor.py,src/rootact/loop_controller.py,src/rootact/harness.py,src/rootact/cli.py" \
    --runner "python3 -m pytest tests/ -q" || true

echo ""
echo "=== Mutation testing complete ==="
python3 -m mutmut results
