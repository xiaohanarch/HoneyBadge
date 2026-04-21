#!/usr/bin/env bash
# =============================================================================
# HoneyBadge E2E Tests — Remote ECS Runner
# =============================================================================
# Tests run as a DETACHED background process on ECS.
# Local machine can be shut down at any time after launch.
#
# Usage:
#   ./scripts/run-e2e-remote.sh [--filter <module>]   # Launch (returns immediately)
#   ./scripts/run-e2e-remote.sh --status              # Show current status / results
#   ./scripts/run-e2e-remote.sh --follow              # Stream live output (Ctrl+C safe)
#   ./scripts/run-e2e-remote.sh --cancel              # Kill running job
#
# Filter modules: auth chat session isolation permission antihal mcp infra
#                 observability context routing
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
ECS_HOST="8.130.95.169"
ECS_USER="root"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/honeybadge_ecs}"
REMOTE_DIR="/tmp/honeybadge-e2e"
LOG_FILE="$REMOTE_DIR/results.log"
PID_FILE="$REMOTE_DIR/runner.pid"
SUMMARY_FILE="$REMOTE_DIR/summary.txt"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[e2e]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC}  $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[fail]${NC} $*" >&2; }

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o BatchMode=yes $ECS_USER@$ECS_HOST"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── Args ──────────────────────────────────────────────────────────────────────
FILTER=""
MODE="run"
while [[ $# -gt 0 ]]; do
  case $1 in
    --filter)   FILTER="$2"; shift 2 ;;
    --status)   MODE="status"; shift ;;
    --follow)   MODE="follow"; shift ;;
    --cancel)   MODE="cancel"; shift ;;
    --help|-h)
      sed -n '2,15p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) fail "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Status / Follow / Cancel (no sync needed) ────────────────────────────────
if [[ "$MODE" == "status" ]]; then
  echo ""
  $SSH bash -s << REMOTE
set -euo pipefail
LOG="$LOG_FILE"; PID_F="$PID_FILE"; SUM="$SUMMARY_FILE"
if [[ -f "\$PID_F" ]]; then
  PID=\$(cat "\$PID_F")
  if ps -p "\$PID" -o args= 2>/dev/null | grep -q "runner.sh"; then
    echo -e "\033[1;33m[RUNNING]\033[0m  PID \$PID — use --follow to stream output"
  else
    echo -e "\033[0;32m[FINISHED]\033[0m"
  fi
else
  echo "[NO JOB] No test run found. Use run-e2e-remote.sh to start one."
fi
echo ""
if [[ -f "\$SUM" ]]; then
  cat "\$SUM"
elif [[ -f "\$LOG" ]]; then
  echo "── Last 40 lines ──────────────────────────────────"
  tail -40 "\$LOG"
fi
REMOTE
  exit 0
fi

if [[ "$MODE" == "follow" ]]; then
  log "Streaming live output (Ctrl+C to detach — tests keep running on ECS)"
  $SSH "tail -f $LOG_FILE" || true
  exit 0
fi

if [[ "$MODE" == "cancel" ]]; then
  $SSH bash -s << REMOTE
if [[ -f "$PID_FILE" ]]; then
  PID=\$(cat "$PID_FILE")
  kill "\$PID" 2>/dev/null && echo "Cancelled PID \$PID" || echo "No process found for PID \$PID"
  rm -f "$PID_FILE"
else
  echo "No running job found."
fi
REMOTE
  exit 0
fi

# ── Map filter names to test files ───────────────────────────────────────────
declare -A FILTER_MAP=(
  [auth]="test_01_auth.py"
  [chat]="test_02_chat.py"
  [session]="test_03_session.py"
  [isolation]="test_04_isolation.py"
  [permission]="test_05_permissions.py"
  [antihal]="test_06_antihal.py"
  [mcp]="test_07_mcp.py"
  [infra]="test_08_infra.py"
  [observability]="test_09_observability.py"
  [context]="test_10_context_and_memory.py"
  [routing]="test_11_worker_routing.py"
)

