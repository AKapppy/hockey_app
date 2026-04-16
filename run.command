#!/bin/bash
# Launch the Hockey App (macOS)
# - Runs the package entrypoint: python -m hockey_app
# - Uses your default python3 on PATH

set -euo pipefail
cd "$(dirname "$0")"

export PYTHONDONTWRITEBYTECODE=1
python3 -m hockey_app
