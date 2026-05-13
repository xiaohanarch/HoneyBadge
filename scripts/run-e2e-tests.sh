#!/bin/bash
# =============================================================================
# HoneyBadge E2E Test Runner - Local Development
# =============================================================================
# This script runs E2E tests locally with the same setup as GitHub Actions.
# Usage:
#   ./scripts/run-e2e-tests.sh                    # Run all tests
#   ./scripts/run-e2e-tests.sh --filter auth      # Run only auth tests
#   ./scripts/run-e2e-tests.sh --filter chat,session  # Run specific tests
#   ./scripts/run-e2e-tests.sh --setup-only       # Only start infra, don't run tests
#   ./scripts/run-e2e-tests.sh --teardown-only    # Only stop infra
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="deploy/docker/docker-compose.yaml"
ENV_FILE="deploy/docker/.env"
TIMEOUT_SECONDS=300

# Parse arguments
FILTER=""
SETUP_ONLY=false
TEARDOWN_ONLY=false
SKIP_SETUP=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --filter)
      FILTER="$2"
      shift 2
      ;;
    --setup-only)
      SETUP_ONLY=true
      shift
      ;;
    --teardown-only)
      TEARDOWN_ONLY=true
      shift
      ;;
    --skip-setup)
      SKIP_SETUP=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [options]"
      echo ""
      echo "Options:"
      echo "  --filter <tests>     Run specific test groups (auth,chat,session,isolation,permission,antihal,mcp,infra,observability)"
      echo "  --setup-only         Only start infrastructure, don't run tests"
      echo "  --teardown-only       Only stop infrastructure"
      echo "  --skip-setup         Skip infrastructure setup (assume services are running)"
      echo "  --help, -h            Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
  echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

check_service() {
  local url=$1
  local name=$2
  local max_attempts=${3:-60}
  local interval=${4:-2}

  log_info "Checking $name at $url..."

  for i in $(seq 1 $max_attempts); do
    if curl -sf "$url" > /dev/null 2>&1; then
      log_success "$name is ready"
      return 0
    fi
    echo -ne "\rWaiting for $name... ($i/$max_attempts)   "
    sleep $interval
  done

  echo ""
  log_error "$name failed to start"
  return 1
}

# =============================================================================
# Setup Infrastructure
# =============================================================================

setup_infrastructure() {
  log_info "Setting up HoneyBadge infrastructure..."

  cd "$(dirname "$0")/.."

  # Check if Docker is running
  if ! docker info > /dev/null 2>&1; then
    log_error "Docker is not running. Please start Docker Desktop."
    exit 1
  fi

  # Check if .env file exists
  if [ ! -f "$ENV_FILE" ]; then
    log_warning ".env file not found at $ENV_FILE"
    log_info "Copying from template if available..."
    if [ -f "$ENV_FILE.example" ]; then
      cp "$ENV_FILE.example" "$ENV_FILE"
    fi
  fi

  # Start core services
  log_info "Starting core services..."
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE up -d

  # Start observability stack
  log_info "Starting observability stack..."
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" --profile observability up -d

  # Wait for core services
  log_info "Waiting for services to be healthy..."

  check_service "http://localhost:8090/api/health" "honeybadge-server" 60 2
  check_service "http://localhost:8091/health" "honeybadge-auth" 60 2

  # Initialize NebulaGraph schema
  log_info "Initializing NebulaGraph schema..."
  bash deploy/docker/init-nebula.sh

  # Seed NebulaGraph with ERP fixtures (idempotent — uses IF NOT EXISTS)
  log_info "Seeding NebulaGraph fixtures..."
  bash deploy/docker/seed-nebula.sh

  # Initialize HiClaw workers
  log_info "Initializing HiClaw workers..."
  bash deploy/hiclaw/init-workers.sh

  # Restart workers
  log_info "Restarting workers..."
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" restart hiclaw-graph-worker hiclaw-analytics-worker

  # Wait for workers
  log_info "Waiting for workers to connect..."
  sleep 30

  log_success "Infrastructure is ready!"

  # Show status
  echo ""
  echo "=== Container Status ==="
  docker compose -f "$COMPOSE_FILE" ps
  echo ""
  echo "=== Service URLs ==="
  echo "Frontend:     http://localhost:3000"
  echo "API Server:   http://localhost:8090"
  echo "Auth:        http://localhost:8091"
  echo "Prometheus:  http://localhost:9090"
  echo "Grafana:     http://localhost:3030"
  echo ""
}

