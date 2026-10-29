#!/usr/bin/env bash
# AGMO çalıştırıcısı (Linux/macOS): venv kur -> paketi bağla -> çalıştır
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
    ./.venv/bin/pip install -q --upgrade pip
fi
./.venv/bin/pip install -q -e . >/dev/null 2>&1 || \
    ./.venv/bin/pip install -q -e .
exec ./.venv/bin/python -m agmo "$@"