#!/usr/bin/env python3
"""Maintain a local Git repository for SAP object source edits."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


README_TEXT = "Local ABAP Repository\n"
BASE_BRANCH = "sap-base"
WORK_BRANCH = "main"

KIND_PATHS = {
    "program": ("programs", ".abap", False),
    "include": ("includes", ".abap", False),
    "class": ("classes", ".abap", False),
    "interface": ("interfaces", ".abap", False),
    "function-group": ("function-groups", ".abap", False),
    "function-module": ("function-modules", ".abap", True),
    "function-include": ("function-includes", ".abap", True),
    "ddl": ("ddls", ".asddl", False),
    "domain": ("domains", ".xml", False),
    "dataelement": ("dataelements", ".xml", False),
    "table": ("tables", ".abap", False),
}

STATE_FILE = "sap-local-git-guard-state.json"


class GuardError(Exception):
    pass


def run_git(repo: Path, args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GuardError(f"git {' '.join(args)} failed: {detail}")
    return completed


def output(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(code)


def state_path(repo: Path) -> Path:
    git_dir = run_git(repo, ["rev-parse", "--git-dir"]).stdout.strip()
    return (repo / git_dir / STATE_FILE).resolve()


def load_state(repo: Path) -> dict:
    path = state_path(repo)
    if not path.exists():
        return {"objects": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GuardError(f"Guard state file is invalid JSON: {path}: {exc}") from exc


def save_state(repo: Path, state: dict) -> None:
    path = state_path(repo)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def remember_object_state(repo: Path, relpath: Path, operation: str, exists_base: bool, needs_baseline: bool) -> None:
    state = load_state(repo)
    objects = state.setdefault("objects", {})
    objects[relpath_for_git(relpath)] = {
        "operation": operation,
        "existsInSapBase": exists_base,
        "needsBaselineDownload": needs_baseline,
    }
    save_state(repo, state)


def object_state(repo: Path, relpath: Path) -> dict:
    return load_state(repo).get("objects", {}).get(relpath_for_git(relpath), {})


def update_object_state(repo: Path, relpath: Path, **updates: object) -> None:
    state = load_state(repo)
    objects = state.setdefault("objects", {})
    current = objects.setdefault(relpath_for_git(relpath), {})
    current.update(updates)
    save_state(repo, state)


def normalize_name(value: str, label: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise GuardError(f"{label} is required.")
    return normalized


def object_relpath(kind: str, name: str, parent: str | None) -> Path:
    if kind not in KIND_PATHS:
        raise GuardError(f"Unsupported kind '{kind}'. Supported kinds: {', '.join(sorted(KIND_PATHS))}.")
    folder, suffix, needs_parent = KIND_PATHS[kind]
    normalized_name = normalize_name(name, "name")
    if needs_parent:
        normalized_parent = normalize_name(parent or "", "parent")
        return Path(folder) / normalized_parent / f"{normalized_name}{suffix}"
    return Path(folder) / f"{normalized_name}{suffix}"


def relpath_for_git(path: Path) -> str:
    return path.as_posix()


def branch_exists(repo: Path, branch: str) -> bool:
    return run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0


def has_commit(repo: Path, ref: str = "HEAD") -> bool:
    return run_git(repo, ["rev-parse", "--verify", "--quiet", ref], check=False).returncode == 0


def rev_parse(repo: Path, ref: str) -> str:
    return run_git(repo, ["rev-parse", "--verify", ref]).stdout.strip()


def current_branch(repo: Path) -> str:
    return run_git(repo, ["branch", "--show-current"]).stdout.strip()


def is_clean(repo: Path) -> bool:
    return run_git(repo, ["status", "--porcelain"]).stdout == ""


def configure_identity(repo: Path) -> None:
    if run_git(repo, ["config", "--get", "user.name"], check=False).returncode != 0:
        run_git(repo, ["config", "user.name", "SAP Local Git Guard"])
    if run_git(repo, ["config", "--get", "user.email"], check=False).returncode != 0:
        run_git(repo, ["config", "user.email", "sap-local-git-guard@example.local"])


def ensure_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        run_git(repo, ["init"])
    configure_identity(repo)

    if not has_commit(repo):
        readme = repo / "readme.md"
        readme.write_text(README_TEXT, encoding="utf-8")
        run_git(repo, ["add", "readme.md"])
        run_git(repo, ["commit", "-m", "SAP base state"])
        run_git(repo, ["branch", "-M", BASE_BRANCH])

    if not branch_exists(repo, BASE_BRANCH):
        if not is_clean(repo):
            raise GuardError(f"Cannot create {BASE_BRANCH} because the repository has uncommitted changes.")
        run_git(repo, ["branch", BASE_BRANCH])

    if not branch_exists(repo, WORK_BRANCH):
        run_git(repo, ["branch", WORK_BRANCH, BASE_BRANCH])

    branch = current_branch(repo)
    if branch != WORK_BRANCH:
        if not is_clean(repo):
            raise GuardError(f"Working tree is dirty on branch '{branch}'. Commit or clean it before switching to {WORK_BRANCH}.")
        run_git(repo, ["checkout", WORK_BRANCH])


def exists_in_ref(repo: Path, ref: str, relpath: Path) -> bool:
    return run_git(repo, ["cat-file", "-e", f"{ref}:{relpath_for_git(relpath)}"], check=False).returncode == 0


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def commit_file_to_base(repo: Path, relpath: Path, file_path: Path) -> dict:
    if not file_path.exists():
        raise GuardError(f"Baseline file does not exist: {file_path}")

    old_base = rev_parse(repo, BASE_BRANCH)
    old_main = rev_parse(repo, WORK_BRANCH)
    rel = relpath_for_git(relpath)

    with tempfile.TemporaryDirectory(prefix="sap-base-index-") as tmp:
        index_path = str(Path(tmp) / "index")
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = index_path
        run_git(repo, ["read-tree", BASE_BRANCH], env=env)
        blob = run_git(repo, ["hash-object", "-w", "--", str(file_path)]).stdout.strip()
        run_git(repo, ["update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"], env=env)
        new_tree = run_git(repo, ["write-tree"], env=env).stdout.strip()

    old_tree = rev_parse(repo, f"{BASE_BRANCH}^{{tree}}")
    if new_tree == old_tree:
        return {"baseUpdated": False, "oldSapBase": old_base, "newSapBase": old_base, "mainAdjusted": False}

    new_commit = run_git(
        repo,
        ["commit-tree", new_tree, "-p", BASE_BRANCH, "-m", "SAP base state"],
    ).stdout.strip()
    run_git(repo, ["update-ref", f"refs/heads/{BASE_BRANCH}", new_commit, old_base])

    main_adjusted = False
    rebase_required = False
    if old_main == old_base:
        run_git(repo, ["update-ref", f"refs/heads/{WORK_BRANCH}", new_commit, old_main])
        if current_branch(repo) == WORK_BRANCH:
            run_git(repo, ["reset", "--", rel])
        main_adjusted = True
    elif is_clean(repo):
        run_git(repo, ["rebase", "--onto", BASE_BRANCH, old_base, WORK_BRANCH])
        main_adjusted = True
    else:
        rebase_required = True

    return {
        "baseUpdated": True,
        "oldSapBase": old_base,
        "newSapBase": new_commit,
        "mainAdjusted": main_adjusted,
        "manualRebaseRequired": rebase_required,
    }


def build_context(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    repo = Path(args.repo).resolve()
    relpath = object_relpath(args.kind, args.name, getattr(args, "parent", None))
    return repo, relpath, repo / relpath


def prepare_object(args: argparse.Namespace) -> None:
    repo, relpath, file_path = build_context(args)
    ensure_repo(repo)

    exists_base = exists_in_ref(repo, BASE_BRANCH, relpath)
    needs_baseline = args.operation in {"update", "delete-existing"} and not exists_base
    remember_object_state(repo, relpath, args.operation, exists_base, needs_baseline)
    ensure_parent(file_path)

    output({
        "result": True,
        "action": "prepare-object",
        "repo": str(repo),
        "branch": current_branch(repo),
        "sapBaseBranch": BASE_BRANCH,
        "workBranch": WORK_BRANCH,
        "kind": args.kind,
        "name": normalize_name(args.name, "name"),
        "parent": normalize_name(args.parent, "parent") if getattr(args, "parent", None) else "",
        "operation": args.operation,
        "relativePath": relpath_for_git(relpath),
        "filePath": str(file_path),
        "existsInSapBase": exists_base,
        "needsBaselineDownload": needs_baseline,
    })


def record_base(args: argparse.Namespace) -> None:
    repo, relpath, file_path = build_context(args)
    ensure_repo(repo)
    state = object_state(repo, relpath)
    operation = state.get("operation", "")
    if operation == "create":
        raise GuardError("Cannot record a SAP baseline for an object prepared as create. New objects must not exist in sap-base.")
    if operation == "discard-created":
        raise GuardError("Cannot record a SAP baseline for an object prepared as discard-created.")
    if operation not in {"update", "delete-existing"}:
        raise GuardError("record-base requires a prior prepare-object with operation update or delete-existing.")
    if not state.get("needsBaselineDownload", False):
        raise GuardError("record-base is only allowed when prepare-object reported needsBaselineDownload=true.")
    baseline_path = Path(args.file_path).resolve() if args.file_path else file_path
    result = commit_file_to_base(repo, relpath, baseline_path)
    update_object_state(repo, relpath, existsInSapBase=True, needsBaselineDownload=False)
    output({
        "result": True,
        "action": "record-base",
        "repo": str(repo),
        "relativePath": relpath_for_git(relpath),
        "filePath": str(baseline_path),
        **result,
    })


def stage_object(args: argparse.Namespace) -> None:
    repo, relpath, file_path = build_context(args)
    ensure_repo(repo)
    if not file_path.exists():
        raise GuardError(f"Cannot stage missing file: {file_path}")
    run_git(repo, ["add", "--", relpath_for_git(relpath)])
    output({
        "result": True,
        "action": "stage-object",
        "repo": str(repo),
        "relativePath": relpath_for_git(relpath),
        "filePath": str(file_path),
    })


def stage_delete_existing(args: argparse.Namespace) -> None:
    repo, relpath, file_path = build_context(args)
    ensure_repo(repo)
    if not exists_in_ref(repo, BASE_BRANCH, relpath):
        output({
            "result": False,
            "action": "stage-delete-existing",
            "repo": str(repo),
            "relativePath": relpath_for_git(relpath),
            "filePath": str(file_path),
            "needsBaselineDownload": True,
            "message": "Object is not present in sap-base. Download and record the SAP baseline before deleting an existing object.",
        }, code=2)
    if file_path.exists():
        file_path.unlink()
    run_git(repo, ["rm", "--ignore-unmatch", "--", relpath_for_git(relpath)])
    output({
        "result": True,
        "action": "stage-delete-existing",
        "repo": str(repo),
        "relativePath": relpath_for_git(relpath),
        "filePath": str(file_path),
    })


def stage_discard_created(args: argparse.Namespace) -> None:
    repo, relpath, file_path = build_context(args)
    ensure_repo(repo)
    if exists_in_ref(repo, BASE_BRANCH, relpath):
        raise GuardError("Object exists in sap-base. Use stage-delete-existing for objects that existed in SAP before this work.")
    if file_path.exists():
        if file_path.is_dir():
            shutil.rmtree(file_path)
        else:
            file_path.unlink()
    run_git(repo, ["rm", "--cached", "--ignore-unmatch", "--", relpath_for_git(relpath)])
    output({
        "result": True,
        "action": "stage-discard-created",
        "repo": str(repo),
        "relativePath": relpath_for_git(relpath),
        "filePath": str(file_path),
    })


def blocking_status_lines(status: str) -> list[str]:
    blocked = []
    for line in status.splitlines():
        if not line:
            continue
        index_state = line[0]
        worktree_state = line[1]
        if line.startswith("??"):
            blocked.append(line)
        elif index_state == " " or worktree_state != " ":
            blocked.append(line)
    return blocked


def finalize(args: argparse.Namespace) -> None:
    repo = Path(args.repo).resolve()
    ensure_repo(repo)
    status = run_git(repo, ["status", "--porcelain"]).stdout
    if not status:
        output({
            "result": True,
            "action": "finalize",
            "repo": str(repo),
            "branch": current_branch(repo),
            "committed": False,
            "message": "No changes to commit.",
        })
    blocked = blocking_status_lines(status)
    if blocked:
        output({
            "result": False,
            "action": "finalize",
            "repo": str(repo),
            "committed": False,
            "message": "Cannot finalize while there are untracked or unstaged changes. Stage intended files with the helper and remove temporary files first.",
            "blockingStatus": blocked,
            "status": status.splitlines(),
        }, code=2)
    run_git(repo, ["commit", "-m", args.message])
    if current_branch(repo) != WORK_BRANCH:
        if not is_clean(repo):
            raise GuardError(f"Cannot switch back to {WORK_BRANCH} after finalizing because the working tree is not clean.")
        run_git(repo, ["checkout", WORK_BRANCH])
    output({
        "result": True,
        "action": "finalize",
        "repo": str(repo),
        "branch": current_branch(repo),
        "committed": True,
        "commit": rev_parse(repo, "HEAD"),
        "message": args.message,
    })


def add_object_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default="src", help="Local SAP source repository path.")
    parser.add_argument("--kind", required=True, choices=sorted(KIND_PATHS))
    parser.add_argument("--name", required=True)
    parser.add_argument("--parent", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain sap-base/main Git state for SAP object CRUD work.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-object")
    add_object_args(prepare)
    prepare.add_argument("--operation", required=True, choices=["create", "update", "delete-existing", "discard-created"])
    prepare.set_defaults(func=prepare_object)

    record = subparsers.add_parser("record-base")
    add_object_args(record)
    record.add_argument("--file-path", default="", help="Optional explicit baseline file path. Defaults to the object path in repo.")
    record.set_defaults(func=record_base)

    stage = subparsers.add_parser("stage-object")
    add_object_args(stage)
    stage.set_defaults(func=stage_object)

    delete_existing = subparsers.add_parser("stage-delete-existing")
    add_object_args(delete_existing)
    delete_existing.set_defaults(func=stage_delete_existing)

    discard_created = subparsers.add_parser("stage-discard-created")
    add_object_args(discard_created)
    discard_created.set_defaults(func=stage_discard_created)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--repo", default="src", help="Local SAP source repository path.")
    finalize_parser.add_argument("--message", required=True)
    finalize_parser.set_defaults(func=finalize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except GuardError as exc:
        output({"result": False, "message": str(exc)}, code=1)
    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
