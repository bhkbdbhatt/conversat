"""Conversation import.

The importer's contract is: accept whatever a team exports, and hand back a
suite that actually runs. "Actually runs" is the part worth testing -- an
importer that produces YAML which then fails to load is worse than none.
"""

from __future__ import annotations

import json

import pytest

from conversat.engine import TestRunner, load_suite
from conversat.errors import ConversatError
from conversat.importer import (
    available_formats,
    detect_format,
    import_conversation,
    normalise_role,
    resolve_format,
)

# -- one export per supported format ------------------------------------- #
JSON_EXPORT = json.dumps(
    [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help you today?"},
        {"role": "user", "content": "I need a refund"},
        {"role": "assistant", "content": "Refunds are available within 30 days of purchase."},
    ]
)
JSONL_EXPORT = '{"role": "user", "content": "Hi"}\n{"role": "assistant", "content": "Hello there friend"}'
CSV_EXPORT = (
    "case,role,text\n"
    "greeting,user,Hello\n"
    "greeting,bot,Hi there friend\n"
    "refund,user,I want a refund\n"
    "refund,bot,Refunds within 30 days\n"
)
TSV_EXPORT = "role\ttext\nuser\tHello\nbot\tHi there friend\n"
XML_EXPORT = (
    '<export><conversation><message role="user">Hello</message>'
    '<message role="bot">Hi there friend</message></conversation></export>'
)
MARKDOWN_EXPORT = (
    "# Greeting\n\n**User:** Hello\n\n**Bot:** Hi there friend\n\n"
    "## Refund\n\n**User:** I want a refund\n\n**Bot:** Refunds within 30 days\n"
)
TEXT_EXPORT = "User: Hello\nBot: Hi there friend\n\nUser: I want a refund\nBot: Refunds within 30 days\n"
HTML_EXPORT = (
    '<html><body><div class="msg user">Hello</div>'
    '<div class="msg bot">Hi there friend</div></body></html>'
)
YAML_EXPORT = "messages:\n  - role: user\n    content: Hello\n  - role: bot\n    content: Hi there friend\n"

EXPORTS = {
    "json": (JSON_EXPORT, 1, 2),
    "jsonl": (JSONL_EXPORT, 1, 1),
    "csv": (CSV_EXPORT, 2, 1),
    "tsv": (TSV_EXPORT, 1, 1),
    "xml": (XML_EXPORT, 1, 1),
    "markdown": (MARKDOWN_EXPORT, 2, 1),
    "text": (TEXT_EXPORT, 1, 2),
    "html": (HTML_EXPORT, 1, 1),
    "yaml": (YAML_EXPORT, 1, 1),
}


# -- format registry ------------------------------------------------------ #
def test_every_format_is_documented() -> None:
    names = {info.name for info in available_formats()}
    assert names == set(EXPORTS) | {"report", "crawl"}
    for info in available_formats():
        assert info.description
        assert info.example


@pytest.mark.parametrize("alias,expected", [("yml", "yaml"), ("md", "markdown"), ("ndjson", "jsonl"), ("tab", "tsv")])
def test_aliases_resolve(alias: str, expected: str) -> None:
    assert resolve_format(alias) == expected


def test_unknown_format_is_rejected() -> None:
    with pytest.raises(ConversatError, match="unknown format"):
        resolve_format("parquet")


@pytest.mark.parametrize("name,expected", [("chat.json", "json"), ("chat.csv", "csv"), ("chat.md", "markdown")])
def test_extension_wins_over_content(name: str, expected: str) -> None:
    assert detect_format("nothing recognisable here", name) == expected


def test_detection_without_a_filename() -> None:
    assert detect_format(JSON_EXPORT) == "json"
    assert detect_format(MARKDOWN_EXPORT) == "markdown"
    assert detect_format(TEXT_EXPORT) == "text"
    assert detect_format(XML_EXPORT) == "xml"
    assert detect_format(HTML_EXPORT) == "html"


def test_empty_content_is_rejected() -> None:
    with pytest.raises(ConversatError, match="empty"):
        detect_format("   \n  ")


def test_unrecognisable_content_is_rejected() -> None:
    with pytest.raises(ConversatError, match="could not detect"):
        detect_format("just a wall of prose with no structure whatsoever")


# -- role normalisation --------------------------------------------------- #
@pytest.mark.parametrize(
    "value", ["user", "Customer", "HUMAN", "inbound", "me", "sender_user", "Visitor"]
)
def test_user_role_spellings(value: str) -> None:
    assert normalise_role(value) == "user"


