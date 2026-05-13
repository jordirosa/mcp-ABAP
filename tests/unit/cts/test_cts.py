from types import SimpleNamespace

from cts import cts


def test_transport_request_uri_normalizes_transport_number():
    assert cts._transport_request_uri(" a4hk900127 ") == "/sap/bc/adt/cts/transportrequests/A4HK900127"


def test_ensure_list_normalizes_singletons():
    assert cts._ensure_list(None) == []
    assert cts._ensure_list("") == []
    assert cts._ensure_list({"a": 1}) == [{"a": 1}]
    assert cts._ensure_list([1, 2]) == [1, 2]


def test_parse_cts_transport_read_response_extracts_request_tasks_and_objects():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<tm:root tm:object_type="R" adtcore:name="A4HK900127" adtcore:type="RQRQ" xmlns:tm="http://www.sap.com/cts/adt/tm" xmlns:adtcore="http://www.sap.com/adt/core">
  <tm:request tm:number="A4HK900127" tm:owner="DEVELOPER" tm:desc="Test Codex" tm:status="D" tm:status_text="Modifiable" tm:target="" tm:target_desc="Local Change Requests" tm:source_client="001" tm:uri="/sap/bc/adt/cts/transportrequests/A4HK900127">
    <tm:all_objects>
      <tm:abap_object tm:pgmid="R3TR" tm:type="DEVC" tm:name="ZCDX" tm:wbtype="DEVC/K" tm:obj_info="Package" tm:position="000001" tm:lock_status="X" tm:dummy_uri="/sap/bc/adt/cts/transportrequests/reference?obj_name=ZCDX"/>
    </tm:all_objects>
    <tm:task tm:number="A4HK900128" tm:parent="A4HK900127" tm:owner="DEVELOPER" tm:desc="Test Codex" tm:type="Development/Correction" tm:status="D" tm:status_text="Modifiable" tm:uri="/sap/bc/adt/cts/transportrequests/A4HK900128">
      <tm:abap_object tm:pgmid="R3TR" tm:type="DEVC" tm:name="ZCDX" tm:wbtype="DEVC/K" tm:obj_info="Package" tm:position="000001" tm:lock_status="X" tm:dummy_uri="/sap/bc/adt/cts/transportrequests/reference?obj_name=ZCDX"/>
    </tm:task>
  </tm:request>
</tm:root>
"""
    response = SimpleNamespace(
        text=xml,
        status_code=200,
        reason="OK",
        headers={"ETag": "etag-1"},
    )

    parsed = cts.parse_cts_transport_read_response(response)

    assert parsed.result is True
    assert parsed.data is not None
    assert parsed.data.transportNumber == "A4HK900127"
    assert parsed.data.description == "Test Codex"
    assert parsed.data.etag == "etag-1"
    assert len(parsed.data.objects) == 1
    assert parsed.data.objects[0].name == "ZCDX"
    assert len(parsed.data.tasks) == 1
    assert parsed.data.tasks[0].transportNumber == "A4HK900128"

