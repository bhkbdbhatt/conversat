"""Assertion evaluation contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias

from conversat.models.assertion import AssertionBase
from conversat.models.response import BotResponse
from conversat.utils import coerce_text, normalize_text, truncate

if TYPE_CHECKING:  # pragma: no cover
    from conversat.engine.base import Connector
    from conversat.models.suite import TestCase, TestSuite, Turn


@dataclass(slots=True)
class AssertionContext:
    """Everything a strategy may look at while checking one reply."""

    response: BotResponse
    request: str | None = None
    turn: Any = None
    case: Any = None
    suite: Any = None
    index: int = 0
    history: list[BotResponse] = field(default_factory=list)
    connector: Connector | None = None

    @property
    def text(self) -> str:
        return self.response.text

    @property
    def payload(self) -> Any:
        return self.response.payload

    def haystack(self, ignore_case: bool) -> str:
        return normalize_text(self.text, case_sensitive=not ignore_case)

    def needle(self, value: str, ignore_case: bool) -> str:
        return normalize_text(value, case_sensitive=not ignore_case)

    def show(self, value: Any, *, limit: int = 160) -> str:
        return truncate(coerce_text(value), limit).replace("\n", " ")


@dataclass(slots=True)
class AssertionResult:
    """Verdict returned by a strategy."""

    passed: bool
    message: str = ""
    expected: str | None = None
    actual: str | None = None


Handler: TypeAlias = Callable[[AssertionBase, AssertionContext], AssertionResult]


def ok(message: str = "", *, expected: str | None = None, actual: str | None = None) -> AssertionResult:
    return AssertionResult(passed=True, message=message, expected=expected, actual=actual)


def fail(
    message: str,
    *,
    expected: str | None = None,
    actual: str | None = None,
) -> AssertionResult:
    return AssertionResult(passed=False, message=message, expected=expected, actual=actual)
