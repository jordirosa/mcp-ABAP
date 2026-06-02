---
name: sap-transport-scope-guard
description: Guard SAP repository changes so they stay inside the approved package and transport scope. Use before any agent creates, modifies, deletes, uploads, locks, or discards SAP repository objects, especially when abap.config defines the allowed package, transport request, and object-level exceptions.
---

# SAP Transport Scope Guard

## Core Rule

Use this skill before any SAP repository object is created, modified, deleted, uploaded, or otherwise locked for change. Its job is to prevent accidental work outside the package and transport scope approved for the current project.

The scope is stored in `abap.config` at the project root. The file is JSON and is part of the local project state. Do not continue with SAP writes when this guard cannot prove the object is inside scope.

## `abap.config`

Use this shape:

```json
{
  "systemId": "A4H",
  "package": "ZPKG",
  "transport": "A4HK900110",
  "localPackage": false,
  "allowedObjects": [
    {
      "type": "PROG/P",
      "name": "YJRS_DEMO",
      "uri": "/sap/bc/adt/programs/programs/YJRS_DEMO",
      "package": "ZPKG",
      "transport": "A4HK900110"
    }
  ]
}
```

For local packages whose name starts with `$`, set `"localPackage": true` and `"transport": null`. `$TMP` and every package beginning with `$` are local-package mode.

Keep object names uppercase when SAP treats them as uppercase. Keep `uri` as an ADT path, not a full URL.

## Initialize Scope

If `abap.config` does not exist, stop and ask the user for the package and transport scope before touching SAP objects.

- Ask for the SAP system if it is not already clear from the task or current session.
- Ask for the package.
- If the package starts with `$`, create `abap.config` with `transport: null` and `localPackage: true`.
- If the package is transportable, ask whether to use an existing transport request or create a new one.
- For an existing request, store the transport number exactly as the approved request.
- For a new request, ask for the request text, then use `cts_transport_create` with the package, request text, and the first relevant object URI when available. Store the returned transport number.

Do not invent package names, transport numbers, or request texts.

## Existing Objects

Before changing or deleting an existing object:

1. Locate the object with repository search or a direct read tool to obtain its ADT URI, object type, name, and package.
2. Verify the package matches `abap.config.package`.
3. Call `cts_transport_check` with the object URI, package, and operation `U` for update or delete validation.
4. Call `internals_object_lock_probe` with the object URI.
5. Read the probe result, especially `corrnr`, `corruser`, `corrtext`, and `isLocal`.
6. Let the probe complete its unlock before continuing.

Allow the change only when:

- local-package mode is active and the probed object is local or has no transport; or
- transportable mode is active and `corrnr` equals `abap.config.transport`.

If the object is already listed in `allowedObjects`, it is still valid only while the package and transport continue to match the stored values.

Abort before local edits, SAP writes, deletes, or Git staging if the package or transport does not match.

## New Objects

For a new object, the object is allowed only when it will be created in `abap.config.package`.

- In local-package mode, pass no transport number.
- In transportable mode, pass `abap.config.transport` to the create/write tool using the relevant `transportNumber`, `corrNr`, or equivalent parameter.
- After creation succeeds, verify the object by repository search or read, and add it to `allowedObjects` with its type, name, URI, package, and transport.

If the object cannot be created in the configured package and transport, stop and report the mismatch.

## Explicit User Override

If an object is outside scope, stop and explain:

- requested object and operation;
- configured package and transport;
- actual package from repository metadata;
- actual transport from `internals_object_lock_probe`;
- why continuing would violate scope.

The user may explicitly approve adding that object to the scope. Only then update `abap.config`.

When adding an override:

- store the exact object type, name, URI, package, and transport observed at approval time;
- require the same package and transport on every later touch;
- do not broaden the package or transport silently;
- do not treat one approval as permission for other objects.

## Failure Handling

Stop and report instead of continuing when:

- `abap.config` is missing and the user has not provided scope;
- repository search cannot identify the target object unambiguously;
- `internals_object_lock_probe` cannot lock the object;
- the probe locks but cannot unlock the object;
- the package does not match the configured package;
- the transport does not match the configured transport;
- SAP reports the object is locked by another transport or user and the user has not explicitly approved scope expansion.

If an unlock fails, do not proceed with the change. Report the URI, lock handle, warning messages, and recommended human cleanup.

## Integration

Run this guard before `sap-local-git-repository-guard` and before SAP CRUD tools. Once this guard approves the object, continue with the repository and activation workflow.

When calling SAP CRUD tools after approval, pass the configured transport number for transportable packages. For local packages, leave transport parameters empty.
