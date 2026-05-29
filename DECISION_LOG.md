# Decision Log

## Scoping Assumptions

- Parsed 837-style JSON can still be loaded directly, and raw 837 EDI files can now be imported through a deterministic parser. PDF parsing remains out of scope for this MVP.
- The MVP targets outbound calls to human reps and IVRs. Dynamic keypad automation is included for common payer menus.
- One call can include up to 3 claims because that is the assignment limit and matches payer rep tolerance.
- Local JSON session storage is acceptable for the take-home; production would use a database and queue.

## Key Decisions

- Kept the existing Twilio outbound and Pipecat Media Streams architecture because it already matches real outbound voice-agent requirements.
- Standardized STT and LLM inference on OpenAI to reduce provider surface area; Cartesia remains the TTS provider for now.
- Added minimal custom Twilio Stream parameters, then loaded claim data server-side to avoid sending full claim data through TwiML.
- Added an OpenAI `press_keypad` tool backed by Pipecat DTMF frames. Twilio bidirectional Media Streams do not accept outbound DTMF events, so the frame path emits keypad audio into the live stream.
- Added optional Twilio `send_digits` for known initial extensions or access codes immediately after answer.
- Used a no-build FastAPI static dashboard instead of React to keep the project mostly Python and quick to run locally.
- Kept raw 837 parsing deterministic and local in `edi_parser.py` instead of adding an external parser dependency, so claim imports are testable and easy to adapt to payer-specific samples.
- Isolated claim normalization, session persistence, prompt building, and transcript extraction into separate modules so later EDI/PDF ingestion can plug into `ClaimInput`.
- Used deterministic post-call extraction for the MVP. A stricter LLM schema extractor can replace `extractor.py` without touching the call flow.

## Next Steps

- Replace JSON file storage with Postgres and add a background worker for call finalization.
- Add LLM-based structured extraction with Pydantic schema validation and confidence/evidence spans.
- Add payer-specific playbooks for IVR paths, verification order, and claim-status questions.
- Add call recordings or redacted audio fixtures to validate IVR paths against representative payer menus.
- Add Twilio signature validation, auth on the dashboard, and PHI-safe logging.
- Build eval fixtures from representative transcripts and track extraction accuracy, call completion rate, latency, and rep escalation reasons.
