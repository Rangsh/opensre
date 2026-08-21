"""Context-local progress tracker isolation."""

from __future__ import annotations

import threading

from platform.observability import (
    NoopProgressTracker,
    get_progress_tracker,
    progress_tracker_scope,
    set_progress_tracker,
)


class _RecordingTracker:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, node_name: str, message: str | None = None) -> None:
        _ = message
        self.started.append(node_name)

    def complete(
        self,
        node_name: str,
        fields_updated: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        _ = (node_name, fields_updated, message)

    def error(self, node_name: str, message: str) -> None:
        _ = (node_name, message)

    def record_tool_start(
        self,
        tool_name: str,
        tool_input: object = None,
        *,
        event_key: str | None = None,
    ) -> None:
        _ = (tool_name, tool_input, event_key)

    def record_tool_end(
        self,
        tool_name: str,
        output: object = None,
        *,
        event_key: str | None = None,
        tool_input: object = None,
    ) -> None:
        _ = (tool_name, output, event_key, tool_input)

    def stop(self) -> None:
        return None


def test_progress_tracker_scope_overrides_global_then_restores() -> None:
    set_progress_tracker(NoopProgressTracker())
    local = _RecordingTracker()
    with progress_tracker_scope(local):
        get_progress_tracker().start("extract_alert")
        assert get_progress_tracker() is local
    assert local.started == ["extract_alert"]
    assert isinstance(get_progress_tracker(), NoopProgressTracker)


def test_progress_tracker_scope_does_not_leak_across_threads() -> None:
    set_progress_tracker(NoopProgressTracker())
    first = _RecordingTracker()
    second = _RecordingTracker()
    started = threading.Barrier(2)
    seen: dict[str, bool] = {}

    def _worker(name: str, tracker: _RecordingTracker) -> None:
        with progress_tracker_scope(tracker):
            started.wait(timeout=5)
            seen[name] = get_progress_tracker() is tracker

    threads = [
        threading.Thread(target=_worker, args=("a", first)),
        threading.Thread(target=_worker, args=("b", second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert seen == {"a": True, "b": True}
    assert isinstance(get_progress_tracker(), NoopProgressTracker)
