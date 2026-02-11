"""Thread-safe in-memory runtime state for async import sessions."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock


_IMPORT_PROGRESS = {}
_IMPORT_SESSIONS = {}
_IMPORT_STATE_LOCK = Lock()
_IMPORT_SESSION_COUNTER = 0


def set_progress(session_id: int, *, status=None, progress=None, message=None, error=None):
    """Update in-memory progress state for async import session."""
    with _IMPORT_STATE_LOCK:
        state = _IMPORT_PROGRESS.get(session_id, {})
        if status is not None:
            state["status"] = status
        if progress is not None:
            state["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            state["message"] = message
        if error is not None:
            state["error"] = error
        _IMPORT_PROGRESS[session_id] = state


def get_progress(session_id: int):
    """Read in-memory progress state for async import session."""
    with _IMPORT_STATE_LOCK:
        state = _IMPORT_PROGRESS.get(session_id, {})
        return {
            "status": state.get("status"),
            "progress": state.get("progress"),
            "message": state.get("message"),
            "error": state.get("error", ""),
        }


def next_import_session_id() -> int:
    """Generate process-local import session id."""
    global _IMPORT_SESSION_COUNTER
    with _IMPORT_STATE_LOCK:
        _IMPORT_SESSION_COUNTER += 1
        return _IMPORT_SESSION_COUNTER


def upsert_import_session(session_id: int, **updates):
    """Upsert in-memory import session payload."""
    with _IMPORT_STATE_LOCK:
        session = _IMPORT_SESSIONS.get(session_id, {})
        session.update(updates)
        _IMPORT_SESSIONS[session_id] = session
        return deepcopy(session)


def get_import_session(session_id: int):
    """Read in-memory import session payload."""
    with _IMPORT_STATE_LOCK:
        session = _IMPORT_SESSIONS.get(session_id)
        return deepcopy(session) if session else None


def all_import_sessions():
    """Return all in-memory import sessions sorted by created_at desc."""
    with _IMPORT_STATE_LOCK:
        sessions = [deepcopy(value) for value in _IMPORT_SESSIONS.values()]
    return sorted(sessions, key=lambda value: str(value.get("created_at") or ""), reverse=True)


def latest_import_session():
    """Return latest in-memory import session."""
    sessions = all_import_sessions()
    return sessions[0] if sessions else None


def reset_import_runtime_state():
    """Clear all process-local import runtime state (mainly for tests)."""
    global _IMPORT_SESSION_COUNTER
    with _IMPORT_STATE_LOCK:
        _IMPORT_PROGRESS.clear()
        _IMPORT_SESSIONS.clear()
        _IMPORT_SESSION_COUNTER = 0

