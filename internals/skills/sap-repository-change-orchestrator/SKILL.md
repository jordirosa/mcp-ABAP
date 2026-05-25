---
name: sap-repository-change-orchestrator
description: Coordinate SAP repository object changes end to end. Use when an agent must create, modify, delete, upload, activate, repair, or commit ABAP repository object work while preserving local Git baseline state through sap-local-git-repository-guard.
---

# SAP Repository Change Orchestrator

## Core Rule

Use this skill for any task that changes SAP repository objects. For every object the task creates, modifies, deletes, or discards, first use the `sap-transport-scope-guard` skill to confirm the object is inside the approved package and transport scope. After scope approval, use the `sap-local-git-repository-guard` skill to prepare the local `src/` repository, preserve SAP baseline state, and stage the local result.

Activation belongs at the end of the full change set, not after each individual object. A change can depend on other objects that are still being created or modified, so upload all intended object changes first, then activate the complete activable set.

## Workflow

1. Identify the SAP system, transport needs, target objects, and likely dependencies.
2. Classify each affected object as `create`, `update`, `delete-existing`, or `discard-created`.
3. For each object, run `sap-transport-scope-guard` before local edits, SAP writes, deletes, locks, or Git staging. Do not continue for that object when the guard reports a package or transport mismatch.
4. For each approved object, run the `sap-local-git-repository-guard` workflow:
   - `prepare-object`
   - SAP `*_read_to_file` plus `record-base` when the helper reports `needsBaselineDownload`
   - local edit/create/delete
   - `stage-object`, `stage-delete-existing`, or `stage-discard-created`
   - add or update ABAPDoc comments when creating or changing public ABAP APIs
5. Apply the SAP-side CRUD operation with the appropriate MCP tool:
   - create objects before uploading their source when the object does not exist yet;
   - use `*_write_from_file` for modified or newly created source;
   - for DDIC objects whose canonical local file is easiest to obtain from SAP, create or update the object with the structured SAP tool, then download the final object content with `*_read_to_file` into the helper's `filePath` before staging;
   - use the relevant delete tool for existing objects that must be removed.
6. For transportable packages, pass the transport approved by `sap-transport-scope-guard` to SAP create, update, write, and delete tools through their `transportNumber`, `corrNr`, or equivalent parameter. For local packages, leave transport parameters empty.
7. Track every object that should be activated by ADT URI and object name. Exclude discarded local objects and objects that were deleted.
8. After all intended SAP writes are complete, call `activation_activate` once for the collected activable objects.
9. Only after successful activation, or after reviewing non-blocking warnings, call `finalize` from `sap-local-git-repository-guard` to create the final `main` commit. If `finalize` reports untracked or unstaged files, stage intended SAP object files with the helper or remove temporary files, then retry.

## Activation Repair Loop

If activation fails, do not commit. Read the activation messages carefully and continue while there is a reasonable path forward.

- Map each error to the object, source location, dependency, syntax issue, missing artifact, transport issue, lock issue, or authorization problem it describes.
- Use local source, SAP reads, syntax checks, navigation, where-used, or repository search tools to gather context.
- Consult the ABAP documentation tool when the error relates to ABAP syntax, APIs, annotations, activation semantics, or SAP-specific behavior.
- Consult internet or external documentation when local/SAP context is insufficient and the issue plausibly depends on public SAP behavior or language rules.
- Fix the local file, stage it again with `sap-local-git-repository-guard`, upload it again with the relevant SAP tool, and retry activation for the needed set.
- Continue only while each iteration has a new, concrete hypothesis or changes the system state in a useful way.

Stop and report instead of committing when there is no reasonable progress path: repeated equivalent activation failure, missing external dependency, unclear functional decision, unavailable authorization, unresolved transport or lock problem, or an object state that cannot be reconciled safely.

## ABAPDoc

When creating or modifying classes and interfaces, document reusable public APIs with ABAPDoc comments.

- Add ABAPDoc (`"!`) before public class/interface declarations when the object has a reusable purpose.
- Add ABAPDoc before public methods, including a short purpose statement.
- Document relevant importing, exporting, changing, returning, and raising elements with ABAPDoc tags such as `@parameter` and `@raising` when they clarify usage.
- Keep comments accurate and concise. Do not add noisy comments for obvious private implementation details.
- Update existing ABAPDoc when behavior or parameters change.

## Failure Report

If the task cannot be completed because activation does not succeed, provide a concise report with:

- requested task and objects affected;
- SAP activation/check messages that matter;
- changes already made locally and uploaded to SAP;
- repair attempts and hypotheses discarded;
- current known state of `src/`, `sap-base`, `main`, and SAP objects;
- what human action or decision is needed next.

Do not run the Git `finalize` command when activation remains blocked.

## Notes

- Never manipulate `sap-base` or `main` manually; delegate local repository state to `sap-local-git-repository-guard`.
- Never bypass `sap-transport-scope-guard` for SAP repository changes. Scope approval must happen before local Git preparation and before SAP locks or writes.
- Prefer activating the complete dependency set over activating a single object early.
- If a newly created object is later discarded before completion, use `discard-created` so it does not enter `sap-base` or activation.
- Keep the skill portable: do not rely on development-time paths for installed skills.
