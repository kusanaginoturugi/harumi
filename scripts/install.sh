#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="${HARUMI_VENV_DIR:-"$ROOT_DIR/.venv"}"
BIN_DIR="${HARUMI_BIN_DIR:-"$HOME/.local/bin"}"
INSTALL_MARKITDOWN_EXTRAS=1

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [options]

Install Harumi from this source checkout and expose the `harumi` command.

Options:
  --python PATH              Python executable to use. Default: python3
  --venv PATH                Virtualenv path. Default: .venv inside this repo
  --bin-dir PATH             Directory for the harumi command symlink. Default: ~/.local/bin
  --no-markitdown-extras     Skip optional PDF/Office MarkItDown extras
  -h, --help                 Show this help

Environment overrides:
  PYTHON                     Same as --python
  HARUMI_VENV_DIR            Same as --venv
  HARUMI_BIN_DIR             Same as --bin-dir
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --no-markitdown-extras)
      INSTALL_MARKITDOWN_EXTRAS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 11):
    version = ".".join(map(str, sys.version_info[:3]))
    raise SystemExit(f"Harumi requires Python 3.11 or newer. Found: {version}")
PY

echo "Installing Harumi"
echo "  source: $ROOT_DIR"
echo "  venv:   $VENV_DIR"
echo "  bin:    $BIN_DIR"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -U pip
"$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR"

if [[ "$INSTALL_MARKITDOWN_EXTRAS" -eq 1 ]]; then
  "$VENV_DIR/bin/python" -m pip install -U "markitdown[pdf,docx,pptx,xlsx,xls]"
fi

mkdir -p "$BIN_DIR"
ln -sfn "$VENV_DIR/bin/harumi" "$BIN_DIR/harumi"

echo
echo "Installed: $BIN_DIR/harumi"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Warning: $BIN_DIR is not in PATH."
  echo "Add this to your shell config:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo
"$BIN_DIR/harumi" --help
