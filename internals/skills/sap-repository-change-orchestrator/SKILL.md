---
name: sap-repository-change-orchestrator
description: Start and follow the sap_repository_change workflow for SAP repository object change requests.
---

# SAP Repository Change Orchestrator

## Rule

Use this skill for any request that may create, modify, delete, upload, activate, repair, or commit SAP repository objects.

Do not perform SAP repository work directly from this skill. Start the `sap_repository_change` workflow and follow only the instructions returned by that workflow.

## Required Calls

1. Call `workflow_start` with:
   - `workflow: "sap_repository_change"`
   - `projectPath`
   - `task`
   - optional `input`
2. If the workflow response includes `expectedInputSchema`, gather exactly that JSON input and call `workflow_continue`.
3. If the workflow response tells you to call another tool, call only that tool with the exact arguments requested, then continue the workflow with the requested result JSON.
4. If the workflow response includes `stopRequired: true`, stop immediately and report the workflow output to the user.

## Boundaries

- Do not infer extra workflow steps.
- Do not call SAP CRUD, activation, transport, Git, or file-editing tools unless a workflow response explicitly instructs that exact action.
- Do not continue after `stopRequired: true`.
- If a workflow response is unclear or cannot be followed, report that workflow blocker instead of improvising.
- Keep this skill portable: do not rely on development-time paths.
