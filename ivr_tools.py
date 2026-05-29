from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    FunctionCallResultProperties,
    OutputAudioRawFrame,
    OutputDTMFUrgentFrame,
)
from pipecat.services.llm_service import FunctionCallParams
from pydantic import BaseModel

from session_store import session_store

LIVE_KEYPAD_CHARS = set("0123456789*#wW,")
INITIAL_KEYPAD_CHARS = set("0123456789ABCDabcd*#wW,")


class KeypadPressResult(BaseModel):
    ok: bool
    digits: str | None = None
    error: str | None = None
    instruction: str | None = None


def keypad_tool_schema() -> FunctionSchema:
    return FunctionSchema(
        name="press_keypad",
        description=(
            "Send keypad tones to the IVR during the current call. Use this only when the "
            "automated phone system asks the caller to press or enter digits."
        ),
        properties={
            "digits": {
                "type": "string",
                "description": (
                    "The keypad sequence to send now. Allowed live-call characters are 0-9, *, "
                    "#, and optional pauses with w or W. Use w for a short pause and W for a "
                    "longer pause between digit groups."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Brief reason for the keypress, such as selecting claims status.",
            },
        },
        required=["digits", "reason"],
    )


def normalize_keypad_digits(
    value: str | None,
    *,
    live_call: bool,
    max_length: int = 32,
) -> str | None:
    if value is None:
        return None

    normalized = "".join(str(value).split()).replace(",", "w")
    if not normalized:
        return None

    allowed = LIVE_KEYPAD_CHARS if live_call else INITIAL_KEYPAD_CHARS
    invalid = sorted({char for char in normalized if char not in allowed})
    if invalid:
        allowed_text = "0-9, *, #, w, W" if live_call else "0-9, A-D, *, #, w, W"
        raise ValueError(f"Invalid keypad character(s): {', '.join(invalid)}. Allowed: {allowed_text}.")

    if not live_call:
        if len(normalized) > max_length:
            raise ValueError(f"Initial keypad digits must be {max_length} characters or fewer.")
        normalized = "".join(
            char.upper() if char.lower() in {"a", "b", "c", "d"} else char
            for char in normalized
        )

    non_pause_chars = [char for char in normalized if char not in {"w", "W"}]
    if not non_pause_chars:
        raise ValueError("Keypad digits must include at least one non-pause character.")

    return normalized


def normalize_live_keypad_digits(value: str | None) -> str:
    normalized = normalize_keypad_digits(value, live_call=True, max_length=80)
    if not normalized:
        raise ValueError("Missing keypad digits.")
    return normalized


def normalize_initial_keypad_digits(value: str | None) -> str | None:
    return normalize_keypad_digits(value, live_call=False, max_length=32)


def _silence_frame(duration_ms: int, sample_rate: int) -> OutputAudioRawFrame:
    sample_count = int(sample_rate * (duration_ms / 1000))
    return OutputAudioRawFrame(
        audio=b"\x00\x00" * sample_count,
        sample_rate=sample_rate,
        num_channels=1,
    )


def keypad_frames(digits: str, *, sample_rate: int = 8000) -> list[Any]:
    normalized = normalize_live_keypad_digits(digits)
    frames: list[Any] = []
    pending_digits: list[str] = []

    def flush_digits() -> None:
        if pending_digits:
            frames.append(OutputDTMFUrgentFrame.from_string("".join(pending_digits)))
            pending_digits.clear()

    for char in normalized:
        if char in {"w", "W"}:
            flush_digits()
            frames.append(_silence_frame(1000 if char == "W" else 500, sample_rate))
            continue
        pending_digits.append(char)

    flush_digits()
    return frames


def make_press_keypad_handler(session_id: str):
    async def press_keypad(params: FunctionCallParams) -> None:
        raw_digits = params.arguments.get("digits")
        reason = str(params.arguments.get("reason") or "").strip()

        try:
            normalized = normalize_live_keypad_digits(str(raw_digits or ""))
            frames = keypad_frames(normalized)
        except ValueError as e:
            logger.warning(f"Rejected keypad tool call for session {session_id}: {e}")
            await params.result_callback(
                KeypadPressResult(ok=False, error=str(e)).model_dump(exclude_none=True)
            )
            return

        logger.info(f"Sending IVR keypad tones for session {session_id}: {normalized}")
        session_store.append_transcript(
            session_id,
            "tool",
            f"Pressed keypad {normalized}" + (f" for {reason}." if reason else "."),
        )

        await params.pipeline_worker.queue_frames(frames)
        await params.result_callback(
            KeypadPressResult(
                ok=True,
                digits=normalized,
                instruction="Wait for the IVR's next prompt before speaking or pressing more keys.",
            ).model_dump(exclude_none=True),
            properties=FunctionCallResultProperties(run_llm=False),
        )

    return press_keypad
