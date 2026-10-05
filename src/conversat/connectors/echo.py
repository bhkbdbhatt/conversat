"""In-process connectors: echo and scripted.

These need no network and are what the examples and the self-tests run
against, so ``conversat run`` works out of the box.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from conversat.engine.base import Connector
from conversat.models.response import BotResponse


class EchoConfig(BaseModel):
    """Echo the user message back, with optional decoration."""

    model_config = ConfigDict(extra="forbid")

    prefix: str = ""
    suffix: str = ""
    uppercase: bool = False
    repeat: int = Field(default=1, ge=1, le=10)
    delay_ms: float = Field(default=0.0, ge=0)
    template: str | None = Field(
        default=None, description="Reply template, e.g. 'You said: {{text}}' (overrides prefix/suffix)"
    )
    error_on: list[str] = Field(
        default_factory=list, description="Substrings that make the bot return an error"
    )
    empty_on: list[str] = Field(default_factory=list)


class EchoConnector(Connector):
    """``echo`` -- deterministic in-memory bot."""

    type_name = "echo"
    config_model = EchoConfig

    def __init__(self, config: EchoConfig | dict[str, Any] | None = None) -> None:
        super().__init__(self._coerce(config))

    @staticmethod
    def _coerce(config: EchoConfig | dict[str, Any] | None) -> EchoConfig:
        if isinstance(config, EchoConfig):
            return config
        return EchoConfig.model_validate(config or {})

    async def connect(self) -> None:
        self.metadata["connected"] = True

    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        started = time.perf_counter()
        cfg = self.config
        if self.config.delay_ms:
            import asyncio

            await asyncio.sleep(self.config.delay_ms / 1000)

        if any(word and word.lower() in text.lower() for word in cfg.error_on):
            response = BotResponse(text="", is_error=True, error="echo connector was told to fail")
            return self.record(text, response, (time.perf_counter() - started) * 1000)

        if any(word and word.lower() in text.lower() for word in cfg.empty_on):
            response = BotResponse(text="")
            return self.record(text, response, (time.perf_counter() - started) * 1000)

        body = text
        if cfg.template:
            from conversat.utils import render_template

            body = render_template(cfg.template, {"text": text})
        else:
            if cfg.uppercase:
                body = body.upper()
            body = f"{cfg.prefix}{body}{cfg.suffix}"
        reply = " ".join([body] * cfg.repeat)
        return self.record(text, BotResponse(text=reply), (time.perf_counter() - started) * 1000)


class ScriptedConfig(BaseModel):
    """Replay a fixed script of replies."""

    model_config = ConfigDict(extra="forbid")

    replies: list[str] = Field(min_length=1)
    repeat_last: bool = True
    delay_ms: float = Field(default=0.0, ge=0)
    error_at: list[int] = Field(
        default_factory=list, description="0-based reply indexes that should raise an error"
    )
    mode: Literal["sequential", "by_length"] = Field(
        default="sequential",
        description="sequential: consume replies in order; by_length: pick by message length",
    )


class ScriptedConnector(Connector):
    """``scripted`` -- replay canned replies (perfect for CI smoke tests)."""

    type_name = "scripted"
    config_model = ScriptedConfig

    def __init__(self, config: ScriptedConfig | dict[str, Any] | None = None) -> None:
        cfg = config if isinstance(config, ScriptedConfig) else ScriptedConfig.model_validate(config)
        super().__init__(cfg)
        self._cursor = 0

    async def connect(self) -> None:
        self._cursor = 0

    async def reset(self) -> None:
        self._cursor = 0

    def _pick(self, text: str) -> int:
        cfg: ScriptedConfig = self.config
        if cfg.mode == "by_length":
            buckets = {len(reply) for reply in cfg.replies}
            target = min(buckets, key=lambda size: abs(size - len(text)))
            return cfg.replies.index(next(r for r in cfg.replies if len(r) == target))
        index = self._cursor
        if index >= len(cfg.replies):
            if not cfg.repeat_last:
                index = len(cfg.replies) - 1
            else:
                index = len(cfg.replies) - 1
        else:
            self._cursor += 1
        return index

    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        started = time.perf_counter()
        cfg: ScriptedConfig = self.config
        if cfg.delay_ms:
            import asyncio

            await asyncio.sleep(cfg.delay_ms / 1000)

        index = self._pick(text)
        if index in cfg.error_at:
            response = BotResponse(text="", is_error=True, error=f"scripted error at index {index}")
        else:
            response = BotResponse(text=cfg.replies[index])
        return self.record(text, response, (time.perf_counter() - started) * 1000)
