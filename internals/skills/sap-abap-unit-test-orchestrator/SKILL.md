---
name: sap-abap-unit-test-orchestrator
description: Orchestrate isolated ABAP Unit work after SAP repository development. Use when an agent must analyze task-scoped SAP source changes, propose ABAP Unit tests for user approval, implement approved testclasses through sap-repository-change-orchestrator, run ABAP Unit with coverage, and report coverage for the code changed in the current task.
---

# SAP ABAP Unit Test Orchestrator

## Core Rule

Use this skill after SAP repository development when ABAP Unit tests must be added or adapted for the current task. Determine scope from the local Git repository managed by `sap-local-git-repository-guard`, but delegate all SAP object writes, activation, repair, and final commit to `sap-repository-change-orchestrator`.

Do not write tests immediately. First analyze the current task, inspect existing tests, and present a test proposal for user approval. Only after approval, invoke `sap-repository-change-orchestrator` with a test-focused change request.

## Scope From Git

Use `git diff sap-base..main` in `src/` to identify the task scope.

- Treat productive ABAP source created or modified by the task as the coverage target.
- Treat ABAP testclasses, test includes, and other test code already present in the diff as test context, not as productive code that needs tests.
- Do not create unit tests for tests.
- Exclude untouched historical code, generated metadata, deleted objects, discarded-created objects, and non-testable artifacts from the coverage target.
- If a changed file cannot be mapped reliably to a SAP object or executable unit, report the limitation before proposing tests.

The goal is 100% coverage of task-scoped productive code that is testable with ABAP Unit, not 100% coverage of the whole package or legacy object.

## Proposal Before Editing

Before creating or changing any tests, inspect the affected productive code and existing ABAP Unit assets. Use source and testclass read tools as needed.

Present a concise proposal containing:

- productive objects affected by the task;
- existing testclasses or test includes to modify;
- new testclasses or test methods to create;
- behavior and edge cases each test will cover;
- dependencies to isolate with ABAP Test Double Framework or Open SQL Test Double Framework;
- task-scoped coverage target and any expected mapping limitations.

Wait for user approval before implementing the tests. If the user asks for changes to the proposal, revise it before writing anything.

## Implementation Delegation

After approval, use `sap-repository-change-orchestrator` to implement the approved test work. The request to that skill must be limited to ABAP Unit changes needed for the approved proposal.

The delegated change request must require:

- create or update only the approved testclasses, local test classes, or test includes;
- upload all test changes to SAP;
- activate only after all approved test changes are uploaded;
- repair activation errors using the orchestrator repair loop;
- finalize the Git commit only after successful activation.

This skill must not bypass the SAP change orchestrator for writes, activation, or commit.

## Unit Test Rules

All tests created or changed by this skill must be true unit tests.

- Use ABAP Test Double Framework for class, interface, function, and collaborator isolation when supported.
- Use Open SQL Test Double Framework for database-facing code.
- Do not use test seams.
- Do not read from or write to real database tables.
- Do not create integration tests.
- Do not modify productive code only to make it testable unless the user separately approves that production change.
- Do not expand the work to legacy behavior outside the task diff.

If the SAP system does not support the required test double capability, stop and report the blocker instead of producing contaminated tests.

## Coverage Workflow

After the delegated test changes activate successfully, run ABAP Unit with coverage for the relevant changed productive objects and the affected test scope.

Use the available ABAP Unit tools in this order when possible:

1. Run ABAP Unit with coverage enabled.
2. Read the coverage measurement URI from the run result.
3. Query coverage for the task-scoped productive objects.
4. Query statement coverage when paths are available.
5. Compare coverage results with the `sap-base..main` productive-code diff.

Coverage expectations:

- newly created productive code should be fully covered when it is testable;
- modified productive lines, branches, or methods should be fully covered when SAP coverage data can map them;
- unchanged legacy code is outside the target;
- unmappable lines must be reported as unmappable, not silently counted as covered.

If tests fail or task-scoped coverage is incomplete, inspect messages and coverage gaps, then iterate through `sap-repository-change-orchestrator` while there is a concrete path to improve the result. Stop when failures require a functional decision, missing dependency, unsupported framework capability, authorization, lock resolution, or production refactor not yet approved.

## Final Report

Produce a Markdown report. Open with an overview table:

- total ABAP Unit tests executed;
- total ABAP Unit tests passed;
- new or modified tests executed;
- new or modified tests passed;
- task-scoped coverage target;
- task-scoped coverage result;
- final status.

Then detail only tests created or modified by this work. For each test, explain in prose:

- the casuistic or behavior being tested;
- the productive code it covers;
- the doubles used and what they isolate;
- test data;
- expected result.

Use compact tables for test data and expected results when helpful. Do not paste full test source code in the report.

If the work cannot complete successfully, include:

- productive objects and test objects affected;
- SAP activation or ABAP Unit messages that matter;
- coverage gaps or unmappable regions;
- attempts made and hypotheses discarded;
- human action or decision needed next.
