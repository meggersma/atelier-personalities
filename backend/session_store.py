import threading
from typing import Dict, Any

_store: Dict[str, Any] = {}
_lock = threading.Lock()

_segments_store: Dict[str, Any] = {}
_segments_lock = threading.Lock()

_personas_store: Dict[str, Any] = {}
_personas_lock = threading.Lock()


def get(session_id: str):
    with _lock:
        return _store.get(session_id)


def set(session_id: str, session: Any):
    with _lock:
        _store[session_id] = session


def delete(session_id: str):
    with _lock:
        _store.pop(session_id, None)


def all_sessions():
    with _lock:
        return dict(_store)


# Segments store

def segments_get(segment_id: str):
    with _segments_lock:
        return _segments_store.get(segment_id)


def segments_set(segment_id: str, segment: Any):
    with _segments_lock:
        _segments_store[segment_id] = segment


def segments_all():
    with _segments_lock:
        return dict(_segments_store)


# Personas store

def personas_get(persona_id: str):
    with _personas_lock:
        return _personas_store.get(persona_id)


def personas_set(persona_id: str, persona: Any):
    with _personas_lock:
        _personas_store[persona_id] = persona


def personas_all():
    with _personas_lock:
        return dict(_personas_store)


# Analyses store

_analyses_store: Dict[str, Any] = {}
_analyses_lock = threading.Lock()


def analyses_get(analysis_id: str):
    with _analyses_lock:
        return _analyses_store.get(analysis_id)


def analyses_set(analysis_id: str, analysis: Any):
    with _analyses_lock:
        _analyses_store[analysis_id] = analysis


def analyses_all():
    with _analyses_lock:
        return dict(_analyses_store)
