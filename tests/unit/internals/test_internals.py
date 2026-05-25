from pathlib import Path

from internals import internals
from internals.internals import SUPPORTED_SKILL_NAMES, install_skills


def test_install_skills_copies_opencode_project_skills_without_agents(tmp_path):
    project_path = tmp_path / "project"

    response = install_skills(
        projectPath=str(project_path),
        client="opencode",
        scope="project",
    )

    assert response.result is True
    assert response.data is not None
    assert response.data.client == "opencode"
    assert response.data.scope == "project"
    assert response.data.skillsRoot == str(project_path / ".opencode" / "skills")

    installed_names = {item.name for item in response.data.installedSkills}
    assert installed_names == set(SUPPORTED_SKILL_NAMES)

    for skill_name in SUPPORTED_SKILL_NAMES:
        destination = project_path / ".opencode" / "skills" / skill_name
        assert (destination / "SKILL.md").is_file()
        assert not (destination / "agents").exists()


def test_install_skills_replaces_existing_by_default(tmp_path):
    project_path = tmp_path / "project"
    destination = project_path / ".opencode" / "skills" / SUPPORTED_SKILL_NAMES[0]
    destination.mkdir(parents=True)
    stale_file = destination / "stale.txt"
    stale_file.write_text("stale", encoding="utf-8")

    response = install_skills(
        projectPath=str(project_path),
        client="opencode",
        scope="project",
    )

    assert response.result is True
    assert not stale_file.exists()
    replaced = {item.name: item.replacedExisting for item in response.data.installedSkills}
    assert replaced[SUPPORTED_SKILL_NAMES[0]] is True


def test_install_skills_skips_existing_when_overwrite_false(tmp_path):
    project_path = tmp_path / "project"
    destination = project_path / ".opencode" / "skills" / SUPPORTED_SKILL_NAMES[0]
    destination.mkdir(parents=True)
    marker = destination / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    response = install_skills(
        projectPath=str(project_path),
        client="opencode",
        scope="project",
        overwrite=False,
    )

    assert response.result is True
    assert marker.read_text(encoding="utf-8") == "keep"
    skipped = {item.name: item.skipped for item in response.data.installedSkills}
    assert skipped[SUPPORTED_SKILL_NAMES[0]] is True
    assert any("overwrite is false" in warning for warning in response.data.warnings)


def test_install_skills_rejects_relative_project_path():
    response = install_skills(
        projectPath=str(Path("relative-project")),
        client="opencode",
        scope="project",
    )

    assert response.result is False
    assert "absolute path" in response.message


def test_install_skills_rejects_unsupported_client_and_scope(tmp_path):
    client_response = install_skills(
        projectPath=str(tmp_path / "project"),
        client="other",
        scope="project",
    )
    scope_response = install_skills(
        projectPath=str(tmp_path / "project"),
        client="opencode",
        scope="global",
    )

    assert client_response.result is False
    assert "Unsupported client" in client_response.message
    assert scope_response.result is False
    assert "Unsupported scope" in scope_response.message


def test_probe_object_lock_locks_and_unlocks(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<asx:abap version="1.0" xmlns:asx="http://www.sap.com/abapxml">
  <asx:values>
    <DATA>
      <LOCK_HANDLE>HANDLE-1</LOCK_HANDLE>
      <CORRNR>A4HK900110</CORRNR>
      <CORRUSER>DEVELOPER</CORRUSER>
      <CORRTEXT>Test package</CORRTEXT>
      <IS_LOCAL/>
      <IS_LINK_UP>X</IS_LINK_UP>
    </DATA>
  </asx:values>
</asx:abap>"""

    class FakeSession:
        def post(self, url, headers=None):
            calls.append((url, headers))
            return FakeResponse()

    monkeypatch.setattr(internals, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(internals, "get_system_config", lambda system_id: type("Config", (), {"server": "https://sap.example"})())
    monkeypatch.setattr(internals, "get_session", lambda system_id: FakeSession())

    response = internals.probe_object_lock("A4H", "/sap/bc/adt/programs/programs/ztest")

    assert response.result is True
    assert response.data is not None
    assert response.data.lockSucceeded is True
    assert response.data.unlocked is True
    assert response.data.corrnr == "A4HK900110"
    assert response.data.corruser == "DEVELOPER"
    assert response.data.corrtext == "Test package"
    assert response.data.isLocal is False
    assert response.data.isLinkUp is True
    assert calls[0][0] == "https://sap.example/sap/bc/adt/programs/programs/ztest?_action=LOCK&accessMode=MODIFY"
    assert calls[1][0] == "https://sap.example/sap/bc/adt/programs/programs/ztest?_action=UNLOCK&lockHandle=HANDLE-1"


def test_probe_object_lock_appends_lock_query_to_uri_with_existing_query(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        reason = "OK"
        text = """<asx:abap version="1.0" xmlns:asx="http://www.sap.com/abapxml"><asx:values><DATA><LOCK_HANDLE>H</LOCK_HANDLE><IS_LOCAL>X</IS_LOCAL></DATA></asx:values></asx:abap>"""

    class FakeSession:
        def post(self, url, headers=None):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(internals, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(internals, "get_system_config", lambda system_id: type("Config", (), {"server": "https://sap.example"})())
    monkeypatch.setattr(internals, "get_session", lambda system_id: FakeSession())

    response = internals.probe_object_lock("A4H", "/sap/bc/adt/foo/bar?sap-client=001")

    assert response.result is True
    assert calls[0] == "https://sap.example/sap/bc/adt/foo/bar?sap-client=001&_action=LOCK&accessMode=MODIFY"
    assert calls[1] == "https://sap.example/sap/bc/adt/foo/bar?sap-client=001&_action=UNLOCK&lockHandle=H"


def test_probe_object_lock_rejects_full_url(monkeypatch):
    monkeypatch.setattr(internals, "ensure_login", lambda system_id: (True, ""))

    response = internals.probe_object_lock("A4H", "https://sap.example/sap/bc/adt/programs/programs/ztest")

    assert response.result is False
    assert "ADT path" in response.message


def test_probe_object_lock_reports_unlock_failure(monkeypatch):
    calls = []

    class FakeLockResponse:
        status_code = 200
        reason = "OK"
        text = """<asx:abap version="1.0" xmlns:asx="http://www.sap.com/abapxml"><asx:values><DATA><LOCK_HANDLE>H</LOCK_HANDLE></DATA></asx:values></asx:abap>"""

    class FakeUnlockResponse:
        status_code = 500
        reason = "Internal Server Error"
        text = "unlock failed"

    class FakeSession:
        def post(self, url, headers=None):
            calls.append(url)
            return FakeLockResponse() if len(calls) == 1 else FakeUnlockResponse()

    monkeypatch.setattr(internals, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(internals, "get_system_config", lambda system_id: type("Config", (), {"server": "https://sap.example"})())
    monkeypatch.setattr(internals, "get_session", lambda system_id: FakeSession())

    response = internals.probe_object_lock("A4H", "/sap/bc/adt/programs/programs/ztest")

    assert response.result is False
    assert response.data.lockSucceeded is True
    assert response.data.unlocked is False
    assert response.data.warnings == ["Unlock failed with HTTP 500: unlock failed"]
