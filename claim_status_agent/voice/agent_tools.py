from __future__ import annotations

from typing import Literal

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from pydantic import BaseModel

from claim_status_agent.core.models import ClaimCallOutcome, ClaimInput, ClaimStatusResult, TranscriptEntry
from claim_status_agent.sessions.store import session_store

WorkflowStatus = Literal["completed", "stopped_in_middle", "failed_need_hil"]
PayerStatus = Literal["paid", "denied", "pending", "rejected", "not_found", "received", "unknown"]

WORKFLOW_STATUSES: tuple[WorkflowStatus, ...] = (
    "completed",
    "stopped_in_middle",
    "failed_need_hil",
)
PAYER_STATUSES: tuple[PayerStatus, ...] = (
    "paid",
    "denied",
    "pending",
    "rejected",
    "not_found",
    "received",
    "unknown",
)

WORKFLOW_STATUS_ALIASES: dict[str, WorkflowStatus] = {
    "complete": "completed",
    "completed": "completed",
    "done": "completed",
    "stopped": "stopped_in_middle",
    "stopped_in_middle": "stopped_in_middle",
    "stopped in middle": "stopped_in_middle",
    "partial": "stopped_in_middle",
    "incomplete": "stopped_in_middle",
    "failed": "failed_need_hil",
    "failed_need_hil": "failed_need_hil",
    "failed needs hil": "failed_need_hil",
    "failed need hil": "failed_need_hil",
    "needs hil": "failed_need_hil",
    "need hil": "failed_need_hil",
    "hil": "failed_need_hil",
}

PAYER_STATUS_ALIASES: dict[str, PayerStatus] = {
    "paid": "paid",
    "payment issued": "paid",
    "processed for payment": "paid",
    "denied": "denied",
    "denial": "denied",
    "pending": "pending",
    "in process": "pending",
    "processing": "pending",
    "under review": "pending",
    "rejected": "rejected",
    "not accepted": "rejected",
    "not found": "not_found",
    "no claim on file": "not_found",
    "not on file": "not_found",
    "received": "received",
    "on file": "received",
    "unknown": "unknown",
}


class ClaimOutcomeToolResult(BaseModel):
    ok: bool
    claim_id: str | None = None
    submitted_claim_id: str | None = None
    workflow_status: WorkflowStatus | None = None
    payer_status: PayerStatus | None = None
    summary: str | None = None
    error: str | None = None
    instruction: str | None = None


def claim_outcome_tool_schema(claim_ids: list[str]) -> FunctionSchema:
    return FunctionSchema(
        name="record_claim_outcome",
        description=(
            "Record the final workflow outcome and 835-like payer result for one submitted claim "
            "after the payer gives a result, refuses to continue, the call gets stuck, or the "
            "claim needs human follow-up."
        ),
        properties={
            "submitted_claim_id": {
                "type": "string",
                "enum": claim_ids,
                "description": "The submitted claim ID from the 837/CLM01 that this outcome applies to.",
            },
            "workflow_status": {
                "type": "string",
                "enum": list(WORKFLOW_STATUSES),
                "description": (
                    "completed means the payer provided enough claim-status details. "
                    "stopped_in_middle means the call ended or moved on before the claim was resolved. "
                    "failed_need_hil means automation cannot finish and a human must review or intervene."
                ),
            },
            "payer_status": {
                "type": "string",
                "enum": list(PAYER_STATUSES),
                "description": "The actual payer claim status, separate from workflow status.",
            },
            "payer_claim_number": {
                "type": "string",
                "description": "The payer's own claim number if different from the submitted claim ID.",
            },
            "allowed_amount": {"type": "number"},
            "paid_amount": {"type": "number"},
            "patient_responsibility": {"type": "number"},
            "denial_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "CARC/group denial codes mentioned by the payer.",
            },
            "remark_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "RARC or other remark codes mentioned by the payer.",
            },
            "payment_date": {"type": "string"},
            "check_or_eft_number": {"type": "string"},
            "rep_name": {"type": "string"},
            "reference_number": {"type": "string"},
            "next_action": {
                "type": "string",
                "description": "Any follow-up action needed from the billing team or payer.",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Plain-language summary of what happened for this claim, including the payer result, "
                    "missing fields, and why human review is needed if applicable."
                ),
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important 835-like fields the payer did not provide.",
            },
            "hil_reason": {
                "type": "string",
                "description": "Required when workflow_status is failed_need_hil.",
            },
        },
        required=["submitted_claim_id", "workflow_status", "payer_status", "summary"],
    )


