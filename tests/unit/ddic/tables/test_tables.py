from ddic.tables import tables


def test_build_table_create_payload_contains_core_metadata():
    payload = tables._build_table_create_payload(
        name="YCDX_TABLE",
        description="Test table",
        package_name="$TMP",
        responsible="DEVELOPER",
        language="EN",
    )

    assert 'adtcore:name="YCDX_TABLE"' in payload
    assert 'adtcore:description="Test table"' in payload
    assert 'adtcore:type="TABL/DT"' in payload
    assert 'adtcore:packageRef' in payload


def test_parse_bool_supports_abap_flags_and_booleans():
    assert tables._parse_bool(True) is True
    assert tables._parse_bool(False) is False
    assert tables._parse_bool("true") is True
    assert tables._parse_bool("x") is True
    assert tables._parse_bool("false") is False
