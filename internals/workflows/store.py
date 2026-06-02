from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / ".runtime"


def default_db_path() -> Path:
    return default_runtime_dir() / "workflows.sqlite"


class WorkflowStore:
    """SQLite persistence for generic workflow runs and events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or default_db_path()).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                create table if not exists workflows (
                    id text primary key,
                    workflow text not null,
                    status text not null,
                    project_path text not null,
                    task text not null,
                    state_json text not null,
                    last_output_json text,
                    created_at text not null,
                    updated_at text not null
                )
            """)
            connection.execute("""
                create table if not exists workflow_events (
                    id integer primary key autoincrement,
                    workflow_id text not null,
                    event_type text not null,
                    payload_json text not null,
                    created_at text not null,
                    foreign key(workflow_id) references workflows(id)
                )
            """)
            connection.execute("""
                create index if not exists idx_workflow_events_workflow_id
                on workflow_events(workflow_id, id)
            """)

    def create_workflow(
        self,
        *,
        workflow_id: str,
        workflow: str,
        project_path: str,
        task: str,
        state: dict[str, Any],
        output: dict[str, Any] | None,
        status: str = "STARTED",
    ) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                insert into workflows
                    (id, workflow, status, project_path, task, state_json, last_output_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    workflow,
                    status,
                    project_path,
                    task,
                    json.dumps(state, sort_keys=True),
                    json.dumps(output, sort_keys=True) if output is not None else None,
                    now,
                    now,
                ),
            )

    def update_workflow(
        self,
        workflow_id: str,
        *,
        status: str,
        state: dict[str, Any],
        output: dict[str, Any] | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update workflows
                set status = ?, state_json = ?, last_output_json = ?, updated_at = ?
                where id = ?
                """,
                (
                    status,
                    json.dumps(state, sort_keys=True),
                    json.dumps(output, sort_keys=True) if output is not None else None,
                    utc_now(),
                    workflow_id,
                ),
            )
            if connection.total_changes == 0:
                raise KeyError(f"Unknown workflow id: {workflow_id}")

    def add_event(self, workflow_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into workflow_events (workflow_id, event_type, payload_json, created_at)
                values (?, ?, ?, ?)
                """,
                (workflow_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
            )

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "select * from workflows where id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown workflow id: {workflow_id}")
        return {
            "id": row["id"],
            "workflow": row["workflow"],
            "status": row["status"],
            "projectPath": row["project_path"],
            "task": row["task"],
            "state": json.loads(row["state_json"]),
            "lastOutput": json.loads(row["last_output_json"]) if row["last_output_json"] else None,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def list_events(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, workflow_id, event_type, payload_json, created_at
                from workflow_events
                where workflow_id = ?
                order by id
                """,
                (workflow_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "workflowId": row["workflow_id"],
                "eventType": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

