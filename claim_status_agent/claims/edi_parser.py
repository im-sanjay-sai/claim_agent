from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from claim_status_agent.core.models import ClaimInput, ServiceLine


class EdiParseError(RuntimeError):
    pass


@dataclass
class EdiDocument:
    segments: list[list[str]]
    element_separator: str = "*"
    component_separator: str = ":"
    segment_terminator: str = "~"


@dataclass
class PersonClaimGroup:
    patient_key: str
    patient_name: str
    patient_dob: str
    member_id: str
    claims: list[ClaimInput] = field(default_factory=list)


@dataclass
class Edi837ParseResult:
    claims: list[ClaimInput]
    people: list[PersonClaimGroup]
    warnings: list[str] = field(default_factory=list)


def _value(segment: list[str], index: int, default: str = "") -> str:
    if index >= len(segment):
        return default
    return segment[index].strip()


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _date(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    if "-" in raw and raw[:8].isdigit():
        raw = raw.split("-", 1)[0]
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return value.strip() or None


def _segment_text(segment: list[str]) -> str:
    return "*".join(segment)


def _detect_segment_terminator(text: str) -> str:
    isa_index = text.find("ISA")
    if isa_index >= 0 and len(text) > isa_index + 105:
        candidate = text[isa_index + 105]
        if candidate not in {"\r", "\n", " ", "\t"}:
            return candidate
    return "~"


def parse_edi_document(text: str) -> EdiDocument:
    if "ST" not in text:
        raise EdiParseError("EDI content does not look like an X12 transaction.")

    segment_terminator = _detect_segment_terminator(text)
    raw_segments = [
        raw.strip().replace("\n", "").replace("\r", "")
        for raw in text.split(segment_terminator)
        if raw.strip()
    ]
    if not raw_segments:
        raise EdiParseError("No EDI segments found.")

    element_separator = raw_segments[0][3] if raw_segments[0].startswith("ISA") and len(raw_segments[0]) > 3 else "*"
    isa_parts = raw_segments[0].split(element_separator)
    component_separator = (
        isa_parts[16][0]
        if raw_segments[0].startswith("ISA") and len(isa_parts) > 16 and isa_parts[16]
        else ":"
    )
    segments = [raw.split(element_separator) for raw in raw_segments]
    return EdiDocument(
        segments=segments,
        element_separator=element_separator,
        component_separator=component_separator,
        segment_terminator=segment_terminator,
    )


def _transactions(segments: list[list[str]]) -> list[list[list[str]]]:
    transactions: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for segment in segments:
        tag = _value(segment, 0)
        if tag == "ST":
            if current:
                transactions.append(current)
            current = [segment]
            continue
        if current is not None:
            current.append(segment)
            if tag == "SE":
                transactions.append(current)
                current = None
    if current:
        transactions.append(current)
    return transactions


def _per_phone(segment: list[str]) -> str | None:
    for index in range(3, len(segment) - 1, 2):
        if _value(segment, index).upper() in {"TE", "WP", "CP"}:
            phone = _phone(_value(segment, index + 1))
            if phone:
                return phone
    return None


def _nm1_person(segment: list[str]) -> dict[str, str]:
    return {
        "last_name": _value(segment, 3),
        "first_name": _value(segment, 4),
        "middle_name": _value(segment, 5),
        "member_id": _value(segment, 9) if _value(segment, 8).upper() in {"MI", "II"} else "",
        "dob": "",
    }


def _nm1_name(segment: list[str]) -> str:
    entity_type = _value(segment, 2)
    if entity_type == "1":
        parts = [_value(segment, 4), _value(segment, 5), _value(segment, 3)]
        return " ".join(part for part in parts if part).strip()
    return _value(segment, 3)


def _nm1_identifier(segment: list[str], qualifiers: set[str]) -> str:
    if _value(segment, 8).upper() in qualifiers:
        return _value(segment, 9)
    return ""


def _service_line_from_sv1(segment: list[str], component_separator: str) -> dict[str, Any]:
    procedure_components = _value(segment, 1).split(component_separator)
    procedure_code = procedure_components[1] if len(procedure_components) > 1 else _value(segment, 1)
    modifier = procedure_components[2] if len(procedure_components) > 2 else None
    return {
        "procedure_code": procedure_code,
        "modifier": modifier,
        "charged_amount": _to_float(_value(segment, 2)),
        "units": _to_float(_value(segment, 4)),
        "source_segment": _segment_text(segment),
    }


def _service_line_from_sv2(segment: list[str], component_separator: str) -> dict[str, Any]:
    procedure_components = _value(segment, 2).split(component_separator)
    procedure_code = _value(segment, 1)
    modifier = None
    if len(procedure_components) > 1:
        procedure_code = procedure_components[1]
        modifier = procedure_components[2] if len(procedure_components) > 2 else None
    return {
        "procedure_code": procedure_code,
        "modifier": modifier,
        "charged_amount": _to_float(_value(segment, 3)),
        "units": _to_float(_value(segment, 5)),
        "source_segment": _segment_text(segment),
    }


def _group_claims_by_patient(claims: list[ClaimInput]) -> list[PersonClaimGroup]:
    groups: dict[str, PersonClaimGroup] = {}
    for claim in claims:
        patient_key = "|".join(
            [
                claim.member_id,
                claim.patient_dob,
                claim.patient_last_name.upper(),
                claim.patient_first_name.upper(),
            ]
        )
        if patient_key not in groups:
            groups[patient_key] = PersonClaimGroup(
                patient_key=patient_key,
                patient_name=claim.patient_name,
                patient_dob=claim.patient_dob,
                member_id=claim.member_id,
            )
        groups[patient_key].claims.append(claim)
    return list(groups.values())


def parse_837_claims(
    text: str,
    *,
    source_file: str | None = None,
    payer_name: str | None = None,
    payer_phone: str | None = None,
) -> Edi837ParseResult:
    document = parse_edi_document(text)
    claims: list[ClaimInput] = []
    warnings: list[str] = []

    for transaction in _transactions(document.segments):
        if len(transaction[0]) < 2 or transaction[0][1] != "837":
            continue

        provider = {"name": "", "npi": "", "tax_id": ""}
        subscriber: dict[str, str] = {}
        patient: dict[str, str] | None = None
        payer = {"name": "", "phone": payer_phone or ""}
        fallback_phone = payer_phone
        subscriber_payer_name = ""
        last_entity = ""
        current_claim: dict[str, Any] | None = None
        current_line: dict[str, Any] | None = None
        transaction_segment = _segment_text(transaction[0])

        def finalize_claim() -> None:
            nonlocal current_claim, current_line
            if not current_claim:
                return

            service_lines = current_claim["service_lines"]
            if not current_claim["date_of_service"]:
                for line in service_lines:
                    if line.get("date_of_service"):
                        current_claim["date_of_service"] = line["date_of_service"]
                        break

            if current_claim["billed_amount"] is None:
                amounts = [line.get("charged_amount") for line in service_lines]
                numeric_amounts = [amount for amount in amounts if isinstance(amount, (int, float))]
                if numeric_amounts:
                    current_claim["billed_amount"] = sum(numeric_amounts)

            try:
                claims.append(
                    ClaimInput(
                        claim_id=current_claim["claim_id"],
                        payer_name=current_claim["payer_name"] or "Unknown payer",
                        payer_phone=current_claim["payer_phone"] or None,
                        provider_name=current_claim["provider_name"] or None,
                        provider_npi=current_claim["provider_npi"] or "",
                        provider_tax_id=current_claim["provider_tax_id"] or "",
                        patient_first_name=current_claim["patient_first_name"] or "",
                        patient_last_name=current_claim["patient_last_name"] or "",
                        patient_dob=current_claim["patient_dob"] or "",
                        member_id=current_claim["member_id"] or "",
                        date_of_service=current_claim["date_of_service"] or "",
                        billed_amount=current_claim["billed_amount"],
                        service_lines=[ServiceLine(**line) for line in service_lines],
                        source=current_claim["source"],
                    )
                )
            except Exception as exc:
                warnings.append(f"Skipped claim {current_claim.get('claim_id') or '<missing>'}: {exc}")
            current_claim = None
            current_line = None

        for segment in transaction[1:]:
            tag = _value(segment, 0)

            if tag in {"HL", "CLM"}:
                finalize_claim()

            if tag == "NM1":
                entity = _value(segment, 1)
                if entity == "85":
                    provider = {
                        "name": _nm1_name(segment),
                        "npi": _nm1_identifier(segment, {"XX"}),
                        "tax_id": provider.get("tax_id", ""),
                    }
                    last_entity = "billing_provider"
                elif entity == "IL":
                    subscriber = _nm1_person(segment)
                    patient = None
                    last_entity = "subscriber"
                elif entity == "QC":
                    patient = _nm1_person(segment)
                    last_entity = "patient"
                elif entity == "PR":
                    payer["name"] = _nm1_name(segment)
                    last_entity = "payer"
                else:
                    last_entity = entity
                continue

            if tag == "SBR":
                subscriber_payer_name = _value(segment, 4)
                continue

            if tag == "REF":
                qualifier = _value(segment, 1)
                if qualifier in {"EI", "TJ"} and last_entity == "billing_provider":
                    provider["tax_id"] = _value(segment, 2)
                elif qualifier == "6R" and current_line is not None:
                    current_line["line_control_number"] = _value(segment, 2)
                continue

            if tag == "PER":
                phone = _per_phone(segment)
                if phone and not fallback_phone:
                    fallback_phone = phone
                continue

            if tag == "DMG":
                target = patient if last_entity == "patient" and patient is not None else subscriber
                if target is not None:
                    target["dob"] = _date(_value(segment, 2))
                continue

            if tag == "CLM":
                person = patient or subscriber
                claim_id = _value(segment, 1)
                if not claim_id:
                    warnings.append(f"Skipped CLM segment without claim id in {transaction_segment}.")
                    continue
                current_claim = {
                    "claim_id": claim_id,
                    "payer_name": payer_name or payer["name"] or subscriber_payer_name or "Unknown payer",
                    "payer_phone": payer_phone or payer["phone"] or fallback_phone,
                    "provider_name": provider["name"],
                    "provider_npi": provider["npi"],
                    "provider_tax_id": provider["tax_id"],
                    "patient_first_name": person.get("first_name", ""),
                    "patient_last_name": person.get("last_name", ""),
                    "patient_dob": person.get("dob", ""),
                    "member_id": person.get("member_id", "") or subscriber.get("member_id", ""),
                    "date_of_service": "",
                    "billed_amount": _to_float(_value(segment, 2)),
                    "service_lines": [],
                    "source": {
                        "source_file": source_file,
                        "source_transaction": transaction_segment,
                        "source_claim_segment": _segment_text(segment),
                        "parser": "deterministic_837",
                    },
                }
                current_line = None
                continue

            if tag in {"SV1", "SV2"} and current_claim is not None:
                current_line = (
                    _service_line_from_sv1(segment, document.component_separator)
                    if tag == "SV1"
                    else _service_line_from_sv2(segment, document.component_separator)
                )
                current_claim["service_lines"].append(current_line)
                continue

            if tag == "DTP" and current_claim is not None:
                qualifier = _value(segment, 1)
                parsed_date = _date(_value(segment, 3))
                if qualifier == "472" and current_line is not None:
                    current_line["date_of_service"] = parsed_date
                elif qualifier in {"472", "434", "435", "454", "304"} and not current_claim["date_of_service"]:
                    current_claim["date_of_service"] = parsed_date

        finalize_claim()

    if not claims:
        raise EdiParseError("No 837 claims were found in the uploaded EDI file.")

    return Edi837ParseResult(
        claims=claims,
        people=_group_claims_by_patient(claims),
        warnings=warnings,
    )


def person_groups_to_json(groups: list[PersonClaimGroup]) -> list[dict[str, Any]]:
    return [
        {
            "patient_key": group.patient_key,
            "patient_name": group.patient_name,
            "patient_dob": group.patient_dob,
            "member_id": group.member_id,
            "claim_count": len(group.claims),
            "claims": [claim.model_dump(mode="json") for claim in group.claims],
        }
        for group in groups
    ]
