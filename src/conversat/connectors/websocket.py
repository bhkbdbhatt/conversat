"""WebSocket connector (websockets)."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from conversat.engine.base import Connector
from conversat.errors import ConnectorError, ConnectorTimeoutError
from conversat.models.response import BotResponse, response_from_payload
from conversat.utils import extract_by_path, render_template

DEFAULT_WS_FALLBACK_KEYS = (
    "reply",
    "message",
    "text",
    "content",
    "output",
    "response",
    "answer",
    "payload.reply",
    "choices[0].message.content",
)


class WebSocketConfig(BaseModel):
    """How to open a socket, frame messages and read replies."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    subprotocols: list[str] = Field(default_factory=list)

    request_template: str = Field(
        default='{"message": "{{text}}"}', description="Outgoing frame template"
    )
    send_as_json: bool = True
    response_text_path: str | None = Field(
        default=None, description="JSON path to the reply inside a JSON frame"
    )
    fallback_keys: list[str] = Field(default_factory=lambda: list(DEFAULT_WS_FALLBACK_KEYS))

    open_timeout: float = Field(default=10.0, gt=0)
    response_timeout: float = Field(default=15.0, gt=0)
    close_timeout: float = Field(default=5.0, gt=0)
    max_frame_bytes: int = Field(default=2_000_000, gt=0)
    receive_json: bool = Field(
        default=True, description="Decode frames as JSON when possible"
    )
    ping_interval: float | None = Field(default=None, ge=0)
    history_size: int = Field(default=100, ge=0, description="0 disables the local transcript")
    handshake_paths: list[str] = Field(
        default_factory=list, description="Messages sent right after connect, in order"
    )
    send_mode: Literal["template", "raw"] = "template"
    open_extra: dict[str, Any] = Field(
        default_factory=dict, description="Extra kwargs for websockets.connect"
    )


class WebSocketConnector(Connector):
    """``websocket`` -- one long-lived socket per test case."""

    type_name = "websocket"
    config_model = WebSocketConfig

    def __init__(self, config: WebSocketConfig | dict[str, Any] | None = None, **kwargs: Any) -> None:
        cfg = config if isinstance(config, WebSocketConfig) else WebSocketConfig.model_validate(config or {})
        super().__init__(cfg)
        self._ws: Any = kwargs.pop("ws", None)
        self._owns_ws = self._ws is None
        self._extra = kwargs

    async def connect(self) -> None:
        if self._ws is not None:
            return
        cfg: WebSocketConfig = self.config
        try:
            from websockets.asyncio.client import connect as ws_connect
        except ImportError:  # pragma: no cover - very old websockets
            from websockets.client import connect as ws_connect  # type: ignore[no-redef]

        kwargs: dict[str, Any] = {
            "open_timeout": cfg.open_timeout,
            "close_timeout": cfg.close_timeout,
            "max_size": cfg.max_frame_bytes,
            "extra_headers": render_template(cfg.headers, {}),
            **cfg.open_extra,
        }
        if cfg.subprotocols:
            kwargs["subprotocols"] = cfg.subprotocols
        if cfg.ping_interval is not None:
            kwargs["ping_interval"] = cfg.ping_interval
        try:
            self._ws = await ws_connect(cfg.url, **kwargs)
        except Exception as exc:  # noqa: BLE001 - normalise socket failures
            raise ConnectorError(f"cannot connect to {cfg.url}: {exc}", connector=self.type_name) from exc

        for handshake in cfg.handshake_paths:
            await self._ws.send(json.dumps({"message": handshake}))
        self.metadata["url"] = cfg.url

    async def close(self) -> None:
        if self._ws is not None and self._owns_ws:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001, S110 - closing must never raise
                pass
            self._ws = None

    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        import asyncio

        cfg: WebSocketConfig = self.config
        if self._ws is None:
            await self.connect()

        frame = (
            text
            if cfg.send_mode == "raw"
            else json.dumps(render_template(cfg.request_template, {"text": text}))
        )
        started = time.perf_counter()
        try:
            await self._ws.send(frame)
            wait_for = timeout or cfg.response_timeout
            raw_frame = await asyncio.wait_for(self._ws.recv(), timeout=wait_for)
        except asyncio.TimeoutError:
            raise ConnectorTimeoutError(
                f"no frame within {timeout or cfg.response_timeout}s", connector=self.type_name
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"socket error: {exc}", connector=self.type_name) from exc

        elapsed = (time.perf_counter() - started) * 1000
        payload = self._decode(raw_frame, cfg)
        response = response_from_payload(
            payload,
            text_path=cfg.response_text_path,
            fallback_keys=tuple(cfg.fallback_keys),
            latency_ms=elapsed,
            metadata={"url": cfg.url, "raw_frame": _preview(raw_frame)},
        )
        if cfg.history_size == 0:
            self.exchanges.clear()
        return self.record(text, response, elapsed)

    @staticmethod
    def _decode(raw_frame: Any, cfg: WebSocketConfig) -> Any:
        if isinstance(raw_frame, (bytes, bytearray)):
            try:
                raw_frame = raw_frame.decode("utf-8")
            except UnicodeDecodeError:
                return {"binary": _preview(raw_frame)}
        if isinstance(raw_frame, str) and cfg.receive_json:
            stripped = raw_frame.strip()
            if stripped[:1] in "{[":
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return raw_frame
        return raw_frame


def _preview(frame: Any, limit: int = 200) -> Any:
    if isinstance(frame, (bytes, bytearray)):
        frame = frame[:limit]
        return {"bytes": len(frame), "hex": frame[:16].hex()}
    text = str(frame)
    return text if len(text) <= limit else text[:limit] + "..."


def reply_from_frame(frame: Any, path: str | None = None) -> str:
    """Utility for tests/scripts: extract the text out of a raw WS frame."""
    payload: Any = frame
    if isinstance(frame, (bytes, bytearray)):
        payload = frame.decode("utf-8", "replace")
    if isinstance(payload, str) and payload.strip()[:1] in "{[":
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return payload
    if path:
        found = extract_by_path(payload, path)
        if found is not None:
            return str(found)
    return response_from_payload(payload).text
