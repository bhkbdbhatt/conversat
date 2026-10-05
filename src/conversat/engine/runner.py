"""The conversat test runner.

Executes a :class:`~conversat.models.suite.TestSuite` case by case, creating one
connector instance per case (so conversations stay isolated), rendering
templates, applying timeouts/retries and evaluating assertions.

    report = await TestRunner(suite).run()
    sys.exit(report.exit_code())
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from conversat.assertions import AssertionContext, AssertionResult, evaluate
from conversat.engine.base import Connector
from conversat.errors import ConnectorError, ConnectorTimeoutError
from conversat.models.assertion import AllOfAssertion, AnyOfAssertion, ErrorAssertion, NotAssertion
from conversat.models.report import (
    AssertionOutcome,
    CaseResult,
    RunReport,
    TurnResult,
    TurnStatus,
    utcnow,
)
from conversat.models.response import BotResponse
from conversat.models.suite import ConnectorConfig, RetryPolicy, TestCase, TestSuite, Turn
from conversat.utils import render_template


@dataclass(slots=True)
class RunOptions:
    """Knobs for a single run."""

    concurrency: int = 4
    fail_fast: bool = False
    include_tags: set[str] = field(default_factory=set)
    exclude_tags: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    name_pattern: str | None = None
    default_timeout: float | None = None
    continue_on_error: bool = True
    dry_run: bool = False

    @property
    def has_filters(self) -> bool:
        return bool(self.include_tags or self.exclude_tags or self.names or self.name_pattern)


class Listener(Protocol):
    """Hook interface for live output (see :mod:`conversat.reporting.console`)."""

    def on_run_start(self, report: RunReport) -> None: ...

    def on_case_start(self, case: TestCase, index: int, total: int) -> None: ...

    def on_turn_result(self, case: TestCase, turn: TurnResult) -> None: ...

    def on_case_end(self, result: CaseResult) -> None: ...

    def on_run_end(self, report: RunReport) -> None: ...


class NullListener:
    """Listener that does nothing (the default)."""

    def on_run_start(self, report: RunReport) -> None:
        return None

    def on_case_start(self, case: TestCase, index: int, total: int) -> None:
        return None

    def on_turn_result(self, case: TestCase, turn: TurnResult) -> None:
        return None

    def on_case_end(self, result: CaseResult) -> None:
        return None

    def on_run_end(self, report: RunReport) -> None:
        return None


def _expects_error(specs: Iterable[Any]) -> bool:
    """True when a turn explicitly asserts that the bot failed.

    Lets a suite test error handling on purpose: ``expect: [{no_error: false}]``
    passes when the connector reports an error, instead of failing the case.
    """
    for spec in specs:
        if isinstance(spec, ErrorAssertion):
            if spec.expect_error:
                return True
        elif isinstance(spec, AllOfAssertion | AnyOfAssertion):
            if _expects_error(spec.assertions):
                return True
        elif isinstance(spec, NotAssertion):
            if isinstance(spec.assertion, ErrorAssertion) and not spec.assertion.expect_error:
                return True
    return False


@dataclass(slots=True)
class _Outcome:
    """Internal result of running one turn (already converted for reporting)."""

    status: TurnStatus
    assertions: list[AssertionOutcome]
    duration_ms: float = 0.0
    response: BotResponse | None = None
    error: str | None = None


class TestRunner:
    """Run one suite against one connector."""

    def __init__(
        self,
        suite: TestSuite,
        *,
        connector_factory: Callable[[ConnectorConfig], Connector] | None = None,
        listener: Listener | None = None,
        options: RunOptions | None = None,
        run_id: str | None = None,
        version: str = "0.1.0",
        environment: dict[str, Any] | None = None,
        labels: Sequence[str] | None = None,
        on_event: Callable[..., Any] | None = None,
    ) -> None:
        self.suite = suite
        self.options = options or RunOptions()
        self.listener: Listener = listener or NullListener()
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.version = version
        self.environment = dict(environment or {})
        self.labels = list(labels or [])
        self._factory = connector_factory or self._default_factory
        self._on_event = on_event
        self._stop = asyncio.Event()
    # -- public API ------------------------------------------------------- #
    def selected_cases(self) -> list[TestCase]:
        return [
            self.suite.resolve_case(case)
            for case in self.suite.select(
                include_tags=self.options.include_tags or None,
                exclude_tags=self.options.exclude_tags or None,
                names=self.options.names or None,
                name_pattern=self.options.name_pattern,
            )
        ]

    async def run(self) -> RunReport:
        """Execute the suite and return the aggregated report."""
        cases = self.selected_cases()
        report = RunReport(
            run_id=self.run_id,
            suite=self.suite.name,
            version=self.version,
            started_at=utcnow(),
            connector=self.suite.connector.label,
            environment=self.environment,
            labels=self.labels,
        )
        self._notify("run_start", report)

        if self.options.dry_run:
            report.cases = [
                CaseResult(
                    name=case.name,
                    status=TurnStatus.SKIPPED,
                    tags=case.tags,
                    connector=self.suite.connector_for(case).label,
                    metadata={"dry_run": True},
                )
                for case in cases
            ]
        else:
            semaphore = asyncio.Semaphore(max(1, self.options.concurrency))
            tasks = [
                asyncio.create_task(self._run_case(case, index, len(cases), semaphore, report))
                for index, case in enumerate(cases, start=1)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for case, result in zip(cases, results, strict=True):
                if isinstance(result, BaseException):
                    report.cases.append(
                        CaseResult(
                            name=case.name,
                            status=TurnStatus.ERROR,
                            tags=case.tags,
                            connector=self.suite.connector_for(case).label,
                            error=f"{type(result).__name__}: {result}",
                        )
                    )
                else:
                    report.cases.append(result)

        report.finished_at = utcnow()
        report.recompute_totals()
        self._notify("run_end", report)
        return report

    # -- case execution --------------------------------------------------- #
    async def _run_case(
        self,
        case: TestCase,
        index: int,
        total: int,
        semaphore: asyncio.Semaphore,
        report: RunReport,
    ) -> CaseResult:
        result = CaseResult(
            name=case.name,
            tags=list(case.tags),
            connector=self.suite.connector_for(case).label,
            started_at=utcnow(),
            status=TurnStatus.PASSED,
            metadata={"suite": self.suite.name, "case": case.name},
        )
        async with semaphore:
            if self._stop.is_set():
                result.status = TurnStatus.SKIPPED
                result.finished_at = utcnow()
                self._notify("case_end", result)
                return result

            self._notify("case_start", case, index, total)
            try:
                connector = self._factory(self.suite.connector_for(case))
            except Exception as exc:  # noqa: BLE001 - surfaced as a case error
                result.status = TurnStatus.ERROR
                result.error = f"cannot create connector: {exc}"
                result.finished_at = utcnow()
                self._after_case(result, report)
                return result

            try:
                async with connector:
                    for turn_index, turn in enumerate(case.all_turns()):
                        turn_result = await self._run_turn(case, turn, turn_index, connector)
                        result.turns.append(turn_result)
                        self._notify("turn_result", case, turn_result)
                        if turn_result.status.is_problem:
                            result.status = turn_result.status
                            if turn_result.error:
                                result.error = turn_result.error
                            if self.options.fail_fast or not self.options.continue_on_error:
                                result.metadata["stopped_early"] = True
                                if self.options.fail_fast:
                                    self._stop.set()
                                break
            except ConnectorError as exc:
                result.status = TurnStatus.ERROR
                result.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - never crash the whole run
                result.status = TurnStatus.ERROR
                result.error = f"{type(exc).__name__}: {exc}"
            finally:
                result.finished_at = utcnow()

            self._after_case(result, report)
            return result

    def _after_case(self, result: CaseResult, report: RunReport) -> None:
        self._notify("case_end", result)

    # -- turn execution --------------------------------------------------- #
    async def _run_turn(
        self,
        case: TestCase,
        turn: Turn,
        index: int,
        connector: Connector,
    ) -> TurnResult:
        timeout = self._timeout_for(case, turn)
        retry = turn.retry or case.retry
        request = self._render_turn(case, turn, index)
        result = TurnResult(index=index, name=turn.name, request=request)

        if turn.clear_context:
            try:
                await connector.reset()
            except Exception as exc:  # noqa: BLE001
                result.status = TurnStatus.ERROR
                result.error = f"reset failed: {exc}"
                return result

        attempts = retry.attempts if retry else 1
        history = [e.response for e in connector.exchanges]
        context = AssertionContext(
            response=BotResponse(text=""),
            request=request,
            turn=turn,
            case=case,
            suite=self.suite,
            index=index,
            history=history,
            connector=connector,
        )

        last: _Outcome | None = None
        for attempt in range(1, attempts + 1):
            if retry and attempt > 1:
                delay = retry.delay_for(attempt)
                if delay:
                    await asyncio.sleep(delay)
            result.attempts = attempt
            last = await self._attempt(case, turn, request, connector, context, timeout)
            if not last.status.is_problem or not retry or not retry.should_retry(last.status.value):
                break

        assert last is not None
        result.status = last.status
        result.assertions = last.assertions
        result.error = last.error
        result.response = last.response
        result.duration_ms = last.duration_ms
        if not turn.expect:
            result.metadata["unasserted"] = True
        return result

    async def _attempt(
        self,
        case: TestCase,
        turn: Turn,
        request: str | None,
        connector: Connector,
        context: AssertionContext,
        timeout: float | None,
    ) -> _Outcome:
        started = time.perf_counter()
        try:
            if timeout is not None:
                response = await asyncio.wait_for(
                    connector.send(request or "", timeout=timeout), timeout=timeout + 0.5
                )
            else:
                response = await connector.send(request or "")
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - started) * 1000
            limit = f" (limit {timeout:g}s)" if timeout else ""
            return _Outcome(
                status=TurnStatus.ERROR,
                assertions=[],
                duration_ms=elapsed,
                error=f"timeout after {elapsed:.0f}ms{limit}",
            )
        except ConnectorTimeoutError as exc:
            return _Outcome(
                status=TurnStatus.ERROR,
                assertions=[],
                duration_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
        except ConnectorError as exc:
            return _Outcome(
                status=TurnStatus.ERROR,
                assertions=[],
                duration_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - report, do not propagate
            return _Outcome(
                status=TurnStatus.ERROR,
                assertions=[],
                duration_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - started) * 1000
        context.response = response
        outcomes, status = self._evaluate(turn, context, response)
        return _Outcome(
            status=status,
            assertions=outcomes,
            duration_ms=elapsed,
            response=response,
            error=response.error if status is TurnStatus.ERROR else None,
        )

    def _evaluate(
        self,
        turn: Turn,
        context: AssertionContext,
        response: BotResponse,
    ) -> tuple[list[AssertionOutcome], TurnStatus]:
        outcomes: list[AssertionOutcome] = []
        failed = False
        for spec in turn.expect:
            started = time.perf_counter()
            try:
                verdict: AssertionResult = evaluate(spec, context)
            except Exception as exc:  # noqa: BLE001
                outcomes.append(
                    AssertionOutcome(
                        type=spec.type,
                        description=spec.describe(),
                        passed=False,
                        message=f"{type(exc).__name__}: {exc}",
                        expected=spec.describe(),
                        actual=response.text,
                    )
                )
                failed = True
                continue
            outcomes.append(
                AssertionOutcome(
                    type=spec.type,
                    description=spec.describe(),
                    passed=verdict.passed,
                    message=verdict.message,
                    expected=verdict.expected,
                    actual=verdict.actual,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            failed = failed or not verdict.passed

        if failed:
            return outcomes, TurnStatus.FAILED
        if response.is_error and not _expects_error(turn.expect):
            return outcomes, TurnStatus.ERROR
        return outcomes, TurnStatus.PASSED

    # -- helpers ---------------------------------------------------------- #
    def _timeout_for(self, case: TestCase, turn: Turn) -> float | None:
        return (
            turn.timeout
            or case.timeout
            or self.suite.defaults.timeout
            or self.options.default_timeout
        )

    def _render_turn(self, case: TestCase, turn: Turn, index: int) -> str | None:
        if turn.send is None:
            return None
        return render_template(turn.send, self._template_context(case, turn, index))

    def _template_context(self, case: TestCase, turn: Turn, index: int) -> dict[str, Any]:
        return {
            "vars": case.variables,
            "case": {"name": case.name, "vars": case.variables, "index": index},
            "suite": {"name": self.suite.name},
            "turn": {"index": index, "name": turn.name},
            "run": {"id": self.run_id, "suite": self.suite.name},
        }

    def _default_factory(self, config: ConnectorConfig) -> Connector:
        from conversat.connectors.registry import create_connector

        return create_connector(config)

    def _notify(self, event: str, *args: Any, **kwargs: Any) -> None:
        handler = getattr(self.listener, f"on_{event}", None)
        if handler is not None:
            handler(*args, **kwargs)
        if self._on_event is not None:
            self._on_event(event, *args, **kwargs)


async def run_suite(
    suite: TestSuite,
    *,
    concurrency: int = 4,
    listener: Listener | None = None,
    **kwargs: Any,
) -> RunReport:
    """Convenience wrapper: build a runner and run it once."""
    options = RunOptions(concurrency=concurrency)
    runner = TestRunner(suite, listener=listener, options=options, **kwargs)
    return await runner.run()


async def run_many(
    suites: Iterable[TestSuite],
    *,
    concurrency: int = 4,
    listener: Listener | None = None,
    **kwargs: Any,
) -> list[RunReport]:
    """Run several suites concurrently and return their reports."""
    runners = [
        TestRunner(
            suite,
            listener=listener,
            options=RunOptions(concurrency=concurrency),
            **kwargs,
        )
        for suite in suites
    ]
    return list(await asyncio.gather(*(runner.run() for runner in runners)))


def case_summary(report: RunReport) -> list[dict[str, Any]]:
    """Flatten a report into a list of plain dicts (handy for the dashboard)."""
    rows: list[dict[str, Any]] = []
    for case in report.cases:
        for turn in case.turns:
            rows.append(
                {
                    "suite": report.suite,
                    "case": case.name,
                    "tags": case.tags,
                    "turn": turn.index,
                    "request": turn.request,
                    "reply": turn.response.text if turn.response else None,
                    "status": turn.status.value,
                    "duration_ms": turn.duration_ms,
                    "attempts": turn.attempts,
                    "assertions": [a.model_dump(mode="json") for a in turn.assertions],
                    "error": turn.error,
                }
            )
    return rows