@pytest.mark.parametrize("value", ["assistant", "bot", "Agent", "gpt", "outbound", "reply", "support"])
def test_bot_role_spellings(value: str) -> None:
    assert normalise_role(value) == "bot"


@pytest.mark.parametrize("value", [None, "", "narrator", "them"])
def test_unknown_role_spellings(value) -> None:
    assert normalise_role(value) is None


def test_role_matching_is_lenient_about_composites() -> None:
    """`from_agent` / `sender: assistant` are common enough to accept."""
    assert normalise_role("from_agent") == "bot"
    assert normalise_role("sender_user") == "user"
    assert normalise_role("system-user-override") == "user"


# -- parsing -------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", sorted(EXPORTS))
def test_each_format_is_detected_and_parsed(fmt: str) -> None:
    content, expected_cases, _ = EXPORTS[fmt]
    result = import_conversation(content, filename=f"sample.{fmt}")
    assert result.format == fmt
    assert len(result.suite.cases) == expected_cases
    assert result.conversations


@pytest.mark.parametrize("fmt", sorted(EXPORTS))
async def test_each_format_produces_a_suite_that_runs_green(fmt: str) -> None:
    """The point of the importer: a suite you can run straight away."""
    content, _, _ = EXPORTS[fmt]
    result = import_conversation(content, filename=f"sample.{fmt}")
    report = await TestRunner(result.suite).run()
    assert report.ok, [
        f"{case.name}: {turn.error or [a.message for a in turn.failed_assertions]}"
        for case in report.cases
        for turn in case.turns
        if turn.status.value != "passed"
    ]
    assert report.totals.assertions >= report.totals.turns


@pytest.mark.parametrize("fmt", sorted(EXPORTS))
def test_each_format_survives_a_yaml_round_trip(fmt: str, tmp_path) -> None:
    """Whatever the importer builds must survive dump_suite -> load_suite."""
    from conversat.engine.loader import dump_suite

    content, _, _ = EXPORTS[fmt]
    result = import_conversation(content, filename=f"sample.{fmt}")
    path = tmp_path / f"{fmt}.yaml"
    dump_suite(result.suite, path)
    assert load_suite(path).name == result.suite.name


def test_csv_case_column_names_each_conversation() -> None:
    result = import_conversation(CSV_EXPORT, fmt="csv")
    assert [case.name for case in result.suite.cases] == ["greeting", "refund"]


def test_csv_tolerates_prefixed_column_names() -> None:
    export = (
        "ticket,agent_role,agent_text,status\n"
        "T-1,customer,My app keeps crashing,solved\n"
        'T-1,support,"Sorry to hear that. Which version are you on?",solved\n'
    )
    result = import_conversation(export, fmt="csv")
    assert result.turns == 1
    assert "crashing" in result.conversations[0].messages[0].text


def test_csv_warns_about_unquoted_commas() -> None:
    export = "role,text\nuser,Hello\nbot,One, two, three\n"
    result = import_conversation(export, fmt="csv")
    assert any("more fields than the header" in warning for warning in result.warnings)
    # The words are still recovered even though the comma is gone.
    assert "two three" in result.conversations[0].messages[1].text


def test_markdown_keeps_multi_line_messages() -> None:
    export = (
        "# Help\n\n**User:** I am stuck\n\n**Bot:** Try this:\n1. open settings\n"
        "2. click billing\n\n**User:** still stuck\n\n**Bot:** Then it is a bug, sorry\n"
    )
    result = import_conversation(export, fmt="markdown")
    messages = result.conversations[0].messages
    assert messages[0].text == "I am stuck"
    assert "open settings" in messages[1].text and "click billing" in messages[1].text
    assert result.turns == 2


def test_text_uses_blank_lines_to_end_a_message() -> None:
    export = "User: Hello\nBot: Hi there\nfriend\n\nUser: Bye\nBot: See you\n"
    result = import_conversation(export, fmt="text")
    assert result.conversations[0].messages[1].text == "Hi there\nfriend"


def test_nested_json_conversations() -> None:
    export = json.dumps(
        [
            {
                "conversation": "alpha",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello there"},
                ],
            },
            {
                "conversation": "beta",
                "messages": [
                    {"role": "user", "content": "help"},
                    {"role": "assistant", "content": "sure thing"},
                ],
            },
        ]
    )
    result = import_conversation(export, fmt="json")
    assert [case.name for case in result.suite.cases] == ["alpha", "beta"]


