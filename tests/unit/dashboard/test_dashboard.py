import json
from pathlib import Path

from dashboard import dashboard


def test_get_dashboard_mcp_status_accepts_utf8_bom_in_copilot_config(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(dashboard, "_claude_desktop_package_family_name", lambda: "")
    config_path = home / ".copilot" / "mcp-config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mcpServers": {
            "mcp-ABAP": {
                "type": "http",
                "url": "http://127.0.0.1:8081/mcp/abap/",
            }
        }
    }
    config_path.write_bytes(("\ufeff" + json.dumps(payload)).encode("utf-8"))

    monkeypatch.setattr(dashboard.Path, "home", staticmethod(lambda: home))
    dashboard.configure_dashboard_mcp_target("127.0.0.1", 8081, "/mcp/abap")

    status = dashboard.get_dashboard_mcp_status()
    copilot = next(client for client in status["clients"] if client["id"] == "copilot")

    assert copilot["mcpState"] == "match"


def test_get_dashboard_mcp_status_accepts_utf8_bom_in_codex_config(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(dashboard, "_claude_desktop_package_family_name", lambda: "")
    config_path = home / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(
        (
            "\ufeff[mcp_servers.mcp-ABAP]\n"
            'url = "http://127.0.0.1:8081/mcp/abap/"\n'
            "tool_timeout_sec = 120\n"
        ).encode("utf-8")
    )

    monkeypatch.setattr(dashboard.Path, "home", staticmethod(lambda: home))
    dashboard.configure_dashboard_mcp_target("127.0.0.1", 8081, "/mcp/abap")

    status = dashboard.get_dashboard_mcp_status()
    codex = next(client for client in status["clients"] if client["id"] == "codex")

    assert codex["mcpState"] == "match"


def test_apply_dashboard_mcp_action_normalizes_inline_codex_toml_header(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(dashboard, "_claude_desktop_package_family_name", lambda: "")
    config_path = home / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('[mcp_servers.mcp-ABAP] url = "http://127.0.0.1:9999/mcp/abap/"\n', encoding="utf-8")

    monkeypatch.setattr(dashboard.Path, "home", staticmethod(lambda: home))
    dashboard.configure_dashboard_mcp_target("127.0.0.1", 8081, "/mcp/abap")

    status = dashboard.get_dashboard_mcp_status()
    codex = next(client for client in status["clients"] if client["id"] == "codex")

    assert codex["mcpState"] == "mismatch"
    assert codex["mcpLabel"] == "Ajustable"
    assert codex["actions"] == ["adjust", "delete"]

    dashboard.apply_dashboard_mcp_action("codex", "adjust")

    assert config_path.read_text(encoding="utf-8") == (
        "[mcp_servers.mcp-ABAP]\n"
        'url = "http://127.0.0.1:8081/mcp/abap/"\n'
        "tool_timeout_sec = 120\n"
    )


def test_get_dashboard_mcp_status_detects_claude_desktop_mcp_remote_config(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    local_app_data = tmp_path / "localappdata"
    config_path = (
        local_app_data
        / "Packages"
        / "Claude_pzs8sxrjxfjjc"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude_desktop_config.json"
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-ABAP": {
                        "command": "npx",
                        "args": ["mcp-remote", "http://127.0.0.1:8081/mcp/abap/", "--allow-http"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(dashboard.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(dashboard, "_claude_desktop_package_family_name", lambda: "")
    dashboard.configure_dashboard_mcp_target("127.0.0.1", 8081, "/mcp/abap")

    status = dashboard.get_dashboard_mcp_status()
    claude = next(client for client in status["clients"] if client["id"] == "claude")

    assert claude["cliInstalled"] is True
    assert claude["mcpState"] == "match"


def test_apply_dashboard_mcp_action_inserts_claude_config_without_removing_other_servers(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    local_app_data = tmp_path / "localappdata"
    config_path = (
        local_app_data
        / "Packages"
        / "Claude_pzs8sxrjxfjjc"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude_desktop_config.json"
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {
                        "command": "node",
                        "args": ["server.js"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(dashboard.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(dashboard, "_claude_desktop_package_family_name", lambda: "")
    dashboard.configure_dashboard_mcp_target("127.0.0.1", 8081, "/mcp/abap")

    result = dashboard.apply_dashboard_mcp_action("claude", "insert")
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["client"]["mcpState"] == "match"
    assert payload["mcpServers"]["other"] == {"command": "node", "args": ["server.js"]}
    assert payload["mcpServers"]["mcp-ABAP"] == {
        "command": "npx",
        "args": ["mcp-remote", "http://127.0.0.1:8081/mcp/abap/", "--allow-http"],
    }