def _normalized_label(value: str | None) -> str:
    normalized = "".join(
        char if char.isalnum() else " "
        for char in str(value or "").strip().lower()
    )
    return " ".join(normalized.split())


def normalize_workflow_status(value: str | None) -> WorkflowStatus:
    status = WORKFLOW_STATUS_ALIASES.get(_normalized_label(value))
    if not status:
        allowed = ", ".join(WORKFLOW_STATUSES)
        raise ValueError(f"Invalid workflow_status. Allowed values: {allowed}.")
    return status


def normalize_claim_outcome_status(value: str | None) -> WorkflowStatus:
    return normalize_workflow_status(value)


def normalize_payer_status(value: str | None) -> PayerStatus:
    status = PAYER_STATUS_ALIASES.get(_normalized_label(value))
    if not status:
        allowed = ", ".join(PAYER_STATUSES)
        raise ValueError(f"Invalid payer_status. Allowed values: {allowed}.")
    return status


def _clean_required_text(value: str | None, *, label: str, max_length: int = 1200) -> str:
    summary = " ".join(str(value or "").split())
    if not summary:
        raise ValueError(f"Missing {label}.")
    if len(summary) > max_length:
        return f"{summary[: max_length - 3].rstrip()}..."
    return summary


def _clean_optional_text(value: object, *, max_length: int = 300) -> str | None:
    if value in (None, ""):
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        return f"{cleaned[: max_length - 3].rstrip()}..."
    return cleaned


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError as e:
        raise ValueError(f"Invalid amount: {value}") from e


def _clean_list(value: object, *, max_items: int = 12) -> list[str]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    cleaned: list[str] = []
    for item in items:
        text = _clean_optional_text(item, max_length=80)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _missing_fields(outcome: ClaimCallOutcome) -> list[str]:
    missing = list(outcome.missing_fields)
    if outcome.payer_status == "unknown" and "payer_status" not in missing:
        missing.append("payer_status")
    if not outcome.reference_number and "reference_number" not in missing:
        missing.append("reference_number")
    return missing


def _meaningful_conversation(transcript: list[TranscriptEntry]) -> bool:
    return any(entry.role in {"rep", "assistant"} for entry in transcript)


def fallback_claim_outcome(
    claim: ClaimInput,
    result: ClaimStatusResult | None,
    *,
    has_conversation: bool,
) -> ClaimCallOutcome:
    if result and result.status != "unknown":
        workflow_status: WorkflowStatus = "completed" if not result.needs_review else "stopped_in_middle"
        payer_status = normalize_payer_status(result.status)
        summary = (
            "No live outcome tool call was recorded before disconnect. "
            f"Extractor found payer status {payer_status} for submitted claim {claim.claim_id}."
        )
    else:
        workflow_status = "stopped_in_middle" if has_conversation else "failed_need_hil"
        payer_status = "unknown"
        summary = (
            "No live outcome tool call was recorded before disconnect. "
            f"Submitted claim {claim.claim_id} was not resolved during the call."
        )

    outcome = ClaimCallOutcome(
        claim_id=claim.claim_id,
        submitted_claim_id=claim.claim_id,
        workflow_status=workflow_status,
        payer_status=payer_status,
        payer_claim_number=result.payer_claim_number if result else None,
        allowed_amount=result.allowed_amount if result else None,
        paid_amount=result.paid_amount if result else None,
        patient_responsibility=result.patient_responsibility if result else None,
        denial_codes=result.denial_codes if result else [],
        payment_date=result.payment_date if result else None,
        check_or_eft_number=result.check_or_eft_number if result else None,
        rep_name=result.rep_name if result else None,
        reference_number=result.reference_number if result else None,
        summary=summary,
        missing_fields=[],
        hil_reason=(
            "Call disconnected before any payer or assistant conversation was captured."
            if workflow_status == "failed_need_hil"
            else None
        ),
    )
    outcome.missing_fields = _missing_fields(outcome)
    return outcome


