import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, StreamingResponse

from app.core import debug


def make_debug_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(debug._DebugMiddleware)
    app.add_exception_handler(debug._DebugStop, debug._handle_debug_stop)
    return app


def test_stop_interrupts_and_returns_prior_entries() -> None:
    app = make_debug_app()

    @app.get("/stop")
    def stop_request() -> dict[str, bool]:
        debug.add({"step": 1}, label="Before stop")
        debug.stop({"result": "inspected"}, label="Stopped value")
        return {"unreachable": True}

    response = TestClient(app).get("/stop")
    payload = response.json()

    assert response.status_code == 200
    assert payload["_auron_payload"] == {"result": "inspected"}
    assert [entry["type"] for entry in payload["_auron_debug"]] == ["value", "stop"]
    assert payload["_auron_debug"][1]["label"] == "Stopped value"


def test_add_preserves_normal_result_and_capture_order() -> None:
    app = make_debug_app()

    @app.get("/add")
    def add_values() -> dict[str, bool]:
        debug.mark("first")
        debug.add(2, label="second")
        debug.snapshot(third=3)
        return {"completed": True}

    payload = TestClient(app).get("/add").json()

    assert payload["_auron_payload"] == {"completed": True}
    assert [entry["type"] for entry in payload["_auron_debug"]] == [
        "mark",
        "value",
        "snapshot",
    ]


def test_add_wraps_before_existing_base_http_middleware_streams_response() -> None:
    app = make_debug_app()

    class ExistingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)

    app.add_middleware(ExistingMiddleware)

    @app.get("/stacked")
    def stacked() -> dict[str, bool]:
        debug.add("captured", label="Stacked middleware")
        return {"completed": True}

    payload = TestClient(app).get("/stacked").json()

    assert payload["_auron_payload"] == {"completed": True}
    assert payload["_auron_debug"][0]["data"] == "captured"


def test_timer_exception_and_source_location() -> None:
    app = make_debug_app()

    @app.get("/helpers")
    async def helpers() -> dict[str, bool]:
        with debug.timer("sync timer"):
            pass
        async with debug.timer("async timer"):
            await asyncio.sleep(0)
        try:
            raise ValueError("provider failed")
        except ValueError as error:
            debug.exception(exception=error, label="Captured provider failure")
        return {"completed": True}

    entries = TestClient(app).get("/helpers").json()["_auron_debug"]

    assert [entry["type"] for entry in entries] == ["timer", "timer", "exception"]
    assert entries[0]["data"]["duration_ms"] >= 0
    assert entries[2]["data"]["exception_type"] == "ValueError"
    assert entries[2]["data"]["message"] == "provider failed"
    assert entries[2]["data"]["traceback"]
    assert entries[2]["location"]["file"].endswith("tests/test_debug.py")
    assert entries[2]["location"]["line"] > 0


class ExampleSchema(BaseModel):
    identifier: object
    created_at: datetime


@dataclass
class ExampleDataclass:
    name: str


class ExampleEnum(Enum):
    READY = "ready"


class Base(DeclarativeBase):
    pass


class ExampleModel(Base):
    __tablename__ = "debug_example"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


def test_common_values_circular_values_and_sensitive_keys_are_safe() -> None:
    app = make_debug_app()
    identifier = uuid4()
    circular: list[object] = []
    circular.append(circular)

    @app.get("/serialization")
    def serialization() -> dict[str, bool]:
        debug.add(
            {
                "schema": ExampleSchema(
                    identifier=identifier,
                    created_at=datetime(2026, 9, 2, tzinfo=UTC),
                ),
                "dataclass": ExampleDataclass(name="example"),
                "enum": ExampleEnum.READY,
                "orm": ExampleModel(id=7, name="row"),
                "circular": circular,
                "password": "never expose this",
            }
        )
        return {"completed": True}

    data = TestClient(app).get("/serialization").json()["_auron_debug"][0]["data"]

    assert data["schema"]["identifier"] == str(identifier)
    assert data["schema"]["created_at"] == "2026-09-02T00:00:00+00:00"
    assert data["dataclass"] == {"name": "example"}
    assert data["enum"] == "ready"
    assert data["orm"] == {"id": 7, "name": "row"}
    assert data["circular"][0] == {"_auron_circular_reference": True}
    assert data["password"] == "[redacted]"


