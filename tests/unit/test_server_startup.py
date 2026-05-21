import asyncio

import server


def test_build_startup_urls_normalizes_mcp_path():
    urls = server._build_startup_urls("127.0.0.1", 8081, "mcp/abap/")

    assert urls["mcp"] == "http://127.0.0.1:8081/mcp/abap"
    assert urls["dashboard"] == "http://127.0.0.1:8081/mcp/abap/dashboard"


def test_wait_for_dashboard_http_200_retries_until_success():
    calls = []

    def status_reader(url: str, timeout_seconds: float) -> int:
        calls.append((url, timeout_seconds))
        return 503 if len(calls) == 1 else 200

    ready = asyncio.run(
        server._wait_for_dashboard_http_200(
            "http://127.0.0.1:8081/mcp/abap/dashboard",
            timeout_seconds=1,
            retry_interval_seconds=0.01,
            status_reader=status_reader,
        )
    )

    assert ready is True
    assert len(calls) == 2


def test_wait_for_dashboard_http_200_times_out():
    ready = asyncio.run(
        server._wait_for_dashboard_http_200(
            "http://127.0.0.1:8081/mcp/abap/dashboard",
            timeout_seconds=0.02,
            retry_interval_seconds=0.01,
            status_reader=lambda _url, _timeout_seconds: 503,
        )
    )

    assert ready is False


def test_log_startup_urls_warns_when_dashboard_readiness_times_out(monkeypatch):
    warnings = []

    async def not_ready(_dashboard_url: str) -> bool:
        return False

    monkeypatch.setattr(server, "_wait_for_dashboard_http_200", not_ready)
    monkeypatch.setattr(server.LOGGER, "warning", lambda message, *args: warnings.append(message % args))
    monkeypatch.setattr(server, "RUN_HOST", "127.0.0.1")
    monkeypatch.setattr(server, "RUN_PORT", 8092)
    monkeypatch.setattr(server, "RUN_PATH", "/mcp/abap")

    asyncio.run(server._log_startup_urls_when_dashboard_ready(0))

    assert warnings == [
        "ABAP MCP server started, but dashboard readiness could not be confirmed within 30 seconds: "
        "http://127.0.0.1:8092/mcp/abap/dashboard"
    ]


def test_dashboard_html_places_env_save_button_and_dirty_dot():
    html = server._dashboard_html()
    env_panel_index = html.index('id="tabPanelEnv"')
    save_button_index = html.index('id="saveButton"')

    assert ".wrap { width: 100%;" in html
    assert "max-width: 1180px" not in html
    assert save_button_index > env_panel_index
    assert 'id="saveDirtyDot"' in html


def test_dashboard_html_uses_global_toast_notifications():
    html = server._dashboard_html()

    assert 'id="toastRegion"' in html
    assert 'id="status"' not in html
    assert "statusEl" not in html
    assert "setStatus(" not in html
    assert "function showToast(" in html
    assert "function placeToastRegion()" in html
    assert "placeToastRegion();" in html
    assert 'document.querySelectorAll("dialog[open]")' in html
    assert "z-index: 2000;" in html
    assert 'showToast(error.message || t("mcp.actionError"), "error")' in html
    assert 'showToast(payload.message || t("config.saveError"), "error")' in html
    assert 'showToast(t("saplogon.credentialsRequired"), "error")' in html


def test_dashboard_html_has_language_selector_and_local_storage_i18n():
    html = server._dashboard_html()

    assert 'id="languageSelect"' in html
    assert 'value="es">Español' in html
    assert 'value="en">English' in html
    assert 'abapMcpDashboardLanguage' in html
    assert "document.documentElement.lang = currentLanguage" in html
    assert "function t(key" in html
    assert "function apiUrl(url)" in html
    assert "data-i18n=" in html
    assert "data-i18n-placeholder=" in html
