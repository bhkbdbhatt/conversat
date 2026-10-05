"""Small shared helpers (templating, JSON paths, text normalisation, stats).

Kept in a single module on purpose: everything here is dependency-free and
used by at least three subsystems.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "Percentile",
    "coerce_text",
    "extract_by_path",
    "flatten",
    "format_duration",
    "indent_block",
    "normalize_text",
    "percentile",
    "percentiles",
    "redact",
    "render_template",
    "shorten",
    "stable_hash",
    "truncate",
    "is_secret_key",
]
_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")
_PATH_TOKEN_RE = re.compile(r"[^.\[\]]+|\[\s*-?\d+\s*\]")
_PLACEHOLDER_DEFAULT = "{{var}}"


def render_template(value: Any, context: Mapping[str, Any], *, keep_missing: bool = True) -> Any:
    """Recursively substitute ``{{ name }}`` / ``{{ a.b }}`` placeholders.

    Mappings and sequences are walked; unknown placeholders are left untouched
    when ``keep_missing`` is true so that bots can legitimately receive
    literal ``{{ }}`` text.
    """
    if isinstance(value, str):
        return _render_string(value, context, keep_missing=keep_missing)
    if isinstance(value, Mapping):
        return {k: render_template(v, context, keep_missing=keep_missing) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        rendered = [render_template(v, context, keep_missing=keep_missing) for v in value]
        return type(value)(rendered) if isinstance(value, tuple) else rendered
    return value


def _render_string(text: str, context: Mapping[str, Any], *, keep_missing: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        found, value = lookup(context, path)
        if not found:
            return match.group(0) if keep_missing else ""
        return value if isinstance(value, str) else str(value)

    return _TEMPLATE_RE.sub(replace, text)


def lookup(context: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve a dotted path such as ``vars.user.name`` against nested mappings."""
    current: Any = context
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def extract_by_path(data: Any, path: str | None, *, default: Any = None) -> Any:
    """Read a value out of a nested JSON structure.

    Supports ``a.b``, ``a[0].b``, ``$.a.b`` and ``[0].a`` styles. Returns
    ``default`` when any segment is missing.
    """
    if not path:
        return data
    cleaned = path.strip()
    if cleaned in ("", "$", "."):
        return data
    if cleaned.startswith("$."):
        cleaned = cleaned[2:]
    elif cleaned == "$":
        return data

    current = data
    for token in _PATH_TOKEN_RE.findall(cleaned):
        token = token.strip()
        if not token:
            continue
        if token.startswith("["):
            try:
                index = int(token[1:-1])
            except ValueError:
                return default
            if isinstance(current, Sequence) and not isinstance(current, str):
                if -len(current) <= index < len(current):
                    current = current[index]
                else:
                    return default
            else:
                return default
            continue
        if isinstance(current, Mapping):
            if token not in current:
                return default
            current = current[token]
        else:
            return default
    return current


def coerce_text(value: Any) -> str:
    """Best-effort conversion of an arbitrary payload into assertable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, Mapping):
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, Sequence):
        parts = [coerce_text(item) for item in value]
        return " ".join(p for p in parts if p)
    return str(value)


def normalize_text(text: str, *, case_sensitive: bool = False, collapse_whitespace: bool = True) -> str:
    """Normalise text for comparisons and de-duplication."""
    out = text
    if collapse_whitespace:
        out = " ".join(out.split())
    if not case_sensitive:
        out = out.casefold()
    return out.strip()


def flatten(values: Iterable[Any]) -> list[Any]:
    """One level of flattening, handy for assertion payloads."""
    out: list[Any] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            out.extend(value)
        else:
            out.append(value)
    return out


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (0-100). Returns 0.0 for an empty input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct <= 0:
        return float(ordered[0])
    if pct >= 100:
        return float(ordered[-1])
    rank = math.ceil(pct / 100 * len(ordered))
    return float(ordered[min(max(rank - 1, 0), len(ordered) - 1)])


def percentiles(values: Sequence[float]) -> Percentile:
    p50 = percentile(values, 50)
    p95 = percentile(values, 95)
    return Percentile(p50=p50, p95=p95, min=min(values) if values else 0.0, max=max(values) if values else 0.0)


class Percentile:
    """Tiny container for latency percentiles (used by reports and crawler)."""

    __slots__ = ("max", "min", "p50", "p95")

    def __init__(self, *, p50: float = 0.0, p95: float = 0.0, min: float = 0.0, max: float = 0.0):
        self.p50 = p50
        self.p95 = p95
        self.min = min
        self.max = max

    def as_dict(self) -> dict[str, float]:
        return {"p50": self.p50, "p95": self.p95, "min": self.min, "max": self.max}

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"Percentile(p50={self.p50:.1f}, p95={self.p95:.1f})"


def truncate(text: str, limit: int = 120, *, suffix: str = "...") -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - len(suffix), 0)] + suffix


shorten = truncate


def format_duration(ms: float | None) -> str:
    if ms is None:
        return "-"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def indent_block(text: str, *, prefix: str = "  ", width: int = 100) -> str:
    """Indent (and soft-wrap) a block of text for terminal output."""
    out: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line
        while len(line) > width:
            out.append(prefix + line[:width])
            line = line[width:]
        out.append(prefix + line)
    return "\n".join(out)


_REDACT_KEYS = re.compile(
    r"(api[_-]?key|authorization|auth[_-]?token|secret|password|passwd|token|cookie|bearer)",
    re.IGNORECASE,
)
_REDACTED = "***"


def is_secret_key(key: str, *, extra_keys: Iterable[str] = ()) -> bool:
    lowered = key.lower()
    if any(extra.lower() in lowered for extra in extra_keys):
        return True
    return bool(_REDACT_KEYS.search(key))


def redact(value: Any, *, extra_keys: Iterable[str] = ()) -> Any:
    """Recursively mask secret-looking values before they reach a report."""

    def walk(node: Any) -> Any:
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for key, item in node.items():
                key_str = str(key)
                out[key_str] = _REDACTED if is_secret_key(key_str, extra_keys=extra_keys) else walk(item)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(value)


def stable_hash(value: str, *, length: int = 8) -> str:
    """Deterministic short hash (used for crawler node ids)."""
    import hashlib

    return hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:length]
