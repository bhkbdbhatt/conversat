"""Run suites on behalf of the dashboard and stream progress to the browser.

The CLI owns one-shot runs; this module owns the long-lived ones started from
the UI. Every started run gets its ``run_id`` up front so a client can open a
WebSocket immediately and watch it unfold.
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from conversat.dashboard.store import RunStore
from conversat.engine.loader import load_suites
from conversat.engine.runner import RunOptions, TestRunner
from conversat.errors import ConversatError
from conversat.models.report import CaseResult, RunReport, TurnResult, utcnow
from conversat.models.suite import ConnectorConfig, TestSuite
from conversat.reporting.writer import write_reports
from conversat.utils import redact

QUEUE_SIZE = 512


def system_environment() -> dict[str, Any]:
    """The same small, non-sensitive snapshot ``conversat run`` records."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "os": platform.system(),
        "machine": platform.machine(),
        "cwd": str(Path.cwd()),
    }


@dataclass
class LiveRun:
    """A run plus the event stream the UI replays."""

    run_id: str
    suite: str
    status: str = "queued"
    started_at: str = field(default_factory=lambda: utcnow().isoformat())
    finished_at: str | None = None
    error: str | None = None
    labels: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    report: RunReport | None = None
    _subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "suite": self.suite,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "labels": list(self.labels),
            "events": len(self.events),
        }
        if self.report is not None:
            data["totals"] = self.report.totals.model_dump(mode="json")
            data["cases"] = [
                {"name": case.name, "status": case.status.value, "turns": len(case.turns)}
                for case in self.report.cases
            ]
        return data

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - slow client
                self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def finish(self, report: RunReport | None, *, status: str, error: str | None = None) -> None:
        self.report = report
        self.status = status
        self.error = error
        self.finished_at = utcnow().isoformat()
        self.emit({"type": "done", "status": status, "error": error, "run_id": self.run_id})


class RunService:
    """Starts runs in the background and keeps their event history."""

    def __init__(
        self,
        store: RunStore,
        *,
        output_dir: str | Path = "reports",
        history: int = 50,
        version: str = "0.1.0",
    ) -> None:
        self.store = store
        self.output_dir = Path(output_dir)
        self.history = history
        self.version = version
        self._live: dict[str, LiveRun] = {}
        self._order: list[str] = []
        self._tasks: set[asyncio.Task[None]] = set()

    # -- lifecycle -------------------------------------------------------- #
    def start(self, suites: Iterable[str], options: dict[str, Any] | None = None) -> list[LiveRun]:
        """Schedule one run per suite; returns immediately with their states.

        Must be called from inside the server's event loop -- the background
        task is created there so live events reach connected WebSockets.
        """
        paths = [str(path) for path in suites]
        if not paths:
            raise ConversatError("at least one suite is required")

        opts = options or {}
        variables = {str(k): v for k, v in (opts.get("variables") or {}).items()}
        overrides: dict[str, Any] = {}
        if variables:
            overrides["variables"] = variables
        connector = _connector_override(opts.get("connector"))
        if connector is not None:
            overrides["connector"] = connector
        if opts.get("timeout") is not None:
            overrides["timeout"] = float(opts["timeout"])

        loaded = load_suites(
            paths, overrides=overrides or None
        )  # raises ConversatError on bad input
        run_options = RunOptions(
            concurrency=max(1, int(opts.get("concurrency", 4) or 4)),
            fail_fast=bool(opts.get("fail_fast", False)),
            include_tags=set(opts.get("tags") or []),
            exclude_tags=set(opts.get("exclude_tags") or []),
            names=set(opts.get("cases") or []),
            name_pattern=opts.get("name_pattern") or None,
            default_timeout=opts.get("timeout"),
            dry_run=bool(opts.get("dry_run", False)),
        )
        labels = [str(label) for label in (opts.get("labels") or [])]
        environment = {
            **system_environment(),
            **({} if not variables else {"variables": redact(variables)}),
        }

        started: list[LiveRun] = []
        for suite in loaded:
            live = self._register(
                LiveRun(run_id=f"run-{uuid.uuid4().hex[:12]}", suite=suite.name, labels=labels)
            )
            started.append(live)
            self._spawn(
                self._execute(
                    live,
                    suite,
                    run_options,
                    environment=environment,
                    labels=labels,
                )
            )
        return started

    def _register(self, live: LiveRun) -> LiveRun:
        if live.run_id in self._live:
            self._order.remove(live.run_id)
        self._live[live.run_id] = live
        self._order.append(live.run_id)
        while len(self._order) > self.history:
            self._live.pop(self._order.pop(0), None)
        return live

    def _spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(
        self,
        live: LiveRun,
        suite: TestSuite,
        options: RunOptions,
        *,
        environment: dict[str, Any],
        labels: list[str],
    ) -> None:
        live.status = "running"
        live.emit({"type": "status", "status": "running", "run_id": live.run_id})
        runner = TestRunner(
            suite,
            options=options,
            run_id=live.run_id,
            version=self.version,
            environment=environment,
            labels=labels,
            on_event=_emitter(live),
        )
        try:
            report = await runner.run()
        except ConversatError as exc:
            live.finish(None, status="error", error=str(exc))
            return
        except Exception as exc:  # surfaced to the UI; never crashes the server
            live.finish(None, status="error", error=f"{type(exc).__name__}: {exc}")
            return

        self.store.add(report)
        await asyncio.to_thread(_write, report, self.output_dir)
        live.finish(report, status="passed" if report.ok else "failed")

    # -- queries ---------------------------------------------------------- #
    def get(self, run_id: str) -> LiveRun | None:
        return self._live.get(run_id)

    def list(self) -> list[dict[str, Any]]:
        return [self._live[run_id].snapshot() for run_id in reversed(self._order)]

    def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()


