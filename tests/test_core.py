from pathlib import Path
import wave

from agent_tools import fallback_claim_outcome, normalize_claim_outcome_status, normalize_payer_status
from claim_store import ClaimStore
from claim_store import normalize_claim
from edi_parser import parse_837_claims
from extractor import extract_claim_status_results
from ivr_tools import (
    keypad_frames,
    keypad_tool_schema,
    normalize_initial_keypad_digits,
    wait_for_user_tool_schema,
)
from models import CallRecording, ClaimCallOutcome, ClaimStatusResult, CreateCallRequest, TranscriptEntry
from pipecat.frames.frames import OutputAudioRawFrame, OutputDTMFUrgentFrame
from prompt_builder import build_claim_call_system_prompt, build_initial_user_message
from recording_files import audio_duration_seconds, write_wav
from server_utils import TwimlRequest, generate_twiml
from session_store import SessionStore


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


def test_parse_raw_837_claims_grouped_by_patient():
    text = Path("sample/edi-claims/raw-837/databricks-chpw-claimdata.txt").read_text()

    result = parse_837_claims(text, source_file="databricks-chpw-claimdata.txt")

    assert len(result.claims) == 5
    assert len(result.people) == 2
    assert [(group.patient_name, len(group.claims)) for group in result.people] == [
        ("JOHN SUBSCRIBER", 3),
        ("SUSAN PATIENT", 2),
    ]
    first = result.claims[0]
    assert first.claim_id == "1805080AV3648339"
    assert first.payer_name == "COMMUNITY HEALTH PLAN OF WASHINGTON"
    assert first.payer_phone == "+18005551212"
    assert first.provider_npi == "1122334455"
    assert first.provider_tax_id == "720000000"
    assert first.date_of_service == "2018-04-28"
    assert first.service_lines[0].procedure_code == "H0003"


def test_parse_837_without_interchange_envelope():
    text = Path("sample/edi-claims/raw-837/databricks-837p.txt").read_text()
    snippet = text[text.index("ST*837") : text.index("SE*41*1239~") + len("SE*41*1239~")]

    result = parse_837_claims(snippet, source_file="snippet.edi")

    assert [claim.claim_id for claim in result.claims] == ["1000A", "1001A"]


