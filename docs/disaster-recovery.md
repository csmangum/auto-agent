# Disaster Recovery Plan

This document defines the disaster recovery (DR) strategy for the Agentic Claim Representative system. It covers recovery objectives, database recovery, service failover, data export/import procedures, and the communication plan for incident response.

> **Scope:** This plan applies to the production deployment of `claim-agent` running on Kubernetes (EKS/GKE/AKS) or AWS ECS with a PostgreSQL backend. SQLite is not covered because it is not suitable for production use — see [Database](database.md#production--pilot-readiness).

---

## 1. Recovery Objectives

| Tier | Scenario | RTO | RPO |
|------|----------|-----|-----|
| **T1 — Critical** | Database primary failure (single-AZ) | 5 min | 0 s (synchronous replica) |
| **T1 — Critical** | Full primary region outage | 30 min | 5 min (async replica lag) |
| **T2 — High** | API service crash / pod eviction | 2 min | 0 s (stateless service) |
| **T2 — High** | Bad deployment rollout | 5 min | 0 s (stateless service) |
| **T3 — Medium** | Corrupt or accidentally deleted data | 1 h | 1 h (point-in-time restore) |
| **T3 — Medium** | Secrets / config loss | 30 min | N/A (external secrets manager) |
| **T4 — Low** | Cold restart from scratch (no prior infrastructure) | 4 h | 24 h (daily backup) |

**RTO** (Recovery Time Objective): maximum acceptable downtime before service is restored.  
**RPO** (Recovery Point Objective): maximum acceptable data loss measured backwards in time from the failure.

---

## 2. Architecture Overview

```
                ┌────────────────────────────────────────┐
                │          Load Balancer / Ingress        │
                └──────────────────┬─────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
     ┌────────▼──────┐   ┌────────▼──────┐   ┌────────▼──────┐
     │  claim-agent  │   │  claim-agent  │   │  claim-agent  │
     │  (replica 1)  │   │  (replica 2)  │   │  (replica N)  │
     └───────────────┘   └───────────────┘   └───────────────┘
              │                    │                    │
              └────────────────────┼────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  PostgreSQL Primary (RDS /   │
                    │    Cloud SQL / Azure DB)     │
                    └──────────────┬──────────────┘
                                   │ streaming replication
                    ┌──────────────▼──────────────┐
                    │  PostgreSQL Read Replica     │
                    │  (READ_REPLICA_DATABASE_URL) │
                    └─────────────────────────────┘
                                   │ WAL archiving
                    ┌──────────────▼──────────────┐
                    │   S3 / GCS / Azure Blob      │
                    │   (WAL archives, backups,    │
                    │    attachment cold storage)  │
                    └─────────────────────────────┘
```

The API service is **stateless**. All persistent state lives in PostgreSQL. File attachments are stored in S3-compatible object storage. This means recovering the service itself is a simple rollout; recovering data requires PostgreSQL failover or restore procedures.

---

## 3. Database Recovery

### 3.1 Managed PostgreSQL (RDS / Cloud SQL / Azure DB) — recommended

These platforms provide automated failover and point-in-time recovery (PITR) out of the box.

#### Automated failover (Multi-AZ / HA)

| Platform | Feature | Typical failover time |
|----------|---------|----------------------|
| AWS RDS Multi-AZ | Synchronous standby; automatic DNS failover | 1–2 min |
| AWS Aurora | Writer + reader endpoints; auto-failover | < 30 s |
| Google Cloud SQL HA | Regional HA with automatic failover | 1–2 min |
| Azure Database for PostgreSQL Flexible Server | Zone-redundant HA | 60–120 s |

**Steps when automated failover occurs:**
1. The managed platform promotes the standby automatically.
2. The DNS endpoint (`DATABASE_URL` host) is updated by the platform — no `DATABASE_URL` change required.
3. `claim-agent` pods reconnect automatically due to SQLAlchemy's connection pool health checks. If connections are not re-established within 30 s, restart the pods:
   ```bash
   kubectl -n claim-agent rollout restart deployment/claim-agent
   ```
4. Verify connectivity via the health endpoint:
   ```bash
   curl https://<your-domain>/health
   ```
5. Check Prometheus for `ClaimAgentDBConnectionFailure` and `ClaimAgentDown` alerts clearing.

#### Point-in-time restore (PITR)

Use PITR when data corruption or accidental deletion is detected.

**AWS RDS PITR:**
```bash
# Restore to a new instance
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier claims-primary \
  --target-db-instance-identifier claims-restored \
  --restore-time 2025-01-31T12:00:00Z

# After restore, update DATABASE_URL to point to the new instance
# and re-import any transactions from the WAL that occurred after
# the restore point using the export procedure in §5.
```

**Google Cloud SQL PITR:**
```bash
gcloud sql instances clone claims-primary claims-restored \
  --point-in-time 2025-01-31T12:00:00.000Z
```

**Minimum recommended backup settings:**

| Setting | Recommended value |
|---------|------------------|
| Automated backup retention | 7 days (increase to 35 for compliance) |
| PITR window | Continuous (WAL archiving enabled) |
| Read replica lag alert threshold | > 60 s |
| Cross-region backup copy | Enabled for production |

### 3.2 Self-managed PostgreSQL

If running PostgreSQL without a managed service, use `pg_basebackup` for base backups and WAL archiving for PITR.

#### Scheduled base backup
```bash
# Run daily — adjust PGHOST, PGUSER, PGPASSWORD as needed
pg_basebackup \
  -h "$PGHOST" -U "$PGUSER" -D /backup/base-$(date +%Y%m%d) \
  -Ft -z -P --wal-method=stream
```

#### WAL archiving (`postgresql.conf`)
```
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://your-bucket/wal/%f'
```

#### Restore from base backup + WAL
```bash
# 1. Stop the old instance
systemctl stop postgresql

# 2. Clear the data directory
rm -rf /var/lib/postgresql/data/*

# 3. Extract base backup
tar -xzf /backup/base-20250131/base.tar.gz -C /var/lib/postgresql/data

# 4. Create recovery signal
touch /var/lib/postgresql/data/recovery.signal

# 5. Set recovery target in postgresql.conf
echo "recovery_target_time = '2025-01-31 12:00:00'" >> /var/lib/postgresql/data/postgresql.conf
echo "restore_command = 'aws s3 cp s3://your-bucket/wal/%f %p'" >> /var/lib/postgresql/data/postgresql.conf

# 6. Start and verify
systemctl start postgresql
psql -c "SELECT pg_is_in_recovery();"  # Should return 'f' after recovery completes
```

### 3.3 Alembic migration state

After any database restore, ensure the Alembic revision stamp matches the codebase:

```bash
# Check current revision
DATABASE_URL="postgresql://..." uv run alembic current

# If behind head, apply remaining migrations
DATABASE_URL="postgresql://..." uv run alembic upgrade head
```

---

## 4. Service Failover

The `claim-agent` API is stateless and horizontally scalable. Failover is handled at the load balancer / Kubernetes layer.

### 4.1 Pod crash / eviction

Kubernetes automatically restarts crashed pods via the Deployment controller. The PodDisruptionBudget (`k8s/pdb.yaml`) ensures at least one replica stays available during voluntary disruptions.

**Verify pod health:**
```bash
kubectl -n claim-agent get pods
kubectl -n claim-agent describe pod <pod-name>
kubectl -n claim-agent logs <pod-name> --previous  # logs from crashed container
```

**Manual restart if pods are stuck:**
```bash
kubectl -n claim-agent rollout restart deployment/claim-agent
kubectl -n claim-agent rollout status deployment/claim-agent
```

### 4.2 Bad deployment rollout

If a new deployment introduces a regression, roll back immediately:

```bash
# Kubernetes — rollback to previous revision
kubectl -n claim-agent rollout undo deployment/claim-agent

# Helm — rollback to previous release revision
helm -n claim-agent rollback claim-agent

# Verify
kubectl -n claim-agent rollout status deployment/claim-agent
curl https://<your-domain>/health
```

The `minReadySeconds` and readiness probe in `k8s/deployment.yaml` prevent new pods from receiving traffic until they pass the `/health` check, limiting blast radius.

### 4.3 Multi-region / active-passive failover

For full regional outages, deploy a passive standby region with:

1. A PostgreSQL cross-region read replica (promoted to primary during failover).
2. A dormant `claim-agent` Deployment (scaled to 0) in the standby region, or a pre-warmed replica with traffic shifted via DNS/GeoDNS.
3. S3 bucket replication enabled for attachment storage.

**Failover steps:**
1. **Promote the read replica** in the standby region to become the new primary:
   ```bash
   # AWS RDS — promote read replica
   aws rds promote-read-replica --db-instance-identifier claims-replica-us-west-2
   ```
2. **Update `DATABASE_URL`** in the standby region's Secret to point to the newly promoted instance.
3. **Scale up the standby Deployment:**
   ```bash
   kubectl -n claim-agent scale deployment/claim-agent --replicas=3
   ```
4. **Shift traffic** via DNS (lower TTL to 60 s in advance; update A/CNAME records or GeoDNS weights).
5. Confirm the health endpoint returns 200 in the standby region.
6. Notify the team and stakeholders (see §6 Communication Plan).

### 4.4 Secrets / configuration loss

All secrets must be stored in an external secrets manager (AWS Secrets Manager, HashiCorp Vault, or GCP Secret Manager) as described in [Deployment](deployment.md#23-review-and-apply-the-remaining-manifests). Recovery:

```bash
# Verify secrets are accessible from Kubernetes
kubectl -n claim-agent get secret claim-agent-secret -o yaml

# If the Secret was accidentally deleted, recreate it from the secrets manager
# (exact command depends on your ESO / Vault integration)
kubectl -n claim-agent delete secret claim-agent-secret  # ensure clean state
kubectl apply -f k8s/secret.yaml  # if using the static manifest with real values
```

---

## 5. Data Export / Import Procedures

### 5.1 Full database export (logical dump)

Use `pg_dump` for a portable logical backup:

```bash
# Export — creates a compressed dump
pg_dump \
  -h "$PGHOST" -U "$PGUSER" -d claims \
  -Fc -Z9 \
  -f claims-$(date +%Y%m%d-%H%M%S).dump

# Upload to S3
aws s3 cp claims-*.dump s3://your-bucket/backups/
```

### 5.2 Full database import (restore from logical dump)

```bash
# Create a fresh target database
psql -h "$PGHOST" -U "$PGUSER" -c "CREATE DATABASE claims_restored;"

# Restore
pg_restore \
  -h "$PGHOST" -U "$PGUSER" -d claims_restored \
  -Fc --no-owner --no-privileges \
  claims-20250131-120000.dump

# Apply any pending Alembic migrations
DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:5432/claims_restored" \
  uv run alembic upgrade head
```

### 5.3 Cold-storage / retention export

The CLI supports exporting claims to S3 for long-term cold storage (Glacier):

```bash
# Export claims older than the retention horizon to cold storage
claim-agent retention-export [--dry-run] [--years N] [--include-litigation-hold]

# Export audit log rows for purged claims
claim-agent audit-log-export -o audit-$(date +%Y%m%d).ndjson [--dry-run] [--years N]
```

These exports produce NDJSON files that can be re-imported by piping them through the REST API or a custom migration script.

### 5.4 Per-claim JSON export

Individual claims can be exported via the REST API for portability or investigation:

```bash
# Export a single claim (requires valid API key)
curl -H "X-API-Key: $API_KEY" \
  https://<your-domain>/api/v1/claims/<claim_id> \
  | jq . > claim-<claim_id>.json
```

### 5.5 Attachment recovery

Attachments are stored in S3-compatible object storage. Enable **versioning** and **cross-region replication** on the bucket:

```bash
# Enable versioning
aws s3api put-bucket-versioning \
  --bucket your-attachments-bucket \
  --versioning-configuration Status=Enabled

# Restore a deleted or overwritten object
aws s3api restore-object \
  --bucket your-attachments-bucket \
  --key attachments/<claim_id>/<filename> \
  --restore-request Days=7
```

---

## 6. Communication Plan

### 6.1 Severity definitions

| Severity | Description | Example |
|----------|-------------|---------|
| **SEV-1** | Complete service outage or data loss affecting all users | Database unreachable; all API requests failing |
| **SEV-2** | Significant degradation affecting a subset of users or claim types | Single-region partial outage; elevated error rate > 20% |
| **SEV-3** | Minor degradation or single-component failure with workaround available | Single pod crash; read replica lag |
| **SEV-4** | No user impact; monitoring or infrastructure concern | Alert rule mis-fire; deployment pipeline failure |

### 6.2 Escalation path

```
On-call engineer (PagerDuty / Opsgenie)
       │
       ▼ (≥ SEV-2 or RTO at risk)
Engineering lead / Team lead
       │
       ▼ (≥ SEV-1 or RTO breached)
Head of Engineering / CTO
       │
       ▼ (data loss, regulatory impact, or extended outage > 2 h)
Legal / Compliance + Executive leadership
```

### 6.3 Notification timeline

| Time (T+…) | Action |
|------------|--------|
| T+0 | Automated alert fires (PagerDuty/Opsgenie via Alertmanager) |
| T+5 min | On-call engineer acknowledges and begins diagnosis |
| T+15 min | Incident channel opened in Slack (`#incident-<date>`) |
| T+15 min | Initial status page update posted (e.g., Statuspage.io) |
| T+30 min | Engineering lead notified if SEV-1/SEV-2 not yet contained |
| T+60 min | Customer-facing status update if user impact is ongoing |
| T+2 h | Executive notification for unresolved SEV-1 |
| Resolution | All-clear notification on status page and Slack |
| T+24 h | Post-incident review (PIR) scheduled |
| T+72 h | PIR document published to team |

### 6.4 Incident response checklist

- [ ] **Detect:** Prometheus alert fires; acknowledge in PagerDuty/Opsgenie.
- [ ] **Assess:** Run `curl https://<your-domain>/health` and check Grafana dashboard.
- [ ] **Communicate:** Open `#incident-<date>` Slack channel; post initial update to status page.
- [ ] **Contain:** Rollback deployment, fail over database, or scale up replicas as needed (see §4).
- [ ] **Recover:** Restore data if needed (see §3); verify health endpoint returns 200.
- [ ] **Verify:** Confirm key workflows (new claim submission, review queue) are functional.
- [ ] **All-clear:** Post resolution to status page and Slack; notify affected stakeholders.
- [ ] **Review:** Schedule and conduct post-incident review within 24 h of resolution.

### 6.5 External contacts

Populate the following table before going to production:

| Contact | Role | Channel |
|---------|------|---------|
| On-call rotation | First responder | PagerDuty / Opsgenie |
| Engineering lead | Escalation — technical | Slack DM / phone |
| Database administrator | Escalation — DB/data | Slack DM / phone |
| Cloud platform team | Escalation — infra | Slack DM / ticket |
| AWS / GCP / Azure support | Infrastructure vendor | Support portal (Business/Enterprise plan) |
| Legal / Compliance | Regulatory notification | Email / phone |
| PR / Communications | External comms | Slack DM / phone |
| Status page admin | Customer-facing updates | Statuspage.io / Atlassian |

---

## 7. DR Testing

A DR plan is only as good as its last successful test. Schedule the following exercises:

| Exercise | Frequency | Owner | Pass criterion |
|----------|-----------|-------|----------------|
| Failover drill — database Multi-AZ | Quarterly | DBA / Infra | RTO ≤ 5 min, zero data loss |
| Restore from PITR backup | Monthly | DBA | Successful restore; Alembic at head |
| Pod chaos / kill a pod | Monthly | Infra | Auto-restart within 2 min |
| Full rollback drill | Each major release | Engineering | Rollback completes within 5 min |
| Cross-region failover simulation | Semi-annually | Infra | RTO ≤ 30 min, RPO ≤ 5 min |
| Communication runbook walkthrough | Annually | All responders | All contacts reachable; runbook accurate |

Record test results in the incident log and update this document if gaps are found.

---

## 8. Related Documents

- [Database](database.md) — Schema, migrations, and PostgreSQL setup
- [Deployment](deployment.md) — Kubernetes, Helm, and ECS deployment guides
- [Alerting](alerting.md) — Prometheus alert rules and Alertmanager configuration
- [Observability](observability.md) — Health endpoints, structured logging, and metrics
- [Configuration](configuration.md) — Environment variables and secrets management
- [PII and Retention](pii-and-retention.md) — Data retention enforcement and export
