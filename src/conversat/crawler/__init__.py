"""Conversation crawler: explore a bot and turn findings into test cases."""

from __future__ import annotations

from conversat.crawler.crawler import Crawler, CrawlOptions, crawl
from conversat.crawler.followups import (
    DEFAULT_FOLLOW_UPS,
    CallableFollowUps,
    FollowUpGenerator,
    StaticFollowUps,
    TemplateFollowUps,
    default_generator,
)
from conversat.crawler.suggest import (
    build_test_cases,
    common_responses,
    coverage_from,
    detect_issues,
    suggested_assertions,
)

__all__ = [
    "CallableFollowUps",
    "CrawlOptions",
    "Crawler",
    "DEFAULT_FOLLOW_UPS",
    "FollowUpGenerator",
    "StaticFollowUps",
    "TemplateFollowUps",
    "build_test_cases",
    "common_responses",
    "coverage_from",
    "crawl",
    "default_generator",
    "detect_issues",
    "suggested_assertions",
]
