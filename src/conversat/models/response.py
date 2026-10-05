"""Bot response payloads exchanged with connectors."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from conversat.utils import coerce_text, extract_by_path, redact, truncate


class BotResponse(BaseModel):
    """A single reply produced by the system under test.

    ``text`` is what assertions run against; ``raw`` keeps the untouched
    payload for debugging and for JSON-path assertions.
    """

    model_config = ConfigDict(extra="allow")

    text: str = Field(default="", description="Assertable text extracted from the reply")
    raw: Any = Field(default=None, description="Original payload (dict, str, ...)")
    latency_ms: float | None = Field(default=None, ge=0, description="Round-trip latency")
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    error: str | None = None
    session_id: str | None = None

    @property
    def ok(self) -> bool:
        return not self.is_error

    @property
    def payload(self) -> Any:
        """The raw payload, falling back to ``text`` when nothing was captured."""
        return self.raw if self.raw is not None else self.text

    def at(self, path: str, default: Any = None) -> Any:
        """Read a JSON path out of the raw payload."""
        return extract_by_path(self.payload, path, default=default)

    def redacted(self) -> BotResponse:
        """A copy safe to persist in a report (secrets masked)."""
        return self.model_copy(update={"raw": redact(self.raw), "metadata": redact(self.metadata)})


def response_from_payload(
    payload: Any,
    *,
    text_path: str | None = None,
    fallback_keys: tuple[str, ...] = (),
    latency_ms: float | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BotResponse:
    """Build a :class:`BotResponse` from a connector payload.

    Resolution order: explicit ``text_path`` -> common reply keys -> the
    payload itself when it is a scalar.
    """
    text = ""
    if text_path:
        found = extract_by_path(payload, text_path, default=None)
        if found is not None:
            text = coerce_text(found)
    if not text:
        for key in fallback_keys:
            found = extract_by_path(payload, key, default=None)
            if found is not None:
                text = coerce_text(found)
                break
    if not text and not isinstance(payload, (dict, list, tuple)):
        text = coerce_text(payload)
    return BotResponse(
        text=text,
        raw=payload,
        latency_ms=latency_ms,
        metadata=metadata or {},
        session_id=session_id,
    )


def describe(response: BotResponse, *, limit: int = 80) -> str:
    """Short human description used in terminal output."""
    if response.error:
        return f"error: {truncate(response.error, limit)}"
    if not response.text:
        return "<empty reply>"
    return truncate(response.text.replace("\n", " "), limit)
