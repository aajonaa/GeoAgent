#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_HOME="${GEOAGENT_BACKLOG_HOME:-$HOME/.local/share/geoagent/backlog-md/1.53.0}"
CLI="$TOOL_HOME/node_modules/backlog.md/cli.js"
if [[ ! -f "$CLI" ]]; then
  printf '%s\n' "Install backlog.md@1.53.0 into $TOOL_HOME first." >&2
  exit 1
fi
cd -- "$ROOT"
exec node "$CLI" browser --port "${GEOAGENT_BOARD_PORT:-6420}" --no-open