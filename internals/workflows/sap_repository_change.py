from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from configuration import call_sap_systems_list


README_TEXT = "Local ABAP Repository\n"
BASE_BRANCH = "sap-base"
WORK_BRANCH = "main"


class WorkflowError(Exception):
    """Raised when a workflow cannot advance with the provided input."""


def scope_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["systemId", "package", "transportMode"],
        "properties": {
            "systemId": {
                "type": "string",
                "description": "Configured SAP system id, for example A4H.",
            },
            "package": {
                "type": "string",
                "description": "Target SAP package. Packages beginning with $ are local and do not require a transport.",
            },
            "transportMode": {
                "type": "string",
                "enum": ["existing", "new", "none"],
                "description": "Use existing for an existing request, new to create one, or none for local packages.",
            },
            "transport": {
                "type": ["string", "null"],
                "description": "Existing SAP transport request when transportMode is existing.",
            },
            "transportDescription": {
                "type": ["string", "null"],
                "description": "Description for a new SAP transport request when transportMode is new.",
            },
        },
        "additionalProperties": False,
    }


def transport_created_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["transportNumber"],
        "properties": {
            "transportNumber": {
                "type": "string",
                "description": "Transport request number returned by cts_transport_create.",
            },
        },
        "additionalProperties": False,
    }


def validate_json_schema(schema: dict[str, Any], value: dict[str, Any]) -> list[str]:
    """Validate the small JSON Schema subset used by workflow prompts."""
    errors: list[str] = []
    if schema.get("type") == "object" and not isinstance(value, dict):
        return ["input must be an object."]

    required = schema.get("required", []) or []
    for field in required:
        if field not in value:
            errors.append(f"{field} is required.")

    properties = schema.get("properties", {}) or {}
    if schema.get("additionalProperties") is False:
        for field in value:
            if field not in properties:
                errors.append(f"{field} is not an allowed property.")

    for field, field_schema in properties.items():
        if field not in value:
            continue
        allowed_types = field_schema.get("type")
        if isinstance(allowed_types, str):
            allowed_types = [allowed_types]
        if not allowed_types:
            continue
        actual = value[field]
        if not _matches_json_type(actual, allowed_types):
            errors.append(f"{field} must be {', '.join(allowed_types)}.")
        allowed_values = field_schema.get("enum")
        if allowed_values and actual not in allowed_values:
            errors.append(f"{field} must be one of: {', '.join(allowed_values)}.")
    return errors


def _matches_json_type(value: Any, allowed_types: list[str]) -> bool:
    type_checks = {
        "string": lambda item: isinstance(item, str),
        "null": lambda item: item is None,
        "object": lambda item: isinstance(item, dict),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
    }
    return any(type_checks.get(json_type, lambda _item: True)(value) for json_type in allowed_types)


def _resolve_project_path(project_path: str) -> Path:
    path = Path(str(project_path or "").strip()).expanduser()
    if not path.is_absolute():
        raise WorkflowError("projectPath must be an absolute path.")
    return path.resolve()


def _run_git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WorkflowError(f"git {' '.join(args)} failed: {detail}")
    return completed


def _has_commit(repo: Path, ref: str = "HEAD") -> bool:
    return _run_git(repo, ["rev-parse", "--verify", "--quiet", ref], check=False).returncode == 0


def _branch_exists(repo: Path, branch: str) -> bool:
    return _run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0


def _current_branch(repo: Path) -> str:
    return _run_git(repo, ["branch", "--show-current"]).stdout.strip()


def _is_clean(repo: Path) -> bool:
    return _run_git(repo, ["status", "--porcelain"]).stdout == ""


def _configure_identity(repo: Path) -> None:
    if _run_git(repo, ["config", "--get", "user.name"], check=False).returncode != 0:
        _run_git(repo, ["config", "user.name", "SAP Local Git Guard"])
    if _run_git(repo, ["config", "--get", "user.email"], check=False).returncode != 0:
        _run_git(repo, ["config", "user.email", "sap-local-git-guard@example.local"])


