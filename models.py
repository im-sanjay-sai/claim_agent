from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    procedure_code: str | None = None
    modifier: str | None = None
    date_of_service: str | None = None
    charged_amount: float | None = None
    units: float | None = None


class ClaimInput(BaseModel):
    """Normalized subset of parsed 837 data needed for payer claim-status calls."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    payer_name: str = "Unknown payer"
    payer_phone: str | None = None
    provider_name: str | None = None
    provider_npi: str
    provider_tax_id: str
    patient_first_name: str
    patient_last_name: str
    patient_dob: str
    member_id: str
    date_of_service: str
    billed_amount: float | None = None
    service_lines: list[ServiceLine] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)

    @property
    def patient_name(self) -> str:
        return f"{self.patient_first_name} {self.patient_last_name}".strip()


class TranscriptEntry(BaseModel):
    role: Literal["assistant", "rep", "system", "tool"]
    text: str
    timestamp: datetime = Field(default_factory=utc_now)
    recording_id: str | None = None
    recording_track: str | None = None


class ClaimStatusResult(BaseModel):
    """835-like structured result captured from the payer conversation."""

    claim_id: str
    status: str = "unknown"
    payer_claim_number: str | None = None
    allowed_amount: float | None = None
    paid_amount: float | None = None
    patient_responsibility: float | None = None
    denial_codes: list[str] = Field(default_factory=list)
    payment_date: str | None = None
    check_or_eft_number: str | None = None
    rep_name: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    confidence: float = 0.0
    needs_review: bool = True


class CallRecording(BaseModel):
    """Local audio artifact captured from the Pipecat media pipeline."""

    recording_id: str
    track: Literal["mixed", "rep", "assistant"]
    label: str
    file_name: str
    url: str
    content_type: str = "audio/wav"
    sample_rate: int
    num_channels: int
    duration_seconds: float
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)


class CallSession(BaseModel):
    session_id: str
    status: str = "created"
    payer_name: str = "Unknown payer"
    payer_phone: str
    from_number: str
    initial_keypad_digits: str | None = None
    claim_ids: list[str]
    claims: list[ClaimInput]
    call_sid: str | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    results: list[ClaimStatusResult] = Field(default_factory=list)
    recordings: list[CallRecording] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CreateCallRequest(BaseModel):
    payer_phone: str
    from_number: str
    claim_ids: list[str] = Field(min_length=1, max_length=3)
    payer_name: str | None = None
    initial_keypad_digits: str | None = None
    dry_run: bool = False


class CreateCallResponse(BaseModel):
    session_id: str
    status: str
    call_sid: str | None = None
    payer_phone: str
    claim_ids: list[str]
    initial_keypad_digits: str | None = None
