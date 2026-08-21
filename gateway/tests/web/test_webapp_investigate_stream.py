"""Tests for ``POST /investigate/stream`` SSE progress."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.agent_harness.investigation_api import (
    install_investigation_payload_runner,
    reset_investigation_payload_runner_for_tests,
)
from gateway.web import webapp
from gateway.web.sse_sink import SSEOutputSink, format_sse, iter_investigation_sse
from platform.observability import get_progress_tracker

_LOOPBACK = ("127.0.0.1", 40000)
_REMOTE = ("203.0.113.9", 40000)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENSRE_ALERT_LISTENER_TOKEN", raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_investigation_runner() -> Iterator[None]:
    reset_investigation_payload_runner_for_tests()
    yield
    reset_investigation_payload_runner_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(webapp.app, client=_LOOPBACK)


def _fake_payload() -> dict[str, Any]:
    return {
        "report": "Root cause identified.",
        "problem_md": "## Problem\nOrders pipeline timed out.",
        "root_cause": "Timeout calling downstream service.",
        "is_noise": False,
        "validity_score": 0.91,
        "tool_calls": [{"key": "logs", "tool_name": "hermes_logs", "data": {}}],
    }


def _sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for frame in body.split("\n\n"):
        line = frame.strip()
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def test_format_sse_writes_data_frame() -> None:
    assert format_sse({"type": "progress", "message": "go"}) == (
        'data: {"type": "progress", "message": "go"}\n\n'
    )


def test_sse_output_sink_maps_tracker_calls() -> None:
    seen: list[dict[str, Any]] = []
    sink = SSEOutputSink(seen.append)
    sink.record_tool_start("fetch_metrics")
    sink.record_tool_end("fetch_metrics", output="CPU 94% on pod payment-api-7f9d")
    sink.start("correlate_upstream", "Correlating metrics with recent deployments...")
    sink.complete("correlate_upstream")

    assert seen == [
        {"type": "tool_call", "tool": "fetch_metrics", "status": "running"},
        {
            "type": "tool_call",
            "tool": "fetch_metrics",
            "status": "done",
            "summary": "CPU 94% on pod payment-api-7f9d",
        },
        {
            "type": "progress",
            "message": "Correlating metrics with recent deployments...",
        },
    ]


def test_stream_emits_tool_progress_then_complete(client: TestClient) -> None:
    def _fake_run(**_: Any) -> dict[str, Any]:
        tracker = get_progress_tracker()
        tracker.record_tool_start("fetch_metrics")
        tracker.record_tool_end("fetch_metrics", output="CPU 94% on pod payment-api-7f9d")
        tracker.start("correlate_upstream", "Correlating metrics with recent deployments...")
        return _fake_payload()

    install_investigation_payload_runner(_fake_run)

    resp = client.post(
        "/investigate/stream",
        json={"raw_alert": {"title": "HighCPU", "service": "payment-api"}},
    )

    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(resp.text)
    assert [event["type"] for event in events] == [
        "tool_call",
        "tool_call",
        "progress",
        "complete",
    ]
    assert events[0] == {
        "type": "tool_call",
        "tool": "fetch_metrics",
        "status": "running",
    }
    assert events[1]["status"] == "done"
    assert events[1]["summary"] == "CPU 94% on pod payment-api-7f9d"
    assert events[2]["message"] == "Correlating metrics with recent deployments..."
    complete = events[3]
    assert complete["type"] == "complete"
    assert complete["report"] == "Root cause identified."
    assert complete["root_cause"] == "Timeout calling downstream service."
    assert complete["problem_md"] == "## Problem\nOrders pipeline timed out."
    assert complete["is_noise"] is False
    assert complete["validity_score"] == 0.91
    assert complete["tool_calls"] == [{"key": "logs", "tool_name": "hermes_logs", "data": {}}]


@pytest.mark.anyio
async def test_iter_investigation_sse_yields_tool_call_before_run_returns() -> None:
    """Progress frames are yielded while the investigation callable is still running."""
    release = threading.Event()
    returned = threading.Event()

    def _run() -> dict[str, Any]:
        get_progress_tracker().record_tool_start("fetch_metrics")
        release.wait(timeout=5)
        returned.set()
        return _fake_payload()

    frames: list[str] = []
    agen = iter_investigation_sse(_run)
    first = await anext(agen)
    frames.append(first)
    assert returned.is_set() is False
    release.set()
    async for frame in agen:
        frames.append(frame)

    events = _sse_events("".join(frames))
    assert events[0] == {
        "type": "tool_call",
        "tool": "fetch_metrics",
        "status": "running",
    }
    assert events[-1]["type"] == "complete"
    assert returned.is_set() is True


def test_stream_pipeline_failure_emits_error_without_leaking_exception_text(
    client: TestClient,
) -> None:
    def _boom(**_: Any) -> dict[str, Any]:
        raise RuntimeError("llm unavailable at s3://internal-bucket/creds.json")

    install_investigation_payload_runner(_boom)

    resp = client.post("/investigate/stream", json={"raw_alert": {"alert_name": "x"}})

    assert resp.status_code == HTTPStatus.OK
    events = _sse_events(resp.text)
    assert events == [{"type": "error", "error": "investigation failed: RuntimeError"}]
    assert "llm unavailable" not in resp.text
    assert "s3://internal-bucket" not in resp.text


def test_stream_malformed_pipeline_result_emits_error(client: TestClient) -> None:
    def _malformed(**_: Any) -> dict[str, Any]:
        return {"report": None, "problem_md": "p", "root_cause": "c"}

    install_investigation_payload_runner(_malformed)

    resp = client.post("/investigate/stream", json={"raw_alert": {"alert_name": "x"}})

    assert resp.status_code == HTTPStatus.OK
    assert _sse_events(resp.text) == [
        {"type": "error", "error": "investigation failed: ValidationError"}
    ]


def test_stream_missing_raw_alert_returns_422(client: TestClient) -> None:
    resp = client.post("/investigate/stream", json={"alert_name": "x"})
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_stream_non_loopback_without_token_returns_403() -> None:
    install_investigation_payload_runner(lambda **_: _fake_payload())
    remote = TestClient(webapp.app, client=_REMOTE)

    resp = remote.post("/investigate/stream", json={"raw_alert": {"alert_name": "x"}})

    assert resp.status_code == HTTPStatus.FORBIDDEN


def test_stream_token_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSRE_ALERT_LISTENER_TOKEN", "sekret")
    install_investigation_payload_runner(lambda **_: _fake_payload())
    remote = TestClient(webapp.app, client=_REMOTE)

    assert (
        remote.post("/investigate/stream", json={"raw_alert": {"alert_name": "x"}}).status_code
        == HTTPStatus.UNAUTHORIZED
    )
    ok = remote.post(
        "/investigate/stream",
        json={"raw_alert": {"alert_name": "x"}},
        headers={"Authorization": "Bearer sekret"},
    )
    assert ok.status_code == HTTPStatus.OK
    assert _sse_events(ok.text)[-1]["type"] == "complete"


def test_stream_at_capacity_returns_503(client: TestClient) -> None:
    from platform.turn_host.concurrency import (
        TurnConcurrencyGate,
        reset_process_turn_gate_for_tests,
        set_process_turn_gate,
    )

    install_investigation_payload_runner(lambda **_: _fake_payload())
    gate = TurnConcurrencyGate(1)
    assert gate.try_acquire() is True
    set_process_turn_gate(gate)
    try:
        resp = client.post("/investigate/stream", json={"raw_alert": {"alert_name": "x"}})
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert "at capacity" in resp.json()["error"]
    finally:
        gate.release()
        reset_process_turn_gate_for_tests()
