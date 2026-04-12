from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterator


_DEBUG_ENABLED = os.getenv("DEBUG", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_DEBUG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "server_debug_context", default={}
)


def debug_enabled() -> bool:
    return _DEBUG_ENABLED


@contextmanager
def debug_context(**kwargs: Any) -> Iterator[None]:
    if not _DEBUG_ENABLED:
        yield
        return
    next_context = dict(_DEBUG_CONTEXT.get())
    next_context.update(
        {key: value for key, value in kwargs.items() if value is not None}
    )
    token = _DEBUG_CONTEXT.set(next_context)
    try:
        yield
    finally:
        _DEBUG_CONTEXT.reset(token)


def current_debug_context() -> dict[str, Any]:
    return dict(_DEBUG_CONTEXT.get())


def _sanitize_component(value: str | None, default: str) -> str:
    if not value:
        return default
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in value
    )


def _log_path(context: dict[str, Any]) -> Path:
    task_id = _sanitize_component(
        str(context.get("task_id") or "unknown_task"), "unknown_task"
    )
    difficulty = _sanitize_component(
        str(context.get("difficulty") or "unknown"), "unknown"
    )
    episode_id = _sanitize_component(
        str(context.get("episode_id") or "global"), "global"
    )
    return (
        Path("outputs") / "debug" / f"{task_id}_{difficulty}_{episode_id}.server.jsonl"
    )


def write_debug_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    if not _DEBUG_ENABLED:
        return
    context = current_debug_context()
    path = _log_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **context,
        "payload": payload or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, default=str))
        handle.write("\n")


__all__ = [
    "current_debug_context",
    "debug_context",
    "debug_enabled",
    "write_debug_event",
]
