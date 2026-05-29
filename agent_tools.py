from __future__ import annotations

from typing import Literal

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from pydantic import BaseModel

from models import ClaimCallOutcome
from session_store import session_store

ClaimOutcomeStatus = Literal["completed", "stopped_in_middle", "failed_need_hil"]

CLAIM_OUTCOME_STATUSES: tuple[ClaimOutcomeStatus, ...] = (
    "completed",
    "stopped_in_middle",
    "failed_need_hil",
)

STATUS_ALIASES: dict[str, ClaimOutcomeStatus] = {
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


class ClaimOutcomeToolResult(BaseModel):
    ok: bool
    claim_id: str | None = None
    status_label: ClaimOutcomeStatus | None = None
    summary: str | None = None
    error: str | None = None
    instruction: str | None = None


def claim_outcome_tool_schema(claim_ids: list[str]) -> FunctionSchema:
    return FunctionSchema(
        name="record_claim_outcome",
        description=(
            "Record the final workflow outcome for one claim after the payer gives a result, "
            "refuses to continue, the call gets stuck, or the claim needs human follow-up."
        ),
        properties={
            "claim_id": {
                "type": "string",
                "enum": claim_ids,
                "description": "The claim ID this outcome applies to.",
            },
            "status_label": {
                "type": "string",
                "enum": list(CLAIM_OUTCOME_STATUSES),
                "description": (
                    "completed means the payer provided enough claim-status details. "
                    "stopped_in_middle means the call ended or moved on before the claim was resolved. "
                    "failed_need_hil means automation cannot finish and a human must review or intervene."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Plain-language summary of what happened for this claim, including the payer result, "
                    "missing fields, and why human review is needed if applicable."
                ),
            },
        },
        required=["claim_id", "status_label", "summary"],
    )


def normalize_claim_outcome_status(value: str | None) -> ClaimOutcomeStatus:
    normalized = "".join(
        char if char.isalnum() else " "
        for char in str(value or "").strip().lower()
    )
    normalized = " ".join(normalized.split())
    status = STATUS_ALIASES.get(normalized)
    if not status:
        allowed = ", ".join(CLAIM_OUTCOME_STATUSES)
        raise ValueError(f"Invalid status_label. Allowed values: {allowed}.")
    return status


def _clean_summary(value: str | None, *, max_length: int = 1200) -> str:
    summary = " ".join(str(value or "").split())
    if not summary:
        raise ValueError("Missing summary.")
    if len(summary) > max_length:
        return f"{summary[: max_length - 3].rstrip()}..."
    return summary


def make_record_claim_outcome_handler(session_id: str):
    async def record_claim_outcome(params: FunctionCallParams) -> None:
        raw_claim_id = params.arguments.get("claim_id")
        claim_id = str(raw_claim_id or "").strip()

        try:
            session = session_store.get(session_id)
            if claim_id not in session.claim_ids:
                raise ValueError(f"Unknown claim_id for this call: {claim_id}")

            status_label = normalize_claim_outcome_status(
                str(params.arguments.get("status_label") or "")
            )
            summary = _clean_summary(str(params.arguments.get("summary") or ""))
            outcome = ClaimCallOutcome(
                claim_id=claim_id,
                status_label=status_label,
                summary=summary,
            )
            session_store.save_claim_outcome(session_id, outcome)
        except ValueError as e:
            logger.warning(f"Rejected claim outcome tool call for session {session_id}: {e}")
            await params.result_callback(
                ClaimOutcomeToolResult(ok=False, error=str(e)).model_dump(exclude_none=True)
            )
            return

        logger.info(
            f"Recorded claim outcome for session {session_id}: {claim_id} {status_label}"
        )
        session_store.append_transcript(
            session_id,
            "tool",
            f"Recorded claim outcome for {claim_id}: {status_label}. Summary: {summary}",
        )
        await params.result_callback(
            ClaimOutcomeToolResult(
                ok=True,
                claim_id=claim_id,
                status_label=status_label,
                summary=summary,
                instruction="Continue to the next claim if any remain; otherwise close the call politely.",
            ).model_dump(exclude_none=True)
        )

    return record_claim_outcome
