"""Generate follow-up messages for the crawler.

The default generator is deterministic and offline: it mines question-shaped
lines out of the bot's replies and falls back to a curated list of generic
probes. Plug in an LLM-backed generator by subclassing
:class:`FollowUpGenerator` and passing it to the crawler.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from conversat.utils import normalize_text

MIN_FOLLOW_UP_WORDS = 3
MAX_FOLLOW_UP_WORDS = 25

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|\s*[-*\u2022]\s+|\s*\d+[.)]\s+")
_QUESTION_WORDS = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can you",
    "could you",
    "do you",
    "is there",
    "are there",
    "tell me",
    "explain",
)

DEFAULT_FOLLOW_UPS: tuple[str, ...] = (
    "Can you tell me more about that?",
    "What are the available options?",
    "How does that work exactly?",
    "Can you give me an example?",
    "What happens if I change something?",
    "Is there anything else I should know?",
    "Can you summarise that in one sentence?",
    "What would you recommend next?",
    "Are there any limitations?",
    "Can you repeat the last part?",
)


class FollowUpGenerator(ABC):
    """Turn a bot reply into the next set of user messages."""

    name = "generator"

    @abstractmethod
    def generate(self, request: str, reply: str, *, limit: int) -> list[str]:
        """Return at most ``limit`` follow-up messages for this exchange."""


class TemplateFollowUps(FollowUpGenerator):
    """Mine the reply for questions, then append curated generic probes.

    No network, no randomness: the same conversation always produces the same
    crawl, which keeps crawls diffable and reproducible in CI.
    """

    name = "template"

    def __init__(
        self,
        *,
        templates: tuple[str, ...] = DEFAULT_FOLLOW_UPS,
        include_mined: bool = True,
        max_mined: int = 3,
        ignore_questions: bool = False,
    ) -> None:
        self.templates = list(templates)
        self.include_mined = include_mined
        self.max_mined = max_mined
        self.ignore_questions = ignore_questions

    def generate(self, request: str, reply: str, *, limit: int) -> list[str]:
        out: list[str] = []
        if self.include_mined and not self.ignore_questions:
            out.extend(self._mine(reply, limit))
        out.extend(t for t in self.templates if normalize_text(t) != normalize_text(request))
        return out[:limit]

    def _mine(self, reply: str, limit: int) -> list[str]:
        candidates: list[str] = []
        for sentence in _SENTENCE_SPLIT.split(reply or ""):
            cleaned = " ".join(sentence.split()).strip(" -*•\t")
            if not cleaned:
                continue
            lowered = cleaned.lower()
            looks_like_question = lowered.endswith("?") or any(w in lowered for w in _QUESTION_WORDS)
            if not looks_like_question:
                continue
            words = cleaned.split()
            if not (MIN_FOLLOW_UP_WORDS <= len(words) <= MAX_FOLLOW_UP_WORDS):
                continue
            candidates.append(cleaned)
        return candidates[: min(self.max_mined, limit)]


class StaticFollowUps(FollowUpGenerator):
    """Always return the same messages (used by the self-tests)."""

    name = "static"

    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)

    def generate(self, request: str, reply: str, *, limit: int) -> list[str]:
        return self.messages[:limit]


class CallableFollowUps(FollowUpGenerator):
    """Delegate to a plain function ``(request, reply, limit) -> list[str]``."""

    name = "callable"

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def generate(self, request: str, reply: str, *, limit: int) -> list[str]:
        result = self._fn(request, reply, limit)
        return [str(item) for item in result][:limit]


def default_generator(extra: list[str] | None = None) -> TemplateFollowUps:
    templates = DEFAULT_FOLLOW_UPS + tuple(extra or ())
    return TemplateFollowUps(templates=templates)