def test_openai_style_content_parts() -> None:
    export = json.dumps(
        [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": " there"}],
            },
        ]
    )
    result = import_conversation(export, fmt="json")
    assert result.conversations[0].messages[1].text == "hello there"


def test_whatsapp_style_exports() -> None:
    export = "12:01 - Ada: Hi there\n12:02 - Support: Hello Ada, how can I help?\n"
    result = import_conversation(export, fmt="text")
    assert [m.role for m in result.conversations[0].messages] == ["user", "bot"]


def test_xml_uses_message_attributes_as_roles() -> None:
    export = (
        '<chat><message from="customer">Hello</message>'
        '<message from="support">Hi there friend</message></chat>'
    )
    result = import_conversation(export, fmt="xml")
    assert [m.role for m in result.conversations[0].messages] == ["user", "bot"]


def test_xml_uses_element_tags_as_roles() -> None:
    export = "<chat><user>Hello</user><bot>Hi there friend</bot></chat>"
    result = import_conversation(export, fmt="xml")
    assert [m.role for m in result.conversations[0].messages] == ["user", "bot"]


def test_html_uses_data_role_attributes() -> None:
    export = (
        '<div data-role="user">Hello</div><div data-role="bot">Hi there friend</div>'
    )
    result = import_conversation(export, fmt="html")
    assert [m.role for m in result.conversations[0].messages] == ["user", "bot"]


def test_bom_is_stripped() -> None:
    result = import_conversation("﻿" + JSON_EXPORT, fmt="json")
    assert result.turns == 2


# -- suite generation ------------------------------------------------------ #
def test_default_connector_replays_the_captured_replies() -> None:
    result = import_conversation(JSON_EXPORT, fmt="json")
    assert result.suite.connector.type == "scripted"
    first = result.suite.cases[0]
    assert first.connector is not None
    assert first.connector.type == "scripted"
    assert first.connector.config["replies"] == [
        "Hello! How can I help you today?",
        "Refunds are available within 30 days of purchase.",
    ]
    assert first.connector.config["repeat_last"] is False


def test_each_case_replays_its_own_transcript() -> None:
    """A fresh connector starts at reply 0, so cases must not share a script."""
    result = import_conversation(CSV_EXPORT, fmt="csv")
    greeting, refund = result.suite.cases
    assert greeting.connector.config["replies"] == ["Hi there friend"]
    assert refund.connector.config["replies"] == ["Refunds within 30 days"]


def test_connector_override_skips_replay() -> None:
    result = import_conversation(
        JSON_EXPORT, fmt="json", connector="http:url=http://127.0.0.1:8099/chat"
    )
    assert result.suite.connector.type == "http"
    assert result.suite.cases[0].connector is None


@pytest.mark.parametrize("style", ["contains", "exact", "none"])
def test_assertion_styles(style: str) -> None:
    result = import_conversation(JSONL_EXPORT, fmt="jsonl", assertions=style)
    specs = [spec.model_dump(mode="json") for spec in result.suite.cases[0].steps[0].expect]
    if style == "exact":
        assert specs[0]["type"] == "equals"
        assert specs[0]["value"] == "Hello there friend"
    elif style == "none":
        assert specs[0]["type"] == "not_empty"
    else:
        assert specs[0]["type"] == "contains"
        assert "Hello there friend" in specs[0]["value"]


def test_generated_contains_fragment_is_a_real_substring() -> None:
    export = json.dumps(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "Sure thing.\n\nHere is what you should do first, step by step, "
                "and then tell me how it goes.",
            },
        ]
    )
    reply = json.loads(export)[1]["content"]
    result = import_conversation(export, fmt="json")
    fragment = result.suite.cases[0].steps[0].expect[0].value
    assert " ".join(fragment.split()) in " ".join(reply.split())


def test_missing_replies_are_flagged_but_imported() -> None:
    export = "User: Hello\nBot: Hi there\n\nUser: Anyone there?\n"
    result = import_conversation(export, fmt="text")
    assert any("no bot reply" in warning for warning in result.warnings)
    assert result.turns == 2


def test_name_comes_from_the_filename() -> None:
    result = import_conversation(JSON_EXPORT, filename="support-bot.json")
    assert result.suite.name == "support-bot"


def test_explicit_name_wins() -> None:
    result = import_conversation(JSON_EXPORT, fmt="json", name="My Suite")
    assert result.suite.name == "my-suite"


