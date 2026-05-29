from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from agent_tools import (
    claim_outcome_tool_schema,
    make_record_claim_outcome_handler,
    save_missing_claim_outcomes,
)
from extractor import extract_claim_status_results
from ivr_tools import keypad_tool_schema, make_press_keypad_handler
from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from prompt_builder import build_claim_call_system_prompt
from recordings import LocalCallRecorder
from session_store import session_store

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))


async def run_bot(transport: BaseTransport, handle_sigint: bool, session_id: str):
    session = session_store.get(session_id)
    system_prompt = build_claim_call_system_prompt(session.claims, session.payer_name)
    openai_api_key = os.getenv("OPENAI_API_KEY")
    recorder = LocalCallRecorder(session_id)

    llm = OpenAILLMService(
        api_key=openai_api_key,
        settings=OpenAILLMService.Settings(
            model=os.getenv("OPENAI_LLM_MODEL", "gpt-4.1-mini"),
            system_instruction=system_prompt,
        ),
    )
    llm.register_function("press_keypad", make_press_keypad_handler(session_id), timeout_secs=10)
    llm.register_function(
        "record_claim_outcome",
        make_record_claim_outcome_handler(session_id),
        timeout_secs=10,
    )

    stt = OpenAIRealtimeSTTService(
        api_key=openai_api_key,
        settings=OpenAIRealtimeSTTService.Settings(
            model=os.getenv("OPENAI_STT_MODEL", "gpt-realtime-whisper"),
            noise_reduction="near_field",
        ),
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        settings=CartesiaTTSService.Settings(
            voice=os.getenv("CARTESIA_VOICE_ID", "71a7ad14-091c-4e8e-a314-022ece01c121"),
        ),
    )

    tools = ToolsSchema(
        standard_tools=[
            keypad_tool_schema(),
            claim_outcome_tool_schema(session.claim_ids),
        ]
    )
    context = LLMContext(tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline_steps = [
        transport.input(),
        stt,
        user_aggregator,
        llm,
        tts,
        transport.output(),
    ]
    recording_processor = recorder.processor()
    if recording_processor:
        pipeline_steps.append(recording_processor)
    pipeline_steps.append(assistant_aggregator)

    pipeline = Pipeline(pipeline_steps)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Starting claim-status listener for session {session_id}")
        session_store.set_status(session_id, "in_progress")
        session_store.append_transcript(
            session_id,
            "system",
            "Twilio media stream connected; waiting for payer greeting or IVR prompt.",
        )
        await recorder.start()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Outbound call ended for session {session_id}")
        session_store.append_transcript(session_id, "system", "Twilio media stream disconnected.")
        await recorder.stop()
        current = session_store.get(session_id)
        results = extract_claim_status_results(current.claims, current.transcript)
        save_missing_claim_outcomes(session_id, results)
        session_store.save_results(session_id, results)
        await worker.cancel()

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
        logger.info(f"Rep: {message.content}")
        session_store.append_transcript(session_id, "rep", message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
        logger.info(f"Assistant: {message.content}")
        session_store.append_transcript(session_id, "assistant", message.content)

    runner = WorkerRunner(handle_sigint=handle_sigint)

    await runner.add_workers(worker)
    await runner.run()


def _stream_body(call_data: dict) -> dict:
    return (
        call_data.get("body")
        or call_data.get("custom_parameters")
        or call_data.get("customParameters")
        or {}
    )


async def bot(runner_args: RunnerArguments):
    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    logger.info(f"Auto-detected transport: {transport_type}")

    body_data = _stream_body(call_data)
    session_id = body_data.get("session_id") or call_data.get("session_id")
    if not session_id:
        raise ValueError("Twilio stream did not include a session_id parameter")

    try:
        session = session_store.get(session_id)
    except KeyError:
        raise ValueError(f"Unknown call session: {session_id}")

    call_sid = call_data.get("call_id")
    if call_sid and not session.call_sid:
        session_store.set_call_sid(session_id, call_sid)

    logger.info(
        f"Call metadata - session: {session_id}, call_sid: {call_sid}, "
        f"payer: {session.payer_name}, claims: {session.claim_ids}"
    )

    serializer = TwilioFrameSerializer(
        stream_sid=call_data["stream_id"],
        call_sid=call_data["call_id"],
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(),
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    await run_bot(transport, runner_args.handle_sigint, session_id)
