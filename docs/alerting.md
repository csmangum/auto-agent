# Alerting

Prometheus alert rules and configuration for the claim agent. Use with [Prometheus](https://prometheus.io) and [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/).

Ready-to-use configuration files live in the `monitoring/` directory:

| File | Purpose |
|------|---------|
| `monitoring/prometheus.yml` | Prometheus scrape config and rule file reference |
| `monitoring/alert_rules.yml` | All alert rules (7 rules) |
| `monitoring/alertmanager.yml` | Alertmanager routing skeleton |
| `monitoring/grafana/provisioning/` | Grafana auto-provisioning (datasource + dashboard provider) |
| `monitoring/grafana/dashboards/claim-agent.json` | Pre-built Grafana dashboard |

## Quick Start (Docker Compose)

Start the full monitoring stack alongside the claim agent:

```bash
docker compose --profile monitoring up
```

| Service | URL |
|---------|-----|
| Claim agent | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Grafana | http://localhost:3000 (admin / admin) |

The Grafana dashboard is provisioned automatically on startup.

## Scrape Configuration

`monitoring/prometheus.yml` is pre-configured to scrape the claim agent inside Docker Compose. If you run Prometheus externally, add this to your own `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: claim-agent
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: /metrics
    scrape_interval: 15s
```

If the agent runs behind a reverse proxy or on a different port, adjust `targets` accordingly.

## Alert Rules

`monitoring/alert_rules.yml` contains the following rules:

| Alert | Severity | Condition |
|-------|----------|-----------|
| `ClaimAgentDown` | critical | Service unreachable for 1 min |
| `ClaimAgentHighErrorRate` | warning | Error rate > 5% over 5 min (failed / processed + failed + escalated) |
| `ClaimAgentHighLatency` | warning | P99 latency > 120 s |
| `ClaimAgentEscalationSpike` | info | > 10 escalations in 1 h |
| `ClaimAgentReviewQueueBacklog` | warning | Queue > 50 for 30+ min |
| `ClaimAgentDBConnectionFailure` | critical | Database unreachable for 1 min |
| `ClaimAgentLLMCostAnomaly` | warning | LLM spend > $10 in 1 h |

## Alertmanager Integration

Edit `monitoring/alertmanager.yml` to add your receivers. Example for a Slack webhook:

```yaml
receivers:
  - name: claims-team
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        channel: '#claims-alerts'
        send_resolved: true
```

Example for a generic webhook:

```yaml
receivers:
  - name: claims-team
    webhook_configs:
      - url: 'https://your-webhook.example.com/claims-alerts'
        send_resolved: true
```

## Health Check

The health endpoint (`GET /api/health`, `/health`, or `/healthz`) returns:

- **200** when the database is connected
- **503** when the database is unreachable

Use it for load balancer health checks or Kubernetes liveness/readiness probes:

```yaml
# Kubernetes example
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

## Tuning Thresholds

Adjust the alert thresholds in `monitoring/alert_rules.yml` to match your SLOs:

| Alert | Default | Tune for |
|-------|--------|----------|
| High error rate | 5% | Failed claims as a share of processed + failed + escalated; tune for your mix |
| P99 latency | 120 s | Typical claim processing time; lower for faster workflows |
| Escalation spike | 10/hour | Normal escalation volume; raise for high-throughput deployments |
| Review queue | 50 | Adjuster capacity; lower if team is small |
| LLM cost anomaly | $10/hour | Expected LLM spend; raise for high-traffic deployments |
