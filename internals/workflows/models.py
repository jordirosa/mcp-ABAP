from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from generics import ApiResponse


class WorkflowOutput(BaseModel):
    """Common output returned by workflow tools."""

    workflowId: str = Field(..., description="Persistent workflow run id.")
    workflow: str = Field(..., description="Workflow name.")
    status: str = Field(..., description="Generic workflow status. V1 uses STARTED or FINISHED.")
    output: dict[str, Any] = Field(default_factory=dict, description="Workflow-specific open JSON output.")
    expectedInputSchema: dict[str, Any] | None = Field(
        None,
        description="JSON Schema for the next workflow_continue input when the workflow expects one.",
    )
    stopRequired: bool = Field(False, description="Whether the agent must stop after reporting the output.")


class WorkflowEventOutput(BaseModel):
    """One workflow event persisted for audit."""

    id: int = Field(..., description="Monotonic event id.")
    workflowId: str = Field(..., description="Workflow run id.")
    eventType: str = Field(..., description="Event type.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload JSON.")
    createdAt: str = Field(..., description="UTC timestamp.")


class WorkflowLogOutput(BaseModel):
    """Full workflow state plus persisted event log."""

    workflowId: str
    workflow: str
    status: str
    projectPath: str
    task: str
    state: dict[str, Any]
    lastOutput: dict[str, Any] | None
    createdAt: str
    updatedAt: str
    events: list[WorkflowEventOutput] = Field(default_factory=list)


class WorkflowResponse(ApiResponse[WorkflowOutput]):
    """Response for workflow start, continue, status and cancel operations."""


class WorkflowLogResponse(ApiResponse[WorkflowLogOutput]):
    """Response for workflow audit log operations."""

