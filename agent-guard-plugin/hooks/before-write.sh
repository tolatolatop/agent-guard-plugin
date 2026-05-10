#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo '{"error":"path argument is required"}'
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/../bin/agent-guard" can-write "$1"
