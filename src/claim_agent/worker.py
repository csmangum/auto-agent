"""RQ worker for async claim processing.

Run with:
  python -m claim_agent.worker

Requires REDIS_URL to be set. Processes jobs from the 'claims' queue.
Uses retry on transient LLM failures (see queue.tasks.process_claim_task).
"""

import os
import sys
from pathlib import Path

# Ensure src is on path when run as script
if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    """Start RQ worker for claims queue."""
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        print("Error: REDIS_URL environment variable is required", file=sys.stderr)
        sys.exit(1)

    from redis import Redis
    from rq import Queue, Worker

    conn = Redis.from_url(url)
    queue = Queue("claims", connection=conn)
    worker = Worker([queue], connection=conn)
    worker.work()


if __name__ == "__main__":
    main()
