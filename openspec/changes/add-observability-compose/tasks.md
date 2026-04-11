## 1. Update Prometheus Configuration

- [x] 1.1 Update `deploy/observability/prometheus/prometheus.yml` — change `higress` scrape target to `hiclaw-manager:8080`
- [x] 1.2 Remove or comment out `nebula-exporter` job (no exporter container in compose)
- [x] 1.3 Update worker scrape targets to actual service names: `hiclaw-graph-worker`, `hiclaw-analytics-worker`

## 2. Add Docker Labels to Services

- [x] 2.1 Add `com.honeybadge.service` label to all honeybadge-* services in `docker-compose.yaml`
- [x] 2.2 Add `com.honeybadge.version` label with value `${IMAGE_TAG:-latest}` to all honeybadge-* services

## 3. Add Observability Services to docker-compose.yaml

- [x] 3.1 Add `prometheus` service (image: prom/prometheus:v2.47.0, profile: observability, port 9090:9090)
- [x] 3.2 Add `grafana` service (image: grafana/grafana:10.1.0, profile: observability, port 3030:3030)
- [x] 3.3 Add `loki` service (image: grafana/loki:2.9.0, profile: observability)
- [x] 3.4 Add `promtail` service (image: grafana/promtail:2.9.0, profile: observability, requires docker.sock mount)
- [x] 3.5 Add `alertmanager` service (image: prom/alertmanager:v0.26.0, profile: observability, port 9093:9093)

## 4. Mount Observability Configs

- [x] 4.1 Mount `deploy/observability/prometheus/prometheus.yml` to prometheus container
- [x] 4.2 Mount `deploy/observability/grafana/provisioning/` to grafana container
- [x] 4.3 Mount `deploy/observability/grafana/dashboards/` to grafana dashboards directory
- [x] 4.4 Mount `deploy/observability/loki/loki-config.yaml` to loki container
- [x] 4.5 Mount `deploy/observability/promtail/promtail-config.yaml` to promtail container
- [x] 4.6 Mount `deploy/observability/alertmanager/alertmanager.yaml` to alertmanager container

## 5. Add Observability Volumes

- [x] 5.1 Add named volumes for prometheus data (prometheus_data)
- [x] 5.2 Add named volumes for grafana data (grafana_data)
- [x] 5.3 Add named volumes for loki data (loki_data)
- [x] 5.4 Add named volumes for promtail positions (promtail_positions)

## 6. Verify Integration

- [x] 6.1 Run `docker compose --profile observability config` to validate syntax
- [x] 6.2 Start observability stack: `docker compose --profile observability up -d`
- [x] 6.3 Verify Prometheus targets: http://localhost:9090/targets — all should show UP
- [x] 6.4 Verify Grafana: http://localhost:3030 — login with admin/admin123
- [x] 6.5 Verify Loki: check logs appear from honeybadge-* containers
- [x] 6.6 Verify Alertmanager: http://localhost:9093 — check configuration
