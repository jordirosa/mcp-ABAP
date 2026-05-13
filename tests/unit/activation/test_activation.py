from activation import activation


def test_derive_object_name_uses_last_uri_segment():
    assert activation._derive_object_name("/sap/bc/adt/programs/programs/ZFOO") == "ZFOO"


def test_build_activation_payload_includes_all_objects():
    payload = activation._build_activation_activate_payload(
        activation.ActivationActivateRequest(
            objects=[
                activation.ActivationObjectReference(uri="/sap/bc/adt/programs/programs/ZFOO"),
                activation.ActivationObjectReference(uri="/sap/bc/adt/programs/programs/ZBAR", name="BAR_ALIAS"),
            ],
            preauditRequested=True,
        )
    )

    assert 'adtcore:uri="/sap/bc/adt/programs/programs/ZFOO"' in payload
    assert 'adtcore:name="ZFOO"' in payload
    assert 'adtcore:name="BAR_ALIAS"' in payload


def test_parse_activation_response_detects_success_and_messages():
    class DummyResponse:
        status_code = 200
        reason = "OK"
        text = """<?xml version="1.0" encoding="utf-8"?>
<chkl:messages xmlns:chkl="http://www.sap.com/adt/checks" checkTitle="Activation">
  <chkl:properties checkExecuted="true" activationExecuted="true" generationExecuted="false"/>
  <msg type="S" line="1" objDescr="Program">
    <shortText><txt>Activated</txt></shortText>
  </msg>
</chkl:messages>"""

    response = activation.parse_activation_activate_response(DummyResponse())
    assert response.result is True
    assert response.data is not None
    assert response.data.checkExecuted is True
    assert response.data.activationExecuted is True
    assert response.data.messages[0]["text"] == "Activated"
