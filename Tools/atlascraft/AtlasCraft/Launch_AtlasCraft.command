#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "AtlasCraft requires Python 3.10 or newer. Install Python from https://www.python.org/downloads/ and reopen this file."
  read -r -p "Press Return to close." _atlascraft_answer
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "AtlasCraft requires Python 3.10 or newer."'
if [ ! -x .venv/bin/atlascraft ]; then
  echo "Preparing AtlasCraft. The first launch downloads its Python dependencies."
  python3 -m venv .venv
  .venv/bin/python -m pip install .
fi
exec .venv/bin/atlascraft serve
