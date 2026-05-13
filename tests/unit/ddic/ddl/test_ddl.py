from ddic.ddl import ddl


def test_build_ddl_source_create_payload_contains_core_metadata():
    payload = ddl._build_ddl_source_create_payload(
        name="YCDX_CDS_TEST",
        description="Test CDS view",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
    )

    assert 'adtcore:name="YCDX_CDS_TEST"' in payload
    assert 'adtcore:description="Test CDS view"' in payload
    assert 'adtcore:type="DDLS/DF"' in payload
    assert 'adtcore:packageRef' in payload
    assert 'adtcore:responsible="DEVELOPER"' in payload
    assert 'adtcore:language="EN"' in payload
    assert 'adtcore:masterLanguage="EN"' in payload


def test_build_ddl_source_create_payload_uses_ddlsources_namespace():
    payload = ddl._build_ddl_source_create_payload(
        name="YCDX_CDS_TEST",
        description="Test",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
    )

    assert 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"' in payload
    assert 'ddl:ddlSource' in payload
    assert 'xmlns:adtcore="http://www.sap.com/adt/core"' in payload


def test_build_ddl_source_create_payload_sets_package_ref():
    payload = ddl._build_ddl_source_create_payload(
        name="YCDX_CDS_TEST",
        description="Test",
        package_name="ZCDX_PKG",
        responsible="DEVELOPER",
        language="DE",
    )

    assert 'adtcore:name="ZCDX_PKG"' in payload
    assert 'adtcore:language="DE"' in payload


def test_build_ddl_source_create_payload_includes_master_system_when_provided():
    payload = ddl._build_ddl_source_create_payload(
        name="YCDX_CDS_TEST",
        description="Test",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
        master_system="A4H",
    )

    assert 'adtcore:masterSystem="A4H"' in payload


def test_build_ddl_source_create_payload_omits_master_system_when_empty():
    payload = ddl._build_ddl_source_create_payload(
        name="YCDX_CDS_TEST",
        description="Test",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
    )

    assert "masterSystem" not in payload


def test_parse_bool_supports_abap_flags_and_booleans():
    assert ddl._parse_bool(True) is True
    assert ddl._parse_bool(False) is False
    assert ddl._parse_bool("true") is True
    assert ddl._parse_bool("x") is True
    assert ddl._parse_bool("X") is True
    assert ddl._parse_bool("false") is False
    assert ddl._parse_bool("") is False
