from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger
from models import CallRecording
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from recording_files import audio_duration_seconds, recording_path, write_wav
from session_store import session_store
from settings import local_recordings_enabled, recording_sample_rate


@dataclass(frozen=True)
class TrackConfig:
    track: str
    label: str
    channels: int


TRACKS = {
    "mixed": TrackConfig(track="mixed", label="Full call recording", channels=2),
    "rep": TrackConfig(track="rep", label="Payer or representative track", channels=1),
    "assistant": TrackConfig(track="assistant", label="Assistant track", channels=1),
}


class LocalCallRecorder:
    """Captures user and bot audio from Pipecat and saves local WAV artifacts."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.enabled = local_recordings_enabled()
        self.sample_rate = recording_sample_rate()
        self.audio_buffer = AudioBufferProcessor(sample_rate=self.sample_rate, num_channels=2)
        self._stopped = False
        self._track_counts = {track: 0 for track in TRACKS}
        self._register_handlers()

    def processor(self) -> AudioBufferProcessor | None:
        return self.audio_buffer if self.enabled else None

    async def start(self) -> None:
        if not self.enabled:
            return
        await self.audio_buffer.start_recording()
        session_store.append_transcript(
            self.session_id,
            "system",
            "Local Pipecat recording started.",
        )

    async def stop(self) -> None:
        if not self.enabled or self._stopped:
            return
        self._stopped = True
        await self.audio_buffer.stop_recording()

    def _register_handlers(self) -> None:
        @self.audio_buffer.event_handler("on_audio_data")
        async def on_audio_data(buffer, audio: bytes, sample_rate: int, num_channels: int):
            await self._save_recording("mixed", audio, sample_rate, num_channels)

        @self.audio_buffer.event_handler("on_track_audio_data")
        async def on_track_audio_data(
            buffer,
            user_audio: bytes,
            bot_audio: bytes,
            sample_rate: int,
            num_channels: int,
        ):
            await self._save_recording("rep", user_audio, sample_rate, TRACKS["rep"].channels)
            await self._save_recording(
                "assistant",
                bot_audio,
                sample_rate,
                TRACKS["assistant"].channels,
            )

    async def _save_recording(
        self,
        track: str,
        audio: bytes,
        sample_rate: int,
        num_channels: int,
    ) -> None:
        if not audio or not any(audio):
            logger.info(f"Skipping empty local recording for session {self.session_id}: {track}")
            return

        config = TRACKS[track]
        self._track_counts[track] += 1
        recording_id = track
        if self._track_counts[track] > 1:
            recording_id = f"{track}-{self._track_counts[track]:03d}"

        file_name = f"{recording_id}.wav"
        try:
            path = recording_path(self.session_id, file_name)
            write_wav(path, audio, sample_rate=sample_rate, num_channels=num_channels)
            recording = CallRecording(
                recording_id=recording_id,
                track=config.track,
                label=config.label,
                file_name=file_name,
                url=f"/api/calls/{self.session_id}/recordings/{recording_id}",
                sample_rate=sample_rate,
                num_channels=num_channels,
                duration_seconds=audio_duration_seconds(
                    audio,
                    sample_rate=sample_rate,
                    num_channels=num_channels,
                ),
                size_bytes=os.path.getsize(path),
            )
            session_store.add_recording(self.session_id, recording)
            logger.info(
                f"Saved local recording for session {self.session_id}: "
                f"{recording.track} {recording.duration_seconds}s {path}"
            )
        except Exception as e:
            logger.error(f"Failed to save local recording for session {self.session_id}: {e}")
