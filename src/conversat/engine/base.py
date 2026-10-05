"""The connector contract that every bot adapter implements."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from conversat.errors import ConnectorError
from conversat.models.response import BotResponse


@dataclass(slots=True)
class Exchange:
    """A single request/reply pair recorded during a run."""

    request: str | None
    response: BotResponse
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class Connector(ABC):
    """Base class for everything that can talk to a bot.

    A connector is used as an async context manager and owns exactly one
    conversation (so the runner creates one per test case)::

        async with MyConnector(config) as bot:
            reply = await bot.send("hello")
            await bot.close()
    """

    #: Registry name, used in reports.
    type_name: str = "connector"
    #: Config model for this connector (kept as a class attribute).
    config_model: type | None = None

    def __init__(self, config: Any | None = None) -> None:
        self.config = config
        self.exchanges: list[Exchange] = []
        self.metadata: dict[str, Any] = {}

    # -- lifecycle -------------------------------------------------------- #
    @abstractmethod
    async def connect(self) -> None:
        """Establish the session (open a socket, launch a browser, ...)."""

    @abstractmethod
    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        """Send one user message and return the bot's reply."""

    async def close(self) -> None:
        """Release resources. Must be safe to call twice."""

    async def reset(self) -> None:
        """Start a fresh conversation, keeping the connection when possible."""

    async def __aenter__(self) -> Connector:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # -- helpers for subclasses ------------------------------------------- #
    def record(self, request: str | None, response: BotResponse, duration_ms: float) -> BotResponse:
        """Append an exchange to the transcript and stamp the latency."""
        response.latency_ms = duration_ms
        self.exchanges.append(
            Exchange(request=request, response=response, duration_ms=duration_ms)
        )
        return response

    @property
    def transcript(self) -> list[Exchange]:
        return list(self.exchanges)

    @property
    def replies(self) -> list[str]:
        return [e.response.text for e in self.exchanges]

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<{type(self).__name__} exchanges={len(self.exchanges)}>"


class SyncFunctionConnector(Connector):
    """Adapter that turns a plain callable into a connector.

    Useful for tests, notebooks and wrapping an in-process bot::

        bot = SyncFunctionConnector(lambda text: f"echo: {text}")
    """

    type_name = "function"

    def __init__(
        self,
        fn: Any,
        *,
        latency: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(config=None)
        self._fn = fn
        self._latency = latency
        self._name = name or getattr(fn, "__name__", "function")

    async def connect(self) -> None:
        return None

    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        started = time.perf_counter()
        result = self._fn(text)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, BotResponse):
            response = result
        elif isinstance(result, str):
            response = BotResponse(text=result)
        else:
            raise ConnectorError(
                f"function connector must return str or BotResponse, got {type(result).__name__}"
            )
        elapsed = (time.perf_counter() - started) * 1000
        return self.record(text, response, elapsed or self._latency)

    @property
    def name(self) -> str:
        return self._name


class ConnectorSequence(Connector):
    """Replays a fixed list of replies, repeating the last one forever.

    Handy as a stub bot in unit tests and as an offline demo target.
    """

    type_name = "sequence"

    def __init__(
        self,
        replies: Iterable[str],
        *,
        repeat_last: bool = True,
        error_at: set[int] | None = None,
    ) -> None:
        super().__init__(config=None)
        self._replies = [str(r) for r in replies]
        if not self._replies:
            raise ConnectorError("sequence connector needs at least one reply")
        self._repeat_last = repeat_last
        self._error_at = error_at or set()
        self._cursor = 0

    async def connect(self) -> None:
        self._cursor = 0

    async def reset(self) -> None:
        self._cursor = 0

    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        index = self._cursor
        if index >= len(self._replies):
            if not self._repeat_last:
                raise ConnectorError("sequence connector exhausted", connector="sequence")
            index = len(self._replies) - 1
        else:
            self._cursor += 1
        started = time.perf_counter()
        if index in self._error_at:
            response = BotResponse(text="", is_error=True, error="scripted failure")
        else:
            response = BotResponse(text=self._replies[index])
        return self.record(text, response, (time.perf_counter() - started) * 1000)
