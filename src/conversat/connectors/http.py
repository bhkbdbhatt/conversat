"""HTTP connector built on httpx (async)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from conversat.engine.base import Connector
from conversat.errors import ConnectorError
from conversat.models.response import BotResponse, response_from_payload
from conversat.utils import render_template

DEFAULT_FALLBACK_KEYS = (
    "reply",
    "message",
    "text",
    "content",
    "output",
    "response",
    "answer",
    "data.reply",
    "data.message",
    "choices[0].message.content",
    "result",
)


class HttpConfig(BaseModel):
    """How to POST (or GET) to the bot and where the reply lives."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, description="Endpoint URL")
    method: Literal["POST", "PUT", "PATCH", "GET", "DELETE"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)

    # Body: templates may reference {{text}} and case variables.
    json_body: dict[str, Any] | None = Field(
        default_factory=lambda: {"message": "{{text}}"},
        description="JSON body template; set to null for no body",
    )
    data: dict[str, Any] | None = Field(default=None, description="Form body template")
    content: str | None = Field(default=None, description="Raw body template")

    response_text_path: str | None = Field(
        default=None, description="JSON path to the reply text, e.g. data.reply"
    )
    fallback_keys: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FALLBACK_KEYS),
        description="Paths probed when response_text_path is not set",
    )
    session_id_path: str | None = Field(
        default=None, description="JSON path holding the conversation id to echo back"
    )
    session_id_field: str = Field(
        default="session_id", description="Body field used to carry the session id"
    )

    timeout: float = Field(default=15.0, gt=0)
    expect_status: list[int] = Field(
        default_factory=lambda: [200, 201, 202, 204], description="Acceptable status codes"
    )
    verify: bool | Literal[False] = True
    follow_redirects: bool = True
    max_connections: int = Field(default=10, ge=1)
    extra_json: dict[str, Any] = Field(
        default_factory=dict, description="Extra top-level JSON fields added to every request"
    )


class HttpConnector(Connector):
    """``http`` -- talk to a JSON (or text) HTTP endpoint."""

    type_name = "http"
    config_model = HttpConfig

    def __init__(self, config: HttpConfig | dict[str, Any] | None = None, **kwargs: Any) -> None:
        cfg = config if isinstance(config, HttpConfig) else HttpConfig.model_validate(config or {})
        super().__init__(cfg)
        self._client: Any = kwargs.pop("client", None)
        self._owns_client = self._client is None
        self._client_kwargs = kwargs
        self._session_id: str | None = None

    # -- lifecycle -------------------------------------------------------- #
    async def connect(self) -> None:
        import httpx

        if self._client is None:
            cfg: HttpConfig = self.config
            self._client = httpx.AsyncClient(
                timeout=cfg.timeout,
                verify=cfg.verify,
                follow_redirects=cfg.follow_redirects,
                cookies=cfg.cookies or None,
                limits=httpx.Limits(max_connections=cfg.max_connections),
                **self._client_kwargs,
            )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    # -- protocol --------------------------------------------------------- #
    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        import httpx

        if self._client is None:
            await self.connect()

        cfg: HttpConfig = self.config
        body = self._build_body(text)
        request_kwargs: dict[str, Any] = {
            "headers": render_template(cfg.headers, {"text": text, "session_id": self._session_id}),
            "params": render_template(cfg.params, {"text": text}),
        }
        if body is not None:
            if cfg.data is not None:
                request_kwargs["data"] = body
            elif cfg.content is not None:
                request_kwargs["content"] = body
            else:
                request_kwargs["json"] = body

        started = time.perf_counter()
        try:
            response = await self._client.request(cfg.method, cfg.url, **request_kwargs)
        except httpx.TimeoutException as exc:
            raise ConnectorError(f"request timed out after {cfg.timeout}s: {exc}", connector=self.type_name) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(f"HTTP error: {exc}", connector=self.type_name) from exc

        elapsed = (time.perf_counter() - started) * 1000
        payload = self._parse(response)
        self._capture_session(payload)

        if cfg.expect_status and response.status_code not in cfg.expect_status:
            return self.record(
                text,
                BotResponse(
                    text="",
                    raw=payload,
                    is_error=True,
                    error=f"unexpected status {response.status_code} (expected {cfg.expect_status})",
                ),
                elapsed,
            )

        bot_response = response_from_payload(
            payload,
            text_path=cfg.response_text_path,
            fallback_keys=tuple(cfg.fallback_keys),
            latency_ms=elapsed,
            session_id=self._session_id,
            metadata={"status_code": response.status_code, "url": cfg.url, "method": cfg.method},
        )
        return self.record(text, bot_response, elapsed)

    # -- helpers ---------------------------------------------------------- #
    def _build_body(self, text: str) -> Any:
        cfg: HttpConfig = self.config
        context = {"text": text, "session_id": self._session_id}
        if cfg.data is not None:
            return render_template(cfg.data, context)
        if cfg.content is not None:
            return render_template(cfg.content, context)
        if cfg.json_body is None:
            return None
        body = render_template(cfg.json_body, context)
        if cfg.extra_json:
            body = {**body, **render_template(cfg.extra_json, context)}
        if cfg.session_id_path and self._session_id:
            body = {**body, cfg.session_id_field: self._session_id}
        return body

    @staticmethod
    def _parse(response: Any) -> Any:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                return response.json()
            except ValueError as exc:
                return {"error": f"invalid JSON: {exc}", "body": response.text[:500]}
        if "text" in content_type or not content_type:
            return response.text
        return {"content_type": content_type, "body": response.text[:2000]}

    def _capture_session(self, payload: Any) -> None:
        cfg: HttpConfig = self.config
        if not cfg.session_id_path:
            return
        from conversat.utils import extract_by_path

        value = extract_by_path(payload, cfg.session_id_path)
        if value is not None:
            self._session_id = str(value)
            self.metadata["session_id"] = self._session_id