# =============================================================================
# Teardown Infrastructure
# =============================================================================

teardown_infrastructure() {
  log_info "Tearing down HoneyBadge infrastructure..."

  cd "$(dirname "$0")/.."

  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down

  log_success "Infrastructure has been stopped"
}

# =============================================================================
# Run Tests
# =============================================================================

run_tests() {
  log_info "Running E2E tests..."

  cd "$(dirname "$0")/.."

  # Set environment variables
  export BASE_URL="${BASE_URL:-http://localhost:3000}"
  export API_BASE_URL="${API_BASE_URL:-http://localhost:8090}"
  export AUTH_BASE_URL="${AUTH_BASE_URL:-http://localhost:8091}"

  # Build pytest command
  PYTEST_CMD="pytest tests/e2e/ -v --tb=short --timeout=120 -x"

  # Add test filter if specified
  if [ -n "$FILTER" ]; then
    log_info "Running tests with filter: $FILTER"

    # Map filter names to test files
    case "$FILTER" in
      auth)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_01_auth.py"
        ;;
      chat)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_02_chat.py"
        ;;
      session)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_03_session.py"
        ;;
      isolation)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_04_isolation.py"
        ;;
      permission)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_05_permissions.py"
        ;;
      antihal)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_06_antihal.py"
        ;;
      mcp)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_07_mcp.py"
        ;;
      infra)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_08_infra.py"
        ;;
      observability)
        PYTEST_CMD="$PYTEST_CMD tests/e2e/test_09_observability.py"
        ;;
      *)
        log_error "Unknown filter: $FILTER"
        log_info "Available filters: auth, chat, session, isolation, permission, antihal, mcp, infra, observability"
        exit 1
        ;;
    esac
  fi

  # Run tests
  echo ""
  log_info "Executing: $PYTEST_CMD"
  echo ""

  if eval "$PYTEST_CMD"; then
    log_success "All tests passed!"
    return 0
  else
    log_error "Some tests failed"
    return 1
  fi
}

# =============================================================================
# Main
# =============================================================================

main() {
  echo ""
  echo "=============================================="
  echo "  HoneyBadge E2E Test Runner"
  echo "=============================================="
  echo ""

  # Handle teardown-only mode
  if [ "$TEARDOWN_ONLY" = true ]; then
    teardown_infrastructure
    exit 0
  fi

  # Handle setup-only mode
  if [ "$SETUP_ONLY" = true ]; then
    setup_infrastructure
    exit 0
  fi

  # Setup infrastructure unless skipped
  if [ "$SKIP_SETUP" = false ]; then
    setup_infrastructure
  fi

  echo ""
  log_info "Ready to run tests. Press Ctrl+C to abort."
  sleep 2

  # Run tests
  if run_tests; then
    echo ""
    log_success "=============================================="
    log_success "  All E2E Tests Passed!"
    log_success "=============================================="
    exit 0
  else
    echo ""
    log_error "=============================================="
    log_error "  E2E Tests Failed!"
    log_error "=============================================="

    # Get logs for debugging
    echo ""
    log_info "Gathering debug information..."
    echo ""
    echo "=== Recent Container Logs ==="
    docker compose -f "$COMPOSE_FILE" logs --tail=50

    exit 1
  fi
}

# Run main function
main
