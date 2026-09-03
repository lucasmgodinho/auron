"""Request-scoped development debugging helpers.

``debug.stop()`` raises a private exception so broad local ``except Exception``
blocks can intercept it. Let that exception reach FastAPI for the stop response.
"""

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from time import perf_counter
from types import TracebackType
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import NoInspectionAvailable
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DebugEntryType = Literal["value", "snapshot", "mark", "timer", "exception", "stop"]
MAX_DEPTH = 6
MAX_ITEMS = 100
MAX_STRING_LENGTH = 4_000
MAX_SERIALIZED_BYTES = 64 * 1024
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ENVELOPE_HEADER = b"x-auron-debug-envelope"
_SENSITIVE_KEYS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
)


@dataclass(slots=True)
class _DebugContext:
    entries: list[dict[str, Any]]


_current_context: ContextVar[_DebugContext | None] = ContextVar(
    "auron_debug_context",
    default=None,
)


class _DebugStop(Exception):
    def __init__(self, payload: Any) -> None:
        super().__init__("Request execution stopped by debug.stop()")
        self.payload = payload


def _begin_context() -> Token[_DebugContext | None]:
    return _current_context.set(_DebugContext(entries=[]))


def _reset_context(token: Token[_DebugContext | None]) -> None:
    _current_context.reset(token)


def _context() -> _DebugContext:
    context = _current_context.get()
    if context is None:
        raise RuntimeError("Auron debug helpers require an active HTTP request")
    return context


def _entries() -> list[dict[str, Any]]:
    context = _current_context.get()
    return list(context.entries) if context is not None else []


