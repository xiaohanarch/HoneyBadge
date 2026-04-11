## ADDED Requirements

### Requirement: Observability stack integration

The system SHALL provide an observability stack integrated into docker-compose for local development and demonstration environments.

#### Scenario: Prometheus metrics collection
- **WHEN** observability profile is enabled with `docker compose --profile observability up`
- **THEN** Prometheus SHALL scrape metrics from all honeybadge-* services and HiClaw Manager
- **AND** Prometheus web UI SHALL be accessible at port 9090

#### Scenario: Grafana visualization
- **WHEN** observability profile is enabled
- **THEN** Grafana SHALL be accessible at port 3030 with default credentials (admin/admin123)
- **AND** Grafana SHALL have pre-configured datasources for Prometheus and Loki
- **AND** Grafana SHALL have HoneyBadge overview dashboard pre-provisioned

#### Scenario: Loki log aggregation
- **WHEN** observability profile is enabled
- **THEN** Loki SHALL receive logs from all containers via Promtail
- **AND** Loki web UI SHALL be accessible for log querying

#### Scenario: Promtail service discovery
- **WHEN** observability profile is enabled
- **THEN** Promtail SHALL automatically discover containers with `com.honeybadge.service` label via Docker socket
- **AND** Promtail SHALL push discovered container logs to Loki

#### Scenario: Alertmanager routing
- **WHEN** observability profile is enabled
- **THEN** Alertmanager SHALL be accessible at port 9093
- **AND** Alertmanager SHALL route alerts based on severity (critical/warning)
- **AND** Alertmanager SHALL send notifications to configured webhook endpoint
