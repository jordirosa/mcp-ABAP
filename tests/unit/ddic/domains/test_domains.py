from ddic.domains import domains


def test_parse_bool_supports_abap_flags_and_booleans():
    assert domains._parse_bool(True) is True
    assert domains._parse_bool(False) is False
    assert domains._parse_bool("true") is True
    assert domains._parse_bool("x") is True
    assert domains._parse_bool("false") is False


def test_build_fix_values_payload_preserves_low_high_and_text():
    payload = domains._build_fix_values_payload([
        domains.DdicDomainFixValue(low="A", high="", text="Activo"),
        domains.DdicDomainFixValue(low="B", high="Z", text="Intervalo"),
    ])

    items = payload["doma:fixValue"]
    assert len(items) == 2
    assert items[0]["doma:low"] == "A"
    assert items[0]["doma:text"] == "Activo"
    assert items[1]["doma:high"] == "Z"


def test_build_domain_update_payload_replaces_output_and_fix_values():
    current_xml = """<?xml version="1.0" encoding="utf-8"?>
<doma:domain xmlns:doma="http://www.sap.com/dictionary/domain" xmlns:adtcore="http://www.sap.com/adt/core" adtcore:name="YCDX_TEST" adtcore:description="Old">
  <doma:content>
    <doma:typeInformation>
      <doma:datatype>CHAR</doma:datatype>
      <doma:length>4</doma:length>
      <doma:decimals>0</doma:decimals>
    </doma:typeInformation>
    <doma:outputInformation>
      <doma:length>4</doma:length>
      <doma:style></doma:style>
      <doma:conversionExit></doma:conversionExit>
      <doma:signExists>false</doma:signExists>
      <doma:lowercase>false</doma:lowercase>
      <doma:ampmFormat>false</doma:ampmFormat>
    </doma:outputInformation>
    <doma:valueInformation>
      <doma:valueTableRef adtcore:name="" />
      <doma:appendExists>false</doma:appendExists>
      <doma:fixValues>
        <doma:fixValue>
          <doma:low>X</doma:low>
          <doma:high></doma:high>
          <doma:text>Old</doma:text>
        </doma:fixValue>
      </doma:fixValues>
    </doma:valueInformation>
  </doma:content>
</doma:domain>
"""

    updated = domains._build_domain_update_payload(
        current_xml=current_xml,
        description="New",
        dataType="NUMC",
        length=10,
        outputLength=10,
        conversionExit="ALPHA",
        fixValues=[
            domains.DdicDomainFixValue(low="1", high="", text="Uno"),
            domains.DdicDomainFixValue(low="2", high="", text="Dos"),
        ],
    )

    assert "ALPHA" in updated
    assert "<doma:datatype>NUMC</doma:datatype>" in updated
    assert "<doma:text>Uno</doma:text>" in updated
    assert "<doma:text>Dos</doma:text>" in updated
    assert "Old" not in updated
