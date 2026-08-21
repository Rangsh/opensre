"""The gateway's single FastAPI app: health probes, alert intake, investigations.

Every HTTP endpoint OpenSRE serves lives here, on one port — ``/`` ``/health``
``/ok`` (health probes), ``/healthz`` (liveness), ``POST /alerts`` (external
alert pushes into the process-wide :class:`AlertInbox`), ``POST /investigate``
(run an investigation synchronously and return the RCA report), and
``POST /investigate/stream`` (same investigation with Server-Sent Events
progress). Hosted by the gateway daemon and the interactive shell via
:mod:`gateway.web.web_server`, or standalone via ``uvicorn gateway.web.webapp:app``.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from config.config import LLMSettings, get_environment
from config.platform_bootstrap import ensure_project_platform_package
from config.version import get_opensre_version
from core.domain.alerts.inbox import (
    AlertInbox,
    IncomingAlert,
    get_current_inbox,
    set_current_inbox,
)

ensure_project_platform_package()

from bootstrap.process import WEB_PROFILE, configure_process  # noqa: E402
from core.agent_harness import AgentSession  # noqa: E402
from gateway.core.process.readiness import is_gateway_ready  # noqa: E402
from gateway.core.storage import open_database  # noqa: E402
from gateway.core.storage.investigations.repository import investigation_repository  # noqa: E402
from gateway.web.investigations import router as investigations_router  # noqa: E402
from gateway.web.sse_sink import SSE_HEADERS, SSE_MEDIA_TYPE, iter_investigation_sse  # noqa: E402
from platform.observability.errors.sentry import capture_exception  # noqa: E402
from platform.process.turn_capacity import turn_slot  # noqa: E402
from tools.investigation.capability import resolve_investigation_context  # noqa: E402

# Standalone uvicorn and in-process gateway both need adapters for /investigate.
configure_process(WEB_PROFILE)  # env → sentry → adapters

logger = logging.getLogger(__name__)

# Cap on POST body size accepted from any caller (authed or not). Realistic
# alert payloads top out around 50 KB, so 1 MiB is ~20× headroom.
MAX_ALERT_BODY_BYTES = 1 * 1024 * 1024

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class HealthResponse(BaseModel):
    ok: bool
    version: str
    llm_configured: bool
    env: str


app = FastAPI()
app.state.investigations = investigation_repository(open_database())
app.include_router(investigations_router)


def get_health_response() -> HealthResponse:
    try:
        LLMSettings.from_env()
        llm_configured = True
    except ValidationError:
        llm_configured = False

    return HealthResponse(
        ok=llm_configured,
        version=get_opensre_version(),
        llm_configured=llm_configured,
        env=get_environment().value,
    )


@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
@app.get("/ok", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    health_response = get_health_response()
    response.status_code = HTTPStatus.OK if health_response.ok else HTTPStatus.SERVICE_UNAVAILABLE
    return health_response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Report mandatory startup readiness separately from process liveness."""
    if is_gateway_ready():
        return JSONResponse({"status": "ready"}, status_code=HTTPStatus.OK)
    return JSONResponse({"status": "not_ready"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)


def _alert_inbox() -> AlertInbox:
    """The process-wide inbox; hosts may install their own via set_current_inbox."""
    inbox = get_current_inbox()
    if inbox is None:
        inbox = AlertInbox()
        set_current_inbox(inbox)
    return inbox


def _gateway_auth_error(request: Request) -> JSONResponse | None:
    """Bearer-token auth when configured; otherwise loopback callers only.

    Shared by every mutating gateway route (``/alerts``, ``/investigate``,
    ``/investigate/stream``) since they sit behind the same trust boundary:
    local callers or a configured token.
    """
    token = os.environ.get("OPENSRE_ALERT_LISTENER_TOKEN")
    if token:
        supplied = request.headers.get("authorization", "")
        if hmac.compare_digest(supplied, f"Bearer {token}"):
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
    client_host = request.client.host if request.client else ""
    if client_host in _LOOPBACK_HOSTS:
        return None
    return JSONResponse(
        {"error": "set OPENSRE_ALERT_LISTENER_TOKEN to accept non-loopback callers"},
        status_code=HTTPStatus.FORBIDDEN,
    )


@app.post("/alerts")
async def receive_alert(request: Request) -> JSONResponse:
    if (auth_error := _gateway_auth_error(request)) is not None:
        return auth_error

    try:
        declared_length = int(request.headers.get("content-length", 0))
    except ValueError:
        return JSONResponse({"error": "invalid Content-Length"}, status_code=HTTPStatus.BAD_REQUEST)
    if declared_length < 0:
        return JSONResponse({"error": "invalid Content-Length"}, status_code=HTTPStatus.BAD_REQUEST)
    if declared_length > MAX_ALERT_BODY_BYTES:
        return JSONResponse(
            {"error": "payload too large"}, status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        )

    body = await request.body()
    if len(body) > MAX_ALERT_BODY_BYTES:
        return JSONResponse(
            {"error": "payload too large"}, status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        )

    try:
        data = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "invalid json"}, status_code=HTTPStatus.BAD_REQUEST)

    try:
        if not isinstance(data, dict):
            raise TypeError("alert payload must be a JSON object")
        if data.get("received_at") is None:
            data["received_at"] = datetime.now(UTC)
        alert = IncomingAlert.model_validate(data)
    except (TypeError, ValidationError, ValueError) as exc:
        # Expected client error: log the full detail, return only the exception
        # type (payload field names and model internals stay out of the
        # response), and skip Sentry capture for routine 400s.
        logger.warning("Alert payload rejected (%s): %s", type(exc).__name__, exc)
        return JSONResponse(
            {"error": f"invalid alert payload: {type(exc).__name__}"},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    inbox = _alert_inbox()
    accepted = inbox.put(alert)
    payload: dict[str, Any] = {"queued": True, "queue_depth": inbox.qsize}
    if not accepted:
        payload["dropped"] = inbox.dropped
        payload["warning"] = "inbox full, oldest alert dropped"
    return JSONResponse(payload, status_code=HTTPStatus.ACCEPTED)


class InvestigateRequest(BaseModel):
    raw_alert: dict[str, Any]
    alert_name: str | None = None
    severity: str | None = None


class InvestigateResponse(BaseModel):
    report: str
    problem_md: str
    root_cause: str
    is_noise: bool = False
    validity_score: float = 0.0
    tool_calls: list[dict[str, Any]] | None = None


@app.post("/investigate", response_model=InvestigateResponse)
def investigate(req: InvestigateRequest, request: Request) -> InvestigateResponse | JSONResponse:
    """Run an investigation synchronously and return the RCA report.

    Lets external systems (CI pipelines, custom webhooks, chat integrations
    without a native tool) trigger the same investigation pipeline the CLI and
    interactive shell use, over HTTP. FastAPI runs this sync handler in a
    threadpool, so a long investigation does not block ``/health`` or ``/alerts``.
    """
    if (auth_error := _gateway_auth_error(request)) is not None:
        return auth_error

    from platform.turn_host.concurrency import AT_CAPACITY_MESSAGE, process_turn_gate

    # Drop rather than queue: the caller is holding an HTTP connection open, so
    # it gets an answer now. Same gate chat and the scheduler take, same sentence
    # chat finalizes.
    with turn_slot(process_turn_gate()) as running:
        if not running:
            return JSONResponse(
                {"error": AT_CAPACITY_MESSAGE},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return _run_investigation(req)


@app.post("/investigate/stream", response_model=None)
async def investigate_stream(
    req: InvestigateRequest, request: Request
) -> StreamingResponse | JSONResponse:
    """Stream investigation progress as Server-Sent Events.

    Same auth, body, capacity gate, and final report fields as
    ``POST /investigate``. Each ``data:`` line is one JSON object (``tool_call``,
    ``progress``, ``complete``, or ``error``). Closing the stream does not cancel
    the investigation; the turn slot is held until the pipeline finishes.
    """
    if (auth_error := _gateway_auth_error(request)) is not None:
        return auth_error

    from platform.turn_host.concurrency import AT_CAPACITY_MESSAGE, process_turn_gate

    gate = process_turn_gate()
    if not gate.try_acquire():
        return JSONResponse(
            {"error": AT_CAPACITY_MESSAGE},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _run() -> dict[str, Any]:
        return _execute_investigation(req).model_dump()

    return StreamingResponse(
        iter_investigation_sse(_run, on_finished=gate.release),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


def _execute_investigation(req: InvestigateRequest) -> InvestigateResponse:
    """Run one investigation and shape the wire-format response."""
    investigation_metadata = resolve_investigation_context(
        raw_alert=req.raw_alert,
        alert_name=req.alert_name,
        severity=req.severity,
    )
    result = AgentSession().investigate(
        req.raw_alert,
        investigation_metadata=investigation_metadata,
    )
    return InvestigateResponse(**result.as_dict())


def _run_investigation(req: InvestigateRequest) -> InvestigateResponse | JSONResponse:
    """Run one investigation; convert failures to an opaque HTTP error."""
    try:
        return _execute_investigation(req)
    except Exception as exc:
        # Full detail (which may include internal paths, stack context, or
        # upstream error bodies) goes to logs/Sentry only. The HTTP response
        # carries just the exception type so it stays actionable without
        # exposing internals to the caller (CodeQL: information exposure
        # through an exception).
        logger.exception("Investigation failed")
        capture_exception(exc, context="gateway.web.webapp.investigate")
        return JSONResponse(
            {"error": f"investigation failed: {type(exc).__name__}"},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
