#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT"

PYTHON="${FLOW_PYTHON:-python}"
PARAMS="${FLOW_PARAMS:-$ROOT/workflow/params.yaml}"
HOOK_SCRIPT="${FLOW_HOOK:-$ROOT/workflow/hook.py}"
RUN_ROOT="${FLOW_RUN_ROOT:-$ROOT/runs}"
LOG="$RUN_ROOT/driver.log"

mkdir -p "$RUN_ROOT"

# 每轮最多提交多少个新任务（按队列容量调）
LIMIT=50
# 轮询间隔（秒）
SLEEP=7200

while true; do
  echo "===== $(date) submit-all begin =====" >> "$LOG"
  "$PYTHON" "$HOOK_SCRIPT" --params "$PARAMS" submit-all --limit "$LIMIT" >> "$LOG" 2>&1 || true
  echo "===== $(date) submit-all end =====" >> "$LOG"
  sleep "$SLEEP"
done
