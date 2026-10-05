"""Turn an exported conversation into a runnable suite.

Teams paste conversations from wherever their bot lives -- a JSON dump, a CSV
export, a support-desk XML dump, a copied chat log in Markdown. This module
parses all of those into one intermediate shape and emits a conversat
:class:`~conversat.models.suite.TestSuite`.

The interesting trick is the default connector: an imported conversation becomes
a ``scripted`` suite that replays the replies that were actually observed. The
result is a golden-transcript regression test -- run it against a bot that
regressed and the assertions fail, with no live bot required.

    from conversat.importer import import_conversation
    result = import_conversation(open("chat.json").read())
    suite = result.suite
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from conversat.errors import ConversatError
from conversat.models.crawler import CrawlReport
from conversat.models.report import RunReport
from conversat.models.suite import ConnectorConfig, TestCase, TestSuite, Turn

Role = Literal["user", "bot"]

#: Every spelling of "the human" we have seen in exports.
USER_ROLES = frozenset(
    {
        "user",
        "human",
        "customer",
        "client",
        "me",
        "self",
        "in",
        "inbound",
        "incoming",
        "question",
        "asker",
        "visitor",
        "guest",
        "requester",
        "caller",
        "contact",
        "sender_user",
    }
)

#: ...and of "the machine".
BOT_ROLES = frozenset(
    {
        "bot",
        "assistant",
        "ai",
        "agent",
        "chatbot",
        "chat bot",
        "gpt",
        "llm",
        "model",
        "out",
        "outbound",
        "outgoing",
        "response",
        "reply",
        "answer",
        "system",
        "bot_message",
        "virtual_agent",
        "support",
        "operator",
        "service",
        "staff",
        "rep",
        "representative",
        "helpdesk",
        "chatbot_agent",
    }
)

#: Field names that may hold the message body, most specific first.
TEXT_KEYS = (
    "text",
    "content",
    "message",
    "body",
    "utterance",
    "value",
    "reply",
    "response",
    "answer",
    "prompt",
    "msg",
    "data",
)

#: Field names that may hold the speaker.
ROLE_KEYS = (
    "role",
    "speaker",
    "from",
    "sender",
    "author",
    "participant",
    "type",
    "direction",
    "speaker_role",
)

#: Field names that may group messages into separate conversations.
CASE_KEYS = (
    "case",
    "case_name",
    "conversation",
    "conversation_id",
    "session",
    "session_id",
    "thread",
    "thread_id",
    "chat_id",
    "id",
    "group",
)

MAX_MESSAGES = 2000
MAX_CASES = 200

AssertionStyle = Literal["none", "contains", "exact"]


# --------------------------------------------------------------------------- #
# intermediate shape
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ImportedMessage:
    role: Role
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportedConversation:
    name: str | None
    messages: list[ImportedMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def pairs(self) -> Iterator[tuple[ImportedMessage, ImportedMessage | None]]:
        """Yield ``(user message, the reply it got)`` for every exchange."""
        pending: ImportedMessage | None = None
        for message in self.messages:
            if message.role == "user":
                if pending is not None:
                    yield pending, None
                pending = message
            elif pending is not None:
                yield pending, message
                pending = None
        if pending is not None:
            yield pending, None

    def replies(self) -> list[str]:
        return [reply.text for _, reply in self.pairs() if reply is not None]


@dataclass(slots=True)
class ImportResult:
    suite: TestSuite
    format: str
    conversations: list[ImportedConversation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def turns(self) -> int:
        return sum(len(case.all_turns()) for case in self.suite.cases)

    def summary(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "name": self.suite.name,
            "cases": len(self.suite.cases),
            "turns": self.turns,
            "messages": sum(len(item.messages) for item in self.conversations),
            "assertions": sum(
                len(turn.expect) for case in self.suite.cases for turn in case.all_turns()
            ),
            "connector": self.suite.connector.label,
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------- #
# format registry
# --------------------------------------------------------------------------- #
@dataclass(slots=True, frozen=True)
class FormatInfo:
    name: str
    extensions: tuple[str, ...]
    description: str
    example: str


FORMATS: dict[str, FormatInfo] = {
    "yaml": FormatInfo(
        "yaml",
        (".yaml", ".yml"),
        "conversat suite, or a list of chat messages",
        "name: chat\nconnector: {type: echo}\ncases:\n  - name: hi\n    steps:\n      - send: Hello\n",
    ),
    "json": FormatInfo(
        "json",
        (".json",),
        "array of messages, nested conversations, or a conversat suite",
        '[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]',
    ),
    "jsonl": FormatInfo(
        "jsonl",
        (".jsonl", ".ndjson"),
        "one JSON message per line",
        '{"role": "user", "content": "Hi"}\n{"role": "assistant", "content": "Hello"}',
    ),
    "csv": FormatInfo(
        "csv",
        (".csv",),
        "spreadsheet export with role/text columns",
        "case,role,text\ngreeting,user,Hello\ngreeting,bot,Hi there",
    ),
    "tsv": FormatInfo(
        "tsv",
        (".tsv",),
        "tab-separated variant of CSV",
        "role\ttext\nuser\tHello\nbot\tHi there",
    ),
    "xml": FormatInfo(
        "xml",
        (".xml",),
        "support-desk dump: <conversation><message role=...>",
        '<conversation><message role="user">Hello</message>'
        '<message role="bot">Hi there</message></conversation>',
    ),
    "markdown": FormatInfo(
        "markdown",
        (".md", ".markdown", ".mdx"),
        "pasted chat log: headings split conversations, '**User:**' lines",
        "# Greeting\n\n**User:** Hello\n\n**Bot:** Hi there",
    ),
    "text": FormatInfo(
        "text",
        (".txt", ".log", ".transcript"),
        "plain transcript with 'User:' / 'Bot:' prefixes",
        "User: Hello\nBot: Hi there",
    ),
    "html": FormatInfo(
        "html",
        (".html", ".htm"),
        "chat widget export with .msg user/.bot elements",
        '<div class="msg user">Hello</div><div class="msg bot">Hi there</div>',
    ),
    "report": FormatInfo(
        "report",
        (".conversat.json",),
        "a conversat run report, converted into a replay suite",
        '{"run_id": "run-1", "suite": "old", "cases": [...]}',
    ),
    "crawl": FormatInfo(
        "crawl",
        (".crawl.json",),
        "a conversat crawl report, converted from its transcripts",
        '{"suite": "bot", "nodes": [...], "coverage": {...}}',
    ),
}

ALIASES = {
    "yml": "yaml",
    "ndjson": "jsonl",
    "md": "markdown",
    "markdown": "markdown",
    "log": "text",
    "txt": "text",
    "transcript": "text",
    "htm": "html",
    "conversat": "report",
    "conversat-report": "report",
    "report": "report",
    "tab": "tsv",
    "tab-separated": "tsv",
}

# --- content sniffing ------------------------------------------------------ #
# Order matters: the first rule that matches wins, so the specific ones lead.

_JSONL = re.compile(r"^\s*\{[^\n]*\}\s*$")
_HTML = re.compile(r"<\s*(?:!doctype\s+html|html|body|div|span|section|li|p|br)\b", re.IGNORECASE)
_XML = re.compile(r"^\s*(?:<\?xml|<!\[CDATA\[|<[a-zA-Z][\w.:-]*)")
# Only structural keys count, so a transcript line such as "name: Bob" is not
# mistaken for a suite.
_YAML = re.compile(r"^\s*(cases|connector|steps|turns|setup|expect)\s*:", re.MULTILINE)
_MARKDOWN = re.compile(r"^\s{0,3}(?:#{1,6}\s|\*\*[^*]+:\*\*|[-*]\s+\*\*[^*]+:\*\*)", re.MULTILINE)
#: ``User: hi`` and ``12:01 - Ada: hi`` both open a speaker line.
_SPEAKER_LINE = re.compile(
    r"^\s*(?:\[\s*\S{1,30}\s*\]\s*)?(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*[-\u2013\u2014|]?\s*"
    r"\S{1,32}:\s",
    re.MULTILINE,
)


def _looks_tabular(text: str, delimiter: str) -> bool:
    """True when several lines share a consistent delimiter -- a real table.

    Counting delimiters beats a single-line regex: prose full of commas would
    otherwise pass for a CSV.
    """
    lines = [line for line in text.splitlines()[:20] if line.strip()]
    if len(lines) < 2:
        return False
    counts = [line.count(delimiter) for line in lines]
    first = counts[0]
    if first < 1:
        return False
    return all(count == first for count in counts)


def _sniff(text: str) -> str:
    if _JSONL.match(text) and all(
        _JSONL.match(line) for line in (row for row in text.splitlines() if row.strip())
    ):
        return "jsonl"
    if text[0] in "[{":
        return "json"
    if _HTML.search(text):
        return "html"
    if _XML.match(text):
        return "xml"
    if _looks_tabular(text, "\t"):
        return "tsv"
    if _looks_tabular(text, ","):
        return "csv"
    if _YAML.search(text):
        return "yaml"
    if _MARKDOWN.search(text):
        return "markdown"
    if _SPEAKER_LINE.search(text):
        return "text"
    raise ConversatError(
        f"could not detect the format; name it explicitly ({', '.join(sorted(FORMATS))}, ...)"
    )


def available_formats() -> list[FormatInfo]:
    return [FORMATS[name] for name in sorted(FORMATS)]


def resolve_format(name: str | None) -> str | None:
    if not name:
        return None
    key = str(name).strip().lower().lstrip(".")
    key = ALIASES.get(key, key)
    if key not in FORMATS:
        raise ConversatError(f"unknown format {name!r}; available: {', '.join(sorted(FORMATS))}")
    return key


def detect_format(content: str, filename: str | None = None) -> str:
    """Guess the format from the filename first, then the content."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            for name, info in FORMATS.items():
                if suffix in info.extensions:
                    return name

    text = content.lstrip("\ufeff").strip()
    if not text:
        raise ConversatError("the file is empty")
    return _sniff(text)