def prepare_src_repo(project_path: Path) -> dict[str, Any]:
    repo = project_path / "src"
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _run_git(repo, ["init"])
    _configure_identity(repo)

    if not _has_commit(repo):
        readme = repo / "readme.md"
        readme.write_text(README_TEXT, encoding="utf-8")
        _run_git(repo, ["add", "readme.md"])
        _run_git(repo, ["commit", "-m", "SAP base state"])
        _run_git(repo, ["branch", "-M", BASE_BRANCH])

    if not _branch_exists(repo, BASE_BRANCH):
        if not _is_clean(repo):
            raise WorkflowError(f"Cannot create {BASE_BRANCH} because src has uncommitted changes.")
        _run_git(repo, ["branch", BASE_BRANCH])

    if not _branch_exists(repo, WORK_BRANCH):
        _run_git(repo, ["branch", WORK_BRANCH, BASE_BRANCH])

    branch = _current_branch(repo)
    if branch != WORK_BRANCH:
        if not _is_clean(repo):
            raise WorkflowError(f"Cannot switch src from '{branch}' to {WORK_BRANCH} because the working tree is dirty.")
        _run_git(repo, ["checkout", WORK_BRANCH])

    return {
        "repoPath": str(repo),
        "branch": _current_branch(repo),
        "sapBaseBranch": BASE_BRANCH,
        "workBranch": WORK_BRANCH,
    }


def _config_path(project_path: Path) -> Path:
    return project_path / "abap.config"


def _config_exists(project_path: Path) -> bool:
    return _config_path(project_path).is_file()


def _load_config(project_path: Path) -> dict[str, Any] | None:
    path = _config_path(project_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"abap.config is not valid JSON: {exc}") from exc


def _system_options() -> list[dict[str, Any]]:
    response = call_sap_systems_list()
    if not response.result or response.data is None:
        return []
    return [
        system.model_dump()
        for system in response.data.systems
    ]


def _validate_scope_input(input_data: dict[str, Any]) -> list[str]:
    errors = validate_json_schema(scope_input_schema(), input_data)
    if errors:
        return errors

    package = str(input_data.get("package", "")).strip()
    transport = input_data.get("transport")
    transport_mode = str(input_data.get("transportMode", "")).strip()
    transport_description = input_data.get("transportDescription")
    system_id = str(input_data.get("systemId", "")).strip()
    if not system_id:
        errors.append("systemId cannot be empty.")
    if not package:
        errors.append("package cannot be empty.")
    if package.startswith("$"):
        if transport_mode != "none":
            errors.append("transportMode must be none for local packages.")
        if transport not in (None, ""):
            errors.append("transport must be null or empty for local packages.")
    elif transport_mode == "existing" and not str(transport or "").strip():
        errors.append("transport is required for transportable packages.")
    elif transport_mode == "new" and not str(transport_description or "").strip():
        errors.append("transportDescription is required when transportMode is new.")
    elif transport_mode == "none":
        errors.append("transportMode none is only valid for local packages.")
    return errors


def _write_config(project_path: Path, input_data: dict[str, Any], transport_number: str | None = None) -> dict[str, Any]:
    package = str(input_data["package"]).strip().upper()
    is_local = package.startswith("$")
    config = {
        "systemId": str(input_data["systemId"]).strip(),
        "package": package,
        "transport": None if is_local else str(transport_number or input_data["transport"]).strip().upper(),
        "localPackage": is_local,
        "allowedObjects": [],
        "createdObjects": [],
    }
    _config_path(project_path).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config


def _request_scope_output(repo_info: dict[str, Any], config_path: Path) -> dict[str, Any]:
    return {
        "code": "SCOPE_REQUIRED",
        "instruction": (
            "Ask the user to choose one configured SAP system, provide the target package, and choose the transport mode. "
            "For local packages whose name begins with $, use transportMode none. "
            "For transportable packages, ask whether to use an existing transport request or create a new one. "
            "When creating a new request, collect the request description. "
            "Then call workflow_continue with the collected JSON."
        ),
        "repo": repo_info,
        "configPath": str(config_path),
        "systemOptions": _system_options(),
        "transportOptions": [
            {
                "mode": "existing",
                "description": "Use an existing transport request supplied by the user.",
            },
            {
                "mode": "new",
                "description": "Create a new transport request using cts_transport_create after the workflow authorizes it.",
            },
            {
                "mode": "none",
                "description": "Use only for local packages whose name begins with $.",
            },
        ],
    }


def _package_object_uri(package: str) -> str:
    return f"/sap/bc/adt/packages/{str(package).strip().lower()}"


def _transport_creation_output(repo_info: dict[str, Any], config_path: Path, scope: dict[str, Any]) -> dict[str, Any]:
    package = str(scope["package"]).strip().upper()
    return {
        "code": "TRANSPORT_CREATION_REQUIRED",
        "instruction": (
            "Create the requested SAP transport with the exact tool and arguments below. "
            "After the tool returns successfully, call workflow_continue with the returned transportNumber."
        ),
        "repo": repo_info,
        "configPath": str(config_path),
        "toolRequest": {
            "tool": "cts_transport_create",
            "arguments": {
                "systemId": str(scope["systemId"]).strip(),
                "packageName": package,
                "requestText": str(scope["transportDescription"]).strip(),
                "objectUri": _package_object_uri(package),
                "operation": "I",
            },
        },
    }


