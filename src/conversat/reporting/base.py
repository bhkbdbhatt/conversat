"""Report formatter contract and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from conversat.errors import RegistryError
from conversat.models.report import RunReport


@dataclass(slots=True)
class FormatterResult:
    """One rendered artefact."""

    name: str
    filename: str
    content: str


class Formatter(ABC):
    """Renders a :class:`RunReport` into text."""

    #: CLI name, e.g. ``console`` or ``junit``.
    name: str = "formatter"
    #: Conventional file extension (``""`` means "stdout only").
    extension: str = ""
    #: True when the formatter needs the full report rather than just totals.
    verbose: bool = True

    @abstractmethod
    def format(self, report: RunReport) -> str:
        """Render the report to a string."""

    def filename_for(self, report: RunReport) -> str:
        stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
        return f"conversat-{report.suite}-{stamp}.{self.extension}" if self.extension else ""


_FORMATTERS: dict[str, type[Formatter]] = {}


def register(name: str) -> Callable[[type[Formatter]], type[Formatter]]:
    def decorator(cls: type[Formatter]) -> type[Formatter]:
        cls.name = name
        _FORMATTERS[name] = cls
        return cls

    return decorator


def _ensure_builtins() -> None:
    if _FORMATTERS:
        return
    from conversat.reporting import console, json_report, junit, markdown  # noqa: F401


def available() -> list[str]:
    _ensure_builtins()
    return sorted(_FORMATTERS)


def get(name: str) -> Formatter:
    _ensure_builtins()
    try:
        cls = _FORMATTERS[name]
    except KeyError:
        raise RegistryError(
            f"unknown report format {name!r}; available: {', '.join(available())}"
        ) from None
    return cls()


def resolve(formats: list[str] | tuple[str, ...] | str | None) -> list[Formatter]:
    """Turn ``["json", "junit"]`` into formatter instances (deduplicated)."""
    if formats is None:
        return [get("console")]
    names = [formats] if isinstance(formats, str) else list(formats)
    out: list[Formatter] = []
    seen: set[str] = set()
    for raw in names:
        for name in str(raw).split(","):
            name = name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(get(name))
    return out or [get("console")]


def render(report: RunReport, formatter: Formatter | str) -> str:
    return (formatter if isinstance(formatter, Formatter) else get(formatter)).format(report)


def dump(report: RunReport) -> dict[str, Any]:
    """JSON-safe dict of a report."""
    return report.model_dump(mode="json")
