#!/bin/bash
# E2E test runner for K8s ECS environment
# BASE_URL uses Traefik public IP (routes /auth/* and /api/* correctly)
# API direct calls use kubectl port-forward on localhost

LOG=/root/e2e-results.log
JUNIT=/root/e2e-junit.xml

# Truncate (not append) so each run produces a clean log file.
# Previous behavior appended forever, making `tail` mix runs together.
echo '========================================' > $LOG
echo "E2E Test Run: $(date)" >> $LOG
echo '========================================' >> $LOG

# Kill leftover port-forwards
pkill -f 'kubectl port-forward' 2>/dev/null || true
sleep 2

# Port-forward backend services for direct API tests
kubectl port-forward -n honeybadge svc/honeybadge-server 8090:8090 >> /root/pf-server.log 2>&1 &
PF1=$!
kubectl port-forward -n honeybadge svc/honeybadge-auth 8091:8091 >> /root/pf-auth.log 2>&1 &
PF2=$!

echo "Port-forwards started (PIDs: $PF1 $PF2)" >> $LOG
sleep 5

# Wait for auth service ready (direct port-forward)
for i in $(seq 1 15); do
  curl -sf http://localhost:8091/health > /dev/null 2>&1 && echo "Auth ready (${i}s)" >> $LOG && break
  sleep 2
done

# Wait for Traefik frontend ready (public IP)
for i in $(seq 1 15); do
  curl -sf http://8.130.95.169/healthz > /dev/null 2>&1 && echo "Traefik frontend ready (${i}s)" >> $LOG && break
  sleep 2
done

echo 'Starting pytest...' >> $LOG

cd /root/HoneyBadge
# MATRIX_HOMESERVER_LOCAL is set to the same NodePort URL the auth service returns,
# so conftest._patch_login's matrix_homeserver rewrite is effectively a no-op in
# the on-cluster scenario (Tuwunel NodePort 30167 is reachable from inside the
# cluster and from the ECS node itself).
BASE_URL=${BASE_URL:-http://8.130.95.169} \
API_BASE_URL=${API_BASE_URL:-http://localhost:8090} \
AUTH_BASE_URL=${AUTH_BASE_URL:-http://localhost:8091} \
MATRIX_HOMESERVER_LOCAL=${MATRIX_HOMESERVER_LOCAL:-http://8.130.95.169:30167} \
python3 -m pytest "${@:-tests/e2e/}" \
  -v --tb=short \
  --junitxml=$JUNIT \
  --ignore=tests/e2e/test_09_observability.py \
  --ignore=tests/e2e/test_08_infra.py \
  2>&1 | tee -a $LOG

# Capture pytest's exit code (not tee's). Without this, a failing or
# crashing pytest is masked by tee's exit 0 and the caller sees success.
EXIT=${PIPESTATUS[0]}
echo "========================================" >> $LOG
echo "Test exit code: $EXIT  Finished: $(date)" >> $LOG
echo "========================================" >> $LOG

kill $PF1 $PF2 2>/dev/null || true

# Exit with pytest's exit code so callers (e.g. the GitHub workflow's
# `bash run-e2e-ecs.sh "$TARGET" || E2E_EXIT=$?` clause) see the truth.
exit $EXIT
