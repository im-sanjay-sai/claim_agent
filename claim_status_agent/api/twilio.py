from __future__ import annotations

import os

from fastapi import HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

from claim_status_agent.voice.ivr_tools import normalize_initial_keypad_digits


class DialoutRequest(BaseModel):
    session_id: str
    to_number: str
    from_number: str
    initial_keypad_digits: str | None = None


class TwilioCallResult(BaseModel):
    call_sid: str
    to_number: str


class DialoutResponse(BaseModel):
    session_id: str
    call_sid: str | None
    status: str
    to_number: str


class TwimlRequest(BaseModel):
    session_id: str
    to_number: str | None = None
    from_number: str | None = None


async def dialout_request_from_request(request: Request) -> DialoutRequest:
    data = await request.json()
    try:
        dialout_request = DialoutRequest.model_validate(data)
        dialout_request.initial_keypad_digits = normalize_initial_keypad_digits(
            dialout_request.initial_keypad_digits
        )
        return dialout_request
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request data: {str(e)}")


def local_server_url() -> str:
    value = os.getenv("LOCAL_SERVER_URL")
    if not value:
        raise ValueError("Missing LOCAL_SERVER_URL")
    return value.rstrip("/")


async def make_twilio_call(dialout_request: DialoutRequest) -> TwilioCallResult:
    """Initiate an outbound call via Twilio API."""

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise ValueError("Missing Twilio credentials")

    base_url = local_server_url()
    twiml_url = f"{base_url}/twiml/{dialout_request.session_id}"
    status_callback_url = f"{base_url}/twilio/status"

    client = TwilioClient(account_sid, auth_token)
    call_args = {
        "to": dialout_request.to_number,
        "from_": dialout_request.from_number,
        "url": twiml_url,
        "method": "POST",
        "status_callback": status_callback_url,
        "status_callback_method": "POST",
        "status_callback_event": ["initiated", "ringing", "answered", "completed"],
    }

    initial_keypad_digits = normalize_initial_keypad_digits(dialout_request.initial_keypad_digits)
    if initial_keypad_digits:
        call_args["send_digits"] = initial_keypad_digits

    call = client.calls.create(**call_args)

    return TwilioCallResult(call_sid=call.sid, to_number=dialout_request.to_number)


async def parse_twiml_request(request: Request, session_id: str) -> TwimlRequest:
    form_data = await request.form()
    return TwimlRequest(
        session_id=session_id,
        to_number=form_data.get("To"),
        from_number=form_data.get("From"),
    )


def get_websocket_url() -> str:
    if os.getenv("ENV", "local").lower() == "local":
        ws_url = local_server_url().replace("https://", "wss://").replace("http://", "ws://")
        return f"{ws_url}/ws"

    logger.warning("If deployed outside us-west, update the Pipecat Cloud WebSocket URL.")
    return "wss://api.pipecat.daily.co/ws/twilio"


def generate_twiml(twiml_request: TwimlRequest) -> str:
    websocket_url = get_websocket_url()
    logger.debug(f"Generating TwiML with WebSocket URL: {websocket_url}")

    response = VoiceResponse()
    connect = Connect()
    stream_args = {"url": websocket_url}
    try:
        stream_args["status_callback"] = f"{local_server_url()}/twilio/stream-status"
        stream_args["status_callback_method"] = "POST"
    except ValueError:
        logger.warning("Missing LOCAL_SERVER_URL; Twilio stream status callback is disabled.")
    stream = Stream(**stream_args)

    stream.parameter(name="session_id", value=twiml_request.session_id)
    stream.parameter(name="ivr_mode", value="enabled")
    if twiml_request.to_number:
        stream.parameter(name="to_number", value=twiml_request.to_number)
    if twiml_request.from_number:
        stream.parameter(name="from_number", value=twiml_request.from_number)

    if os.getenv("ENV") == "production":
        agent_name = os.getenv("AGENT_NAME")
        org_name = os.getenv("ORGANIZATION_NAME")
        if agent_name and org_name:
            stream.parameter(name="_pipecatCloudServiceHost", value=f"{agent_name}.{org_name}")

    connect.append(stream)
    response.append(connect)
    response.pause(length=20)
    return str(response)
