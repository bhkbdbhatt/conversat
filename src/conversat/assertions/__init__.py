"""Assertion strategies: pure models in :mod:`conversat.models.assertion`,
behaviour here."""

from __future__ import annotations

from conversat.assertions.base import AssertionContext, AssertionResult, fail, ok
from conversat.assertions.registry import (
    available,
    evaluate,
    get,
    register,
    unregister,
)
from conversat.assertions.strategies import *  # noqa: F401,F403  (registers handlers)

__all__ = [
    "AssertionContext",
    "AssertionResult",
    "available",
    "evaluate",
    "fail",
    "get",
    "ok",
    "register",
    "unregister",
]
