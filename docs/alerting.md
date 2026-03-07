# Alerting

Recommended Prometheus alert rules and configuration for the claim agent. Use with [Prometheus](https://prometheus.io) and [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/).

## Scrape Configuration

Add the claim agent to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: claim-agent
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: /metrics
    scrape_interval: 15s
```

If the agent runs behind a reverse proxy or on a different port, adjust `targets` accordingly.

## Recommended Alert Rules

Save as `claim-agent-alerts.yml` and include in your Prometheus config:

```yaml
groups:
  - name: claim-agent
    rules:
      # Service down
      - alert: ClaimAgentDown
        expr: up{job="claim-agent"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Claim agent is down"
          description: "Prometheus cannot scrape {{ $labels.instance }} for 1 minute."

      # High error rate
      - alert: ClaimAgentHighErrorRate
        expr: |
          (
            rate(claims_failed_total[5m])
            /
            (rate(claims_processed_total[5m]) + rate(claims_failed_total[5m]) + 1e-9)
          ) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Claim agent error rate above 5%"
          description: "More than 5% of claims are failing over the last 5 minutes."

      # P99 latency SLO breach
      - alert: ClaimAgentHighLatency
        expr: |
          histogram_quantile(0.99, rate(claim_processing_duration_seconds_bucket[5m])) > 120
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Claim agent P99 latency above 2 minutes"
          description: "99th percentile claim processing time exceeds 120 seconds."

      # Escalation spike (fraud or review queue buildup)
      - alert: ClaimAgentEscalationSpike
        expr: increase(claims_escalated_total[1h]) > 10
        for: 0m
        labels:
          severity: info
        annotations:
          summary: "Elevated claim escalations in the last hour"
          description: "More than 10 claims escalated to human review in the past hour."

      # Review queue backlog
      - alert: ClaimAgentReviewQueueBacklog
        expr: review_queue_size > 50
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Review queue backlog"
          description: "More than 50 claims awaiting human review for 30+ minutes."
```

## Alertmanager Integration

Route claim-agent alerts to your team. Example `alertmanager.yml`:

```yaml
route:
  receiver: default
  group_by: ['alertname', 'job']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        job: claim-agent
      receiver: claims-team
      continue: true

receivers:
  - name: default
    # ... your default receiver config

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

Adjust the alert thresholds to match your SLOs:

| Alert | Default | Tune for |
|-------|--------|----------|
| High error rate | 5% | Expected failure rate; increase for noisier environments |
| P99 latency | 120s | Typical claim processing time; lower for faster workflows |
| Escalation spike | 10/hour | Normal escalation volume; raise for high-throughput deployments |
| Review queue | 50 | Adjuster capacity; lower if team is small |
