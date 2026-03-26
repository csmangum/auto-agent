# Production Deployment Guide

This document covers how to deploy claim-agent to a production Kubernetes cluster using either raw manifests or the bundled Helm chart. It also includes notes on AWS ECS deployment.

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

```bash
helm install claim-agent ./helm/claim-agent \
  --namespace claim-agent \
  --create-namespace \
  --set secrets.databaseUrl="postgresql://user:pass@host:5432/claims" \
  --set secrets.openaiApiKey="sk-..." \
  --set secrets.apiKeys="mykey:admin" \
  --set secrets.jwtSecret="$(openssl rand -hex 32)" \
  --set secrets.webhookSecret="$(openssl rand -hex 32)"
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
| `image.tag` | chart `appVersion` | Image tag |
| `config.logFormat` | `json` | Log format (`json` or `human`) |
| `config.runMigrationsOnStartup` | `true` | Run Alembic migrations at startup |
| `config.otelTracing` | `false` | Enable OTEL tracing |
| `secrets.databaseUrl` | — | PostgreSQL connection string |
| `secrets.openaiApiKey` | — | OpenAI / OpenRouter API key |
| `secrets.apiKeys` | — | Comma-separated `key:role` pairs |
| `secrets.jwtSecret` | — | JWT signing secret |
| `ingress.enabled` | `false` | Create an Ingress resource |
| `autoscaling.enabled` | `false` | Enable HorizontalPodAutoscaler |
| `podDisruptionBudget.enabled` | `true` | Enable PodDisruptionBudget |
| `networkPolicy.enabled` | `false` | Enable NetworkPolicy |
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

## 6. Environment variable reference

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

## 7. Security checklist

- [ ] Replace all `CHANGE_ME` placeholder values in `k8s/secret.yaml` before applying.
- [ ] Use an external secrets manager (AWS Secrets Manager, Vault, Sealed Secrets) in production — do not commit plaintext credentials to Git.
- [ ] Enable `networkPolicy.enabled: true` in Helm values to restrict pod-level network traffic.
- [ ] Set `readOnlyRootFilesystem: true` — the manifests already include ephemeral `emptyDir` volumes for `/tmp` and `/app/data`.
- [ ] Pin image tags — avoid `latest` in production; use explicit version tags.
- [ ] Configure IRSA (EKS) or Workload Identity (GKE) on the ServiceAccount instead of long-lived AWS credentials.
- [ ] Set `ENFORCE_HTTPS=false` and `TRUST_FORWARDED_FOR=true` when TLS is terminated at the ingress/ALB.
- [ ] Review CORS origins (`CORS_ORIGINS`) — restrict to your actual frontend domain(s).
- [ ] Enable audit logging (`AUDIT_LOG_PURGE_ENABLED`, `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE`) per your data-retention policy.
