"""JUnit XML formatter (compatible with Jenkins, GitLab CI, Azure DevOps...)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from conversat.models.report import CaseResult, RunReport, TurnStatus
from conversat.reporting.base import Formatter, register


@register("junit")
class JUnitFormatter(Formatter):
    """``<testsuites>`` document with one testcase per turn."""

    name = "junit"
    extension = "xml"

    def format(self, report: RunReport) -> str:
        totals = report.totals
        suites = ET.Element(
            "testsuites",
            {
                "name": f"conversat:{report.suite}",
                "tests": str(totals.turns or totals.cases),
                "failures": str(totals.cases_failed),
                "errors": str(totals.cases_errored),
                "skipped": str(totals.cases_skipped),
                "time": f"{report.duration_ms / 1000:.3f}",
                "timestamp": report.started_at.isoformat(),
            },
        )

        for case in report.cases:
            suite = ET.SubElement(
                suites,
                "testsuite",
                {
                    "name": case.name,
                    "tests": str(max(len(case.turns), 1)),
                    "failures": str(sum(1 for t in case.turns if t.status is TurnStatus.FAILED)),
                    "errors": str(sum(1 for t in case.turns if t.status is TurnStatus.ERROR)),
                    "skipped": str(sum(1 for t in case.turns if t.status is TurnStatus.SKIPPED)),
"time": f"{self._duration_ms(case) / 1000:.3f}",
                "timestamp": case.started_at.isoformat(),
            },
        )
            props = ET.SubElement(suite, "properties")
            ET.SubElement(props, "property", {"name": "conversat.tags", "value": ",".join(case.tags)})
            ET.SubElement(props, "property", {"name": "conversat.connector", "value": case.connector})

            if not case.turns:
                self._add_case(suite, case.name, "setup", TurnStatus.ERROR, case.error, None)
                continue
            for turn in case.turns:
                label = turn.name or turn.summary(limit=40)
                detail = None
                if turn.status is TurnStatus.FAILED:
                    detail = "\n".join(
                        f"{a.description}: {a.message}" for a in turn.failed_assertions
                    )
                elif turn.error:
                    detail = turn.error
                self._add_case(suite, case.name, label, turn.status, detail, turn)

        ET.indent(suites, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suites, encoding="unicode")

    @staticmethod
    def _duration_ms(case: CaseResult) -> float:
        return (case.finished_at - case.started_at).total_seconds() * 1000

    @staticmethod
    def _add_case(
        suite: ET.Element,
        case_name: str,
        label: str,
        status: TurnStatus,
        detail: str | None,
        turn: object,
    ) -> None:
        node = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": case_name,
                "name": f"{label}" if label else "turn",
                "time": f"{getattr(turn, 'duration_ms', 0.0) / 1000:.3f}",
            },
        )
        if status is TurnStatus.FAILED:
            failure = ET.SubElement(node, "failure", {"message": "assertion failed"})
            failure.text = detail or "assertions failed"
            reply = getattr(getattr(turn, "response", None), "text", None)
            if reply:
                ET.SubElement(node, "system-out").text = f"reply: {reply}"
        elif status is TurnStatus.ERROR:
            error = ET.SubElement(node, "error", {"message": "error"})
            error.text = detail or "turn errored"
        elif status is TurnStatus.SKIPPED:
            ET.SubElement(node, "skipped", {"message": detail or "skipped"})
        else:
            reply = getattr(getattr(turn, "response", None), "text", None)
            if reply:
                ET.SubElement(node, "system-out").text = f"reply: {reply}"
