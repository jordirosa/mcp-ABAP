from pathlib import Path

from internals.workflows import sap_repository_change
from internals.workflows.engine import WorkflowEngine
from internals.workflows.store import WorkflowStore


def _engine(tmp_path) -> WorkflowEngine:
    return WorkflowEngine(WorkflowStore(tmp_path / "runtime" / "workflows.sqlite"))


def test_workflow_store_creates_database_and_persists_events(tmp_path):
    db_path = tmp_path / "runtime" / "workflows.sqlite"
    store = WorkflowStore(db_path)

    store.create_workflow(
        workflow_id="wf_test",
        workflow="sap_repository_change",
        project_path=str(tmp_path / "project"),
        task="Task",
        state={"step": "test"},
        output={"code": "TEST"},
    )
    store.add_event("wf_test", "input", {"hello": "world"})

    row = store.get_workflow("wf_test")
    events = store.list_events("wf_test")

    assert db_path.is_file()
    assert row["status"] == "STARTED"
    assert row["state"] == {"step": "test"}
    assert row["lastOutput"] == {"code": "TEST"}
    assert events[0]["eventType"] == "input"
    assert events[0]["payload"] == {"hello": "world"}


def test_sap_repository_workflow_requests_scope_when_config_is_missing(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)

    response = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a test report",
    )

    assert response.result is True
    assert response.data.status == "STARTED"
    assert response.data.output["code"] == "SCOPE_REQUIRED"
    assert response.data.expectedInputSchema["required"] == ["systemId", "package", "transportMode"]
    assert "systemOptions" in response.data.output
    assert {"mode": "new", "description": "Create a new transport request using cts_transport_create after the workflow authorizes it."} in response.data.output["transportOptions"]
    assert (project_path / "src" / ".git").is_dir()
    assert (project_path / "src" / "readme.md").read_text(encoding="utf-8") == "Local ABAP Repository\n"


def test_sap_repository_workflow_creates_transportable_config_and_stops(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)
    start = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a test report",
    )

    response = engine.continue_workflow(
        workflow_id=start.data.workflowId,
        input_data={"systemId": "A4H", "package": "ZBOOKS", "transportMode": "existing", "transport": "A4HK900116"},
    )

    assert response.result is True
    assert response.data.status == "FINISHED"
    assert response.data.stopRequired is True
    assert response.data.output["code"] == "BOOTSTRAP_COMPLETE"
    assert '"transport": "A4HK900116"' in (project_path / "abap.config").read_text(encoding="utf-8")
    assert '"localPackage": false' in (project_path / "abap.config").read_text(encoding="utf-8")


def test_sap_repository_workflow_accepts_local_package_without_transport(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)

    response = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a local report",
        input_data={"systemId": "A4H", "package": "$TMP", "transportMode": "none", "transport": None},
    )

    assert response.result is True
    assert response.data.status == "FINISHED"
    config_text = (project_path / "abap.config").read_text(encoding="utf-8")
    assert '"package": "$TMP"' in config_text
    assert '"transport": null' in config_text
    assert '"localPackage": true' in config_text


def test_sap_repository_workflow_rejects_transportable_package_without_transport(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)
    start = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a report",
    )

    response = engine.continue_workflow(
        workflow_id=start.data.workflowId,
        input_data={"systemId": "A4H", "package": "ZBOOKS", "transportMode": "existing", "transport": None},
    )

    assert response.result is True
    assert response.data.status == "STARTED"
    assert response.data.output["validationErrors"] == ["transport is required for transportable packages."]
    assert not (project_path / "abap.config").exists()


def test_sap_repository_workflow_authorizes_transport_creation_before_config(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)
    start = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a report",
    )

    response = engine.continue_workflow(
        workflow_id=start.data.workflowId,
        input_data={
            "systemId": "A4H",
            "package": "ZBOOKS",
            "transportMode": "new",
            "transportDescription": "Prueba ZBOOKS1",
        },
    )

    assert response.result is True
    assert response.data.status == "STARTED"
    assert response.data.output["code"] == "TRANSPORT_CREATION_REQUIRED"
    assert response.data.expectedInputSchema["required"] == ["transportNumber"]
    assert response.data.output["toolRequest"] == {
        "tool": "cts_transport_create",
        "arguments": {
            "systemId": "A4H",
            "packageName": "ZBOOKS",
            "requestText": "Prueba ZBOOKS1",
            "objectUri": "/sap/bc/adt/packages/zbooks",
            "operation": "I",
        },
    }
    assert not (project_path / "abap.config").exists()

    finish = engine.continue_workflow(
        workflow_id=start.data.workflowId,
        input_data={"transportNumber": "A4HK900130"},
    )

    assert finish.result is True
    assert finish.data.status == "FINISHED"
    assert '"transport": "A4HK900130"' in (project_path / "abap.config").read_text(encoding="utf-8")


def test_sap_repository_workflow_includes_configured_system_options(tmp_path, monkeypatch):
    class FakeSystem:
        def model_dump(self):
            return {"id": "A4H", "name": "Demo", "type": "Dev"}

    class FakeResponse:
        result = True
        data = type("Data", (), {"systems": [FakeSystem()]})()

    monkeypatch.setattr(sap_repository_change, "call_sap_systems_list", lambda: FakeResponse())

    response = _engine(tmp_path).start(
        workflow="sap_repository_change",
        project_path=str(tmp_path / "project"),
        task="Create a report",
    )

    assert response.data.output["systemOptions"] == [{"id": "A4H", "name": "Demo", "type": "Dev"}]


def test_workflow_log_returns_inputs_outputs_and_validation_errors(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)
    start = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a report",
    )
    engine.continue_workflow(
        workflow_id=start.data.workflowId,
        input_data={"systemId": "A4H", "package": "ZBOOKS", "transportMode": "existing", "transport": None},
    )

    log = engine.log(start.data.workflowId)

    assert log.result is True
    event_types = [event.eventType for event in log.data.events]
    assert event_types == ["start_input", "workflow_output", "continue_input", "validation_error", "workflow_output"]
    assert log.data.status == "STARTED"


def test_workflow_cancel_finishes_run(tmp_path):
    project_path = tmp_path / "project"
    engine = _engine(tmp_path)
    start = engine.start(
        workflow="sap_repository_change",
        project_path=str(project_path),
        task="Create a report",
    )

    response = engine.cancel(start.data.workflowId)

    assert response.result is True
    assert response.data.status == "FINISHED"
    assert response.data.output["code"] == "WORKFLOW_CANCELLED"
    assert engine.status(start.data.workflowId).data.status == "FINISHED"