TEST_PATHS=""
if [[ -n "$FILTER" ]]; then
  IFS=',' read -ra MODULES <<< "$FILTER"
  for m in "${MODULES[@]}"; do
    m="${m// /}"
    if [[ -z "${FILTER_MAP[$m]+x}" ]]; then
      fail "Unknown filter '$m'. Available: ${!FILTER_MAP[*]}"; exit 1
    fi
    TEST_PATHS="$TEST_PATHS tests/e2e/${FILTER_MAP[$m]}"
  done
  TEST_PATHS="${TEST_PATHS# }"
else
  TEST_PATHS="tests/e2e/"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  HoneyBadge E2E — Remote ECS Runner"
echo "  Host   : $ECS_USER@$ECS_HOST"
echo "  Tests  : ${TEST_PATHS}"
echo "  Mode   : detached (local machine can be shut down)"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 1. Sync test files ────────────────────────────────────────────────────────
log "Syncing test files to ECS…"
$SSH "mkdir -p $REMOTE_DIR"
(cd "$REPO_ROOT" && tar -czf - \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  tests/ pytest.ini \
) | $SSH "tar -xzf - -C $REMOTE_DIR"
ok "Test files synced"

# ── 2. Write runner script to ECS ─────────────────────────────────────────────
log "Uploading runner script…"
TEST_PATHS_ESCAPED="$TEST_PATHS"

$SSH "cat > $REMOTE_DIR/runner.sh" << RUNNER_SCRIPT
#!/usr/bin/env bash
set -euo pipefail
REMOTE_DIR="$REMOTE_DIR"
TEST_PATHS="$TEST_PATHS_ESCAPED"
LOG_FILE="$LOG_FILE"
SUMMARY_FILE="$SUMMARY_FILE"
START_TS=\$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[\$(date '+%H:%M:%S')] \$*" | tee -a "\$LOG_FILE"; }

echo "" >> "\$LOG_FILE"
echo "══════════════════════════════════════════════" >> "\$LOG_FILE"
echo "  HoneyBadge E2E — Started \$START_TS" >> "\$LOG_FILE"
echo "  Tests: \$TEST_PATHS" >> "\$LOG_FILE"
echo "══════════════════════════════════════════════" >> "\$LOG_FILE"

# ── Python environment ───────────────────────────────────────────────────────
log "Checking Python environment…"
MISSING=""
command -v python3 &>/dev/null || MISSING="python3 \$MISSING"
python3 -m venv --help &>/dev/null || MISSING="python3-venv \$MISSING"
command -v pip3 &>/dev/null   || MISSING="python3-pip \$MISSING"
if [[ -n "\$MISSING" ]]; then
  log "Installing: \$MISSING"
  DEBIAN_FRONTEND=noninteractive apt-get install -y \$MISSING >> "\$LOG_FILE" 2>&1
fi

VENV="\$REMOTE_DIR/.venv"
if [[ ! -f "\$VENV/bin/activate" ]]; then
  log "Creating virtualenv…"
  rm -rf "\$VENV"
  python3 -m venv "\$VENV"
fi
source "\$VENV/bin/activate"

# ── Install pip deps (hash-gated) ────────────────────────────────────────────
REQ_FILE="\$REMOTE_DIR/tests/e2e/requirements.txt"
REQ_HASH_FILE="\$VENV/.req_hash"
REQ_HASH=\$(md5sum "\$REQ_FILE" | cut -d' ' -f1)
if [[ ! -f "\$REQ_HASH_FILE" ]] || [[ "\$(cat "\$REQ_HASH_FILE")" != "\$REQ_HASH" ]]; then
  log "Installing Python deps…"
  pip install --quiet --upgrade pip >> "\$LOG_FILE" 2>&1
  pip install --quiet -r "\$REQ_FILE" >> "\$LOG_FILE" 2>&1
  echo "\$REQ_HASH" > "\$REQ_HASH_FILE"
  log "Python deps installed"
else
  log "Python deps up to date"
fi

# ── Install Chromium (binary-check, no spurious reinstall) ───────────────────
CHROMIUM_BIN=\$(find "\${PLAYWRIGHT_BROWSERS_PATH:-\$HOME/.cache/ms-playwright}" \
  -name "chrome" -path "*/chromium-*/chrome-linux/*" 2>/dev/null | head -1)
