from ddic.dataelements import dataelements


def test_parse_bool_supports_abap_flags_and_booleans():
    assert dataelements._parse_bool(True) is True
    assert dataelements._parse_bool(False) is False
    assert dataelements._parse_bool("true") is True
    assert dataelements._parse_bool("x") is True
    assert dataelements._parse_bool("false") is False


def test_build_dataelement_create_payload_contains_core_metadata():
    payload = dataelements._build_dataelement_create_payload(
        name="YCDX_TEST_DE",
        description="Test data element",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
    )

    assert 'adtcore:name="YCDX_TEST_DE"' in payload
    assert 'adtcore:description="Test data element"' in payload
    assert 'adtcore:type="DTEL/DE"' in payload
    assert 'adtcore:packageRef' in payload


def test_build_dataelement_update_payload_supports_builtin_and_labels():
    current_xml = """<?xml version="1.0" encoding="utf-8"?>
<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel" xmlns:adtcore="http://www.sap.com/adt/core" xmlns:dtel="http://www.sap.com/adt/ddic/dataelements" adtcore:name="YCDX_TEST_DE" adtcore:description="Old">
  <adtcore:packageRef adtcore:name="$TMP"/>
  <dtel:dataElement>
    <dtel:typeKind>predefinedAbapType</dtel:typeKind>
    <dtel:typeName></dtel:typeName>
    <dtel:dataType>CHAR</dtel:dataType>
    <dtel:dataTypeLength>4</dtel:dataTypeLength>
    <dtel:dataTypeDecimals>0</dtel:dataTypeDecimals>
    <dtel:shortFieldLabel>Old</dtel:shortFieldLabel>
    <dtel:shortFieldLength>4</dtel:shortFieldLength>
    <dtel:mediumFieldLabel>Old medium</dtel:mediumFieldLabel>
    <dtel:mediumFieldLength>10</dtel:mediumFieldLength>
  </dtel:dataElement>
</blue:wbobj>
"""

    updated = dataelements._build_dataelement_update_payload(
        current_xml,
        dataelements.DdicDataElementUpdateRequest(
            description="New",
            typeKind="predefinedAbapType",
            dataType="NUMC",
            dataTypeLength=10,
            shortFieldLabel="Clave",
            shortFieldLength=5,
            mediumFieldLabel="Clave media",
            mediumFieldLength=11,
            deactivateInputHistory=True,
        ),
    )

    assert 'adtcore:description="New"' in updated
    assert "<dtel:dataType>NUMC</dtel:dataType>" in updated
    assert "<dtel:dataTypeLength>10</dtel:dataTypeLength>" in updated
    assert "<dtel:shortFieldLabel>Clave</dtel:shortFieldLabel>" in updated
    assert "<dtel:deactivateInputHistory>true</dtel:deactivateInputHistory>" in updated


def test_build_dataelement_update_payload_supports_domain_reference():
    current_xml = """<?xml version="1.0" encoding="utf-8"?>
<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel" xmlns:adtcore="http://www.sap.com/adt/core" xmlns:dtel="http://www.sap.com/adt/ddic/dataelements" adtcore:name="YCDX_TEST_DE" adtcore:description="Old">
  <adtcore:packageRef adtcore:name="$TMP"/>
  <dtel:dataElement>
    <dtel:typeKind>predefinedAbapType</dtel:typeKind>
    <dtel:typeName></dtel:typeName>
    <dtel:dataType>CHAR</dtel:dataType>
    <dtel:dataTypeLength>4</dtel:dataTypeLength>
    <dtel:dataTypeDecimals>0</dtel:dataTypeDecimals>
  </dtel:dataElement>
</blue:wbobj>
"""

    updated = dataelements._build_dataelement_update_payload(
        current_xml,
        dataelements.DdicDataElementUpdateRequest(
            typeKind="domain",
            typeName="YCDX_DOMAIN",
        ),
    )

    assert "<dtel:typeKind>domain</dtel:typeKind>" in updated
    assert "<dtel:typeName>YCDX_DOMAIN</dtel:typeName>" in updated
