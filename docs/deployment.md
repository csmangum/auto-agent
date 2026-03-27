# Production Deployment Guide

This document covers how to deploy claim-agent to a production Kubernetes cluster using either raw manifests or the bundled Helm chart. It also includes notes on AWS ECS deployment.

## Kubernetes: pick one path (`k8s/` **or** Helm)

The **`k8s/`** directory and the **`helm/claim-agent/`** chart are **alternatives**. They are **not** meant to be applied together in the same namespace: you would get duplicate Deployments, Services, or conflicting resource names.

- Use **`kubectl apply -f k8s/`** when you want fixed resource names and manifests that always include NetworkPolicy and HPA (as checked into the repo).
- Use **`helm install|upgrade`** when you want templated values, checksum-based rollouts, and optional components toggled via `values.yaml`.

Default **Helm** values now match the raw manifests for **autoscaling** and **network policy** (both enabled). For **Pod Security** labels on the namespace, either apply [`k8s/namespace.yaml`](k8s/namespace.yaml) before Helm, or pre-create the namespace with equivalent `pod-security.kubernetes.io/*` labels—`helm install --create-namespace` alone does not add those labels.

## Prerequisites

- A container image built from the repository `Dockerfile` and pushed to a registry accessible from your cluster.
- A PostgreSQL instance (RDS, Cloud SQL, Azure Database, etc.). SQLite is **not** suitable for production.
- (Optional) An S3-compatible bucket for attachment storage and cold-storage exports.

---

## 1. Container image

Build and push the image:

```bash
# Build
docker build -t ghcr.io/<your-org>/auto-agent:<tag> .

# Push
docker push ghcr.io/<your-org>/auto-agent:<tag>
```

The image runs as non-root (UID 1000), exposes port 8000, and includes a built-in health endpoint at `GET /health`.

---

## 2. Kubernetes — raw manifests (`k8s/`)

The `k8s/` directory contains ready-to-apply Kubernetes manifests suitable for any conformant cluster (EKS, GKE, AKS, OpenShift, etc.).

### 2.1 Apply the namespace first

```bash
kubectl apply -f k8s/namespace.yaml
```

### 2.2 Configure secrets

`k8s/secret.yaml` contains **placeholder** values. Replace each `CHANGE_ME` with real values, then apply:

```bash
# Edit the file (do NOT commit real credentials to Git)
vim k8s/secret.yaml

kubectl apply -f k8s/secret.yaml
```

`CORS_ORIGINS` is **not** a secret: it lives in `k8s/configmap.yaml` as `CORS_ORIGINS`.

For production, prefer one of the following instead of storing secrets in Git:

