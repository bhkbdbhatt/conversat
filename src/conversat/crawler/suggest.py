"""Turn a crawl into human findings and ready-to-run test cases."""

from __future__ import annotations

from collections import Counter

from conversat.models.assertion import parse_assertions
from conversat.models.crawler import CrawlIssue, CrawlNode, CrawlReport
from conversat.models.report import TurnStatus
from conversat.models.suite import TestCase, Turn
from conversat.utils import normalize_text, percentiles, truncate

ERROR_KEYWORDS = ("i'm sorry", "i am sorry", "an error", "internal server error", "traceback", "exception")
SLOW_THRESHOLD_MS = 4000.0
SHORT_REPLY_CHARS = 2


def _issue(
    kind: str,
    severity: str,
    message: str,
    node: CrawlNode,
) -> CrawlIssue:
    return CrawlIssue(
        kind=kind,
        severity=severity,
        node_id=node.id,
        depth=node.depth,
        message=message,
        request=truncate(node.request, 120),
        response=truncate(node.response.text, 200) if node.response else None,
    )


def detect_issues(report: CrawlReport) -> list[CrawlIssue]:
    """Flag empty replies, errors, slow answers and suspicious repetition."""
    cfg = report.config
    keywords = tuple(cfg.error_keywords) or ERROR_KEYWORDS
    issues: list[CrawlIssue] = []
    seen: dict[str, list[str]] = {}

    for node in report.nodes:
        response = node.response
        reply = response.text if response else ""

        if node.status is TurnStatus.ERROR or (response and response.is_error):
            issues.append(
                _issue("error", "error", node.error or "turn failed with an error", node)
            )
            continue

        if not reply.strip():
            issues.append(_issue("empty_response", "warning", "bot returned an empty reply", node))
            continue

        if len(reply.strip()) <= max(SHORT_REPLY_CHARS, cfg.min_response_length):
            issues.append(
                _issue("empty_response", "info", "reply is suspiciously short", node)
            )

        if response and response.latency_ms and response.latency_ms > SLOW_THRESHOLD_MS:
            issues.append(
                _issue(
                    "slow_response",
                    "warning",
                    f"slow reply ({response.latency_ms:.0f}ms)",
                    node,
                )
            )

        lowered = normalize_text(reply)
        if any(k in lowered for k in keywords):
            issues.append(
                _issue("error", "warning", "reply looks like an error message", node)
            )

        key = normalize_text(reply)[:120]
        seen.setdefault(key, []).append(node.id)
        if len(seen[key]) >= 3:
            issues.append(
                _issue(
                    "repeated_response",
                    "info",
                    f"identical reply seen {len(seen[key])} times",
                    node,
                )
            )

    return issues


def coverage_from(report: CrawlReport) -> None:
    """Fill in ``report.coverage`` from the collected nodes (in place)."""
    nodes = report.nodes
    latencies = [n.response.latency_ms for n in nodes if n.response and n.response.latency_ms]
    pct = percentiles(latencies)
    unique = {normalize_text(n.response.text) for n in nodes if n.response and n.response.text}
    errored = sum(1 for n in nodes if n.status is TurnStatus.ERROR)
    empty = sum(1 for n in nodes if n.response and not n.response.text.strip())

    report.coverage = report.coverage.model_copy(
        update={
            "nodes": len(nodes),
            "passed": sum(1 for n in nodes if n.status is TurnStatus.PASSED),
            "errored": errored,
            "empty_responses": empty,
            "unique_responses": len(unique),
            "max_depth_reached": max((n.depth for n in nodes), default=0),
            "response_p50_ms": pct.p50,
            "response_p95_ms": pct.p95,
            "error_rate": (errored / len(nodes) * 100) if nodes else 0.0,
            "explored": bool(nodes),
            "exhausted_budget": len(nodes) >= report.config.max_turns,
        }
    )


def common_responses(report: CrawlReport, *, top: int = 5) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for node in report.nodes:
        if node.response and node.response.text:
            counter[normalize_text(truncate(node.response.text, 80))] += 1
    return counter.most_common(top)


def suggested_assertions(node: CrawlNode) -> list:
    """Pick a small, high-signal assertion set for one crawled exchange."""
    specs: list = []
    reply = node.response.text if node.response else ""
    if node.status is TurnStatus.ERROR:
        specs.extend(parse_assertions([{"no_error": {"expect_error": True}}]))
        return specs

    specs.extend(parse_assertions([{"type": "no_error", "expect_error": False}]))
    if not reply.strip():
        specs.extend(parse_assertions([{"type": "is_empty"}]))
        return specs

    specs.extend(parse_assertions([{"type": "not_empty"}]))
    words = [w.strip(".,!?") for w in reply.split() if len(w) > 3]
    if words:
        specs.extend(parse_assertions([{"type": "contains_any", "values": words[:5]}]))
    if node.response and node.response.latency_ms:
        budget = max(1000.0, round((node.response.latency_ms + node.response.latency_ms * 0.5) / 500) * 500)
        specs.extend(parse_assertions([{"type": "response_time_under", "value": budget}]))
    return specs


def build_test_cases(report: CrawlReport, *, name_prefix: str = "crawl") -> list[TestCase]:
    """Generate one test case per successful root-to-leaf transcript."""
    cases: list[TestCase] = []
    for index, transcript in enumerate(report.transcripts(), start=1):
        healthy = [n for n in transcript if n.status is TurnStatus.PASSED and n.response and n.response.text.strip()]
        if not healthy:
            continue
        turns: list[Turn] = []
        for node in healthy:
            turns.append(
                Turn(
                    send=node.request,
                    expect=suggested_assertions(node),
                    name=f"depth-{node.depth}",
                    metadata={"crawl_node": node.id, "reply": truncate(node.response.text, 200)},
                )
            )
        if not turns:
            continue
        cases.append(
            TestCase(
                name=f"{name_prefix}-{index:02d}",
                description=f"Auto-generated from a crawl of {report.suite}",
                tags=["crawl", "generated"],
                steps=turns,
                metadata={"source": "crawler", "depth": transcript[-1].depth},
            )
        )
    return cases
