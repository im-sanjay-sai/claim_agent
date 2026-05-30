from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
SAMPLE_EDI_DIR = BASE_DIR / "samples" / "edi-claims" / "raw-837"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def claims_json_path() -> Path:
    return Path(os.getenv("CLAIMS_JSON_PATH", str(DATA_DIR / "claims.json"))).expanduser()


def session_store_path() -> Path:
    return Path(os.getenv("SESSION_STORE_PATH", str(DATA_DIR / "sessions.json"))).expanduser()


def dry_run_calls_enabled() -> bool:
    return env_bool("DRY_RUN_CALLS", default=False)


def local_recordings_enabled() -> bool:
    return env_bool("LOCAL_RECORDINGS_ENABLED", default=os.getenv("ENV", "local").lower() == "local")


def recordings_dir() -> Path:
    return Path(os.getenv("RECORDINGS_DIR", str(DATA_DIR / "recordings"))).expanduser()


def recording_sample_rate() -> int:
    return int(os.getenv("LOCAL_RECORDING_SAMPLE_RATE", "8000"))
