import shutil
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import xmltodict
from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from generics import ApiResponse


SUPPORTED_SKILL_NAMES = (
    "sap-transport-scope-guard",
    "sap-local-git-repository-guard",
    "sap-repository-change-orchestrator",
    "sap-abap-unit-test-orchestrator",
)

INTERNAL_PATH_MARKERS = (
    "/".join(("internal", "skills")),
    "\\".join(("internal", "skills")),
    "/".join(("internals", "skills")),
    "\\".join(("internals", "skills")),
)


class SkillsInstallResult(BaseModel):
    """One installed project skill."""

    name: str = Field(..., description="Installed skill name.")
    destinationPath: str = Field(..., description="Absolute destination folder for the installed skill.")
    replacedExisting: bool = Field(..., description="Whether an existing installed skill folder was replaced.")
    skipped: bool = Field(False, description="Whether this skill was skipped instead of copied.")


class SkillsInstallOutput(BaseModel):
    """Result of installing SAP skills into a supported client project."""

    client: str = Field(..., description="Client whose project layout was configured.")
    scope: str = Field(..., description="Installation scope used for the client.")
    projectPath: str = Field(..., description="Absolute project root path.")
    skillsRoot: str = Field(..., description="Absolute folder where skills were installed.")
    installedSkills: list[SkillsInstallResult] = Field(default_factory=list, description="Per-skill installation details.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings encountered during setup.")


class SkillsInstallResponse(ApiResponse[SkillsInstallOutput]):
    """Response for skill installation operations."""


