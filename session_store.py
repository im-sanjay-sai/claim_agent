from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from models import CallSession, ClaimInput, ClaimStatusResult, TranscriptEntry, utc_now
from settings import session_store_path


class SessionStore:
    def __init__(self, path: Path | None = None):
        self.path = path or session_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, CallSession]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        sessions = payload.get("sessions", payload)
        return {
            session_id: CallSession.model_validate(session_data)
            for session_id, session_data in sessions.items()
        }

    def _write_all(self, sessions: dict[str, CallSession]) -> None:
        payload = {
            "sessions": {
                session_id: session.model_dump(mode="json")
                for session_id, session in sessions.items()
            }
        }
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        tmp_path.replace(self.path)

    def list_sessions(self) -> list[CallSession]:
        with self._lock:
            sessions = self._read_all()
        return sorted(sessions.values(), key=lambda session: session.created_at, reverse=True)

    def get(self, session_id: str) -> CallSession:
        with self._lock:
            sessions = self._read_all()
        if session_id not in sessions:
            raise KeyError(session_id)
        return sessions[session_id]

    def get_by_call_sid(self, call_sid: str) -> CallSession | None:
        with self._lock:
            sessions = self._read_all()
        for session in sessions.values():
            if session.call_sid == call_sid:
                return session
        return None

    def create(
        self,
        payer_name: str,
        payer_phone: str,
        from_number: str,
        claims: list[ClaimInput],
        initial_keypad_digits: str | None = None,
    ) -> CallSession:
        session = CallSession(
            session_id=uuid.uuid4().hex,
            payer_name=payer_name,
            payer_phone=payer_phone,
            from_number=from_number,
            initial_keypad_digits=initial_keypad_digits,
            claim_ids=[claim.claim_id for claim in claims],
            claims=claims,
        )
        with self._lock:
            sessions = self._read_all()
            sessions[session.session_id] = session
            self._write_all(sessions)
        return session

    def save(self, session: CallSession) -> CallSession:
        session.updated_at = utc_now()
        with self._lock:
            sessions = self._read_all()
            sessions[session.session_id] = session
            self._write_all(sessions)
        return session

    def set_call_sid(self, session_id: str, call_sid: str) -> CallSession:
        session = self.get(session_id)
        session.call_sid = call_sid
        session.status = "call_initiated"
        return self.save(session)

    def set_status(self, session_id: str, status: str, error_message: str | None = None) -> CallSession:
        session = self.get(session_id)
        session.status = status
        if error_message:
            session.error_message = error_message
        return self.save(session)

    def append_transcript(self, session_id: str, role: str, text: str) -> CallSession:
        session = self.get(session_id)
        cleaned = text.strip()
        if cleaned:
            session.transcript.append(TranscriptEntry(role=role, text=cleaned))
        return self.save(session)

    def save_results(self, session_id: str, results: list[ClaimStatusResult]) -> CallSession:
        session = self.get(session_id)
        session.results = results
        session.status = "completed"
        return self.save(session)


session_store = SessionStore()