def _write(report: RunReport, output_dir: Path) -> None:
    """Persist the finished run as JSON so ``conversat report`` can find it."""
    with contextlib.suppress(OSError):  # pragma: no cover - unwritable reports dir
        write_reports(report, formats=["json"], output_dir=output_dir)


def _connector_override(value: Any) -> dict[str, Any] | None:
    """Accept ``http`` / ``http:url=...,timeout=5`` / ``{"type": ...}`` overrides.

    Mirrors the CLI's ``--connector`` flag so the UI speaks the same language.
    """
    if not value:
        return None
    if isinstance(value, ConnectorConfig):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    name, _, rest = str(value).partition(":")
    config: dict[str, Any] = {}
    for pair in rest.split(","):
        if not pair.strip():
            continue
        key, _, item = pair.partition("=")
        config[key.strip()] = item.strip()
    return {"type": name.strip(), "config": config}


def _emitter(live: LiveRun) -> Any:
    """Adapt :class:`TestRunner` events into JSON payloads for the UI."""

    def on_event(event: str, *args: Any) -> None:
        if event == "case_start":
            case, index, total = args[0], args[1], args[2]
            live.emit(
                {
                    "type": "case_start",
                    "run_id": live.run_id,
                    "case": case.name,
                    "index": index,
                    "total": total,
                }
            )
        elif event == "turn_result":
            case, turn = args[0], args[1]
            live.emit(
                {
                    "type": "turn_result",
                    "run_id": live.run_id,
                    "case": case.name,
                    **_turn_payload(turn),
                }
            )
        elif event == "case_end":
            live.emit({"type": "case_end", "run_id": live.run_id, **_case_payload(args[0])})
        elif event == "run_end":
            report: RunReport = args[0]
            live.emit(
                {
                    "type": "run_end",
                    "run_id": live.run_id,
                    "totals": report.totals.model_dump(mode="json"),
                    "ok": report.ok,
                }
            )

    return on_event


def _turn_payload(turn: TurnResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": turn.index,
        "name": turn.name,
        "status": str(turn.status),
        "request": turn.request,
        "reply": turn.response.text if turn.response else None,
        "duration_ms": round(turn.duration_ms, 1),
        "attempts": turn.attempts,
        "error": turn.error,
        "assertions": [a.model_dump(mode="json") for a in turn.assertions],
    }
    if turn.response is not None:
        payload["latency_ms"] = turn.response.latency_ms
    return payload


def _case_payload(case: CaseResult) -> dict[str, Any]:
    return {
        "case": case.name,
        "status": case.status.value,
        "tags": list(case.tags),
        "turns": len(case.turns),
        "duration_ms": round(case.duration_ms, 1),
        "error": case.error,
        "assertions": sum(len(t.assertions) for t in case.turns),
        "failed": sum(len(t.failed_assertions) for t in case.turns),
    }
