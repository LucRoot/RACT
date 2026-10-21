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
            # The directory is optional: `--venv` alone means `.venv`.
            if [[ $# -ge 2 && "$2" != --* ]]; then
                VENV_DIR="$2"
                shift 2
            else
                VENV_DIR=".venv"
                shift
            fi
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
  --venv [DIR]  Create and install into a virtual environment at DIR
                (default: .venv). Recommended on Ubuntu/Debian, where
                system-wide pip is blocked (PEP 668).
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

if [[ "$INSTALL_FLAGS" == "-e" && "$SOURCE" != "local" ]]; then
    warn "--edit only applies with --local; ignoring."
    INSTALL_FLAGS=""
fi

if [[ -n "$VENV_DIR" ]]; then
    log "creating virtual environment at $VENV_DIR"
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    PYTHON_CMD=$(command -v python)
fi

# PEP 668 (Ubuntu 23.04+, Debian 12+, recent Homebrew): system pip refuses to
# install. Print the fix instead of leaving the user with pip's raw error.
pip_install() {
    if ! "$PYTHON_CMD" -m pip install "$@"; then
        if [[ -z "$VENV_DIR" && -z "${VIRTUAL_ENV:-}" ]]; then
            warn "pip failed outside a virtual environment."
            warn "if the error was 'externally-managed-environment', rerun with:"
            warn "  bash scripts/install.sh --local --venv"
        fi
        exit 1
    fi
}

if [[ "$SOURCE" == "local" ]]; then
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    PROJECT_DIR=$(dirname "$SCRIPT_DIR")
    if [[ -n "$INSTALL_FLAGS" ]]; then
        log "installing RACT in editable mode from $PROJECT_DIR"
        pip_install "$INSTALL_FLAGS" "$PROJECT_DIR"
    else
        log "installing RACT from local source at $PROJECT_DIR"
        pip_install "$PROJECT_DIR"
    fi
else
    log "installing RACT from PyPI"
    pip_install --upgrade ract
fi

if command -v ract >/dev/null 2>&1; then
    INSTALLED_VERSION=$(ract --version || true)
    log "installed successfully: $INSTALLED_VERSION"
    log "run 'ract --help' to get started."
else
    warn "ract command not found on PATH after install."
    warn "you may need to add your Python scripts directory to PATH."
fi

if [[ -n "$VENV_DIR" ]]; then
    # `source` above only affected this script's shell, not the caller's.
    log "activate it in your shell with: source $VENV_DIR/bin/activate"
fi
# RACT 0.1.1 - Trust and tooling