| Approach | Tool |
|----------|------|
| AWS Secrets Manager → k8s Secret | [External Secrets Operator](https://external-secrets.io/) |
| HashiCorp Vault → k8s Secret | [Vault Secrets Operator](https://developer.hashicorp.com/vault/docs/platform/k8s/vso) |
| Encrypted secrets in Git | [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) or [SOPS](https://github.com/getsops/sops) |

### 2.3 Review and apply the remaining manifests

Edit `k8s/configmap.yaml` to adjust non-sensitive settings (log level, OTEL endpoint, etc.), then apply everything:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/pdb.yaml
kubectl apply -f k8s/networkpolicy.yaml
```

Or apply the whole directory at once:

```bash
kubectl apply -f k8s/
```

### 2.4 Verify the rollout

```bash
kubectl -n claim-agent rollout status deployment/claim-agent
kubectl -n claim-agent get pods
kubectl -n claim-agent logs -l app.kubernetes.io/name=claim-agent --tail=50
```

### 2.5 TLS with cert-manager

Install cert-manager and create a `ClusterIssuer` before applying the Ingress:

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Create a Let's Encrypt ClusterIssuer (edit email)
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@your-domain.example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
EOF
```

Then update `k8s/ingress.yaml` with your real hostname and apply it.

---

## 3. Kubernetes — Helm chart (`helm/claim-agent/`)

The Helm chart wraps all of the above manifests and makes them configurable through `values.yaml`.

### 3.1 Install with default values (dev/staging)

The chart **refuses to render** if `secrets.*` still contain placeholder `CHANGE_ME` values (unless you set `existingSecret`). Override every secret below with real values.

`CORS_ORIGINS` is non-secret and is set via `config.corsOrigins` (ConfigMap).

```bash
helm install claim-agent ./helm/claim-agent \
  --namespace claim-agent \
  --create-namespace \
  --set secrets.databaseUrl="postgresql://user:pass@host:5432/claims" \
  --set secrets.openaiApiKey="sk-..." \
  --set secrets.apiKeys="mykey:admin" \
  --set secrets.jwtSecret="$(openssl rand -hex 32)" \
  --set secrets.webhookSecret="$(openssl rand -hex 32)" \
  --set config.corsOrigins="https://your-frontend.example.com"
```

### 3.2 Production values file

Create `values.production.yaml` (do **not** commit secrets in plaintext):

```yaml
replicaCount: 3

image:
  repository: ghcr.io/<your-org>/auto-agent
  tag: "1.2.3"

config:
  logFormat: "json"
  otelTracing: "true"
  otelExporterOtlpEndpoint: "http://otel-collector.observability:4318"

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: claims.your-domain.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: claim-agent-tls
      hosts:
        - claims.your-domain.example.com

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20

networkPolicy:
  enabled: true

# Use an ExternalSecret / SealedSecret for real credentials — leave secrets block
# empty and set existingSecret to the name of a pre-created k8s Secret.
existingSecret: "claim-agent-secret"
```

```bash
helm upgrade --install claim-agent ./helm/claim-agent \
  --namespace claim-agent \
  --create-namespace \
  -f values.production.yaml
```

### 3.3 Helm chart reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `replicaCount` | `2` | Number of pod replicas (overridden by HPA when enabled) |
| `image.repository` | `ghcr.io/csmangum/auto-agent` | Container image repository |
| `image.tag` | chart `appVersion` | Image tag (pin explicitly in production) |
| `image.pullPolicy` | `IfNotPresent` | Kubernetes image pull policy |
| `config.corsOrigins` | placeholder URL | Allowed frontend origins (ConfigMap) |
| `config.logFormat` | `json` | Log format (`json` or `human`) |
| `config.runMigrationsOnStartup` | `true` | Run Alembic migrations at startup |
| `config.otelTracing` | `false` | Enable OTEL tracing |
| `secrets.databaseUrl` | — | PostgreSQL connection string |
| `secrets.openaiApiKey` | — | OpenAI / OpenRouter API key |
| `secrets.apiKeys` | — | Comma-separated `key:role` pairs |
| `secrets.jwtSecret` | — | JWT signing secret |
| `ingress.enabled` | `false` | Create an Ingress resource |
| `autoscaling.enabled` | `true` | Enable HorizontalPodAutoscaler (matches raw `k8s/hpa.yaml`; set `false` for minimal dev) |
| `podDisruptionBudget.enabled` | `true` | Enable PodDisruptionBudget |
| `networkPolicy.enabled` | `true` | Enable NetworkPolicy (matches raw `k8s/networkpolicy.yaml`; set `false` if CNI unsupported) |
| `networkPolicy.egress.*` | `0.0.0.0/0` CIDRs | Egress `to:` scoping (tighten for production) |
| `existingSecret` | `""` | Use a pre-existing Secret instead of creating one |

---

## 4. AWS ECS (Fargate)

If you prefer a managed container platform without Kubernetes, AWS ECS on Fargate is a straightforward option.

### 4.1 Architecture overview

```
Internet → ALB (HTTPS/443) → ECS Service (Fargate) → RDS PostgreSQL
                                      ↓
                               CloudWatch Logs
                               AWS Secrets Manager
```

### 4.2 Key ECS task definition settings

```json
{
  "family": "claim-agent",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/claim-agent-task-role",
  "containerDefinitions": [
    {
      "name": "claim-agent",
      "image": "ghcr.io/<your-org>/auto-agent:<tag>",
      "portMappings": [{ "containerPort": 8000, "protocol": "tcp" }],
      "essential": true,
      "user": "1000",
      "readonlyRootFilesystem": true,
      "environment": [
        { "name": "CLAIM_AGENT_LOG_FORMAT", "value": "json" },
        { "name": "CLAIM_AGENT_ENVIRONMENT", "value": "production" },
        { "name": "RUN_MIGRATIONS_ON_STARTUP", "value": "true" },
        { "name": "TRUST_FORWARDED_FOR", "value": "true" },
        { "name": "SECRET_PROVIDER", "value": "aws_secrets_manager" },
        { "name": "AWS_SECRET_NAME", "value": "claim-agent/production" },
        { "name": "AWS_REGION", "value": "us-east-1" }
      ],
      "secrets": [],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/claim-agent",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"
        ],
        "interval": 10,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      }
    }
  ]
}
```

### 4.3 AWS Secrets Manager setup

Store all secrets in a single JSON-valued secret named `claim-agent/production`:

```bash
aws secretsmanager create-secret \
  --name claim-agent/production \
  --secret-string '{
    "DATABASE_URL": "postgresql://user:pass@rds-host:5432/claims",
    "OPENAI_API_KEY": "sk-...",
    "API_KEYS": "mykey:admin",
    "JWT_SECRET": "...",
    "WEBHOOK_SECRET": "...",
    "CORS_ORIGINS": "https://your-domain.example.com"
  }'
```

Grant the ECS task role `secretsmanager:GetSecretValue` on that secret ARN.

### 4.4 ECS service configuration highlights

| Setting | Recommended value |
|---------|------------------|
| Launch type | Fargate |
| Min healthy percent | 100 |
| Max percent | 200 |
| Desired count | ≥ 2 |
| ALB health check path | `/health` |
| ALB idle timeout | 120 s |
| Auto-scaling target | 70% CPU |

---

## 5. Database migrations

Alembic migrations run automatically at startup when `RUN_MIGRATIONS_ON_STARTUP=true` (the default). To run migrations as a separate step before deploying a new version:

```bash
# Kubernetes — run as a Job or an init container
kubectl run migrations \
  --image=ghcr.io/<your-org>/auto-agent:<tag> \
  --restart=Never \
  --env="DATABASE_URL=postgresql://..." \
  -- uv run alembic upgrade head

# ECS / local
DATABASE_URL="postgresql://..." uv run alembic upgrade head
```

---

## 6. Deployment strategies — Blue/Green and Canary

### 6.0 Choosing raw Kubernetes vs Helm vs GitHub Actions

Use this matrix to avoid mixing incompatible tooling (especially for blue/green).

| Tooling | Blue/green topology | Canary | Rolling | Notes |
|---------|----------------------|--------|---------|-------|
| **Raw manifests** (`k8s/`, `k8s/blue-green/`) | Two Deployments: `claim-agent-blue` and `claim-agent-green`, plus `claim-agent-active` Service | `deployment-canary.yaml` shares the stable Service | `k8s/deployment.yaml` | Matches `.github/workflows/deploy.yml`, `scripts/blue_green_switch.sh`, and `scripts/canary_deploy.sh` resource names. |
| **Helm — single-Deployment mode** (`deploymentStrategy.blueGreen.dualDeployment: false`, default) | **One** Deployment whose `deployment-slot` pod label is toggled via `helm upgrade`; Service selector follows the slot automatically | Template `deployment-canary.yaml` when `deploymentStrategy.type=Canary` | Default single Deployment | Simple; no downtime during slot flip. Incompatible with `blue_green_switch.sh` and the Deploy workflow (different resource names). |
| **Helm — dual-Deployment mode** (`deploymentStrategy.blueGreen.dualDeployment: true`) | Two Deployments (`<release>-blue` / `<release>-green`) + `<release>-active` Service — same topology as raw manifests | Same as above | Default single Deployment | When release name is `claim-agent`, resource names match raw manifests exactly; compatible with `blue_green_switch.sh` and `.github/workflows/deploy.yml`. |
| **GitHub Actions** (`.github/workflows/deploy.yml`) | `kubectl set image deployment/claim-agent-blue` / `…-green` | `claim-agent` + `claim-agent-canary` | `deployment/claim-agent` | Designed for clusters created from **raw** `k8s/` YAML or Helm with `dualDeployment: true` and release name `claim-agent`. |

The default deployment strategy is `RollingUpdate` (zero-downtime, in-place). For production workloads that require a safe rollback mechanism or incremental traffic shifting, two additional strategies are provided:

| Strategy | Files | When to use |
|----------|-------|-------------|
| **Blue/Green** | `k8s/blue-green/`, `scripts/blue_green_switch.sh` | Instant, atomic traffic switch; easy full rollback |
| **Canary** | `k8s/blue-green/deployment-canary.yaml`, `scripts/canary_deploy.sh` | Incremental traffic shifting to detect regressions |
| **Rolling** | `k8s/deployment.yaml` (default) | Simple zero-downtime in-place update |

Rolling, canary, and **two Helm blue/green modes** (single- or dual-Deployment) are available via `deploymentStrategy.type` in the Helm chart — see the matrix above before combining Helm with the shell scripts or CI workflow.

---

### 6.1 Blue/Green (raw manifests)

Blue/Green maintains two identical deployments — **blue** and **green** — and switches traffic atomically by changing the Service selector. Only one slot serves live traffic at a time; the inactive slot can be kept warm for instant rollback.

#### Initial setup

```bash
# Apply all blue/green resources (both deployment slots + active Service)
kubectl apply -f k8s/blue-green/

# Verify both slots start up (only the active slot receives traffic)
kubectl rollout status deployment/claim-agent-blue  -n claim-agent
kubectl rollout status deployment/claim-agent-green -n claim-agent
```

The `claim-agent-active` Service initially routes to the **blue** slot (see `k8s/blue-green/service.yaml`).

#### Deploying a new version

```bash
# 1. Update the INACTIVE slot (assume green is inactive)
kubectl set image deployment/claim-agent-green \
  claim-agent=ghcr.io/<your-org>/auto-agent:<new-tag> \
  -n claim-agent

# 2. Wait for it to be ready
kubectl rollout status deployment/claim-agent-green -n claim-agent --timeout=300s

# 3. Switch traffic to green
bash scripts/blue_green_switch.sh green

# 4. (Optional) Scale down inactive blue slot to save resources
bash scripts/blue_green_switch.sh green --scale-down-inactive
```

#### Rolling back

```bash
# Switch traffic back to the previous slot instantly
bash scripts/blue_green_switch.sh blue
```

#### Blue/Green with Helm — dual-Deployment mode (matches raw manifests)

Set `deploymentStrategy.blueGreen.dualDeployment: true` to render two named Deployments
(`<release>-blue` / `<release>-green`) and a `<release>-active` Service, matching the raw
`k8s/blue-green/` topology exactly. When the Helm release name is `claim-agent` the resource
names are identical to the raw manifests, so `scripts/blue_green_switch.sh` and
`.github/workflows/deploy.yml` work without any changes.

```bash
# Initial install — both blue and green Deployments are created; blue receives traffic
helm upgrade --install claim-agent ./helm/claim-agent \
  --set deploymentStrategy.type=BlueGreen \
  --set deploymentStrategy.blueGreen.dualDeployment=true \
  --set deploymentStrategy.blueGreen.initialSlot=blue \
  --set image.tag=1.0.0

# Verify both slots are running
kubectl rollout status deployment/claim-agent-blue  -n <namespace>
kubectl rollout status deployment/claim-agent-green -n <namespace>

# Deploy a new image to the inactive (green) slot without touching live traffic
kubectl set image deployment/claim-agent-green \
  claim-agent=ghcr.io/<your-org>/auto-agent:1.1.0 \
  -n <namespace>
kubectl rollout status deployment/claim-agent-green -n <namespace> --timeout=300s

# Switch traffic to green (no Helm upgrade needed for the traffic cut-over)
bash scripts/blue_green_switch.sh green -n <namespace>

# Roll back instantly if needed
bash scripts/blue_green_switch.sh blue -n <namespace>
```

> **Note:** HPA is disabled in dual-Deployment mode. Scale each slot independently
> via `deploymentStrategy.blueGreen.replicasPerSlot` (default `2`).

#### Blue/Green with Helm — single-Deployment mode

The original single-Deployment approach toggles the `deployment-slot` pod label via
`helm upgrade`. This is simpler but **incompatible** with `blue_green_switch.sh` and the
Deploy workflow because the Deployment name never includes `-blue` or `-green`.

```bash
# Initial install — deploy the blue slot
helm upgrade --install claim-agent ./helm/claim-agent \
  --set deploymentStrategy.type=BlueGreen \
  --set deploymentStrategy.blueGreenSlot=blue \
  --set image.tag=1.0.0

# Deploy new version — helm upgrade atomically flips the slot and switches traffic
helm upgrade claim-agent ./helm/claim-agent \
  --set deploymentStrategy.type=BlueGreen \
  --set deploymentStrategy.blueGreenSlot=green \
  --set image.tag=1.1.0

# Rollback: re-run helm upgrade with blueGreenSlot=blue
```

---

### 6.2 Canary (raw manifests)

A canary deployment runs the new version on a small number of replicas alongside the stable version. The existing Service selects pods from both, distributing traffic proportionally to replica counts. For example: 1 canary + 9 stable ≈ 10 % canary traffic.

#### Apply the canary deployment

```bash
# Ensure the stable deployment and Service are running
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Apply the canary manifest
kubectl apply -f k8s/blue-green/deployment-canary.yaml
```

#### Managing the canary rollout

The `scripts/canary_deploy.sh` helper manages the full lifecycle:

```bash
# Start: 10 % canary traffic (1 canary / 9 stable)
bash scripts/canary_deploy.sh start \
  --image ghcr.io/<your-org>/auto-agent:1.1.0 \
  --canary-replicas 1 \
  --stable-replicas 9

# Monitor error rates and latency, then increase to 50 %
bash scripts/canary_deploy.sh promote \
  --canary-replicas 5 \
  --stable-replicas 5

# Fully promote: update stable to the new image, scale canary to 0
bash scripts/canary_deploy.sh finish --final-replicas 2

# Roll back: scale canary to 0, restore stable
bash scripts/canary_deploy.sh rollback --stable-replicas 9
```

#### Canary with Helm

```bash
# Deploy stable version
helm upgrade --install claim-agent ./helm/claim-agent \
  --set image.tag=1.0.0

# Add a 10 % canary for a new image
helm upgrade claim-agent ./helm/claim-agent \
  --set deploymentStrategy.type=Canary \
  --set deploymentStrategy.canary.replicas=1 \
  --set deploymentStrategy.canary.imageTag=1.1.0 \
  --set replicaCount=9

# Promote: update stable image, remove canary
helm upgrade claim-agent ./helm/claim-agent \
  --set deploymentStrategy.type=RollingUpdate \
  --set image.tag=1.1.0 \
  --set replicaCount=2
```

---

### 6.3 Automated deployment via GitHub Actions

The `.github/workflows/deploy.yml` workflow automates deployments after CI passes on `main`. It can be triggered manually with a choice of strategy:

```
Actions → Deploy → Run workflow
  environment: production | staging
  strategy: blue-green | canary | rolling
  canary_weight: 10        # % traffic for canary (canary strategy only)
  image_tag: (optional)    # leave blank to use the commit SHA
```

**Prerequisites for the workflow:**
- Add a `KUBECONFIG` repository secret containing the base64-encoded kubeconfig for your cluster:
  ```bash
  cat ~/.kube/config | base64 | pbcopy
  # paste as GitHub secret: Settings → Secrets → KUBECONFIG
  ```
- Configure a GitHub [environment](https://docs.github.com/en/actions/deployment/targeting-different-environments) named `production` (and optionally `staging`) with any required approval gates.

---

## 7. Environment variable reference

See `.env.example` for the full list of supported environment variables. The most important ones for production are:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `OPENAI_API_KEY` | Yes | LLM API key |
| `API_KEYS` or `JWT_SECRET` | Yes | At least one auth mechanism |
| `CORS_ORIGINS` | Yes | Allowed frontend origins |
| `WEBHOOK_SECRET` | Yes if webhooks enabled | HMAC signing secret |
| `CLAIM_AGENT_LOG_FORMAT` | Recommended | Set to `json` in production |
| `CLAIM_AGENT_ENVIRONMENT` | Recommended | Set to `production` |
| `SECRET_PROVIDER` | Recommended | `aws_secrets_manager` or `hashicorp_vault` |
| `OTEL_TRACING` | Optional | Enable distributed tracing |
| `READ_REPLICA_DATABASE_URL` | Optional | PostgreSQL read replica for HA |

---

## 8. Security checklist

- [ ] **Monitoring stack:** In `docker-compose.prod.yml`, Loki, Prometheus, Alertmanager, and Grafana bind to **127.0.0.1** only. Do not expose `3100`/`9090` on `0.0.0.0` without TLS and auth. Default `monitoring/loki-config.yml` has `auth_enabled: false` — acceptable on a trusted Docker network; for shared hosts, enable Loki auth or keep the port localhost-only.
- [ ] Replace all `CHANGE_ME` placeholder values in `k8s/secret.yaml` before applying.
- [ ] Use an external secrets manager (AWS Secrets Manager, Vault, Sealed Secrets) in production — do not commit plaintext credentials to Git.
- [ ] Confirm NetworkPolicy matches your cluster (Helm defaults to `networkPolicy.enabled: true`; disable only if your CNI does not support it).
- [ ] Set `readOnlyRootFilesystem: true` — the manifests already include ephemeral `emptyDir` volumes for `/tmp` and `/app/data`.
- [ ] Pin image tags — avoid `latest` in production; use explicit version tags.
- [ ] Configure IRSA (EKS) or Workload Identity (GKE) on the ServiceAccount instead of long-lived AWS credentials.
- [ ] When TLS terminates at the ingress/ALB, pods see plain HTTP from the proxy: set `ENFORCE_HTTPS=false` (no in-app redirect loop) and `TRUST_FORWARDED_FOR=true` so the app trusts `X-Forwarded-Proto` for HTTPS/HSTS behavior.
- [ ] Review CORS origins (`CORS_ORIGINS`) — restrict to your actual frontend domain(s).
- [ ] Enable audit logging (`AUDIT_LOG_PURGE_ENABLED`, `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE`) per your data-retention policy.
