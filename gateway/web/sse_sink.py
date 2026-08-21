"""SSE progress sink for ``POST /investigate/stream``.

Investigations report live progress through :class:`ProgressReporter`, not
the chat :class:`~core.agent_harness.ports.OutputSink`. This adapter implements
that reporter and writes one JSON object per ``data:`` line onto a
``StreamingResponse``.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Final

from core.tool.execution import summarise
from platform.observability import progress_tracker_scope
from platform.observability.errors.sentry import capture_exception

logger = logging.getLogger(__name__)

SSE_MEDIA_TYPE: Final = "text/event-stream"
SSE_HEADERS: Final = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_SSE_KEEPALIVE_SECONDS: Final = 15.0
_DONE: Final = object()


def format_sse(payload: Mapping[str, Any]) -> str:
    """Encode one SSE ``data:`` frame (JSON object, blank line terminated)."""
    return f"data: {json.dumps(dict(payload), ensure_ascii=False)}\n\n"


def _tool_summary(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        text = output.strip()
        if len(text) > 120:
            return text[:120] + "..."
        return text
    return summarise(output)


def _enqueue(loop: asyncio.AbstractEventLoop, items: asyncio.Queue[object], item: object) -> None:
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(items.put_nowait, item)


class SSEOutputSink:
    """:class:`~platform.observability.render.progress.ProgressReporter` over SSE payloads.

    Pipeline stages already call ``start`` / ``record_tool_start`` /
    ``record_tool_end``; this sink forwards those as ``progress`` and
    ``tool_call`` events. The ``complete`` event is emitted by the stream
    iterator once :meth:`AgentSession.investigate` returns.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        self._on_event = on_event

    def start(self, node_name: str, message: str | None = None) -> None:
        text = (message or "").strip() or node_name.replace("_", " ")
        self._emit({"type": "progress", "message": text})

    def complete(
        self,
        node_name: str,
        fields_updated: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        _ = (node_name, fields_updated)
        text = (message or "").strip()
        if text:
            self._emit({"type": "progress", "message": text})

    def error(self, node_name: str, message: str) -> None:
        text = message.strip() or node_name.replace("_", " ")
        self._emit({"type": "progress", "message": text})

    def record_tool_start(
        self,
        tool_name: str,
        tool_input: Any = None,
        *,
        event_key: str | None = None,
    ) -> None:
        _ = (tool_input, event_key)
        self._emit({"type": "tool_call", "tool": tool_name or "tool", "status": "running"})

    def record_tool_end(
        self,
        tool_name: str,
        output: Any = None,
        *,
        event_key: str | None = None,
        tool_input: Any = None,
    ) -> None:
        _ = (event_key, tool_input)
        payload: dict[str, Any] = {
            "type": "tool_call",
            "tool": tool_name or "tool",
            "status": "done",
        }
        summary = _tool_summary(output)
        if summary:
            payload["summary"] = summary
        self._emit(payload)

    def stop(self) -> None:
        return None

    def _emit(self, payload: dict[str, Any]) -> None:
        try:
            self._on_event(payload)
        except Exception:
            logger.debug("sse sink emit failed", exc_info=True)


async def iter_investigation_sse(
    run: Callable[[], Mapping[str, Any]],
    *,
    on_finished: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    """Run ``run`` in a worker thread and yield SSE frames as progress arrives.

    ``run`` is the same investigation callable as ``POST /investigate``. Progress
    is bound for that thread only via :func:`progress_tracker_scope`.
    ``on_finished`` runs on the worker thread after the investigation ends
    (success or failure) so a capacity slot can be released even if the HTTP
    client has already disconnected.
    """
    loop = asyncio.get_running_loop()
    items: asyncio.Queue[object] = asyncio.Queue()

    def _on_event(payload: dict[str, Any]) -> None:
        _enqueue(loop, items, payload)

    sink = SSEOutputSink(_on_event)

    def _run() -> None:
        try:
            with progress_tracker_scope(sink):
                payload = dict(run())
            framed = {k: v for k, v in payload.items() if k != "type"}
            _enqueue(loop, items, {"type": "complete", **framed})
        except Exception as exc:
            logger.exception("Investigation failed")
            capture_exception(exc, context="gateway.web.sse_sink")
            _enqueue(
                loop,
                items,
                {"type": "error", "error": f"investigation failed: {type(exc).__name__}"},
            )
        finally:
            _enqueue(loop, items, _DONE)
            if on_finished is not None:
                on_finished()

    thread = threading.Thread(
        target=contextvars.copy_context().run,
        args=(_run,),
        daemon=True,
        name="investigate-sse",
    )
    thread.start()
    while True:
        try:
            item = await asyncio.wait_for(items.get(), timeout=_SSE_KEEPALIVE_SECONDS)
        except TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is _DONE:
            break
        if isinstance(item, dict):
            yield format_sse(item)


__all__ = [
    "SSE_HEADERS",
    "SSE_MEDIA_TYPE",
    "SSEOutputSink",
    "format_sse",
    "iter_investigation_sse",
]
