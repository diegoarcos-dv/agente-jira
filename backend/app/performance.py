from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterator
from uuid import uuid4

logger = logging.getLogger(__name__)
_current_trace: contextvars.ContextVar[PerformanceTrace | None] = contextvars.ContextVar(
    "agente_jira_performance_trace", default=None
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class PerformanceTrace:
    operation: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    proposal_id: str | None = None
    activity_count: int | None = None
    started_at: float = field(default_factory=time.perf_counter)
    events: list[dict[str, Any]] = field(default_factory=list)
    phase_totals: dict[str, float] = field(default_factory=dict)
    jira_call_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    max_concurrency: int = 1
    _active_reads: int = 0
    _mutex: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def current_request_id(self) -> str:
        return self.request_id

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            self.phase_totals[name] = round(self.phase_totals.get(name, 0.0) + duration_ms, 1)

    def call_started(self) -> None:
        with self._mutex:
            self._active_reads += 1
            self.max_concurrency = max(self.max_concurrency, self._active_reads)

    def call_finished(self) -> None:
        with self._mutex:
            self._active_reads = max(0, self._active_reads - 1)

    def record_call(
        self,
        operation: str,
        duration_ms: float,
        *,
        result: str = "OK",
        cache_status: str = "MISS",
        phase: str = "jira_read",
        proposal_id: str | None = None,
        row_id: str | None = None,
    ) -> None:
        self.jira_call_count += 1
        if cache_status == "HIT":
            self.cache_hits += 1
        elif cache_status == "MISS":
            self.cache_misses += 1
        self.events.append(
            {
                "operation": operation,
                "duration_ms": round(duration_ms, 1),
                "phase": phase,
                "cache_status": cache_status,
                "result": result,
                "request_id": self.request_id,
                "proposal_id": proposal_id or self.proposal_id,
                "row_id": row_id,
            }
        )

    def record_cache_event(
        self,
        operation: str,
        *,
        cache_status: str,
        phase: str,
        proposal_id: str | None = None,
        row_id: str | None = None,
    ) -> None:
        if cache_status == "HIT":
            self.cache_hits += 1
        elif cache_status == "MISS":
            self.cache_misses += 1
        self.events.append(
            {
                "operation": operation,
                "duration_ms": 0.0,
                "phase": phase,
                "cache_status": cache_status,
                "result": "CACHE",
                "request_id": self.request_id,
                "proposal_id": proposal_id or self.proposal_id,
                "row_id": row_id,
            }
        )

    def record_phase(self, name: str, duration_ms: float) -> None:
        self.phase_totals[name] = round(self.phase_totals.get(name, 0.0) + duration_ms, 1)

    def summary(self, *, status_code: int | None = None) -> dict[str, Any]:
        total_ms = round((time.perf_counter() - self.started_at) * 1000, 1)
        slowest = max(self.phase_totals.items(), key=lambda item: item[1], default=(None, 0.0))
        calls_by_operation: dict[str, int] = {}
        cache_events_by_operation: dict[str, dict[str, int]] = {}
        for event in self.events:
            operation = str(event.get("operation") or "unknown")
            if event.get("result") != "CACHE":
                calls_by_operation[operation] = calls_by_operation.get(operation, 0) + 1
            else:
                status = str(event.get("cache_status") or "unknown").lower()
                counters = cache_events_by_operation.setdefault(operation, {"hit": 0, "miss": 0})
                if status in counters:
                    counters[status] += 1
        return {
            "operation": self.operation,
            "request_id": self.request_id,
            "duration_ms": total_ms,
            "phase_durations_ms": dict(self.phase_totals),
            "slowest_phase": {"name": slowest[0], "duration_ms": slowest[1]} if slowest[0] else None,
            "jira_call_count": self.jira_call_count,
            "calls_by_operation": calls_by_operation,
            "cache_events_by_operation": cache_events_by_operation,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "max_concurrency": self.max_concurrency,
            "proposal_id": self.proposal_id,
            "activity_count": self.activity_count,
            "status_code": status_code,
            "events": list(self.events),
            "finished_at": _iso_now(),
        }


class PerformanceRegistry:
    def __init__(self, max_entries: int = 50) -> None:
        self.max_entries = max(10, max_entries)
        self._items: list[dict[str, Any]] = []
        self._mutex = threading.Lock()

    def add(self, summary: dict[str, Any]) -> None:
        with self._mutex:
            self._items.append(summary)
            del self._items[:-self.max_entries]

    def latest(self) -> dict[str, Any] | None:
        with self._mutex:
            return dict(self._items[-1]) if self._items else None

    def list(self) -> list[dict[str, Any]]:
        with self._mutex:
            return [dict(item) for item in self._items]


def current_trace() -> PerformanceTrace | None:
    return _current_trace.get()


def set_trace(trace: PerformanceTrace) -> contextvars.Token[PerformanceTrace | None]:
    return _current_trace.set(trace)


def reset_trace(token: contextvars.Token[PerformanceTrace | None]) -> None:
    _current_trace.reset(token)


def log_summary(summary: dict[str, Any]) -> None:
    logger.info("performance_summary %s", json.dumps(summary, ensure_ascii=False, sort_keys=True))