def save_missing_claim_outcomes(session_id: str, results: list[ClaimStatusResult]) -> int:
    session = session_store.get(session_id)
    recorded_claim_ids = {outcome.claim_id for outcome in session.claim_outcomes}
    results_by_claim = {result.claim_id: result for result in results}
    has_conversation = _meaningful_conversation(session.transcript)
    saved_count = 0

    for claim in session.claims:
        if claim.claim_id in recorded_claim_ids:
            continue
        outcome = fallback_claim_outcome(
            claim,
            results_by_claim.get(claim.claim_id),
            has_conversation=has_conversation,
        )
        session_store.save_claim_outcome(session_id, outcome)
        saved_count += 1

    if saved_count:
        session_store.append_transcript(
            session_id,
            "tool",
            f"Recorded fallback outcomes for {saved_count} unresolved claim(s) after disconnect.",
        )
    return saved_count


def make_record_claim_outcome_handler(session_id: str):
    async def record_claim_outcome(params: FunctionCallParams) -> None:
        raw_claim_id = params.arguments.get("submitted_claim_id") or params.arguments.get("claim_id")
        claim_id = str(raw_claim_id or "").strip()

        try:
            session = session_store.get(session_id)
            if claim_id not in session.claim_ids:
                raise ValueError(f"Unknown claim_id for this call: {claim_id}")

            workflow_status = normalize_workflow_status(
                str(params.arguments.get("workflow_status") or params.arguments.get("status_label") or "")
            )
            payer_status = normalize_payer_status(str(params.arguments.get("payer_status") or "unknown"))
            summary = _clean_required_text(
                str(params.arguments.get("summary") or ""),
                label="summary",
            )
            outcome = ClaimCallOutcome(
                claim_id=claim_id,
                submitted_claim_id=claim_id,
                workflow_status=workflow_status,
                payer_status=payer_status,
                payer_claim_number=_clean_optional_text(params.arguments.get("payer_claim_number")),
                allowed_amount=_optional_float(params.arguments.get("allowed_amount")),
                paid_amount=_optional_float(params.arguments.get("paid_amount")),
                patient_responsibility=_optional_float(params.arguments.get("patient_responsibility")),
                denial_codes=_clean_list(params.arguments.get("denial_codes")),
                remark_codes=_clean_list(params.arguments.get("remark_codes")),
                payment_date=_clean_optional_text(params.arguments.get("payment_date")),
                check_or_eft_number=_clean_optional_text(params.arguments.get("check_or_eft_number")),
                rep_name=_clean_optional_text(params.arguments.get("rep_name")),
                reference_number=_clean_optional_text(params.arguments.get("reference_number")),
                next_action=_clean_optional_text(params.arguments.get("next_action"), max_length=600),
                summary=summary,
                missing_fields=_clean_list(params.arguments.get("missing_fields")),
                hil_reason=_clean_optional_text(params.arguments.get("hil_reason"), max_length=600),
            )
            outcome.missing_fields = _missing_fields(outcome)
            if outcome.workflow_status == "failed_need_hil" and not outcome.hil_reason:
                raise ValueError("hil_reason is required when workflow_status is failed_need_hil.")
            session_store.save_claim_outcome(session_id, outcome)
        except ValueError as e:
            logger.warning(f"Rejected claim outcome tool call for session {session_id}: {e}")
            await params.result_callback(
                ClaimOutcomeToolResult(ok=False, error=str(e)).model_dump(exclude_none=True)
            )
            return

        logger.info(
            f"Recorded claim outcome for session {session_id}: {claim_id} "
            f"{workflow_status}/{payer_status}"
        )
        session_store.append_transcript(
            session_id,
            "tool",
            f"Recorded claim outcome for submitted claim {claim_id}: "
            f"{workflow_status}, payer status {payer_status}. Summary: {summary}",
        )
        await params.result_callback(
            ClaimOutcomeToolResult(
                ok=True,
                claim_id=claim_id,
                submitted_claim_id=claim_id,
                workflow_status=workflow_status,
                payer_status=payer_status,
                summary=summary,
                instruction="Continue to the next claim if any remain; otherwise close the call politely.",
            ).model_dump(exclude_none=True)
        )

    return record_claim_outcome
