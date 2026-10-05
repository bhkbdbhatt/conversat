"""Run report models: the value objects every formatter consumes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from conversat.models.assertion import AssertionBase
from conversat.models.response import BotResponse
from conversat.utils import format_duration, percentiles, truncate


def utcnow() -> datetime:
    return datetime.now(UTC)


def computed_fields_are_readonly(*names: str) -> Any:
    """Allow serialised ``computed_field`` values back in as input.

    ``computed_field`` values are emitted by ``model_dump`` but are not real
    fields, so re-validating our own JSON would trip ``extra="forbid"``. Reports
    are written and read back as JSON by the dashboard, the formatters and
    ``conversat report``, so the round trip has to be lossless.
    """
    drop = set(names)

    @model_validator(mode="before")
    @classmethod
    def _strip(cls, data: Any) -> Any:
        if isinstance(data, dict) and drop & data.keys():
            return {k: v for k, v in data.items() if k not in drop}
        return data

    return _strip


class TurnStatus(StrEnum):
    """Outcome of a turn, a case or a whole run."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def is_problem(self) -> bool:
        return self in (TurnStatus.FAILED, TurnStatus.ERROR)


class AssertionOutcome(BaseModel):
    """Result of evaluating one assertion against one reply."""

    model_config = ConfigDict(extra="forbid")

    type: str
    description: str
    passed: bool
    message: str | None = None
    expected: str | None = None
    actual: str | None = None
    duration_ms: float | None = None

    @classmethod
    def from_spec(cls, spec: AssertionBase, **kwargs: Any) -> AssertionOutcome:
        return cls(type=spec.type, description=spec.describe(), **kwargs)


class TurnResult(BaseModel):
    """One user message, the reply and the assertion results."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str | None = None
    request: str | None = None
    response: BotResponse | None = None
    status: TurnStatus = TurnStatus.PASSED
    assertions: list[AssertionOutcome] = Field(default_factory=list)
    duration_ms: float = Field(default=0.0, ge=0)
    attempts: int = Field(default=1, ge=1)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assertion_count(self) -> int:
        return len(self.assertions)

    _read_computed = computed_fields_are_readonly("assertion_count")

    @property
    def failed_assertions(self) -> list[AssertionOutcome]:
        return [a for a in self.assertions if not a.passed]

    @property
    def ok(self) -> bool:
        return self.status is TurnStatus.PASSED

    def summary(self, *, limit: int = 60) -> str:
        if self.error:
            return f"error: {truncate(self.error, limit)}"
        reply = self.response.text if self.response else ""
        return truncate(reply.replace("\n", " "), limit) if reply else "<empty reply>"


class CaseResult(BaseModel):
    """Aggregated result of one test case."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: TurnStatus = TurnStatus.PASSED
    tags: list[str] = Field(default_factory=list)
    connector: str = "unknown"
    turns: list[TurnResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return max((t.duration_ms for t in self.turns), default=0.0) or (
            (self.finished_at - self.started_at).total_seconds() * 1000
        )

    @property
    def latencies(self) -> list[float]:
        return [t.response.latency_ms for t in self.turns if t.response and t.response.latency_ms]

    @property
    def ok(self) -> bool:
        return self.status is TurnStatus.PASSED


class RunTotals(BaseModel):
    """Counters shown in the summary line and in machine-readable reports."""

    cases: int = 0
    cases_passed: int = 0
    cases_failed: int = 0
    cases_errored: int = 0
    cases_skipped: int = 0
    turns: int = 0
    turns_passed: int = 0
    assertions: int = 0
    assertions_passed: int = 0
    duration_ms: float = 0.0
    response_p50_ms: float = 0.0
    response_p95_ms: float = 0.0

    @property
    def pass_rate(self) -> float:
        return (self.cases_passed / self.cases * 100) if self.cases else 0.0

    @classmethod
    def from_cases(cls, cases: list[CaseResult], *, duration_ms: float = 0.0) -> RunTotals:
        turns = [t for case in cases for t in case.turns]
        assertions = [a for t in turns for a in t.assertions]
        latencies = [t.response.latency_ms for t in turns if t.response and t.response.latency_ms]
        pct = percentiles(latencies)
        return cls(
            cases=len(cases),
            cases_passed=sum(1 for c in cases if c.status is TurnStatus.PASSED),
            cases_failed=sum(1 for c in cases if c.status is TurnStatus.FAILED),
            cases_errored=sum(1 for c in cases if c.status is TurnStatus.ERROR),
            cases_skipped=sum(1 for c in cases if c.status is TurnStatus.SKIPPED),
            turns=len(turns),
            turns_passed=sum(1 for t in turns if t.status is TurnStatus.PASSED),
            assertions=len(assertions),
            assertions_passed=sum(1 for a in assertions if a.passed),
            duration_ms=duration_ms,
            response_p50_ms=pct.p50,
            response_p95_ms=pct.p95,
        )


class RunReport(BaseModel):
    """Everything a run produced, in one serialisable object."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    suite: str
    version: str = "0.1.0"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)
    connector: str = "unknown"
    environment: dict[str, Any] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)
    totals: RunTotals = Field(default_factory=RunTotals)
    labels: list[str] = Field(default_factory=list, description="CI labels / tags applied to the run")

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() * 1000 or self.totals.duration_ms

    @property
    def ok(self) -> bool:
        return not any(c.status.is_problem for c in self.cases)

    @property
    def failed_cases(self) -> list[CaseResult]:
        return [c for c in self.cases if c.status.is_problem]

    def case(self, name: str) -> CaseResult | None:
        return next((c for c in self.cases if c.name == name), None)

    def recompute_totals(self) -> Self:
        self.totals = RunTotals.from_cases(self.cases, duration_ms=self.duration_ms)
        return self

    def summary_line(self) -> str:
        t = self.totals
        return (
            f"{t.cases_passed}/{t.cases} cases passed | "
            f"{t.assertions_passed}/{t.assertions} assertions | "
            f"p95 {format_duration(t.response_p95_ms)} | "
            f"{format_duration(self.duration_ms)}"
        )

    def exit_code(self) -> int:
        """0 = green, 1 = failing assertions, 2 = errors, 5 = nothing ran."""
        if not self.cases:
            return 5
        if self.totals.cases_errored:
            return 2
        if self.totals.cases_failed:
            return 1
        return 0
