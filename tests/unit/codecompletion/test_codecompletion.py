from types import SimpleNamespace

from codecompletion import codecompletion


def test_build_codecompletion_uri_adds_start_position():
    result = codecompletion._build_codecompletion_uri(
        "/sap/bc/adt/programs/programs/yjrs_r0001/source/main",
        66,
        23,
    )

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=66,23"


def test_build_codecompletion_uri_strips_existing_fragment():
    result = codecompletion._build_codecompletion_uri(
        "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=1,1",
        66,
        23,
    )

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=66,23"


def test_parse_codecompletion_proposals_response_extracts_scc_completion_items():
    response = SimpleNamespace(
        status_code=200,
        reason="OK",
        text="""<?xml version="1.0" encoding="utf-8"?>
<asx:abap version="1.0" xmlns:asx="http://www.sap.com/abapxml">
  <asx:values>
    <DATA>
      <SCC_COMPLETION>
        <KIND>1</KIND>
        <IDENTIFIER>IV_DYNNR</IDENTIFIER>
        <ICON>6</ICON>
        <SUBICON>0</SUBICON>
        <BOLD>1</BOLD>
        <QUICKINFO_EVENT>1</QUICKINFO_EVENT>
        <INSERT_EVENT>1</INSERT_EVENT>
        <IS_META>0</IS_META>
        <PREFIXLENGTH>1</PREFIXLENGTH>
        <ROLE>21</ROLE>
        <LOCATION>0</LOCATION>
        <GRADE>0</GRADE>
        <VISIBILITY>0</VISIBILITY>
        <IS_INHERITED>0</IS_INHERITED>
        <PROP1>1</PROP1>
        <PROP2>1</PROP2>
        <PROP3>1</PROP3>
        <SYNTCNTXT>13</SYNTCNTXT>
      </SCC_COMPLETION>
      <SCC_COMPLETION>
        <KIND>0</KIND>
        <IDENTIFIER>@end</IDENTIFIER>
        <QUICKINFO_EVENT>0</QUICKINFO_EVENT>
        <INSERT_EVENT>0</INSERT_EVENT>
        <PREFIXLENGTH>0</PREFIXLENGTH>
      </SCC_COMPLETION>
    </DATA>
  </asx:values>
</asx:abap>""",
    )

    output = codecompletion.parse_codecompletion_proposals_response(
        response,
        "/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=66,23",
    )

    assert output.totalCount == 2
    assert output.proposals[0].identifier == "IV_DYNNR"
    assert output.proposals[0].quickinfoEvent is True
    assert output.proposals[0].prefixLength == 1
    assert output.proposals[0].syntaxContext == 13
    assert output.proposals[1].isMeta is True


def test_parse_codecompletion_element_info_response_extracts_properties():
    response = SimpleNamespace(
        status_code=200,
        reason="OK",
        text="""<?xml version="1.0" encoding="utf-8"?>
<abapsource:elementInfo adtcore:name="IV_DYNNR" xmlns:abapsource="http://www.sap.com/adt/abapsource" xmlns:adtcore="http://www.sap.com/adt/core">
  <abapsource:properties>
    <abapsource:entry abapsource:key="visibility">local</abapsource:entry>
    <abapsource:entry abapsource:key="abapType">TYPE SYCHAR04</abapsource:entry>
    <abapsource:entry abapsource:key="paramType">importing</abapsource:entry>
    <abapsource:entry abapsource:key="optional">true</abapsource:entry>
  </abapsource:properties>
</abapsource:elementInfo>""",
    )

    info = codecompletion.parse_codecompletion_element_info_response(response)

    assert info.name == "IV_DYNNR"
    assert info.properties["visibility"] == "local"
    assert info.properties["abapType"] == "TYPE SYCHAR04"
    assert info.properties["optional"] == "true"
