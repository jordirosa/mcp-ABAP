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


def test_build_usage_reference_source_uri_adds_active_version_and_range():
    request = info_repository.InfoRepositoryUsageReferencesRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main",
        startLine=29,
        startColumn=10,
        endLine=29,
        endColumn=20,
    )

    result = info_repository._build_usage_reference_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main?version=active#start=29,10;end=29,20"


def test_build_usage_reference_source_uri_keeps_existing_version():
    request = info_repository.InfoRepositoryUsageReferencesRequest(
        sourceUri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main?version=inactive#start=1,1",
        startLine=29,
        startColumn=10,
    )

    result = info_repository._build_usage_reference_source_uri(request)

    assert result == "/sap/bc/adt/programs/programs/yjrs_r0001/source/main?version=inactive#start=29,10;end=29,10"


def test_parse_usage_references_response_extracts_object_identifier():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<usageReferences:usageReferenceResult numberOfResults="1" resultDescription="[A4H] Where-Used List: YJRS_R0001 - IV_PROGRAM (Field)" referencedObjectIdentifier="ABAPFullName;\\PR:YJRS_R0001\\DA:IV_PROGRAM" xmlns:usageReferences="http://www.sap.com/adt/ris/usageReferences">
  <usageReferences:referencedObjects>
    <usageReferences:referencedObject uri="/sap/bc/adt/packages/%24tmp" isResult="false" canHaveChildren="true">
      <usageReferences:adtObject adtcore:responsible="DEVELOPER" adtcore:name="$TMP" adtcore:type="DEVC/K" xmlns:adtcore="http://www.sap.com/adt/core">
        <adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/%24tmp" adtcore:type="DEVC/K" adtcore:name="$TMP"/>
      </usageReferences:adtObject>
    </usageReferences:referencedObject>
    <usageReferences:referencedObject uri="/sap/bc/adt/programs/programs/yjrs_r0001" parentUri="/sap/bc/adt/packages/%24tmp" isResult="false" canHaveChildren="true" usageInformation="gradeDirect,includeProductive">
      <usageReferences:adtObject adtcore:responsible="DEVELOPER" adtcore:name="YJRS_R0001" adtcore:type="PROG/P" xmlns:adtcore="http://www.sap.com/adt/core">
        <adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/%24tmp" adtcore:type="DEVC/K" adtcore:name="$TMP"/>
      </usageReferences:adtObject>
      <objectIdentifier>ABAPFullName;YJRS_R0001;YJRS_R0001;\\PR:YJRS_R0001\\TY:LCL_DYNPRO_READER\\ME:READ_DYNPROS\\DA:IV_PROGRAM;2</objectIdentifier>
    </usageReferences:referencedObject>
  </usageReferences:referencedObjects>
</usageReferences:usageReferenceResult>"""

    response = info_repository.parse_info_repository_usage_references_response(DummyResponse())

    assert response.result is True
    assert response.data.numberOfResults == 1
    assert response.data.referencedObjects[1].name == "YJRS_R0001"
    assert response.data.referencedObjects[1].packageName == "$TMP"
    assert response.data.objectIdentifiers == [
        "ABAPFullName;YJRS_R0001;YJRS_R0001;\\PR:YJRS_R0001\\TY:LCL_DYNPRO_READER\\ME:READ_DYNPROS\\DA:IV_PROGRAM;2"
    ]


def test_build_usage_snippets_payload_includes_identifiers():
    request = info_repository.InfoRepositoryUsageSnippetsRequest(
        objectIdentifiers=[
            info_repository.InfoRepositoryUsageSnippetIdentifier(
                objectIdentifier="ABAPFullName;YJRS_R0001;YJRS_R0001;\\PR:YJRS_R0001\\DA:IV_PROGRAM;2"
            )
        ]
    )

    payload = info_repository._build_usage_snippets_payload(request)

    assert "usageSnippetRequest" in payload
    assert 'optional="false"' in payload
    assert "ABAPFullName;YJRS_R0001;YJRS_R0001;" in payload


def test_parse_usage_snippets_response_extracts_code_snippets():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<usageReferences:usageSnippetResult xmlns:usageReferences="http://www.sap.com/adt/ris/usageReferences">
  <usageReferences:codeSnippetObjects>
    <usageReferences:codeSnippetObject>
      <objectIdentifier>ABAPFullName;YJRS_R0001;YJRS_R0001;\\PR:YJRS_R0001\\DA:IV_PROGRAM;2</objectIdentifier>
      <usageReferences:codeSnippets>
        <usageReferences:codeSnippet uri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=47,19;end=47,29" matches="19-29,accessRead,gradeDirect">
          <content>        progname = iv_program</content>
          <description>Usage Kind: direct usage, read access</description>
        </usageReferences:codeSnippet>
        <usageReferences:codeSnippet uri="/sap/bc/adt/programs/programs/yjrs_r0001/source/main#start=125,4;end=125,14" matches="4-14,accessUnknown,gradeDirect">
          <content>    iv_program = p_prog</content>
          <description>Usage Kind: direct usage</description>
        </usageReferences:codeSnippet>
      </usageReferences:codeSnippets>
    </usageReferences:codeSnippetObject>
  </usageReferences:codeSnippetObjects>
</usageReferences:usageSnippetResult>"""

    response = info_repository.parse_info_repository_usage_snippets_response(DummyResponse())

    assert response.result is True
    assert response.data.totalCount == 2
    assert response.data.codeSnippetObjects[0].totalCount == 2
    assert response.data.codeSnippetObjects[0].codeSnippets[0].matches == "19-29,accessRead,gradeDirect"
    assert "iv_program" in response.data.codeSnippetObjects[0].codeSnippets[1].content
