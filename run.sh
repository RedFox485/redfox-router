#!/usr/bin/env bash
# Start the RedFox Router locally.
#   ./run.sh            -> 127.0.0.1:8787
#   PORT=9000 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec uvicorn redfox_router.server:app --host 127.0.0.1 --port "${PORT:-8787}"
