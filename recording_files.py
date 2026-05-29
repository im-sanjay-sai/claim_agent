from __future__ import annotations

import wave
from pathlib import Path

from settings import recordings_dir


BYTES_PER_SAMPLE = 2


def audio_duration_seconds(audio: bytes, *, sample_rate: int, num_channels: int) -> float:
    if sample_rate <= 0 or num_channels <= 0:
        return 0.0
    return round(len(audio) / (sample_rate * num_channels * BYTES_PER_SAMPLE), 3)


def write_wav(path: Path, audio: bytes, *, sample_rate: int, num_channels: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(BYTES_PER_SAMPLE)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio)


def recording_session_dir(session_id: str) -> Path:
    safe_session_id = "".join(char for char in session_id if char.isalnum() or char in {"-", "_"})
    if not safe_session_id:
        raise ValueError("Invalid session id for recording path")
    return recordings_dir() / safe_session_id


def recording_path(session_id: str, file_name: str) -> Path:
    base_dir = recording_session_dir(session_id).resolve()
    path = (base_dir / file_name).resolve()
    if base_dir not in path.parents:
        raise ValueError("Invalid recording path")
    return path