class ObjectLockProbeOutput(BaseModel):
    """Result of probing whether one ADT object can be locked and which CTS request SAP reports."""

    uri: str = Field(..., description="ADT URI that was probed.")
    lockSucceeded: bool = Field(..., description="Whether the lock request succeeded and returned a lock handle.")
    unlocked: bool = Field(..., description="Whether the probe released the lock before returning.")
    lockHandle: str = Field("", description="Transient lock handle returned by SAP. The probe releases it before returning.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(False, description="Whether SAP reports the locked object as local.")
    isLinkUp: bool = Field(False, description="Whether SAP reports a link-up for the lock.")
    modificationSupport: str = Field("", description="Modification support information returned by SAP when present.")
    scopeMessages: str = Field("", description="Additional scope messages returned by SAP when present.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings, such as unlock failures.")


class ObjectLockProbeResponse(ApiResponse[ObjectLockProbeOutput]):
    """Response for object lock probes."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _skills_source_root() -> Path:
    return _repo_root() / "internals" / "skills"


def _resolve_absolute_project_path(project_path: str) -> Path:
    raw_path = str(project_path or "").strip()
    if not raw_path:
        raise ValueError("projectPath is required.")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("projectPath must be an absolute path.")
    return path.resolve()


def _validate_target_inside_project(project_path: Path, target_path: Path) -> None:
    resolved_project = project_path.resolve()
    resolved_target = target_path.resolve()
    if resolved_project not in [resolved_target, *resolved_target.parents]:
        raise ValueError("Resolved installation path must stay inside projectPath.")


def _validate_skill_source(skill_path: Path) -> None:
    skill_file = skill_path / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"Missing SKILL.md for skill '{skill_path.name}'.")


def _scan_for_internal_paths(skill_path: Path) -> list[str]:
    warnings: list[str] = []
    for item in skill_path.rglob("*"):
        if not item.is_file():
            continue
        if item.parts and any(part == "agents" for part in item.parts):
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in INTERNAL_PATH_MARKERS:
            if marker in text:
                warnings.append(f"{item}: contains portable-path marker '{marker}'.")
                break
    return warnings


def _copy_skill_without_agent_metadata(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    for item in source.iterdir():
        if item.name == "agents":
            continue

        target = destination / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(item, target)


def _normalize_adt_uri(uri: str) -> str:
    normalized_uri = str(uri or "").strip()
    if not normalized_uri:
        raise ValueError("objectUri is required.")
    if not normalized_uri.startswith("/"):
        raise ValueError("objectUri must be an absolute ADT path starting with '/'.")
    if "://" in normalized_uri:
        raise ValueError("objectUri must be an ADT path, not a full URL.")
    return normalized_uri


def _append_query_parameter(uri: str, parameter: str) -> str:
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}{parameter}"


def _parse_bool_flag(value) -> bool:
    return str(value or "").strip().upper() == "X"


def _parse_lock_payload(text: str) -> dict:
    parsed = xmltodict.parse(text)
    return (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})


def probe_object_lock(systemId: str, objectUri: str) -> ObjectLockProbeResponse:
    """Lock and immediately unlock one ADT object URI to inspect SAP CTS lock metadata."""
    normalized_uri = ""
    lock_handle = ""
    warnings: list[str] = []
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ObjectLockProbeResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot probe the object lock because no SAP session is available: {error_msg}",
                "data": None,
            })

        normalized_uri = _normalize_adt_uri(objectUri)
        system_config = get_system_config(systemId)
        lock_uri = _append_query_parameter(normalized_uri, "_action=LOCK&accessMode=MODIFY")
        response = get_session(systemId).post(
            f"{system_config.server}{lock_uri}",
            headers=build_adt_headers(
                sessionType="stateful",
                extra={
                    "Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
                },
            ),
        )

        if response.status_code != 200:
            return ObjectLockProbeResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the object lock probe: {response.text}",
                "data": ObjectLockProbeOutput(
                    uri=normalized_uri,
                    lockSucceeded=False,
                    unlocked=False,
                    warnings=[],
                ),
            })

        data = _parse_lock_payload(response.text)
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the object.")

        output = ObjectLockProbeOutput(
            uri=normalized_uri,
            lockSucceeded=True,
            unlocked=False,
            lockHandle=lock_handle,
            corrnr=str(data.get("CORRNR", "") or ""),
            corruser=str(data.get("CORRUSER", "") or ""),
            corrtext=str(data.get("CORRTEXT", "") or ""),
            isLocal=_parse_bool_flag(data.get("IS_LOCAL")),
            isLinkUp=_parse_bool_flag(data.get("IS_LINK_UP")),
            modificationSupport=str(data.get("MODIFICATION_SUPPORT", "") or ""),
            scopeMessages=str(data.get("SCOPE_MESSAGES", "") or ""),
            warnings=warnings,
        )
    except ValueError as exc:
        return ObjectLockProbeResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ObjectLockProbeResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while probing the object lock: {str(exc)}",
            "data": None,
        })

    try:
        system_config = get_system_config(systemId)
        unlock_uri = _append_query_parameter(
            normalized_uri,
            f"_action=UNLOCK&lockHandle={quote(lock_handle, safe='')}",
        )
        unlock_response = get_session(systemId).post(
            f"{system_config.server}{unlock_uri}",
            headers=build_adt_headers(sessionType="stateful"),
        )
        if unlock_response.status_code == 200:
            output.unlocked = True
        else:
            warnings.append(f"Unlock failed with HTTP {unlock_response.status_code}: {unlock_response.text}")
    except Exception as exc:
        warnings.append(f"Unlock failed: {str(exc)}")

    output.warnings = warnings
    return ObjectLockProbeResponse(
        result=output.lockSucceeded and output.unlocked,
        httpCode=200,
        httpReason="OK",
        message="Object lock probe completed successfully." if output.unlocked else "Object lock probe completed, but unlock failed.",
        data=output,
    )


def install_skills(
    projectPath: str,
    client: Literal["opencode"],
    scope: Literal["project"],
    overwrite: bool = True,
) -> SkillsInstallResponse:
    """Install the bundled SAP skills into a supported client project."""
    try:
        if client != "opencode":
            raise ValueError("Unsupported client. Supported value in v1: opencode.")
        if scope != "project":
            raise ValueError("Unsupported scope. Supported value in v1: project.")

        project_path = _resolve_absolute_project_path(projectPath)
        source_root = _skills_source_root()
        if not source_root.is_dir():
            raise FileNotFoundError(f"Skills source folder not found: {source_root}")

        project_path.mkdir(parents=True, exist_ok=True)
        skills_root = (project_path / ".opencode" / "skills").resolve()
        _validate_target_inside_project(project_path, skills_root)
        skills_root.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        installed: list[SkillsInstallResult] = []

        for skill_name in SUPPORTED_SKILL_NAMES:
            source_skill = source_root / skill_name
            _validate_skill_source(source_skill)
            warnings.extend(_scan_for_internal_paths(source_skill))

            destination_skill = (skills_root / skill_name).resolve()
            _validate_target_inside_project(project_path, destination_skill)

            existed = destination_skill.exists()
            if existed and not overwrite:
                warnings.append(f"Skill '{skill_name}' already exists and overwrite is false; skipped.")
                installed.append(SkillsInstallResult(
                    name=skill_name,
                    destinationPath=str(destination_skill),
                    replacedExisting=False,
                    skipped=True,
                ))
                continue

            _copy_skill_without_agent_metadata(source_skill, destination_skill)
            installed.append(SkillsInstallResult(
                name=skill_name,
                destinationPath=str(destination_skill),
                replacedExisting=existed,
                skipped=False,
            ))

        return SkillsInstallResponse(
            result=True,
            message="Skills installed.",
            data=SkillsInstallOutput(
                client=client,
                scope=scope,
                projectPath=str(project_path),
                skillsRoot=str(skills_root),
                installedSkills=installed,
                warnings=warnings,
            ),
        )
    except Exception as exc:
        return SkillsInstallResponse(
            result=False,
            message=str(exc),
            data=None,
        )
