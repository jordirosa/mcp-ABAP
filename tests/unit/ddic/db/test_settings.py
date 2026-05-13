from ddic.db import settings


def test_build_db_settings_update_payload_replaces_selected_fields():
    current_xml = """<?xml version="1.0" encoding="utf-8"?>
<ts:tableSettings xmlns:ts="http://www.sap.com/adt/ddic/db/settings" xmlns:adtcore="http://www.sap.com/adt/core" adtcore:name="YCDX_TABLE">
  <adtcore:containerRef adtcore:uri="/sap/bc/adt/ddic/tables/ycdx_table" adtcore:type="TABL/DT" adtcore:name="YCDX_TABLE"/>
  <ts:dataClassCategory>APPL0</ts:dataClassCategory>
  <ts:sizeCategory>0</ts:sizeCategory>
  <ts:buffering>
    <ts:allowed>N</ts:allowed>
    <ts:type></ts:type>
    <ts:areaKeyFields>0</ts:areaKeyFields>
  </ts:buffering>
  <ts:storageType></ts:storageType>
  <ts:sharingType></ts:sharingType>
  <ts:loadUnit></ts:loadUnit>
  <ts:loggingEnabled>false</ts:loggingEnabled>
</ts:tableSettings>
"""

    updated = settings._build_db_settings_update_payload(
        current_xml,
        settings.DdicTableDbSettingsUpdateRequest(
            dataClassCategory="APPL1",
            sizeCategory="1",
            bufferingAllowed="N",
            storageType="C",
            sharingType="L",
            loggingEnabled=True,
        ),
    )

    assert "<ts:dataClassCategory>APPL1</ts:dataClassCategory>" in updated
    assert "<ts:sizeCategory>1</ts:sizeCategory>" in updated
    assert "<ts:storageType>C</ts:storageType>" in updated
    assert "<ts:sharingType>L</ts:sharingType>" in updated
    assert "<ts:loggingEnabled>true</ts:loggingEnabled>" in updated


def test_parse_bool_supports_abap_flags_and_booleans():
    assert settings._parse_bool(True) is True
    assert settings._parse_bool(False) is False
    assert settings._parse_bool("true") is True
    assert settings._parse_bool("x") is True
    assert settings._parse_bool("false") is False
