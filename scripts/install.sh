#!/usr/bin/env bash
# Rooted by Dr. Lucas Root, Ph.D.
# Cross-platform install script for RACT.
# Works on macOS, Linux, and Windows via Git Bash / WSL.

set -euo pipefail

RACT_NAME="RACT"
REPO_URL="https://github.com/LucRoot/RACT"
PYTHON_MIN="3.11"

log() {
    echo "[ract-install] $*"
}

warn() {
    echo "[ract-install] warning: $*" >&2
}

find_python() {
    for cmd in python3.12 python3.11 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            "$cmd" --version >/dev/null 2>&1 && echo "$cmd" && return 0
        fi
    done
    return 1
}

PYTHON_CMD=$(find_python) || {
    echo "[ract-install] error: Python $PYTHON_MIN+ is required but not found." >&2
    exit 1
}

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
log "found Python $PYTHON_VERSION ($PYTHON_CMD)"

# macOS gets a quiet nod: RACT is forged on Windows, but it runs just as well
# on a MacBook in a coffee shop.
OS=$(uname -s)
case "$OS" in
    Darwin)
        log "macOS detected. Same wheel, no fan noise."
        ;;
    Linux)
        log "Linux detected."
        ;;
    MINGW* | MSYS* | CYGWIN*)
        log "Windows shell detected."
        ;;
    *)
        log "detected OS: $OS"
        ;;
esac

INSTALL_FLAGS=""
SOURCE="pypi"
VENV_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)
            SOURCE="local"
            shift
            ;;
        --venv)
            VENV_DIR="${2:-.venv}"
            shift 2
            ;;
        --edit)
            INSTALL_FLAGS="-e"
            shift
            ;;
        --help)
            cat << 'EOF'
Usage: install.sh [options]

Options:
  --local       Install from the current source tree instead of PyPI.
  --venv DIR    Create and install into a virtual environment at DIR.
  --edit        Install in editable mode (only with --local).
  --help        Show this message.
EOF
            exit 0
            ;;
        *)
            warn "unknown argument: $1"
            shift
            ;;
    esac
done

if [[ -n "$VENV_DIR" ]]; then
    log "creating virtual environment at $VENV_DIR"
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    PYTHON_CMD=$(command -v python)
fi

if [[ "$SOURCE" == "local" ]]; then
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    PROJECT_DIR=$(dirname "$SCRIPT_DIR")
    if [[ -n "$INSTALL_FLAGS" ]]; then
        log "installing RACT in editable mode from $PROJECT_DIR"
        "$PYTHON_CMD" -m pip install "$INSTALL_FLAGS" "$PROJECT_DIR"
    else
        log "installing RACT from local source at $PROJECT_DIR"
        "$PYTHON_CMD" -m pip install "$PROJECT_DIR"
    fi
else
    log "installing RACT from PyPI"
    "$PYTHON_CMD" -m pip install --upgrade rootact
fi

if command -v rootact >/dev/null 2>&1; then
    INSTALLED_VERSION=$(rootact --version || true)
    log "installed successfully: $INSTALLED_VERSION"
    log "run 'rootact --help' to get started."
else
    warn "rootact command not found on PATH after install."
    warn "you may need to add your Python scripts directory to PATH."
fi
