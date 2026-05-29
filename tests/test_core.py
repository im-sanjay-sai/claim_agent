from claim_store import normalize_claim
from extractor import extract_claim_status_results
from ivr_tools import keypad_frames, normalize_initial_keypad_digits
from models import TranscriptEntry
from pipecat.frames.frames import OutputAudioRawFrame, OutputDTMFUrgentFrame
from server_utils import TwimlRequest, generate_twiml


def test_normalize_claim_from_nested_payload():
    claim = normalize_claim(
        {
            "claimControlNumber": "ABC123",
            "payer": {"name": "Example Health", "phone": "+15550001111"},
            "billingProvider": {"npi": "1234567890", "taxId": "12-3456789"},
            "patient": {
                "firstName": "Sam",
                "lastName": "Lee",
                "dateOfBirth": "1980-01-01",
                "memberId": "M001",
            },
            "serviceLines": [{"procedureCode": "99213", "dateOfService": "2026-04-01"}],
        },
        0,
    )

    assert claim.claim_id == "ABC123"
    assert claim.payer_name == "Example Health"
    assert claim.provider_npi == "1234567890"
    assert claim.member_id == "M001"
    assert claim.date_of_service == "2026-04-01"


def test_extract_claim_status_result():
    claim = normalize_claim(
        {
            "claim_id": "CLM-1",
            "payer_name": "Example Health",
            "provider_npi": "1234567890",
            "provider_tax_id": "12-3456789",
            "patient_first_name": "Sam",
            "patient_last_name": "Lee",
            "patient_dob": "1980-01-01",
            "member_id": "M001",
            "date_of_service": "2026-04-01",
        },
        0,
    )
    transcript = [
        TranscriptEntry(role="rep", text="My name is Alex Smith."),
        TranscriptEntry(
            role="rep",
            text="Claim CLM-1 was paid. Allowed amount is $100. Paid amount is $80. Reference number REF12345.",
        ),
    ]

    result = extract_claim_status_results([claim], transcript)[0]

    assert result.status == "paid"
    assert result.allowed_amount == 100
    assert result.paid_amount == 80
    assert result.reference_number == "REF12345"
    assert result.rep_name == "Alex Smith"


def test_generate_twiml_includes_session_id(monkeypatch):
    monkeypatch.setenv("ENV", "local")
    monkeypatch.setenv("LOCAL_SERVER_URL", "https://example.ngrok.io")

    twiml = generate_twiml(TwimlRequest(session_id="session-1", to_number="+1", from_number="+2"))

    assert "wss://example.ngrok.io/ws" in twiml
    assert 'name="session_id" value="session-1"' in twiml
    assert 'name="ivr_mode" value="enabled"' in twiml
    assert 'statusCallback="https://example.ngrok.io/twilio/stream-status"' in twiml


def test_keypad_frames_support_digits_and_pauses():
    frames = keypad_frames("1w2#")

    assert isinstance(frames[0], OutputDTMFUrgentFrame)
    assert frames[0].to_string() == "1"
    assert isinstance(frames[1], OutputAudioRawFrame)
    assert frames[1].sample_rate == 8000
    assert isinstance(frames[2], OutputDTMFUrgentFrame)
    assert frames[2].to_string() == "2#"


def test_keypad_digit_validation():
    assert normalize_initial_keypad_digits("w1234#a") == "w1234#A"

    try:
        keypad_frames("12x")
    except ValueError as e:
        assert "Invalid keypad" in str(e)
    else:
        raise AssertionError("Expected invalid keypad character to fail")
