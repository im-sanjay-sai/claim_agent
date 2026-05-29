from __future__ import annotations

import os

import uvicorn
from claim_store import ClaimStore, ClaimStoreError
from dotenv import load_dotenv
from extractor import extract_claim_status_results
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from ivr_tools import normalize_initial_keypad_digits
from loguru import logger
from models import CreateCallRequest, CreateCallResponse
from server_utils import (
    DialoutRequest,
    DialoutResponse,
    dialout_request_from_request,
    generate_twiml,
    make_twilio_call,
    parse_twiml_request,
)
from session_store import session_store
from settings import STATIC_DIR, dry_run_calls_enabled

load_dotenv(override=True)


app = FastAPI(title="Claim Status Voice Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
claim_store = ClaimStore()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/claims")
async def list_claims() -> dict:
    try:
        claims = claim_store.list_claims()
    except ClaimStoreError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"claims": [claim.model_dump(mode="json") for claim in claims]}


@app.get("/api/calls")
async def list_call_sessions() -> dict:
    sessions = session_store.list_sessions()
    return {"sessions": [session.model_dump(mode="json") for session in sessions]}


@app.get("/api/calls/{session_id}")
async def get_call_session(session_id: str) -> dict:
    try:
        session = session_store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump(mode="json")


@app.post("/api/calls", response_model=CreateCallResponse)
async def create_call(request: CreateCallRequest) -> CreateCallResponse:
    try:
        claims = claim_store.get_claims(request.claim_ids)
    except ClaimStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        initial_keypad_digits = normalize_initial_keypad_digits(request.initial_keypad_digits)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    payer_name = request.payer_name or claims[0].payer_name
    session = session_store.create(
        payer_name=payer_name,
        payer_phone=request.payer_phone,
        from_number=request.from_number,
        claims=claims,
        initial_keypad_digits=initial_keypad_digits,
    )

    if request.dry_run or dry_run_calls_enabled():
        session.status = "dry_run_ready"
        session_store.save(session)
        return CreateCallResponse(
            session_id=session.session_id,
            status=session.status,
            call_sid=None,
            payer_phone=session.payer_phone,
            claim_ids=session.claim_ids,
            initial_keypad_digits=session.initial_keypad_digits,
        )

    dialout_request = DialoutRequest(
        session_id=session.session_id,
        to_number=request.payer_phone,
        from_number=request.from_number,
        initial_keypad_digits=session.initial_keypad_digits,
    )

    try:
        call_result = await make_twilio_call(dialout_request)
    except Exception as e:
        session_store.set_status(session.session_id, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

    session_store.set_call_sid(session.session_id, call_result.call_sid)
    return CreateCallResponse(
        session_id=session.session_id,
        status="call_initiated",
        call_sid=call_result.call_sid,
        payer_phone=session.payer_phone,
        claim_ids=session.claim_ids,
        initial_keypad_digits=session.initial_keypad_digits,
    )


@app.post("/api/calls/{session_id}/finalize")
async def finalize_session(session_id: str) -> dict:
    try:
        session = session_store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    results = extract_claim_status_results(session.claims, session.transcript)
    session = session_store.save_results(session_id, results)
    return session.model_dump(mode="json")


@app.post("/dialout", response_model=DialoutResponse)
async def handle_dialout_request(request: Request) -> DialoutResponse:
    """Compatibility endpoint for direct API callers."""

    dialout_request = await dialout_request_from_request(request)
    try:
        call_result = await make_twilio_call(dialout_request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    session_store.set_call_sid(dialout_request.session_id, call_result.call_sid)
    return DialoutResponse(
        session_id=dialout_request.session_id,
        call_sid=call_result.call_sid,
        status="call_initiated",
        to_number=call_result.to_number,
    )


@app.post("/twiml/{session_id}")
async def get_twiml(session_id: str, request: Request) -> HTMLResponse:
    logger.info(f"Serving TwiML for session {session_id}")

    try:
        session_store.set_status(session_id, "twiml_requested")
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    twiml_request = await parse_twiml_request(request, session_id)
    twiml_content = generate_twiml(twiml_request)
    return HTMLResponse(content=twiml_content, media_type="application/xml")


@app.post("/twilio/status")
async def twilio_status_callback(request: Request) -> dict:
    form = await request.form()
    call_sid = str(form.get("CallSid") or "")
    call_status = str(form.get("CallStatus") or form.get("CallStatusCallbackEvent") or "unknown")

    if not call_sid:
        return {"ok": True}

    session = session_store.get_by_call_sid(call_sid)
    if not session:
        logger.warning(f"Received Twilio status for unknown call SID {call_sid}")
        return {"ok": True}

    if session.status != "completed":
        session.status = f"twilio_{call_status}"
        session_store.save(session)

    return {"ok": True}


@app.post("/twilio/stream-status")
async def twilio_stream_status_callback(request: Request) -> dict:
    form = await request.form()
    call_sid = str(form.get("CallSid") or "")
    stream_event = str(form.get("StreamEvent") or "unknown")
    stream_error = str(form.get("StreamError") or "")

    if not call_sid:
        return {"ok": True}

    session = session_store.get_by_call_sid(call_sid)
    if not session:
        logger.warning(f"Received Twilio stream status for unknown call SID {call_sid}")
        return {"ok": True}

    note = f"Twilio media stream {stream_event}."
    if stream_error:
        note = f"{note} {stream_error}"
    session_store.append_transcript(session.session_id, "system", note)

    if stream_event == "stream-error":
        session_store.set_status(session.session_id, "stream_error", stream_error or None)

    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from bot import bot
    from pipecat.runner.types import WebSocketRunnerArguments

    await websocket.accept()
    logger.info("WebSocket connection accepted for outbound claim-status call")

    try:
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        await bot(runner_args)
    except Exception as e:
        logger.error(f"Error in WebSocket endpoint: {e}")
        await websocket.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    logger.info(f"Starting claim-status voice agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