# --------------------------------------------------------------------------- #
# shared parsing helpers
# --------------------------------------------------------------------------- #
def normalise_role(value: Any) -> Role | None:
    """Map a speaker field onto ``user``/``bot``, or ``None`` if unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "user" if value else "bot"
    if isinstance(value, int):
        return {0: "bot", 1: "user", 2: "assistant"}.get(value)
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if text in USER_ROLES:
        return "user"
    if text in BOT_ROLES:
        return "bot"
    text = text.replace("_", " ")
    if text in USER_ROLES:
        return "user"
    if text in BOT_ROLES:
        return "bot"
    # "from_user" / "sender: assistant" / "isBot: true"
    if any(token in text for token in ("user", "human", "customer", "inbound")):
        return "user"
    if any(token in text for token in ("bot", "assistant", "agent", "ai", "outbound")):
        return "bot"
    return None


def _first(mapping: dict[str, Any], keys: Sequence[str]) -> Any:
    """First value whose key matches one of ``keys``, tolerating ``prefix_`` names."""
    column = match_column(list(mapping), keys)
    if column is None:
        return None
    value = mapping.get(column)
    return None if value in (None, "") else value


def match_column(headers: Sequence[str], keys: Sequence[str]) -> str | None:
    """Find the column that plays the role of one of ``keys``.

    Real exports name columns things like ``agent_role`` or ``message_text``, so
    an exact hit wins but a ``*_<key>`` suffix is accepted too.
    """
    normalised = {str(header).strip().lower().replace(" ", "_"): header for header in headers}
    for key in keys:
        if key in normalised:
            return normalised[key]
    for key in keys:
        suffix = f"_{key}"
        for lowered, original in normalised.items():
            if lowered.endswith(suffix):
                return original
    for key in keys:
        for lowered, original in normalised.items():
            if key in lowered.split("_"):
                return original
    return None


def coerce_text(value: Any) -> str:
    """Flatten a message body that may be a string, a dict or a content list."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in TEXT_KEYS:
            if key in value:
                return coerce_text(value[key])
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        # OpenAI-style content parts: concatenate the fragments verbatim, so a
        # part like " there" keeps its leading space.
        return "".join(_flatten_part(item) for item in value).strip()
    return str(value).strip()


