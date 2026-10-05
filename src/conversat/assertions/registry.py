"""Strategy registry.

Custom strategies are one decorator away::

    from conversat.assertions import register

    @register("starts_with_hello")
    def check(spec, ctx):
        return AssertionResult(ctx.text.startswith("hello"))
"""

from __future__ import annotations

from conversat.assertions.base import AssertionContext, AssertionResult, Handler
from conversat.errors import RegistryError
from conversat.models.assertion import AssertionBase

_STRATEGIES: dict[str, Handler] = {}
_BUILTINS_LOADED = False


def register(name: str, *, override: bool = False) -> Callable[[Handler], Handler]:
    """Register a handler for an assertion ``type``."""

    def decorator(handler: Handler) -> Handler:
        if name in _STRATEGIES and not override:
            raise RegistryError(f"assertion strategy {name!r} is already registered")
        _STRATEGIES[name] = handler
        return handler

    return decorator


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from conversat.assertions import strategies  # noqa: F401  (import registers handlers)


def available() -> list[str]:
    """Names of every registered assertion strategy (sorted)."""
    _ensure_builtins()
    return sorted(_STRATEGIES)


def get(name: str) -> Handler:
    _ensure_builtins()
    try:
        return _STRATEGIES[name]
    except KeyError:
        raise RegistryError(
            f"unknown assertion strategy {name!r}; available: {', '.join(available())}"
        ) from None


def evaluate(spec: AssertionBase, context: AssertionContext) -> AssertionResult:
    """Dispatch a parsed assertion spec to its handler."""
    return get(spec.type)(spec, context)


def unregister(name: str) -> None:
    _STRATEGIES.pop(name, None)


def reset() -> None:
    """Drop every registration (test helper)."""
    _STRATEGIES.clear()
    global _BUILTINS_LOADED
    _BUILTINS_LOADED = False