def test_claim_store_upserts_claims(tmp_path):
    store = ClaimStore(tmp_path / "claims.json")
    claim = normalize_claim(
        {
            "claim_id": "CLM-UPSERT",
            "payer_name": "Original Health",
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

    created = store.upsert_claims([claim])
    updated_claim = claim.model_copy(update={"payer_name": "Updated Health"})
    updated = store.upsert_claims([updated_claim])

    assert created == {"created": 1, "updated": 0, "total": 1}
    assert updated == {"created": 0, "updated": 1, "total": 1}
    assert store.list_claims()[0].payer_name == "Updated Health"


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


def test_prompt_prevents_keypad_for_live_rep_and_unclear_audio():
    claim = normalize_claim(
        {
            "claim_id": "CLM-PROMPT",
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

    prompt = build_claim_call_system_prompt([claim], "Example Health")

    assert "If a live representative asks for NPI" in prompt
    assert "Do not call `press_keypad`" in prompt
    assert "Only call `press_keypad` when the latest speaker is an automated IVR" in prompt
    assert "If the payer or IVR audio is unclear" in prompt
    assert "call `wait_for_user` and do not speak" in prompt


def test_prompt_starts_with_opening_line():
    claim = normalize_claim(
        {
            "claim_id": "CLM-START",
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

    prompt = build_claim_call_system_prompt([claim], "Example Health")

    assert "When the call connects, start by saying the opening line once." in prompt
    assert "payer-facing claim status agent" in prompt
    assert build_initial_user_message() == "The call has connected. Say the opening line now."


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

    try:
        keypad_frames("1" * 81)
    except ValueError as e:
        assert "80 characters" in str(e)
    else:
        raise AssertionError("Expected overlong keypad sequence to fail")


def test_voice_control_tool_schemas_define_keypad_gate_and_wait_tool():
    keypad_schema = keypad_tool_schema()
    wait_schema = wait_for_user_tool_schema()

    assert keypad_schema.name == "press_keypad"
    assert "Never use this for a live representative" in keypad_schema.description
    assert wait_schema.name == "wait_for_user"
    assert wait_schema.required == []
    assert "without speaking or pressing keys" in wait_schema.description


def test_claim_outcome_status_validation():
    assert normalize_claim_outcome_status("completed") == "completed"
    assert normalize_claim_outcome_status("stopped in middle") == "stopped_in_middle"
    assert normalize_claim_outcome_status("failed") == "failed_need_hil"
    assert normalize_claim_outcome_status("failed (need HIL)") == "failed_need_hil"
    assert normalize_payer_status("no claim on file") == "not_found"

    try:
        normalize_claim_outcome_status("waiting")
    except ValueError as e:
        assert "Invalid workflow_status" in str(e)
    else:
        raise AssertionError("Expected invalid claim outcome status to fail")


def test_create_call_request_requires_e164_phone_numbers():
    request = CreateCallRequest(
        payer_phone=" +17167309413 ",
        from_number="+16506145449",
        claim_ids=["CLM-1"],
    )
    assert request.payer_phone == "+17167309413"

    try:
        CreateCallRequest(
            payer_phone="7167309413",
            from_number="+16506145449",
            claim_ids=["CLM-1"],
        )
    except ValueError as e:
        assert "E.164" in str(e)
    else:
        raise AssertionError("Expected non-E.164 phone number to fail")


def test_write_wav_creates_playable_local_recording(tmp_path):
    audio = b"\x01\x00" * 8000
    path = tmp_path / "recording.wav"

    write_wav(path, audio, sample_rate=8000, num_channels=1)

    assert audio_duration_seconds(audio, sample_rate=8000, num_channels=1) == 1.0
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 8000
        assert wav_file.getnframes() == 8000


def test_session_store_attaches_recording_to_transcript(tmp_path):
    claim = normalize_claim(
        {
            "claim_id": "CLM-REC",
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
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(
        payer_name="Example Health",
        payer_phone="+15550001111",
        from_number="+15550002222",
        claims=[claim],
    )
    recording = CallRecording(
        recording_id="mixed",
        track="mixed",
        label="Full call recording",
        file_name="mixed.wav",
        url=f"/api/calls/{session.session_id}/recordings/mixed",
        sample_rate=8000,
        num_channels=2,
        duration_seconds=1.0,
        size_bytes=32044,
    )

    saved = store.add_recording(session.session_id, recording)

    assert saved.recordings[0].recording_id == "mixed"
    assert saved.transcript[-1].recording_id == "mixed"
    assert "Local recording saved" in saved.transcript[-1].text


def test_session_store_saves_one_claim_outcome_per_claim(tmp_path):
    claim = normalize_claim(
        {
            "claim_id": "CLM-OUTCOME",
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
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(
        payer_name="Example Health",
        payer_phone="+15550001111",
        from_number="+15550002222",
        claims=[claim],
    )

    store.save_claim_outcome(
        session.session_id,
        ClaimCallOutcome(
            claim_id="CLM-OUTCOME",
            workflow_status="stopped_in_middle",
            payer_status="unknown",
            summary="The IVR looped before claim status was reached.",
        ),
    )
    saved = store.save_claim_outcome(
        session.session_id,
        ClaimCallOutcome(
            claim_id="CLM-OUTCOME",
            submitted_claim_id="CLM-OUTCOME",
            workflow_status="failed_need_hil",
            payer_status="unknown",
            summary="The payer required portal verification that the agent could not complete.",
            hil_reason="Portal verification was required.",
        ),
    )

    assert len(saved.claim_outcomes) == 1
    assert saved.claim_outcomes[0].submitted_claim_id == "CLM-OUTCOME"
    assert saved.claim_outcomes[0].workflow_status == "failed_need_hil"
    assert "portal verification" in saved.claim_outcomes[0].summary


def test_fallback_claim_outcome_uses_extracted_result_when_available():
    claim = normalize_claim(
        {
            "claim_id": "CLM-FALLBACK",
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
    result = ClaimStatusResult(
        claim_id="CLM-FALLBACK",
        status="paid",
        payer_claim_number="PAYER-123",
        paid_amount=80,
        reference_number="REF123",
        needs_review=False,
    )

    outcome = fallback_claim_outcome(claim, result, has_conversation=True)

    assert outcome.submitted_claim_id == "CLM-FALLBACK"
    assert outcome.workflow_status == "completed"
    assert outcome.payer_status == "paid"
    assert outcome.payer_claim_number == "PAYER-123"
    assert outcome.reference_number == "REF123"
