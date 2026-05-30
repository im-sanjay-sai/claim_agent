from __future__ import annotations

import re

from claim_status_agent.core.models import ClaimInput, ClaimStatusResult, TranscriptEntry


STATUS_PATTERNS: list[tuple[str, str]] = [
    ("denied", r"\bdenied\b|\bdeny\b|\bdenial\b"),
    ("paid", r"\bpaid\b|\bpayment issued\b|\bprocessed for payment\b"),
    ("pending", r"\bpending\b|\bin process\b|\bprocessing\b|\bunder review\b"),
    ("rejected", r"\brejected\b|\bnot accepted\b"),
    ("not_found", r"\bnot found\b|\bno claim on file\b|\bnot on file\b|\bcannot locate\b"),
    ("received", r"\breceived\b|\bon file\b"),
]


def _money_after(label: str, text: str) -> float | None:
    pattern = rf"{label}[^.\n$0-9]{{0,40}}\$?([0-9][0-9,]*(?:\.[0-9]{{2}})?)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,:;")
    return None


def _claim_window(claim: ClaimInput, text: str) -> str:
    needles = [claim.claim_id, claim.member_id, claim.patient_last_name]
    lowered = text.lower()
    spans: list[str] = []
    for needle in needles:
        if not needle:
            continue
        index = lowered.find(str(needle).lower())
        if index >= 0:
            start = max(0, index - 900)
            end = min(len(text), index + 1600)
            spans.append(text[start:end])
    return "\n".join(spans) or text


def _status(text: str) -> tuple[str, float]:
    for status, pattern in STATUS_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return status, 0.7
    return "unknown", 0.2


def extract_claim_status_results(
    claims: list[ClaimInput],
    transcript: list[TranscriptEntry],
) -> list[ClaimStatusResult]:
    """Extract a pragmatic 835-like result from the saved transcript.

    This is intentionally deterministic for the take-home MVP. It is isolated so
    a stricter LLM or rules engine extractor can replace it later without
    changing Twilio or web code.
    """

    full_text = "\n".join(f"{entry.role}: {entry.text}" for entry in transcript)
    global_reference = _first_match(
        [
            r"(?:reference|ref|confirmation)\s*(?:number|#)?\s*(?:is|:)?\s*([A-Z0-9-]{4,})",
            r"\bcall\s*ref(?:erence)?\s*(?:is|:)?\s*([A-Z0-9-]{4,})",
        ],
        full_text,
    )
    global_rep = _first_match(
        [
            r"(?:my name is|this is|representative(?:'s)? name is|rep(?:resentative)? name is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"\brep(?:resentative)?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        ],
        full_text,
    )

    results: list[ClaimStatusResult] = []
    for claim in claims:
        window = _claim_window(claim, full_text)
        status, confidence = _status(window)
        denial_codes = re.findall(r"\b(?:CO|PR|OA|PI|CR|CARC|RARC)[ -]?[0-9A-Z]{1,5}\b", window, re.IGNORECASE)
        payer_claim_number = _first_match(
            [
                r"(?:payer claim|claim)\s*(?:number|#)?\s*(?:is|:)?\s*([A-Z0-9-]{5,})",
                r"\bclaim\s+([A-Z0-9-]{5,})\b",
            ],
            window,
        )
        reference_number = _first_match(
            [
                r"(?:reference|ref|confirmation)\s*(?:number|#)?\s*(?:is|:)?\s*([A-Z0-9-]{4,})",
                r"\bcall\s*ref(?:erence)?\s*(?:is|:)?\s*([A-Z0-9-]{4,})",
            ],
            window,
        ) or global_reference

        result = ClaimStatusResult(
            claim_id=claim.claim_id,
            status=status,
            payer_claim_number=payer_claim_number,
            allowed_amount=_money_after(r"(?:allowed|allowable)", window),
            paid_amount=_money_after(r"(?:paid|payment)", window),
            patient_responsibility=_money_after(r"(?:patient responsibility|patient owes|copay|coinsurance|deductible)", window),
            denial_codes=sorted({code.upper().replace(" ", "") for code in denial_codes}),
            payment_date=_first_match(
                [
                    r"(?:payment date|paid on|check date)\s*(?:is|:)?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
                    r"(?:payment date|paid on|check date)\s*(?:is|:)?\s*([A-Z][a-z]+ [0-9]{1,2},? [0-9]{4})",
                ],
                window,
            ),
            check_or_eft_number=_first_match(
                [r"(?:check|eft)\s*(?:number|#)?\s*(?:is|:)?\s*([A-Z0-9-]{4,})"],
                window,
            ),
            rep_name=global_rep,
            reference_number=reference_number,
            notes=window[-700:] if window else None,
            confidence=confidence,
            needs_review=status == "unknown" or reference_number is None,
        )
        results.append(result)

    return results
