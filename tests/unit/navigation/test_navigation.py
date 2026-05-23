from types import SimpleNamespace

from navigation import navigation


def test_build_navigation_source_uri_adds_range_fragment():
    request = navigation.NavigationTargetRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main",
        source="REPORT yjrs_r0001.",
        startLine=74,
        startColumn=21,
        endLine=74,
        endColumn=31,
    )

    result = navigation._build_navigation_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=74,21;end=74,31"


def test_build_navigation_source_uri_strips_existing_fragment():
    request = navigation.NavigationTargetRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=1,1",
        source="REPORT yjrs_r0001.",
        startLine=74,
        startColumn=21,
    )

    result = navigation._build_navigation_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=74,21;end=74,21"


def test_parse_navigation_target_response_minimal_reference():
    response = SimpleNamespace(
        status_code=200,
        reason="OK",
        text="""<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReference adtcore:uri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=29,10" xmlns:adtcore="http://www.sap.com/adt/core"/>""",
    )

    result = navigation.parse_navigation_target_response(
        response,
        "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=74,21;end=74,31",
        "definition",
    )

    assert result.result is True
    assert result.data is not None
    assert result.data.target.uri == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=29,10"
    assert result.data.filter == "definition"


def test_parse_navigation_target_response_full_reference_metadata():
    response = SimpleNamespace(
        status_code=200,
        reason="OK",
        text="""<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReference xmlns:adtcore="http://www.sap.com/adt/core" adtcore:uri="/sap/bc/adt/oo/classes/zcl_demo/source/main#start=10,5" adtcore:type="CLAS/OM" adtcore:name="DO_WORK" adtcore:packageName="$TMP" adtcore:description="Method"/>""",
    )

    result = navigation.parse_navigation_target_response(response, "/source#start=1,1;end=1,4", "definition")

    assert result.result is True
    assert result.data.target.name == "DO_WORK"
    assert result.data.target.type == "CLAS/OM"
    assert result.data.target.packageName == "$TMP"