def test_custom_tags_are_applied() -> None:
    result = import_conversation(JSON_EXPORT, fmt="json", tags=["regression", "chat"])
    assert all("regression" in case.tags for case in result.suite.cases)


def test_conversation_without_a_user_turn_is_rejected() -> None:
    with pytest.raises(ConversatError, match="no user turns"):
        import_conversation('[{"role": "bot", "content": "unprompted"}]', fmt="json")


def test_invalid_json_is_reported_clearly() -> None:
    with pytest.raises(ConversatError, match="invalid JSON"):
        import_conversation("[{not json", fmt="json")


def test_invalid_xml_is_reported_clearly() -> None:
    with pytest.raises(ConversatError, match="invalid XML"):
        import_conversation("<a><b></a>", fmt="xml")


def test_csv_without_recognisable_columns_is_rejected() -> None:
    with pytest.raises(ConversatError, match="no messages with a recognisable speaker"):
        import_conversation("alpha,beta\n1,2\n", fmt="csv")


def test_text_without_speaker_labels_is_rejected() -> None:
    with pytest.raises(ConversatError, match="User:"):
        import_conversation("just some prose\nwith no labels\n", fmt="text")


# -- conversat's own artefacts -------------------------------------------- #
async def test_run_report_becomes_a_replay_suite() -> None:
    original = await TestRunner(load_suite("examples/suites/echo.yaml")).run()
    result = import_conversation(original.model_dump_json(), fmt="report")

    assert len(result.suite.cases) == len(original.cases)
    assert result.suite.connector.type == "scripted"

    replayed = await TestRunner(result.suite).run()
    assert replayed.ok, "replaying a report must reproduce it exactly"
    assert replayed.totals.assertions_passed == replayed.totals.assertions


async def test_report_replay_preserves_intentional_errors() -> None:
    """A case that tested for a failure must still test for that failure."""
    original = await TestRunner(load_suite("examples/suites/echo.yaml")).run()
    result = import_conversation(original.model_dump_json(), fmt="report")
    errored = [
        case for case in result.suite.cases if case.connector and case.connector.config.get("error_at")
    ]
    assert errored, "the echo suite has a case that expects an error"
    assert (await TestRunner(result.suite).run()).ok


async def test_report_import_detects_a_changed_reply() -> None:
    """The generated assertions must have teeth against a drifting bot."""
    original = await TestRunner(load_suite("examples/suites/echo.yaml")).run()
    result = import_conversation(original.model_dump_json(), fmt="report")

    case = result.suite.cases[0]
    case.connector = case.connector.model_copy(
        update={"config": {**case.connector.config, "replies": ["a completely different answer"]}}
    )
    outcome = await TestRunner(result.suite).run()
    assert not outcome.ok


async def test_crawl_report_becomes_a_replay_suite() -> None:
    from conversat.crawler.crawler import crawl
    from conversat.models.crawler import CrawlConfig
    from conversat.models.suite import ConnectorConfig

    crawled = await crawl(
        CrawlConfig(seeds=["hello", "thanks"], max_depth=1, max_turns=4, branching=1),
        ConnectorConfig(type="echo", config={"prefix": ">> "}),
    )
    result = import_conversation(crawled.model_dump_json(), fmt="crawl")
    assert result.conversations
    assert (await TestRunner(result.suite).run()).ok


def test_a_suite_pasted_as_yaml_passes_through() -> None:
    source = "name: kept\nconnector: {type: echo}\ncases:\n  - name: c\n    steps:\n      - send: hi\n"
    result = import_conversation(source)
    assert result.format == "yaml"
    assert result.suite.name == "kept"
    assert len(result.suite.cases) == 1
    assert result.suite.connector.type == "echo"


def test_suite_shaped_yaml_behind_a_transcript_detector() -> None:
    """Detection is a heuristic; a suite must not be lost to the text parser."""
    source = "name: kept\nconnector: {type: echo}\ncases:\n  - name: c\n    steps:\n      - send: hi\n"
    result = import_conversation(source, filename="mystery.dat")
    assert result.suite.name == "kept"


def test_summary_reports_the_numbers_the_ui_shows() -> None:
    summary = import_conversation(MARKDOWN_EXPORT, fmt="markdown").summary()
    assert summary["format"] == "markdown"
    assert summary["cases"] == 2
    assert summary["turns"] == 2
    assert summary["messages"] == 4
    assert summary["assertions"] > 0
    assert summary["warnings"]
