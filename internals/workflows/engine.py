from __future__ import annotations

import uuid
from typing import Any

from internals.workflows import sap_repository_change
from internals.workflows.models import (
    WorkflowEventOutput,
    WorkflowLogOutput,
    WorkflowLogResponse,
    WorkflowOutput,
    WorkflowResponse,
)
from internals.workflows.store import WorkflowStore


SUPPORTED_WORKFLOWS = {"sap_repository_change"}


class WorkflowEngine:
    """Generic dispatcher for JSON-driven workflows."""

    def __init__(self, store: WorkflowStore | None = None) -> None:
        self.store = store or WorkflowStore()

    def start(
        self,
        *,
        workflow: str,
        project_path: str,
        task: str,
        input_data: dict[str, Any] | None = None,
    ) -> WorkflowResponse:
        try:
            workflow_name = _normalize_workflow(workflow)
            if workflow_name != "sap_repository_change":
                raise ValueError(f"Unsupported workflow: {workflow_name}")
            workflow_id = f"wf_{uuid.uuid4().hex}"
            input_payload = dict(input_data or {})
            status, state, output, expected_schema, stop_required = sap_repository_change.start(
                project_path,
                str(task or ""),
                input_payload,
            )
            self.store.create_workflow(
                workflow_id=workflow_id,
                workflow=workflow_name,
                project_path=state["projectPath"],
                task=str(task or ""),
                state=state,
                output=output,
                status=status,
            )
            self.store.add_event(workflow_id, "start_input", {
                "workflow": workflow_name,
                "projectPath": project_path,
                "task": task,
                "input": input_payload,
            })
            self.store.add_event(workflow_id, "workflow_output", {
                "status": status,
                "output": output,
                "expectedInputSchema": expected_schema,
                "stopRequired": stop_required,
            })
            return WorkflowResponse(
                result=True,
                message="Workflow started.",
                data=WorkflowOutput(
                    workflowId=workflow_id,
                    workflow=workflow_name,
                    status=status,
                    output=output,
                    expectedInputSchema=expected_schema,
                    stopRequired=stop_required,
                ),
            )
        except Exception as exc:
            return WorkflowResponse(result=False, message=str(exc), data=None)

    def continue_workflow(self, *, workflow_id: str, input_data: dict[str, Any]) -> WorkflowResponse:
        try:
            row = self.store.get_workflow(_normalize_workflow_id(workflow_id))
            if row["status"] == "FINISHED":
                return WorkflowResponse(
                    result=True,
                    message="Workflow is already finished.",
                    data=WorkflowOutput(
                        workflowId=row["id"],
                        workflow=row["workflow"],
                        status=row["status"],
                        output=row["lastOutput"] or {},
                        expectedInputSchema=None,
                        stopRequired=bool((row["lastOutput"] or {}).get("code") == "BOOTSTRAP_COMPLETE"),
                    ),
                )

            self.store.add_event(row["id"], "continue_input", {"input": dict(input_data or {})})
            if row["workflow"] != "sap_repository_change":
                raise ValueError(f"Unsupported workflow: {row['workflow']}")

            status, state, output, expected_schema, stop_required, validation_errors = sap_repository_change.continue_workflow(
                row["state"],
                dict(input_data or {}),
            )
            self.store.update_workflow(row["id"], status=status, state=state, output=output)
            if validation_errors:
                self.store.add_event(row["id"], "validation_error", {"errors": validation_errors})
            self.store.add_event(row["id"], "workflow_output", {
                "status": status,
                "output": output,
                "expectedInputSchema": expected_schema,
                "stopRequired": stop_required,
            })
            return WorkflowResponse(
                result=True,
                message="Workflow advanced." if not validation_errors else "Workflow input was rejected.",
                data=WorkflowOutput(
                    workflowId=row["id"],
                    workflow=row["workflow"],
                    status=status,
                    output=output,
                    expectedInputSchema=expected_schema,
                    stopRequired=stop_required,
                ),
            )
        except Exception as exc:
            return WorkflowResponse(result=False, message=str(exc), data=None)

    def status(self, workflow_id: str) -> WorkflowResponse:
        try:
            row = self.store.get_workflow(_normalize_workflow_id(workflow_id))
            return WorkflowResponse(
                result=True,
                message="Workflow status loaded.",
                data=WorkflowOutput(
                    workflowId=row["id"],
                    workflow=row["workflow"],
                    status=row["status"],
                    output=row["lastOutput"] or {},
                    expectedInputSchema=(row["state"] or {}).get("expectedInputSchema"),
                    stopRequired=bool((row["lastOutput"] or {}).get("code") == "BOOTSTRAP_COMPLETE"),
                ),
            )
        except Exception as exc:
            return WorkflowResponse(result=False, message=str(exc), data=None)

    def log(self, workflow_id: str) -> WorkflowLogResponse:
        try:
            row = self.store.get_workflow(_normalize_workflow_id(workflow_id))
            events = [
                WorkflowEventOutput.model_validate(event)
                for event in self.store.list_events(row["id"])
            ]
            return WorkflowLogResponse(
                result=True,
                message="Workflow log loaded.",
                data=WorkflowLogOutput(
                    workflowId=row["id"],
                    workflow=row["workflow"],
                    status=row["status"],
                    projectPath=row["projectPath"],
                    task=row["task"],
                    state=row["state"],
                    lastOutput=row["lastOutput"],
                    createdAt=row["createdAt"],
                    updatedAt=row["updatedAt"],
                    events=events,
                ),
            )
        except Exception as exc:
            return WorkflowLogResponse(result=False, message=str(exc), data=None)

    def cancel(self, workflow_id: str) -> WorkflowResponse:
        try:
            row = self.store.get_workflow(_normalize_workflow_id(workflow_id))
            state = dict(row["state"] or {})
            state["cancelled"] = True
            state["step"] = "cancelled"
            output = {
                "code": "WORKFLOW_CANCELLED",
                "instruction": "The workflow was cancelled. Stop using this workflow id.",
            }
            self.store.update_workflow(row["id"], status="FINISHED", state=state, output=output)
            self.store.add_event(row["id"], "workflow_cancelled", {"output": output})
            return WorkflowResponse(
                result=True,
                message="Workflow cancelled.",
                data=WorkflowOutput(
                    workflowId=row["id"],
                    workflow=row["workflow"],
                    status="FINISHED",
                    output=output,
                    expectedInputSchema=None,
                    stopRequired=True,
                ),
            )
        except Exception as exc:
            return WorkflowResponse(result=False, message=str(exc), data=None)


_DEFAULT_ENGINE: WorkflowEngine | None = None


def default_engine() -> WorkflowEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = WorkflowEngine()
    return _DEFAULT_ENGINE


def _normalize_workflow(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("workflow is required.")
    if normalized not in SUPPORTED_WORKFLOWS:
        raise ValueError(f"Unsupported workflow: {normalized}")
    return normalized


def _normalize_workflow_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("workflowId is required.")
    return normalized


def workflow_start(workflow: str, projectPath: str, task: str, input: dict[str, Any] | None = None) -> WorkflowResponse:
    return default_engine().start(
        workflow=workflow,
        project_path=projectPath,
        task=task,
        input_data=input,
    )


def workflow_continue(workflowId: str, input: dict[str, Any]) -> WorkflowResponse:
    return default_engine().continue_workflow(workflow_id=workflowId, input_data=input)


def workflow_status(workflowId: str) -> WorkflowResponse:
    return default_engine().status(workflowId)


def workflow_log(workflowId: str) -> WorkflowLogResponse:
    return default_engine().log(workflowId)


def workflow_cancel(workflowId: str) -> WorkflowResponse:
    return default_engine().cancel(workflowId)

