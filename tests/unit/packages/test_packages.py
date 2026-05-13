from packages import packages


def test_normalize_package_name_uppercases_and_strips():
    assert packages._normalize_package_name(" zcdx_test ") == "ZCDX_TEST"


def test_package_object_uri_uses_lowercase_path():
    assert packages._package_object_uri("ZCDX_TEST") == "/sap/bc/adt/packages/zcdx_test"


def test_build_package_payload_contains_expected_metadata():
    payload = packages._build_package_payload(
        "A4H",
        name="ZCDX_TEST",
        description="Package test",
        language="EN",
        responsible="DEVELOPER",
        superPackageName="",
        packageType="development",
        isEncapsulated=True,
        softwareComponent="HOME",
        transportLayer="",
        applicationComponent="",
    )

    assert 'adtcore:name="ZCDX_TEST"' in payload
    assert 'adtcore:type="DEVC/K"' in payload
    assert 'pak:packageType="development"' in payload
    assert 'pak:isEncapsulated="true"' in payload
