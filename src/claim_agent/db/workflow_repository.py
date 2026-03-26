"""Workflow repository: persistence for workflow runs and task stage checkpoints."""

from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, row_to_dict


class WorkflowRepository:
    """Repository for workflow run results and stage checkpoint persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def save_workflow_result(
        self,
        claim_id: str,
        claim_type: str,
        router_output: str,
        workflow_output: str,
    ) -> None:
        """Save workflow run result to workflow_runs."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
                VALUES (:claim_id, :claim_type, :router_output, :workflow_output)
                """),
                {
                    "claim_id": claim_id,
                    "claim_type": claim_type,
                    "router_output": router_output,
                    "workflow_output": workflow_output,
                },
            )

    def get_workflow_runs(
        self,
        claim_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch workflow run records for a claim, most recent first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT claim_type, router_output, workflow_output, created_at
                FROM workflow_runs
                WHERE claim_id = :claim_id
                ORDER BY created_at DESC
                LIMIT :limit
                """),
                {"claim_id": claim_id, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def save_task_checkpoint(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_key: str,
        output: str,
    ) -> None:
        """Persist a stage checkpoint. Replaces any existing checkpoint for the same key."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO task_checkpoints (claim_id, workflow_run_id, stage_key, output)
                VALUES (:claim_id, :workflow_run_id, :stage_key, :output)
                ON CONFLICT (claim_id, workflow_run_id, stage_key)
                DO UPDATE SET output = EXCLUDED.output
                """),
                {
                    "claim_id": claim_id,
                    "workflow_run_id": workflow_run_id,
                    "stage_key": stage_key,
                    "output": output,
                },
            )

    def get_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
    ) -> dict[str, str]:
        """Load all checkpoints for a workflow run. Returns {stage_key: output_json}."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT stage_key, output FROM task_checkpoints
                WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                """),
                {"claim_id": claim_id, "workflow_run_id": workflow_run_id},
            ).fetchall()
        return {(d := row_to_dict(r))["stage_key"]: d["output"] for r in rows}

    def delete_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_keys: list[str] | None = None,
    ) -> None:
        """Delete checkpoints. If stage_keys given, only those; if None, all for the run.

        Empty list deletes nothing.
        """
        if stage_keys is not None and not stage_keys:
            return
        with get_connection(self._db_path) as conn:
            if stage_keys is not None:
                params: dict[str, Any] = {
                    "claim_id": claim_id,
                    "workflow_run_id": workflow_run_id,
                }
                for i, sk in enumerate(stage_keys):
                    params[f"sk{i}"] = sk
                placeholders = ", ".join(f":sk{i}" for i in range(len(stage_keys)))
                conn.execute(
                    text(f"""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                    AND stage_key IN ({placeholders})
                    """),
                    params,
                )
            else:
                conn.execute(
                    text("""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                    """),
                    {"claim_id": claim_id, "workflow_run_id": workflow_run_id},
                )

    def get_latest_checkpointed_run_id(self, claim_id: str) -> str | None:
        """Return the most recent workflow_run_id that has checkpoints for this claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT workflow_run_id FROM task_checkpoints
                WHERE claim_id = :claim_id
                ORDER BY id DESC
                LIMIT 1
                """),
                {"claim_id": claim_id},
            ).fetchone()
        return row_to_dict(row)["workflow_run_id"] if row else None