def _finished_output(repo_info: dict[str, Any], config_path: Path, config: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "code": "BOOTSTRAP_COMPLETE",
        "instruction": (
            "Workflow bootstrap is complete. This workflow version is work in progress. "
            "Stop now and report this to the user. Do not create, modify, delete, upload, "
            "activate, or commit SAP repository objects."
        ),
        "repo": repo_info,
        "configPath": str(config_path),
        "config": config,
    }


def start(project_path_value: str, task: str, input_data: dict[str, Any] | None) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None, bool]:
    project_path = _resolve_project_path(project_path_value)
    project_path.mkdir(parents=True, exist_ok=True)
    repo_info = prepare_src_repo(project_path)
    config_path = _config_path(project_path)
    existing_config = _load_config(project_path)

    state = {
        "step": "bootstrap",
        "projectPath": str(project_path),
        "task": task,
        "repo": repo_info,
        "configPath": str(config_path),
        "configPresent": existing_config is not None,
    }

    if existing_config is not None:
        output = _finished_output(repo_info, config_path, existing_config)
        state["step"] = "done_for_now"
        state["config"] = existing_config
        return "FINISHED", state, output, None, True

    if input_data:
        errors = _validate_scope_input(input_data)
        if errors:
            output = _request_scope_output(repo_info, config_path)
            output["validationErrors"] = errors
            state["step"] = "awaiting_scope"
            state["expectedInputSchema"] = scope_input_schema()
            return "STARTED", state, output, scope_input_schema(), False
        if input_data["transportMode"] == "new":
            state["step"] = "awaiting_transport_creation"
            state["pendingScope"] = input_data
            state["expectedInputSchema"] = transport_created_input_schema()
            return "STARTED", state, _transport_creation_output(repo_info, config_path, input_data), transport_created_input_schema(), False
        config = _write_config(project_path, input_data)
        output = _finished_output(repo_info, config_path, config)
        state["step"] = "done_for_now"
        state["configPresent"] = True
        state["config"] = config
        return "FINISHED", state, output, None, True

    output = _request_scope_output(repo_info, config_path)
    state["step"] = "awaiting_scope"
    state["expectedInputSchema"] = scope_input_schema()
    return "STARTED", state, output, scope_input_schema(), False


def continue_workflow(state: dict[str, Any], input_data: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None, bool, list[str]]:
    project_path = _resolve_project_path(state["projectPath"])
    repo_info = prepare_src_repo(project_path)
    config_path = _config_path(project_path)
    if state.get("step") == "awaiting_transport_creation":
        errors = validate_json_schema(transport_created_input_schema(), input_data)
        transport_number = str(input_data.get("transportNumber", "")).strip().upper()
        if not transport_number:
            errors.append("transportNumber cannot be empty.")
        if errors:
            output = _transport_creation_output(repo_info, config_path, state["pendingScope"])
            output["validationErrors"] = errors
            state["repo"] = repo_info
            state["expectedInputSchema"] = transport_created_input_schema()
            return "STARTED", state, output, transport_created_input_schema(), False, errors

        config = _write_config(project_path, state["pendingScope"], transport_number)
        state["repo"] = repo_info
        state["step"] = "done_for_now"
        state["configPresent"] = True
        state["config"] = config
        state.pop("pendingScope", None)
        output = _finished_output(repo_info, config_path, config)
        return "FINISHED", state, output, None, True, []

    errors = _validate_scope_input(input_data)
    if errors:
        output = _request_scope_output(repo_info, config_path)
        output["validationErrors"] = errors
        state["repo"] = repo_info
        state["step"] = "awaiting_scope"
        state["expectedInputSchema"] = scope_input_schema()
        return "STARTED", state, output, scope_input_schema(), False, errors

    if input_data["transportMode"] == "new":
        state["repo"] = repo_info
        state["step"] = "awaiting_transport_creation"
        state["pendingScope"] = input_data
        state["expectedInputSchema"] = transport_created_input_schema()
        output = _transport_creation_output(repo_info, config_path, input_data)
        return "STARTED", state, output, transport_created_input_schema(), False, []

    config = _write_config(project_path, input_data)
    state["repo"] = repo_info
    state["step"] = "done_for_now"
    state["configPresent"] = True
    state["config"] = config
    output = _finished_output(repo_info, config_path, config)
    return "FINISHED", state, output, None, True, []