def _flatten_part(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in TEXT_KEYS:
            if key in value:
                return _flatten_part(value[key])
        return ""
    if isinstance(value, list):
        return "".join(_flatten_part(item) for item in value)
    return "" if value is None else str(value)


def _looks_like_message(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    role = _first(item, ROLE_KEYS)
    if normalise_role(role) is None:
        return False
    return any(key in {k.lower() for k in item} for key in TEXT_KEYS)


def message_from_mapping(item: dict[str, Any]) -> ImportedMessage | None:
    role = normalise_role(_first(item, ROLE_KEYS))
    text = coerce_text(_first(item, TEXT_KEYS))
    if role is None or not text:
        return None
    consumed = {match_column(list(item), ROLE_KEYS), match_column(list(item), TEXT_KEYS)}
    metadata = {
        str(key): value
        for key, value in item.items()
        if str(key) not in consumed and isinstance(value, (str, int, float, bool))
    }
    return ImportedMessage(role=role, text=text, metadata=metadata)


def _split_cases(
    items: Iterable[ImportedMessage], payload: Sequence[Any]
) -> list[ImportedConversation]:
    """Group flat messages by a conversation/session column when present."""
    groups: dict[str, ImportedConversation] = {}
    order: list[str] = []
    for index, message in enumerate(items):
        source = payload[index] if index < len(payload) and isinstance(payload[index], dict) else {}
        key_value = _first(source, CASE_KEYS)
        key = str(key_value) if key_value is not None else "conversation-1"
        if key not in groups:
            groups[key] = ImportedConversation(
                name=str(key_value) if key_value is not None else None, messages=[]
            )
            order.append(key)
        if len(groups[key].messages) >= MAX_MESSAGES:
            continue
        groups[key].messages.append(message)
    return [groups[key] for key in order][:MAX_CASES]


# --------------------------------------------------------------------------- #
# format parsers -- each returns a list of conversations
# --------------------------------------------------------------------------- #
def _parse_json_like(payload: Any, warnings: list[str]) -> list[ImportedConversation]:
    """Handle every JSON shape we have seen: suite, conversations, or messages."""
    if isinstance(payload, dict):
        if {"run_id", "cases"} <= set(payload):
            warnings.append("looks like a conversat run report; use format 'report' to convert it")
            payload = payload.get("cases") or []
        elif "cases" in payload and "connector" in payload:
            warnings.append("looks like a conversat suite; it was imported unchanged")
            payload = [payload]
        else:
            for key in (
                "conversations",
                "threads",
                "sessions",
                "chats",
                "dialogs",
                "cases",
                "data",
            ):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                payload = [payload]

    conversations: list[ImportedConversation] = []
    flat: list[ImportedMessage] = []
    raw: list[Any] = []

    for entry in payload if isinstance(payload, list) else [payload]:
        if _looks_like_message(entry):
            message = message_from_mapping(entry)
            if message:
                flat.append(message)
                raw.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        inner = entry
        for key in ("messages", "turns", "exchanges", "events", "history", "items"):
            if isinstance(entry.get(key), list):
                inner = entry
                break
        messages: list[ImportedMessage] = []
        sources: list[Any] = []
        for key in ("messages", "turns", "exchanges", "events", "history", "items"):
            value = inner.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        message = message_from_mapping(item)
                        if message:
                            messages.append(message)
                            sources.append(item)
                break
        else:
            messages = [m for m in (message_from_mapping(entry),) if m]
            sources = [entry] if messages else []

        if not messages:
            continue
        name = _first(entry, CASE_KEYS)
        conversation = ImportedConversation(
            name=str(name) if name else None,
            messages=messages[:MAX_MESSAGES],
            metadata={},
        )
        if len(messages) > MAX_MESSAGES:
            warnings.append(f"truncated {name or 'a conversation'} to {MAX_MESSAGES} messages")
        conversations.append(conversation)

    if flat:
        grouped = _split_cases(flat, raw)
        # Only report grouping when the export actually carried a case column.
        if len(grouped) > 1:
            conversations.extend(grouped)
        else:
            conversations.extend(grouped)
    return conversations


def _parse_json(content: str, warnings: list[str]) -> list[ImportedConversation]:
    try:
        payload = json.loads(content.lstrip("﻿"))
    except json.JSONDecodeError as exc:
        raise ConversatError(f"invalid JSON: {exc}") from exc
    return _parse_json_like(payload, warnings)


def _parse_jsonl(content: str, warnings: list[str]) -> list[ImportedConversation]:
    items: list[Any] = []
    for number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConversatError(f"invalid JSON on line {number}: {exc}") from exc
    return _parse_json_like(items, warnings)


def _parse_delimited(
    content: str, warnings: list[str], *, delimiter: str
) -> list[ImportedConversation]:
    stream = io.StringIO(content.lstrip("﻿"))
    sample = content[:4096]
    try:
        dialect = (
            csv.Sniffer().sniff(sample, delimiters=delimiter + ",")
            if delimiter == ","
            else "excel-tab"
        )
    except csv.Error:
        dialect = "excel" if delimiter == "," else "excel-tab"  # type: ignore[assignment]
    rows = list(csv.DictReader(stream, dialect=dialect))
    if not rows:
        raise ConversatError("no rows found")

    headers = [str(key) for key in rows[0] if key]
    role_column = match_column(headers, ROLE_KEYS)
    text_column = match_column(headers, TEXT_KEYS)
    if text_column is None:
        # Two unnamed columns are the common "sender, message" export.
        columns = [key for key in rows[0] if key]
        if len(columns) >= 2:
            role_column, text_column = columns[0], columns[1]
            warnings.append(f"guessed columns: role='{role_column}', text='{text_column}'")
    if text_column is None:
        raise ConversatError(
            f"no text column found; expected one of {', '.join(TEXT_KEYS)} in {', '.join(headers)}"
        )

    messages: list[ImportedMessage] = []
    sources: list[Any] = []
    unquoted = 0
    for row in rows:
        overflow = " ".join(str(part) for part in (row.get(None) or []))
        item = {str(k).lower(): v for k, v in row.items() if k}
        message = message_from_mapping(item)
        if message:
            if overflow:
                # Best effort: the delimiter itself is gone, so the words are
                # recovered but the punctuation is not.
                message.text = " ".join(f"{message.text} {overflow}".split())
                unquoted += 1
            messages.append(message)
            sources.append(item)
        elif role_column and row.get(role_column):
            warnings.append(f"skipped a row with unknown role {row.get(role_column)!r}")
    if unquoted:
        warnings.append(
            f"{unquoted} row(s) had more fields than the header -- quote any message "
            "containing a comma or quote character"
        )
    if not messages:
        raise ConversatError(
            f"no messages with a recognisable speaker; expected a role column "
            f"({', '.join(ROLE_KEYS[:6])}, possibly prefixed) and a text column "
            f"({', '.join(TEXT_KEYS[:6])}) in {', '.join(headers)}"
        )
    return _split_cases(messages, sources)


def _parse_csv(content: str, warnings: list[str]) -> list[ImportedConversation]:
    return _parse_delimited(content, warnings, delimiter=",")


def _parse_tsv(content: str, warnings: list[str]) -> list[ImportedConversation]:
    return _parse_delimited(content, warnings, delimiter="\t")


def _parse_xml(content: str, warnings: list[str]) -> list[ImportedConversation]:
    try:
        root = ElementTree.fromstring(content.lstrip("﻿"))
    except ElementTree.ParseError as exc:
        raise ConversatError(f"invalid XML: {exc}") from exc

    conversations: list[ImportedConversation] = []
    flat: list[ImportedMessage] = []

    for element in root.iter():
        role = normalise_role(
            element.get("role")
            or element.get("speaker")
            or element.get("author")
            or element.get("from")
            or element.get("name")
            or element.tag
        )
        text = coerce_text(element.text) or "".join(element.itertext()).strip()
        if role is None or not text or not (element.text or "").strip():
            continue
        message = ImportedMessage(
            role=role,
            text=text.strip(),
            metadata={
                "element": element.tag,
                **{k: v for k, v in element.attrib.items() if k != "role"},
            },
        )
        flat.append(message)

    if not flat:
        raise ConversatError("no <message>-like elements with a recognisable speaker found")
    warnings.append(f"flattened {len(flat)} message element(s) from <{root.tag}>")
    conversations.extend(_split_cases(flat, []))
    return conversations


_MD_SPEAKER = re.compile(r"^([A-Za-z][A-Za-z ._-]{0,24}?)\s*[:：]\s*(.*)$")
_MD_ARROW = re.compile(r"^(\S[^:>]{0,20})\s*>\s*(.+)$")


def _strip_label_emphasis(line: str) -> str:
    """Turn ``**User:** Hello`` into ``User: Hello`` so one regex can match both."""
    for marker in ("**", "__"):
        if not line.startswith(marker):
            continue
        close = line.find(marker, len(marker))
        return (
            line[:close] + line[close + len(marker) :] if 0 < close <= 40 else line[len(marker) :]
        )
    return line


#: ``12:01``, ``2026-01-04 10:00``, ``[10:02:31]`` -- chat exports timestamp lines.
_TIMESTAMP = re.compile(
    r"^\s*(?:\[\s*\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?\s*\]"
    r"|\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]"
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"
    r"|\d{1,2}:\d{2}(?::\d{2})?(?:\s?[apAP]\.?[mM]\.?)?)"
    r"\s*(?:[-–—|]\s*)?"
)


def _speaker_from_prefix(text: str) -> tuple[str | None, str]:
    """Split ``"12:01 - Ada: hi"`` into its label and its text.

    The label is returned raw: it may be a role ("User") or a person's name
    ("Ada"), and deciding which is the caller's job.
    """
    line = re.sub(r"^\s*(?:[-*>+]\s*)+", "", text.strip())
    for candidate in (_strip_label_emphasis(line), _TIMESTAMP.sub("", line, count=1)):
        match = _MD_SPEAKER.match(candidate)
        if match:
            return match.group(1).strip(), re.sub(r"^[\*_`\s]+", "", match.group(2).strip())
    return None, text.strip()


class _SpeakerRoles:
    """Maps a speaker label onto ``user``/``bot``.

    Exports come with names rather than roles ("12:01 - Ada:"). The first
    speaker in a document is taken to be the human and the next distinct one the
    bot, which is what a two-party chat always looks like.
    """

    def __init__(self, warnings: list[str]) -> None:
        self._warnings = warnings
        self._names: dict[str, Role] = {}
        self._inferred = False

    def resolve(self, label: str | None) -> Role | None:
        if not label:
            return None
        known = normalise_role(label)
        if known is not None:
            return known
        if not self._looks_like_a_name(label):
            return None
        if label not in self._names:
            self._names[label] = "user" if not self._names else "bot"
            if not self._inferred:
                self._inferred = True
                self._warnings.append(
                    f"speakers are named rather than labelled -- treating "
                    f"{', '.join(self._names)} as the user and the bot"
                )
        return self._names[label]

    @staticmethod
    def _looks_like_a_name(label: str) -> bool:
        cleaned = label.strip()
        if not cleaned or len(cleaned) > 32:
            return False
        if any(char in cleaned for char in ".,;!?*#=/\\|"):
            return False
        return bool(re.match(r"^[\w'\u00c0-\u024f][\w '\u00c0-\u024f.-]*$", cleaned, re.UNICODE))


def _parse_transcript_text(
    content: str, warnings: list[str], *, stop_at_blank: bool
) -> list[ImportedConversation]:
    """Shared engine for the Markdown and plain-text transcript formats.

    Lines are grouped into blocks; a block's role comes from the speaker label
    that opened it and every following line is a continuation. Headings split
    one document into several conversations.
    """
    conversations: list[ImportedConversation] = []
    current = ImportedConversation(name=None, messages=[])
    heading = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
    rule = re.compile(r"^\s*(?:[-*_]\s*){3,}$")

    roles = _SpeakerRoles(warnings)
    pending_role: Role | None = None
    buffer: list[str] = []

    def commit() -> None:
        nonlocal pending_role, buffer
        text = "\n".join(buffer).strip()
        role = pending_role
        buffer = []
        pending_role = None
        if not text:
            return
        if role is None:
            if current.messages:
                current.messages.append(ImportedMessage(role="bot", text=text))
            else:
                warnings.append("dropped text before the first speaker label")
            return
        if len(current.messages) < MAX_MESSAGES:
            current.messages.append(ImportedMessage(role=role, text=text))

    def flush() -> None:
        if current.messages:
            conversations.append(current)

    for raw_line in content.lstrip("\ufeff").splitlines():
        line = raw_line.rstrip()
        if rule.match(line):
            continue

        found_heading = heading.match(line)
        if found_heading:
            commit()
            flush()
            current = ImportedConversation(name=found_heading.group(1).strip() or None, messages=[])
            continue

        if not line.strip():
            if stop_at_blank:
                commit()
            continue

        label, remainder = _speaker_from_prefix(line)
        role = roles.resolve(label)
        if role is not None:
            commit()
            pending_role = role
            buffer = [remainder] if remainder else []
        elif buffer:
            buffer.append(line.strip())
        else:
            # Unlabelled prose: part of this block, or a bot aside.
            buffer = [line.strip()]

    commit()
    flush()

    usable = [
        item
        for item in conversations
        if item.messages and any(message.role == "user" for message in item.messages)
    ]
    for item in conversations:
        if item.messages and all(message.role != "user" for message in item.messages):
            warnings.append(f"{item.name or 'a conversation'} had no user turns; skipped")
    if not usable:
        raise ConversatError(
            "no messages with a recognisable speaker found; expected labels like "
            "'User:' / 'Bot:' (or '**User:**' in Markdown)"
        )
    return usable


def _parse_markdown(content: str, warnings: list[str]) -> list[ImportedConversation]:
    return _parse_transcript_text(content, warnings, stop_at_blank=False)


def _parse_text(content: str, warnings: list[str]) -> list[ImportedConversation]:
    if not re.search(r"\S[^:\n]{0,24}:\s", content):
        raise ConversatError(
            "no 'User:' / 'Bot:' style labels found; name the format explicitly if this is Markdown"
        )
    return _parse_transcript_text(content, warnings, stop_at_blank=True)


class _ChatHtmlParser(HTMLParser):
    """Reads the message bubbles out of a chat widget's exported HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[ImportedMessage] = []
        self._role: Role | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        classes = f"{attributes.get('class', '')} {attributes.get('data-role', '')} {attributes.get('id', '')}".lower()
        role = normalise_role(
            attributes.get("data-role") or attributes.get("data-conversat-msg")
        ) or normalise_role(classes)
        if role is None:
            return
        self.flush()
        self._role = role

    def handle_endtag(self, tag: str) -> None:
        self.flush()
        self._role = None

    def handle_data(self, data: str) -> None:
        if self._role is not None and data.strip():
            self._buffer.append(data.strip())

    def flush(self) -> None:
        text = " ".join(part.strip() for part in self._buffer if part.strip()).strip()
        self._buffer = []
        if text and self._role:
            self.messages.append(ImportedMessage(role=self._role, text=text))


def _parse_html(content: str, warnings: list[str]) -> list[ImportedConversation]:
    parser = _ChatHtmlParser()
    parser.feed(content.lstrip("﻿"))
    parser.flush()
    if not parser.messages:
        raise ConversatError(
            "no chat bubbles found; expected elements whose class or data-role marks the speaker"
        )
    return [ImportedConversation(name=None, messages=parser.messages[:MAX_MESSAGES])]


def _parse_report(content: str, warnings: list[str]) -> list[ImportedConversation]:
    """Convert a stored run report into conversations you can replay."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConversatError(f"invalid JSON: {exc}") from exc

    report: RunReport | None = None
    if isinstance(payload, dict) and {"run_id", "cases"} <= set(payload):
        try:
            report = RunReport.model_validate(payload)
        except ValueError as exc:
            raise ConversatError(f"not a conversat run report: {exc}") from exc
    else:
        try:
            report = RunReport.model_validate(payload)
        except ValueError as exc:
            raise ConversatError(f"not a conversat run report: {exc}") from exc

    conversations: list[ImportedConversation] = []
    for case in report.cases:
        messages: list[ImportedMessage] = []
        for turn in case.turns:
            if turn.request:
                messages.append(ImportedMessage(role="user", text=turn.request))
            if turn.response is not None:
                messages.append(
                    ImportedMessage(
                        role="bot",
                        text=turn.response.text,
                        metadata={
                            "latency_ms": turn.response.latency_ms or 0,
                            "is_error": bool(turn.response.is_error),
                        },
                    )
                )
            elif turn.error:
                # Keep the failure: the replay must reproduce it, not paper over it.
                messages.append(
                    ImportedMessage(
                        role="bot",
                        text=turn.error,
                        metadata={"is_error": True, "error": turn.error},
                    )
                )
        if messages:
            conversations.append(ImportedConversation(name=case.name, messages=messages))
    if not conversations:
        raise ConversatError("the report contains no turns to replay")
    warnings.append(f"replaying {len(conversations)} case(s) from run {report.run_id}")
    return conversations


def _parse_crawl(content: str, warnings: list[str]) -> list[ImportedConversation]:
    """Convert a crawl report's transcripts into replayable conversations."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConversatError(f"invalid JSON: {exc}") from exc
    try:
        report = CrawlReport.model_validate(payload)
    except ValueError as exc:
        raise ConversatError(f"not a conversat crawl report: {exc}") from exc

    conversations: list[ImportedConversation] = []
    for index, transcript in enumerate(report.transcripts(), start=1):
        messages: list[ImportedMessage] = []
        for node in transcript:
            # A crawl node is a whole turn: a request and the reply it got.
            if node.request:
                messages.append(ImportedMessage(role="user", text=node.request))
            if node.response and node.response.text:
                messages.append(
                    ImportedMessage(
                        role="bot",
                        text=node.response.text,
                        metadata={"is_error": bool(node.response.is_error)},
                    )
                )
            elif node.error:
                messages.append(
                    ImportedMessage(
                        role="bot",
                        text=node.error,
                        metadata={"is_error": True, "error": node.error},
                    )
                )
        if any(message.role == "user" for message in messages):
            conversations.append(ImportedConversation(name=f"crawl-{index:02d}", messages=messages))
    if not conversations:
        raise ConversatError("the crawl report contains no transcripts")
    warnings.append(f"replaying {len(conversations)} transcript(s) from the crawl")
    return conversations


_PARSERS = {
    "json": _parse_json,
    "jsonl": _parse_jsonl,
    "csv": _parse_csv,
    "tsv": _parse_tsv,
    "xml": _parse_xml,
    "markdown": _parse_markdown,
    "text": _parse_text,
    "html": _parse_html,
    "report": _parse_report,
    "crawl": _parse_crawl,
}


def _parse_yaml(content: str, warnings: list[str]) -> list[ImportedConversation]:
    import yaml

    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConversatError(f"invalid YAML: {exc}") from exc
    if payload is None:
        raise ConversatError("the file is empty")
    if isinstance(payload, dict) and {"cases", "connector"} <= set(payload):
        # A real suite: hand it back untouched via the sentinel below.
        warnings.append("the input is already a conversat suite")
        return []
    return _parse_json_like(payload, warnings)


def parse_conversations(
    content: str, *, fmt: str | None = None, filename: str | None = None
) -> tuple[list[ImportedConversation], str, list[str]]:
    """Parse ``content`` into conversations, detecting the format if needed."""
    resolved = resolve_format(fmt) or detect_format(content, filename)
    warnings: list[str] = []
    if resolved == "yaml" or resolved not in _PARSERS:
        return _parse_yaml(content, warnings), "yaml", warnings

    try:
        return _PARSERS[resolved](content, warnings), resolved, warnings
    except ConversatError:
        # Detection is a heuristic; a transcript-shaped suite YAML is common
        # enough to be worth a second attempt before giving up.
        if resolved in ("text", "markdown", "csv", "tsv") and _looks_like_suite_yaml(content):
            warnings.append(f"parsed as {resolved}, but the content is a suite -- read as YAML")
            return _parse_yaml(content, warnings), "yaml", warnings
        raise


def _looks_like_suite_yaml(content: str) -> bool:
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a hard dependency
        return False
    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    return isinstance(payload, dict) and {"cases", "connector"} <= set(payload)


# --------------------------------------------------------------------------- #
# suite building
# --------------------------------------------------------------------------- #
def _assertions_for(reply: str, style: AssertionStyle, request: str | None) -> list[dict[str, Any]]:
    if style == "none":
        return [{"not_empty": True}]
    if style == "exact":
        return [{"equals": reply}]
    # "contains": pin a distinctive fragment rather than the whole reply, so
    # cosmetic wording changes do not fail the suite.
    fragment = _salient_fragment(reply, request)
    if not fragment:
        return [{"not_empty": True}]
    return [{"contains": fragment}, {"not_empty": True}]


def _salient_fragment(reply: str, request: str | None) -> str:
    """A contiguous slice of ``reply`` worth asserting on.

    ``contains`` matches against the whitespace-normalised reply, so collapsing
    the whitespace here keeps the fragment a real substring. Picking the
    longest sentence avoids pinning a suite to a throwaway greeting.
    """
    flat = " ".join(reply.split())
    if not flat:
        return ""
    if len(flat) <= 60:
        return flat
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", flat) if part.strip()]
    longest = max(sentences, key=len) if sentences else flat
    words = longest.split()
    return " ".join(words[:6]) if len(words) > 6 else longest


def _resolve_connector_override(override: Any) -> ConnectorConfig | None:
    """Accept a ConnectorConfig, a mapping, or ``http:url=...,timeout=5``."""
    if not override:
        return None
    if isinstance(override, ConnectorConfig):
        return override
    if isinstance(override, dict):
        return ConnectorConfig.model_validate(override)
    name, _, rest = str(override).partition(":")
    config: dict[str, Any] = {}
    for pair in rest.split(","):
        if pair.strip():
            key, _, value = pair.partition("=")
            config[key.strip()] = value.strip()
    return ConnectorConfig(type=name.strip(), config=config)


def _scripted(replies: Sequence[str], *, error_at: Sequence[int] = ()) -> ConnectorConfig:
    config: dict[str, Any] = {
        "replies": list(replies),
        "repeat_last": False,
        "mode": "sequential",
    }
    if error_at:
        config["error_at"] = list(error_at)
    return ConnectorConfig(type="scripted", config=config)


def _all_replies(conversations: Sequence[ImportedConversation]) -> list[str]:
    return [reply for conversation in conversations for reply in conversation.replies()]


def import_conversation(
    content: str,
    *,
    fmt: str | None = None,
    filename: str | None = None,
    name: str | None = None,
    connector: Any = None,
    assertions: AssertionStyle = "contains",
    tags: Sequence[str] = ("imported",),
    description: str | None = None,
) -> ImportResult:
    """Parse ``content`` and return a runnable suite.

    Raises :class:`~conversat.errors.ConversatError` with an actionable message
    when the content cannot be understood.
    """
    conversations, resolved, warnings = parse_conversations(content, fmt=fmt, filename=filename)

    # An input that was already a suite comes back from the YAML branch empty.
    if not conversations:
        import yaml

        payload = yaml.safe_load(content)
        suite = _suite_from_payload(payload, name=name, tags=tags)
        warnings.append("returned the suite unchanged")
        return ImportResult(suite=suite, format="yaml", conversations=[], warnings=warnings)

    suite_name = name or _default_name(conversations, filename)
    override = _resolve_connector_override(connector)
    replaying = override is None
    if replaying:
        all_replies = _all_replies(conversations)
        if not all_replies:
            all_replies = ["(no reply captured)"]
            warnings.append("no bot replies were captured; using a placeholder reply")

    cases: list[TestCase] = []
    for index, conversation in enumerate(conversations, start=1):
        turns: list[Turn] = []
        replies: list[str] = []
        error_at: list[int] = []
        for pair_index, (request, reply) in enumerate(conversation.pairs(), start=1):
            if reply is None:
                warnings.append(
                    f"{conversation.name or 'conversation'} turn {pair_index} has no bot reply"
                )
                turns.append(
                    Turn(send=request.text, expect=[{"not_empty": True}], name=f"turn-{pair_index}")
                )
                continue
            failed = bool(reply.metadata.get("is_error"))
            if failed:
                # A turn that errored when it was captured must error again on
                # replay, or the suite would quietly pass a broken bot.
                error_at.append(len(replies))
                expect: list[dict[str, Any]] = [{"type": "no_error", "expect_error": True}]
            else:
                expect = _assertions_for(reply.text, assertions, request.text)
            replies.append(reply.text or f"(error) {reply.metadata.get('error', '')}".strip())
            turns.append(
                Turn(
                    send=request.text,
                    name=f"turn-{pair_index}",
                    expect=expect,
                    metadata={
                        "imported_reply_length": len(reply.text),
                        **({"imported_error": True} if failed else {}),
                    },
                )
            )
        if not turns:
            continue
        case_name = conversation.name or f"conversation-{index}"
        cases.append(
            TestCase(
                name=_slug(case_name, index),
                description=conversation.metadata.get("source") or description,
                tags=list(tags),
                steps=turns,
                # Each case gets its own scripted script: a fresh connector starts
                # at reply 0, so a shared script would replay the wrong transcript.
                connector=(
                    _scripted(replies or ["(no reply captured)"], error_at=error_at)
                    if replaying
                    else None
                ),
                metadata={"imported_from": resolved, **conversation.metadata},
            )
        )

    if not cases:
        raise ConversatError(
            "no user turns found; a conversation needs at least one message from the user"
        )

    suite = TestSuite(
        name=_slug(suite_name),
        description=description or f"Imported from a {resolved} conversation export",
        connector=override or _scripted(all_replies),
        cases=cases,
    )
    if replaying:
        warnings.append(
            f"replaying the captured replies with the scripted connector ({len(all_replies)} turn(s))"
        )
    return ImportResult(
        suite=suite, format=resolved, conversations=conversations, warnings=warnings
    )


def _suite_from_payload(payload: Any, *, name: str | None, tags: Sequence[str]) -> TestSuite:
    from conversat.engine.loader import suite_from_dict

    if not isinstance(payload, dict):
        raise ConversatError("expected a conversat suite mapping")
    suite = suite_from_dict(payload, name=name)
    if name and suite.name != name:
        suite = suite.model_copy(update={"name": name})
    if tags:
        suite = suite.model_copy(
            update={"defaults": suite.defaults.model_copy(update={"tags": list(tags)})}
        )
    return suite


def _default_name(conversations: Sequence[ImportedConversation], filename: str | None) -> str:
    if filename:
        return Path(filename).stem
    if len(conversations) == 1 and conversations[0].name:
        return conversations[0].name
    return "imported-conversation"


def _slug(name: str, index: int = 1) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " _-" else "-" for ch in name.strip().lower())
    cleaned = "-".join(part for part in cleaned.replace("_", "-").split() if part)
    return cleaned or f"conversation-{index}"


__all__ = [
    "FORMATS",
    "AssertionStyle",
    "FormatInfo",
    "ImportResult",
    "ImportedConversation",
    "ImportedMessage",
    "available_formats",
    "detect_format",
    "import_conversation",
    "normalise_role",
    "parse_conversations",
    "resolve_format",
]