def _concise_path(filename: str) -> str:
    path = Path(filename).resolve()
    try:
        return path.relative_to(_REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.name


def _caller_location() -> dict[str, str | int]:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            frame = frame.f_back
            if frame is None:
                break
            if Path(frame.f_code.co_filename).resolve() != Path(__file__).resolve():
                return {
                    "file": _concise_path(frame.f_code.co_filename),
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                }
    finally:
        del frame
    return {"file": "unknown", "function": "unknown", "line": 0}


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(sensitive in normalized for sensitive in _SENSITIVE_KEYS)


def _serialize_value(value: Any, *, depth: int, seen: set[int]) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        if len(value) <= MAX_STRING_LENGTH:
            return value
        return {
            "_auron_truncated": True,
            "preview": value[:MAX_STRING_LENGTH],
        }
    if isinstance(value, UUID | date | datetime):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _serialize_value(value.value, depth=depth, seen=seen)
    if depth >= MAX_DEPTH:
        return {"_auron_truncated": True, "reason": "maximum depth reached"}

    track_identity = isinstance(value, Mapping | Sequence) or is_dataclass(value)
    if track_identity:
        identity = id(value)
        if identity in seen:
            return {"_auron_circular_reference": True}
        seen.add(identity)

    try:
        if isinstance(value, BaseModel):
            return _serialize_value(
                value.model_dump(mode="python"),
                depth=depth + 1,
                seen=seen,
            )
        if isinstance(value, BaseException):
            return {
                "exception_type": type(value).__name__,
                "message": str(value)[:MAX_STRING_LENGTH],
            }
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= MAX_ITEMS:
                    result["_auron_truncated"] = True
                    break
                normalized_key = str(key)[:200]
                result[normalized_key] = (
                    "[redacted]"
                    if _is_sensitive_key(key)
                    else _serialize_value(item, depth=depth + 1, seen=seen)
                )
            return result
        if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
            items = [
                _serialize_value(item, depth=depth + 1, seen=seen)
                for item in value[:MAX_ITEMS]
            ]
            if len(value) > MAX_ITEMS:
                items.append({"_auron_truncated": True})
            return items
        if isinstance(value, set | frozenset):
            items = list(value)
            return _serialize_value(items, depth=depth, seen=seen)
        if is_dataclass(value) and not isinstance(value, type):
            return _serialize_value(
                {field.name: getattr(value, field.name) for field in fields(value)},
                depth=depth + 1,
                seen=seen,
            )
        try:
            inspection = sqlalchemy_inspect(value)
        except NoInspectionAvailable:
            inspection = None
        if inspection is not None and hasattr(inspection, "mapper"):
            columns = {
                attribute.key: getattr(value, attribute.key)
                for attribute in inspection.mapper.column_attrs
            }
            return _serialize_value(columns, depth=depth + 1, seen=seen)
    finally:
        if track_identity:
            seen.discard(id(value))

    return {"_auron_unsupported_type": type(value).__name__}


def _serialize(value: Any) -> Any:
    try:
        serialized = _serialize_value(value, depth=0, seen=set())
        encoded = json.dumps(
            serialized,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) <= MAX_SERIALIZED_BYTES:
            return serialized
        return {
            "_auron_truncated": True,
            "reason": "maximum serialized size reached",
            "preview": encoded[:MAX_SERIALIZED_BYTES]
            .decode("utf-8", errors="ignore"),
        }
    except Exception as error:
        return {
            "_auron_serialization_error": type(error).__name__,
            "value_type": type(value).__name__,
        }


def _append_entry(
    entry_type: DebugEntryType,
    *,
    label: str | None,
    data: Any = None,
    location: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": entry_type,
        "label": label[:200] if label is not None else None,
        "location": location or _caller_location(),
    }
    if entry_type != "mark":
        entry["data"] = _serialize(data)
    _context().entries.append(entry)
    return entry


def add(value: Any, label: str | None = None) -> None:
    _append_entry("value", label=label, data=value)


def stop(value: Any, label: str | None = None) -> None:
    entry = _append_entry("stop", label=label, data=value)
    raise _DebugStop(entry["data"])


def snapshot(**values: Any) -> None:
    _append_entry("snapshot", label=None, data=values)


def mark(label: str) -> None:
    _append_entry("mark", label=label)


def _exception_location(
    traceback_value: TracebackType | None,
) -> tuple[dict[str, str | int], list[dict[str, str | int]]]:
    frames: list[dict[str, str | int]] = []
    current = traceback_value
    while current is not None:
        frames.append(
            {
                "file": _concise_path(current.tb_frame.f_code.co_filename),
                "function": current.tb_frame.f_code.co_name,
                "line": current.tb_lineno,
            }
        )
        current = current.tb_next
    return (frames[-1] if frames else _caller_location(), frames[-20:])


def exception(exception: BaseException, label: str | None = None) -> None:
    location, traceback_frames = _exception_location(exception.__traceback__)
    _append_entry(
        "exception",
        label=label,
        location=location,
        data={
            "exception_type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback_frames,
        },
    )


class _DebugTimer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.location = _caller_location()
        self.started_at: float | None = None

    def __enter__(self) -> _DebugTimer:
        self.started_at = perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self._record()

    async def __aenter__(self) -> _DebugTimer:
        self.started_at = perf_counter()
        return self

    async def __aexit__(self, *_: object) -> None:
        self._record()

    def _record(self) -> None:
        if self.started_at is None:
            return
        _append_entry(
            "timer",
            label=self.label,
            location=self.location,
            data={"duration_ms": round((perf_counter() - self.started_at) * 1000, 3)},
        )


def timer(label: str) -> _DebugTimer:
    return _DebugTimer(label)


def _is_json_content_type(headers: list[tuple[bytes, bytes]]) -> bool:
    for name, value in headers:
        if name.lower() == b"content-type":
            content_type = value.decode("latin-1").split(";", 1)[0].strip().lower()
            return content_type == "application/json" or content_type.endswith("+json")
    return False


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    for name, value in headers:
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _remove_header(
    headers: list[tuple[bytes, bytes]],
    header_name: bytes,
) -> list[tuple[bytes, bytes]]:
    return [(name, value) for name, value in headers if name.lower() != header_name]


class _DebugMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        context_token = _begin_context()
        pending_start: Message | None = None
        try:
            async def send_wrapper(message: Message) -> None:
                nonlocal pending_start
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    if any(name.lower() == _ENVELOPE_HEADER for name, _ in headers):
                        message["headers"] = _remove_header(headers, _ENVELOPE_HEADER)
                        await send(message)
                        return
                    content_length = _content_length(headers)
                    if (
                        not _entries()
                        or message["status"] in {204, 304}
                        or content_length is None
                        or content_length == 0
                        or not _is_json_content_type(headers)
                    ):
                        await send(message)
                        return
                    pending_start = message
                    return

                if message["type"] != "http.response.body" or pending_start is None:
                    await send(message)
                    return

                if message.get("more_body", False):
                    await send(pending_start)
                    pending_start = None
                    await send(message)
                    return

                body = message.get("body", b"")
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await send(pending_start)
                    pending_start = None
                    await send(message)
                    return

                wrapped_body = json.dumps(
                    {"_auron_payload": payload, "_auron_debug": _entries()},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                headers = _remove_header(
                    list(pending_start.get("headers", [])),
                    b"content-length",
                )
                headers.append((b"content-length", str(len(wrapped_body)).encode("ascii")))
                pending_start["headers"] = headers
                await send(pending_start)
                pending_start = None
                await send({"type": "http.response.body", "body": wrapped_body})

            await self.app(scope, receive, send_wrapper)
        finally:
            _reset_context(context_token)


async def _handle_debug_stop(_: Request, error: _DebugStop) -> JSONResponse:
    return JSONResponse(
        content={
            "_auron_payload": error.payload,
            "_auron_debug": _entries(),
        },
        status_code=200,
        headers={_ENVELOPE_HEADER.decode("ascii"): "1"},
    )