def test_unsupported_and_oversized_values_fail_gracefully() -> None:
    app = make_debug_app()

    @app.get("/limits")
    def limits() -> dict[str, bool]:
        debug.add(object(), label="unsupported")
        debug.add("x" * 100_000, label="oversized")
        debug.add({"items": ["x" * 4_000] * 100}, label="total size")
        return {"completed": True}

    entries = TestClient(app).get("/limits").json()["_auron_debug"]

    assert entries[0]["data"] == {"_auron_unsupported_type": "object"}
    assert entries[1]["data"]["_auron_truncated"] is True
    assert entries[2]["data"] == {
        "_auron_truncated": True,
        "reason": "maximum serialized size reached",
        "preview": entries[2]["data"]["preview"],
    }


def test_normal_empty_streaming_and_non_json_responses_are_unchanged() -> None:
    app = make_debug_app()

    @app.get("/normal")
    def normal() -> dict[str, bool]:
        return {"normal": True}

    @app.get("/empty", status_code=204)
    def empty() -> Response:
        debug.add("not wrapped")
        return Response(status_code=204)

    @app.get("/text")
    def text() -> Response:
        debug.add("not wrapped")
        return Response("plain text", media_type="text/plain")

    @app.get("/download")
    def download() -> FileResponse:
        debug.add("not wrapped")
        return FileResponse(__file__, filename="test_debug.py")

    @app.get("/not-modified", status_code=304)
    def not_modified() -> Response:
        debug.add("not wrapped")
        return Response(status_code=304)

    @app.get("/stream")
    def stream() -> StreamingResponse:
        debug.add("not wrapped")
        return StreamingResponse(iter([b'{"streamed":', b"true}"]), media_type="application/json")

    client = TestClient(app)

    assert client.get("/normal").content == b'{"normal":true}'
    assert client.get("/empty").content == b""
    assert client.get("/text").content == b"plain text"
    assert b"test_stop_interrupts_and_returns_prior_entries" in client.get("/download").content
    assert client.get("/not-modified").content == b""
    assert client.get("/stream").content == b'{"streamed":true}'


def test_context_is_cleared_after_success_and_failure() -> None:
    app = make_debug_app()

    @app.get("/success")
    def success() -> dict[str, bool]:
        debug.add("inside request")
        return {"completed": True}

    @app.get("/failure")
    def failure() -> None:
        debug.add("inside failed request")
        raise ValueError("expected failure")

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/success").status_code == 200
    with pytest.raises(RuntimeError, match="active HTTP request"):
        debug.add("outside request")
    assert client.get("/failure").status_code == 500
    with pytest.raises(RuntimeError, match="active HTTP request"):
        debug.add("outside request")


def test_concurrent_request_contexts_are_isolated() -> None:
    app = make_debug_app()
    barrier = Barrier(2)

    @app.get("/concurrent/{value}")
    def concurrent(value: str) -> dict[str, str]:
        debug.add(value, label=value)
        barrier.wait(timeout=10)
        return {"value": value}

    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda value: client.get(f"/concurrent/{value}"), ("a", "b")))

    for response in responses:
        payload = response.json()
        expected = payload["_auron_payload"]["value"]
        assert [entry["data"] for entry in payload["_auron_debug"]] == [expected]


def test_debug_entries_do_not_use_application_event_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_debug_app()
    calls: list[object] = []
    monkeypatch.setattr(
        "app.core.application_events.service.record_event",
        lambda **values: calls.append(values),
    )

    @app.get("/debug")
    def debug_only() -> dict[str, bool]:
        debug.add({"debug": True})
        return {"completed": True}

    assert TestClient(app).get("/debug").status_code == 200
    assert calls == []
