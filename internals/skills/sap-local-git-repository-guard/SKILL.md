---
name: sap-local-git-repository-guard
description: Maintain a local Git-backed SAP repository snapshot before CRUD operations on SAP repository objects. Use when an agent will create, read, update, delete, discard, activate, or upload ABAP repository object files and must preserve an SAP baseline in sap-base while editing on main.
---

# SAP Local Git Repository Guard

## Core Rule

Before any CRUD operation on SAP repository object content, prepare the local repository with `scripts/sap_git_repo.py`. Keep the canonical repository in `src/`; this is where downloaded SAP object files and local edits live.

The `src/` repository uses type-specific subfolders so SAP objects with the same technical name but different object types do not collide. Keep the folder mapping deterministic and do not place object source files directly at the root of `src/`.

Keep the Git branches in `src/` as:

- `sap-base`: what SAP contained before the current work changed anything.
- `main`: the working branch for local edits, activation fixes, and final commit.

Do not manually improvise Git branch choreography or object paths. Use the helper for initialization, path calculation, baseline registration, staging, deletion tracking, and final commit.

## Workflow

Run commands from the workspace root. Resolve `scripts/sap_git_repo.py` relative to this skill's installed directory. The helper prints JSON; read it before taking the next step.

1. Prepare the object.

```bash
python /path/to/sap-local-git-repository-guard/scripts/sap_git_repo.py prepare-object --kind program --name YJRS_TEST --operation update
```

2. If the JSON says `needsBaselineDownload: true`, call the matching SAP `*_read_to_file` tool and download into the returned `filePath`.

3. Register the downloaded SAP baseline.

```bash
python /path/to/sap-local-git-repository-guard/scripts/sap_git_repo.py record-base --kind program --name YJRS_TEST
```

4. Edit, create, or remove the local file on `main`.

5. Stage the result with the matching helper command.

```bash
python /path/to/sap-local-git-repository-guard/scripts/sap_git_repo.py stage-object --kind program --name YJRS_TEST
```

6. Repeat for every object. Activate objects in SAP only after all intended local changes are ready.

7. After SAP activation and corrections are complete, create the final `main` commit. `finalize` must fail if any untracked or unstaged files remain and should leave the repository checked out on `main`.

```bash
python /path/to/sap-local-git-repository-guard/scripts/sap_git_repo.py finalize --message "Update SAP repository objects"
```

## Operations

- For create: run `prepare-object --operation create`, create the file on `main`, then `stage-object`. Do not add anything to `sap-base`.
- For update: run `prepare-object --operation update`; if needed, download and `record-base`; then edit and `stage-object`.
- For deleting an object that existed in SAP before the current work changed it: run `prepare-object --operation delete-existing`; if needed, download and `record-base`; then run `stage-delete-existing`.
- For discarding an object created during this work session: run `stage-discard-created`. This must not touch `sap-base`.

`record-base` is only valid after `prepare-object` reports `needsBaselineDownload: true` for an `update` or `delete-existing` operation. It must fail for objects prepared as `create` or `discard-created`, because new objects must never enter `sap-base`.

## Supported Kinds

The first version supports source-like and DDIC objects with deterministic paths under `src/`. These subfolders are mandatory to avoid name collisions between SAP object types:

- `program` -> `programs/<NAME>.abap`
- `include` -> `includes/<NAME>.abap`
- `class` -> `classes/<NAME>.abap`
- `interface` -> `interfaces/<NAME>.abap`
- `function-group` -> `function-groups/<NAME>.abap`
- `function-module` -> `function-modules/<PARENT>/<NAME>.abap`
- `function-include` -> `function-includes/<PARENT>/<NAME>.abap`
- `ddl` -> `ddls/<NAME>.asddl`
- `domain` -> `domains/<NAME>.xml`
- `dataelement` -> `dataelements/<NAME>.xml`
- `table` -> `tables/<NAME>.abap`

For function modules and function includes, pass `--parent <FUNCTION_GROUP>`.

## Safety Notes

- The helper avoids checking out `sap-base` from a dirty `main`.
- If a new baseline is added while `main` has uncommitted changes, the helper updates branch refs and the index for that object path without wiping local edits.
- A created-then-discarded object must use `stage-discard-created`; it never belongs in `sap-base`.
- A created object must be absent from `sap-base`; `git cat-file -e sap-base:<object-path>` should fail for objects created during the current work.
- `finalize` commits only fully staged changes, fails when there are untracked files or unstaged edits, and leaves the working tree on `main`. Remove temporary files or stage intended files with the helper before retrying.
- If the helper reports an error or `needsBaselineDownload`, do not continue the SAP write/delete until the reported condition is handled.
