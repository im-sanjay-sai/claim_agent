from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import ClaimInput, ServiceLine
from settings import claims_json_path


class ClaimStoreError(RuntimeError):
    pass


def _deep_get(data: dict[str, Any], dotted_key: str) -> Any:
    current: Any = data
    for part in dotted_key.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _pick(data: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = _deep_get(data, key)
        if value not in (None, ""):
            return value
    return default


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _service_lines(raw: Any) -> list[ServiceLine]:
    if not isinstance(raw, list):
        return []
    lines: list[ServiceLine] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        lines.append(
            ServiceLine(
                procedure_code=_pick(item, ["procedure_code", "procedureCode", "cpt", "service.procedureCode"]),
                modifier=_pick(item, ["modifier", "modifiers.0"]),
                date_of_service=_pick(item, ["date_of_service", "dateOfService", "service_date", "serviceDate"]),
                charged_amount=_to_float(_pick(item, ["charged_amount", "chargeAmount", "billed_amount"])),
                units=_to_float(_pick(item, ["units", "quantity"])),
            )
        )
    return lines


def normalize_claim(raw: dict[str, Any], index: int) -> ClaimInput:
    claim_id = str(
        _pick(
            raw,
            [
                "claim_id",
                "claimId",
                "claim_control_number",
                "claimControlNumber",
                "clm.claimSubmitterIdentifier",
                "patient_control_number",
            ],
            f"claim-{index + 1}",
        )
    )

    first_name = _pick(raw, ["patient_first_name", "patient.first_name", "patient.firstName", "subscriber.firstName"])
    last_name = _pick(raw, ["patient_last_name", "patient.last_name", "patient.lastName", "subscriber.lastName"])
    patient_name = _pick(raw, ["patient_name", "patient.name", "subscriber.name"], "")
    if (not first_name or not last_name) and patient_name:
        parts = str(patient_name).split()
        first_name = first_name or (parts[0] if parts else "")
        last_name = last_name or (" ".join(parts[1:]) if len(parts) > 1 else "")

    date_of_service = _pick(
        raw,
        [
            "date_of_service",
            "dateOfService",
            "service_date",
            "serviceDate",
            "service_lines.0.date_of_service",
            "serviceLines.0.dateOfService",
        ],
    )

    line_data = _pick(raw, ["service_lines", "serviceLines", "lines"], [])

    return ClaimInput(
        claim_id=claim_id,
        payer_name=str(_pick(raw, ["payer_name", "payer.name", "receiver.name"], "Unknown payer")),
        payer_phone=_pick(raw, ["payer_phone", "payer.phone", "receiver.phone"]),
        provider_name=_pick(raw, ["provider_name", "provider.name", "billing_provider.name"]),
        provider_npi=str(_pick(raw, ["provider_npi", "provider.npi", "billing_provider.npi", "billingProvider.npi"], "")),
        provider_tax_id=str(
            _pick(raw, ["provider_tax_id", "provider.tax_id", "billing_provider.taxId", "billingProvider.taxId"], "")
        ),
        patient_first_name=str(first_name or ""),
        patient_last_name=str(last_name or ""),
        patient_dob=str(_pick(raw, ["patient_dob", "patient.dob", "patient.dateOfBirth", "subscriber.dob"], "")),
        member_id=str(_pick(raw, ["member_id", "memberId", "subscriber.memberId", "patient.memberId"], "")),
        date_of_service=str(date_of_service or ""),
        billed_amount=_to_float(_pick(raw, ["billed_amount", "totalChargeAmount", "claim_amount", "claimAmount"])),
        service_lines=_service_lines(line_data),
        source=raw,
    )


class ClaimStore:
    def __init__(self, path: Path | None = None):
        self.path = path or claims_json_path()

    def list_claims(self) -> list[ClaimInput]:
        if not self.path.exists():
            raise ClaimStoreError(f"Claims JSON not found at {self.path}")

        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if isinstance(payload, dict):
            raw_claims = payload.get("claims", [])
        elif isinstance(payload, list):
            raw_claims = payload
        else:
            raise ClaimStoreError("Claims JSON must be a list or an object with a claims array")

        if not isinstance(raw_claims, list):
            raise ClaimStoreError("claims must be an array")

        return [normalize_claim(item, index) for index, item in enumerate(raw_claims) if isinstance(item, dict)]

    def get_claims(self, claim_ids: list[str]) -> list[ClaimInput]:
        claims_by_id = {claim.claim_id: claim for claim in self.list_claims()}
        missing = [claim_id for claim_id in claim_ids if claim_id not in claims_by_id]
        if missing:
            raise ClaimStoreError(f"Unknown claim ids: {', '.join(missing)}")
        return [claims_by_id[claim_id] for claim_id in claim_ids]
