from types import SimpleNamespace

from docu.abap import docu_abap


def test_build_docu_abap_source_uri_adds_selection_fragment():
    request = docu_abap.DocuAbapLanguageHelpRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main",
        source="LOOP AT lt_screens INTO ls_screen.",
        startLine=60,
        startColumn=4,
        endLine=60,
        endColumn=8,
    )

    result = docu_abap._build_docu_abap_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=60,4;end=60,8"


def test_build_docu_abap_source_uri_strips_existing_fragment():
    request = docu_abap.DocuAbapLanguageHelpRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=1,1",
        source="LOOP AT lt_screens INTO ls_screen.",
        startLine=60,
        startColumn=4,
    )

    result = docu_abap._build_docu_abap_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=60,4;end=60,4"


def test_html_to_text_extracts_title_and_visible_documentation():
    html = """<!DOCTYPE html>
<html><head><title>ABAP Keyword Documentation</title><style>body { color: red; }</style></head>
<body>
  <div class="topnav">Navigation Chrome</div>
  <h2>ABAP Programming Language</h2>
  <span><a href="adtcom:/sap/bc/adt/docu/abap/langu?object=ABAPLOOP_AT_ITAB_VARIANTS">LOOP AT itab, ABAP Statement</a></span>
  <script>console.log("skip me")</script>
</body></html>"""

    title, plain_text = docu_abap._html_to_text(html)

    assert title == "ABAP Keyword Documentation"
    assert "ABAP Programming Language" in plain_text
    assert "LOOP AT itab, ABAP Statement" in plain_text
    assert "color: red" not in plain_text
    assert "console.log" not in plain_text


def test_call_docu_abap_language_help_parses_success(monkeypatch):
    class DummySession:
        def post(self, url, headers, data):
            self.url = url
            self.headers = headers
            self.data = data
            return SimpleNamespace(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "application/vnd.sap.adt.docu.v1+html; charset=utf-8"},
                text="""<html><head><title>ABAP Keyword Documentation</title></head>
<body><h2>ABAP Programming Language</h2><a>LOOP AT itab, ABAP Statement</a></body></html>""",
            )

    dummy_session = DummySession()
    monkeypatch.setattr(docu_abap, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(docu_abap, "get_system_config", lambda system_id: SimpleNamespace(server="http://sap.example"))
    monkeypatch.setattr(docu_abap, "get_session", lambda system_id: dummy_session)

    request = docu_abap.DocuAbapLanguageHelpRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main",
        source="LOOP AT lt_screens INTO ls_screen.",
        startLine=60,
        startColumn=4,
        endLine=60,
        endColumn=8,
    )

    response = docu_abap.call_docu_abap_language_help("A4H", request)

    assert response.result is True
    assert response.data.title == "ABAP Keyword Documentation"
    assert "LOOP AT itab" in response.data.plainText
    assert "format=eclipse" in dummy_session.url
    assert "language=EN" in dummy_session.url
    assert "uri=%2Fsap%2Fbc%2Fadt%2Fprograms" in dummy_session.url
