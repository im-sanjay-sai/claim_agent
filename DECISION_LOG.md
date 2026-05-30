# Decision Log

## What I Built

- I built a local MVP for outbound claim-status calls to insurance payers.
- The agent can call a payer, handle a human or IVR, ask about submitted claims, and save structured results.
- I kept the call limit to 3 claims because that matches the take-home scope and is realistic for payer reps.
- I used 837-style claim data as the input and captured 835-like status/payment details as the output.

## EDI Data Flow

- I downloaded sample EDI data and used it as the claim source for testing.
- I wrote a Python parser in `claim_status_agent/claims/edi_parser.py` which uses the standard library for extracting EDI files.
- The parser normalizes provider, patient, member, payer, service date, charge, and service-line data.
- `claim_status_agent/claims/store.py` loads those parsed claims into `data/claims.json`.
- The UI reads from that claim store so a user can select claims before starting a call.

## UI

- I built a simple FastAPI static UI with HTML, CSS, and JavaScript.
- The Claims view shows parsed claims grouped by patient.
- The user can select up to 3 claims, enter payer/caller phone numbers, and start a call.
- The session panel shows call status, transcript, recordings, and structured results.
- The results area shows payer status, workflow status, payer claim number, payment fields, denial codes, reference number, and summary.
- The EDI view lets a user load sample 837 files, upload raw EDI, preview extracted claims, and save them.

## Voice Pipeline

- I used Twilio for outbound phone calls.
- I used Twilio Media Streams to send live call audio into the app over WebSocket.
- I used Pipecat to build the voice pipeline.
- The pipeline is:
  - Twilio audio input
  - OpenAI realtime STT
  - OpenAI LLM
  - Cartesia TTS
  - Twilio audio output
- `claim_status_agent/voice/bot.py` owns this live pipeline.
- `claim_status_agent/api/server.py` owns the Twilio webhooks, TwiML, dashboard APIs, and `/ws` media endpoint.

## Models

- `ClaimInput` stores normalized 837-style claim data.
- `ServiceLine` stores CPT/procedure and service-line details.
- `CallSession` stores the call state, selected claims, transcript, recordings, and results.
- `TranscriptEntry` stores system, representative, assistant, and tool turns.
- `ClaimStatusResult` stores 835-like extracted claim result fields.
- `ClaimCallOutcome` stores the agent's final per-claim outcome, including workflow status, payer status, summary, missing fields, and HIL reason.
- `CallRecording` stores metadata for local WAV recordings.

## Tool Calls

- I added `press_keypad` for IVR navigation.
- The agent uses it when an IVR asks the caller to press or enter digits.
- I added `record_claim_outcome` for final per-claim structured capture.
- The agent uses it after each claim discussion before moving to the next claim or ending the call.
- `record_claim_outcome` captures submitted claim ID, payer claim number, payer status, workflow status, payment fields, denial/remark codes, rep name, reference number, summary, and missing fields.


## Recordings

- I save local WAV recordings for each completed call.
- I save mixed audio, representative audio, and assistant audio.
- These recordings help a human review what happened in the call.
- They can also be used by another agent or evaluation workflow to analyze failures, compare TTS/STT behavior, and improve the call strategy over time.
- In a real product, these recordings would need PHI-safe storage, access controls, and retention rules.


- I kept the architecture modular so claim extraction, call flow, tools, and storage can be swapped later.

## Testing

- I added tests for claim normalization and EDI parsing.
- I added tests for TwiML generation and keypad validation.
- I added tests for local WAV recording helpers.
- I added tests for transcript extraction and claim outcome fallback.
- I manually verified that Twilio can call the number, connect to `/ws`, stream audio, transcribe speech, and play the assistant response.

## Improvements I Would Make Next

- I would improve observability using Pipecat metrics, traces, and richer pipeline event logging.
- I would add deeper monitoring around agent workflows: IVR path, claim lookup status, tool-call success, dropped calls, HIL reasons, and completion rate.
- I would add payer-specific workflows for verification order, IVR menus, status questions, and escalation rules.
- I would parallelize work where it makes sense, such as post-call extraction, recording upload, eval scoring, and session finalization.
- I would add replay-based evals using redacted audio recordings and transcripts.
- I would compare STT, LLM, and TTS providers against the same call fixtures before changing models.
- I would move storage to Postgres and add a background worker for reliable call finalization.
- I would add Twilio signature validation, dashboard auth, and PHI-safe logging before production use.
