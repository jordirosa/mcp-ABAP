from deletion import deletion


def test_build_deletion_payload_contains_uri_and_transport():
    payload = deletion._build_deletion_delete_payload(
        objectUri="/sap/bc/adt/programs/programs/zfoo",
        transportNumber="A4HK900999",
    )

    assert 'adtcore:uri="/sap/bc/adt/programs/programs/zfoo"' in payload
    assert "<del:transportNumber>A4HK900999</del:transportNumber>" in payload


def test_parse_deletion_response_detects_deleted_object():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<del:deletionResult xmlns:del="http://www.sap.com/adt/deletion" xmlns:adtcore="http://www.sap.com/adt/core">
  <del:object del:isDeleted="true" adtcore:uri="/sap/bc/adt/programs/programs/zfoo" adtcore:type="PROG/P" adtcore:name="ZFOO" adtcore:packageName="$TMP">
    <del:message del:priority="0" del:type="S">
      <del:text>Deleted</del:text>
    </del:message>
  </del:object>
</del:deletionResult>"""

    response = deletion.parse_deletion_delete_response(DummyResponse())
    assert response.result is True
    assert response.data is not None
    assert response.data.isDeleted is True
    assert response.data.name == "ZFOO"
    assert response.data.messageText == "Deleted"
