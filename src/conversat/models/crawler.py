"""Crawler models: crawl configuration, graph nodes and the crawl report."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from conversat.models.report import TurnStatus, utcnow
from conversat.models.response import BotResponse
from conversat.models.suite import Expectations, RetryPolicy, TestCase, Turn


class CrawlConfig(BaseModel):
    """Budget and behaviour of a conversation crawl."""

    model_config = ConfigDict(extra="forbid")

    seeds: list[str] = Field(min_length=1, description="Opening messages")
    max_depth: int = Field(default=2, ge=1, le=10)
    max_turns: int = Field(default=20, ge=1, le=500)
    branching: int = Field(default=2, ge=1, le=10, description="Follow-ups per response")
    concurrency: int = Field(default=2, ge=1, le=16)
    timeout: float | None = Field(default=None, gt=0)
    retry: RetryPolicy | None = None
    follow_ups: list[str] = Field(default_factory=list, description="Extra follow-up templates")
    dedupe: bool = True
    case_sensitive: bool = False
    stop_on_error: bool = False
    error_keywords: list[str] = Field(default_factory=list)
    error_statuses: list[str] = Field(default_factory=list)
    min_response_length: int = Field(default=0, ge=0)
    ignore_turns_containing: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def budget_for_depth(self, depth: int) -> int:
        """How many turns may still be sent (used by the frontier scheduler)."""
        remaining_depth = max(self.max_depth - depth, 0)
        return remaining_depth * self.branching


class CrawlNode(BaseModel):
    """One request/response pair in the conversation tree."""

    model_config = ConfigDict(extra="forbid")

    id: str
    depth: int = Field(ge=0)
    request: str
    response: BotResponse | None = None
    status: TurnStatus = TurnStatus.PASSED
    duration_ms: float = 0.0
    parent: str | None = None
    children: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is TurnStatus.PASSED


class CrawlCoverage(BaseModel):
    """Aggregate statistics used to judge how well a bot was explored."""

    model_config = ConfigDict(extra="forbid")

    nodes: int = 0
    passed: int = 0
    errored: int = 0
    empty_responses: int = 0
    unique_responses: int = 0
    max_depth_reached: int = 0
    response_p50_ms: float = 0.0
    response_p95_ms: float = 0.0
    error_rate: float = 0.0
    explored: bool = False
    exhausted_budget: bool = False


class CrawlIssue(BaseModel):
    """Something a human (or a generated test) should look at."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="empty_response | slow_response | error | repeated_response")
    severity: str = Field(default="warning", description="info | warning | error")
    node_id: str | None = None
    depth: int | None = None
    message: str
    request: str | None = None
    response: str | None = None


class CrawlReport(BaseModel):
    """Result of a crawl, including optional generated test cases."""

    model_config = ConfigDict(extra="forbid")

    suite: str = "crawled"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)
    config: CrawlConfig
    connector: str = "unknown"
    connector_config: dict[str, Any] = Field(
        default_factory=dict, description="Reused verbatim when generating a suite"
    )
    roots: list[str] = Field(default_factory=list)
    nodes: list[CrawlNode] = Field(default_factory=list)
    coverage: CrawlCoverage = Field(default_factory=CrawlCoverage)
    issues: list[CrawlIssue] = Field(default_factory=list)
    suggested_cases: list[TestCase] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.coverage.errored == 0

    def node(self, node_id: str) -> CrawlNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() * 1000

    def transcripts(self) -> list[list[CrawlNode]]:
        """Every root-to-leaf conversation, in discovery order."""
        by_id = {n.id: n for n in self.nodes}
        out: list[list[CrawlNode]] = []

        def walk(node: CrawlNode, acc: list[CrawlNode]) -> None:
            path = [*acc, node]
            kids = [by_id[c] for c in node.children if c in by_id]
            if not kids:
                out.append(path)
                return
            for kid in kids:
                walk(kid, path)

        for root_id in self.roots:
            root = by_id.get(root_id)
            if root is not None:
                walk(root, [])
        return out

    def to_suite(self, *, name: str | None = None) -> dict[str, Any]:
        """Serialise the crawl (plus generated cases) as a suite payload."""
        return {
            "name": name or f"{self.suite}-crawl",
            "description": "Generated by the conversat crawler",
            "connector": {"type": self.connector, "config": dict(self.connector_config)},
            "metadata": {
                "generated_by": "conversat.crawler",
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "coverage": self.coverage.model_dump(mode="json"),
            },
            "cases": [
                case.model_dump(mode="json", by_alias=True, exclude_none=True)
                for case in self.suggested_cases
            ],
        }


def turn_from_node(node: CrawlNode, expectations: Expectations | None = None) -> Turn:
    """Build a :class:`Turn` mirroring one crawled exchange."""
    return Turn(send=node.request, expect=list(expectations or []), name=f"depth-{node.depth}")
