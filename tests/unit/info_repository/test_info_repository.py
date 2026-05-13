from info_repository import info_repository


def test_parse_info_repository_response_single_reference():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/tables/sflight" adtcore:type="TABL/DT" adtcore:name="SFLIGHT" adtcore:packageName="SAPBC_DATAMODEL" adtcore:description="Flight"/>
</adtcore:objectReferences>"""

    response = info_repository.parse_info_repository_search_response(DummyResponse())
    assert response.result is True
    assert response.data is not None
    assert response.data.totalCount == 1
    assert response.data.objectReferences[0].name == "SFLIGHT"
    assert response.data.objectReferences[0].type == "TABL/DT"


def test_parse_info_repository_response_multiple_references():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/programs/programs/ycdx_prog_0401" adtcore:type="PROG/P" adtcore:name="YCDX_PROG_0401" adtcore:packageName="$TMP" adtcore:description="Program"/>
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/programs/includes/ycdx_inc_0401" adtcore:type="PROG/I" adtcore:name="YCDX_INC_0401" adtcore:packageName="$TMP" adtcore:description="Include"/>
</adtcore:objectReferences>"""

    response = info_repository.parse_info_repository_search_response(DummyResponse())
    assert response.result is True
    assert response.data is not None
    assert response.data.totalCount == 2
    assert {item.type for item in response.data.objectReferences} == {"PROG/P", "PROG/I"}