if [[ -z "\$CHROMIUM_BIN" ]]; then
  log "Installing Playwright Chromium (first run, ~1 min)…"
  "\$VENV/bin/playwright" install chromium --with-deps >> "\$LOG_FILE" 2>&1
  log "Chromium installed"
else
  log "Chromium already cached: \$CHROMIUM_BIN"
fi

# ── Service connectivity check ───────────────────────────────────────────────
log "Verifying service connectivity…"
for svc in "80/:frontend" "8090/api/health:server" "8091/health:auth"; do
  path="\${svc%%:*}"; port="\${path%%/*}"; urlpath="/\${path#*/}"; name="\${svc##*:}"
  if curl -sf -o /dev/null "http://localhost:\${port}\${urlpath}" 2>/dev/null; then
    log "\$name OK (localhost:\$port)"
  else
    log "WARNING: \$name not responding (localhost:\$port) — tests may fail"
  fi
done

# ── Run pytest ───────────────────────────────────────────────────────────────
cd "\$REMOTE_DIR"
export BASE_URL="http://localhost"
export API_BASE_URL="http://localhost:8090"
export AUTH_BASE_URL="http://localhost:8091"
export PYTHONPATH="\$REMOTE_DIR"

PYTEST_ARGS="-v --tb=short --timeout=300 --disable-warnings"
if python3 -c "import xdist" 2>/dev/null && [[ "\$TEST_PATHS" == "tests/e2e/" ]]; then
  PYTEST_ARGS="\$PYTEST_ARGS -n 3"
  log "Parallel mode: 3 workers"
fi

log "Running: pytest \$TEST_PATHS \$PYTEST_ARGS"
echo "───────────────────────────────────────────────" >> "\$LOG_FILE"

EXIT_CODE=0
"\$VENV/bin/pytest" \$TEST_PATHS \$PYTEST_ARGS >> "\$LOG_FILE" 2>&1 || EXIT_CODE=\$?

END_TS=\$(date '+%Y-%m-%d %H:%M:%S')
echo "───────────────────────────────────────────────" >> "\$LOG_FILE"

# ── Write summary ────────────────────────────────────────────────────────────
{
  echo "══════════════════════════════════════════════"
  echo "  E2E Test Run Summary"
  echo "  Started : \$START_TS"
  echo "  Finished: \$END_TS"
  echo "  Tests   : \$TEST_PATHS"
  if [[ \$EXIT_CODE -eq 0 ]]; then
    echo "  Result  : ALL PASSED ✓"
  else
    echo "  Result  : FAILED (exit \$EXIT_CODE)"
  fi
  echo "══════════════════════════════════════════════"
  echo ""
  # Extract pytest summary lines
  grep -E "^(PASSED|FAILED|ERROR|tests/e2e|=====)" "\$LOG_FILE" | tail -30 || true
} > "\$SUMMARY_FILE"

log "Done. Summary written to \$SUMMARY_FILE"
exit \$EXIT_CODE
RUNNER_SCRIPT

ok "Runner script uploaded"

# ── 3. Launch detached — survives SSH disconnect / local shutdown ──────────────
log "Launching detached test job on ECS…"

$SSH "
  # Kill any previous run
  if [[ -f $PID_FILE ]]; then
    OLD_PID=\$(cat $PID_FILE)
    kill \$OLD_PID 2>/dev/null || true
  fi
  rm -f $LOG_FILE $SUMMARY_FILE $PID_FILE
  touch $LOG_FILE
  # nohup + </dev/null ensures complete detachment from this SSH session
  nohup bash $REMOTE_DIR/runner.sh > $LOG_FILE 2>&1 < /dev/null &
  echo \$! > $PID_FILE
  echo \"Job started: PID \$(cat $PID_FILE)\"
  echo \"Log: $LOG_FILE\"
"

echo ""
ok "═══ Tests launched on ECS — local machine can now be shut down ═══"
echo ""
echo "  Check status:  bash scripts/run-e2e-remote.sh --status"
echo "  Stream output: bash scripts/run-e2e-remote.sh --follow"
echo "  Cancel job:    bash scripts/run-e2e-remote.sh --cancel"
echo ""
