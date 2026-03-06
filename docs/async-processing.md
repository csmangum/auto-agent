# Async Processing and Job Queue

This document describes the asynchronous claim processing flow, job queue integration, and worker deployment.

## Overview

For high-volume scenarios (batch ingestion, API responsiveness), claims can be submitted asynchronously:

- **POST /api/claims** (async): Returns 202 with `job_id` and `claim_id`; processing runs in background
- **GET /api/jobs/{job_id}**: Poll for job status (pending, running, completed, failed)
- **POST /api/claims/batch**: Submit multiple claims; returns list of job_ids

Sync mode is preserved for the CLI (`claim-agent process`) and for API requests with `?async=false`.

## Architecture

```
┌─────────────┐     POST /claims      ┌─────────────┐     enqueue      ┌─────────────┐
│   Client    │ ───────────────────► │   API       │ ──────────────► │   Redis     │
│             │  202 {job_id,claim_id}│   Server    │                  │   (RQ)      │
└─────────────┘                       └─────────────┘                  └──────┬──────┘
       │                                                                    │
       │ GET /jobs/{job_id}                                                 │
       │ ◄─────────────────────────────────────────────────────────────────┘
       │                                                                    │
       │                                                                    ▼
       │                                                           ┌─────────────┐
       │                                                           │   Worker    │
       │                                                           │   Process   │
       │                                                           └──────┬──────┘
       │                                                                  │
       │                                                                  │ run_claim_workflow
       │                                                                  ▼
       │                                                           ┌─────────────┐
       │                                                           │   SQLite    │
       │                                                           │   (claims)  │
       │                                                           └─────────────┘
```

## Configuration

### Redis

Set `REDIS_URL` in `.env`:

```bash
REDIS_URL=redis://localhost:6379/0
```

For Redis with password:

```bash
REDIS_URL=redis://:password@localhost:6379/0
```

For Redis Cloud or similar:

```bash
REDIS_URL=rediss://default:xxx@redis-xxx.cloud.redislabs.com:12345
```

### Optional: Sync Fallback

When `REDIS_URL` is not set:

- **POST /api/claims?async=true** → 503 (async requires Redis)
- **POST /api/claims?async=false** → 200 (processes synchronously)

## API Endpoints

### POST /api/claims

Submit a single claim.

| Query Param | Default | Description |
|-------------|---------|-------------|
| `async` | `true` | If true, enqueue and return 202; if false, process synchronously |

**Request body:** JSON matching `ClaimInput` (policy_number, vin, vehicle_year, etc.)

**Response (async, 202):**
```json
{
  "job_id": "abc-123-def",
  "claim_id": "CLM-11EEF959",
  "message": "Claim queued for processing. Poll GET /api/jobs/{job_id} for status."
}
```

**Response (sync, 200):** Full workflow result (claim_id, claim_type, summary, etc.)

### GET /api/jobs/{job_id}

Poll job status.

**Response:**
```json
{
  "job_id": "abc-123-def",
  "claim_id": "CLM-11EEF959",
  "status": "completed",
  "result": { "claim_id": "...", "claim_type": "partial_loss", "summary": "..." }
}
```

Status values: `pending`, `running`, `completed`, `failed`

### GET /api/claims/{claim_id}/job

Get job info for a claim (if submitted async).

### POST /api/claims/batch

Submit multiple claims. Always async. Returns 202 with list of job_ids and claim_ids.

**Request body:** Array of claim objects

**Response (202):**
```json
{
  "jobs": [
    { "index": 0, "job_id": "job-1", "claim_id": "CLM-AAA", "error": null },
    { "index": 1, "job_id": "job-2", "claim_id": "CLM-BBB", "error": null }
  ]
}
```

## Worker Deployment

### Start the Worker

```bash
# Option 1: Python module
python -m claim_agent.worker

# Option 2: Installed script
claim-agent-worker

# Option 3: RQ CLI (if REDIS_URL is set)
rq worker claims --url $REDIS_URL
```

### Run Multiple Workers

Scale by running multiple worker processes:

```bash
# Terminal 1
python -m claim_agent.worker

# Terminal 2
python -m claim_agent.worker
```

### Process Manager (Supervisor)

Example `/etc/supervisor/conf.d/claim-worker.conf`:

```ini
[program:claim-worker]
command=/path/to/.venv/bin/python -m claim_agent.worker
directory=/path/to/project
environment=REDIS_URL="redis://localhost:6379/0",CLAIMS_DB_PATH="data/claims.db"
autostart=true
autorestart=true
stdout_logfile=/var/log/claim-worker.log
stderr_logfile=/var/log/claim-worker.err
```

### Retry Behavior

The worker uses `with_llm_retry` for transient failures. On transient LLM errors (timeout, rate limit, 5xx):

- Retries up to 3 times with exponential backoff
- Failed jobs remain in Redis for 24 hours (failure_ttl)

Permanent failures (e.g., invalid claim data) are not retried.

## CLI (Sync Mode)

The CLI always processes synchronously:

```bash
claim-agent process tests/sample_claims/partial_loss_parking.json
```

No Redis or worker required for CLI usage.

## Database

The `claim_jobs` table tracks job_id → claim_id mapping:

| Column | Type | Description |
|--------|------|-------------|
| job_id | TEXT | RQ job ID (primary key) |
| claim_id | TEXT | Claim ID |
| status | TEXT | queued, running, completed, failed |
| result_summary | TEXT | Summary or error message |
| created_at | TEXT | |
| updated_at | TEXT | |

## Related

- [Configuration](configuration.md) – REDIS_URL, etc.
- [main_crew.py](../src/claim_agent/crews/main_crew.py) – run_claim_workflow
