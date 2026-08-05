"""Structured outputs for steps that another step branches on.

Anything that drives control flow is a Pydantic model, never prose. The Phase 4 Flow
router reads :attr:`QAReport.passed` — a boolean — rather than grepping an LLM's summary
for the word "pass", which is the difference between a bounded loop and a demo that
loops forever.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """How badly a finding blocks release.

    Only ``BLOCKER`` and ``MAJOR`` fail the build; the rest are advisory, so a pedantic
    inspector cannot trap the crew in a rework loop over cosmetics.
    """

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


FAILING_SEVERITIES = frozenset({Severity.BLOCKER, Severity.MAJOR})


class Finding(BaseModel):
    """One defect, tied to a place in the sandbox and to what the requirements asked for."""

    severity: Severity
    file: str = Field(description="Sandbox file the finding applies to, e.g. 'account.py'")
    summary: str = Field(description="One sentence stating the defect")
    detail: str = Field(default="", description="Why it is wrong and how to fix it")
    requirement: str = Field(
        default="",
        description="The requirement this violates, if it traces to one",
    )


class QAReport(BaseModel):
    """The inspector's verdict on a build.

    ``passed`` is set by the inspector, but :meth:`verdict` recomputes it from the
    findings so an agent that says "passed" while reporting blockers cannot wave a
    broken build through.
    """

    passed: bool = Field(description="True only if nothing blocker- or major-severity remains")
    summary: str = Field(description="Two or three sentences on the state of the build")
    findings: list[Finding] = Field(default_factory=list)
    tests_run: bool = Field(default=False, description="Whether the unit tests were executed")
    tests_passed: bool = Field(default=False, description="Whether every executed test passed")

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in FAILING_SEVERITIES]

    def verdict(self) -> bool:
        """Return the trustworthy pass/fail, ignoring a self-contradictory ``passed``.

        A build passes only if the inspector claimed so, no blocking findings remain,
        and the tests actually ran and passed. "I did not run the tests" is not a pass.
        """
        return (
            self.passed
            and not self.blocking_findings
            and self.tests_run
            and self.tests_passed
        )
