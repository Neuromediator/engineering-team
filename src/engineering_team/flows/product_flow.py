"""The outer loop: build, inspect, decide, revise.

The hierarchical crew decides *how* to build. This Flow decides *whether the result is
good enough* and whether to go round again — and, crucially, it is the thing that cannot
loop forever.

Why the split: autonomy is valuable inside a single build (the manager genuinely should
pick who does what), but a self-assessing agent deciding "shall I keep spending money?"
is not a property you want in a demo. So the decision to iterate lives here, in ordinary
Python, branching on :meth:`QAReport.verdict` — a boolean derived from structured findings,
never on parsed prose.

    @start / @start("revise")  build      -> run the hierarchical crew
    @router(build)             evaluate   -> "approved" | "revise" | "exhausted"
    @listen("approved")        finalize
    @listen("exhausted")       stop_at_cap

``@persist()`` checkpoints state to SQLite after every step, which is what makes the
Phase 5 human-in-the-loop pause survivable: the UI can come back later via
``Flow.from_pending(flow_id)`` and resume.
"""

from __future__ import annotations

from crewai.flow.flow import Flow, listen, router, start
from crewai.flow.persistence import persist
from pydantic import BaseModel, Field

from ..crew import EngineeringTeam
from ..schemas import QAReport
from ..tools.sandbox_tools import reset_sandbox


# The cost ceiling. Each iteration is a full hierarchical crew run, so this number is
# the difference between a bounded demo and an unbounded bill.
MAX_AUTO_ITERATIONS = 3


class IterationRecord(BaseModel):
    """One trip round the loop, kept so the UI can show what changed and why."""

    iteration: int
    passed: bool
    blocking_findings: int
    tests_passed: bool
    summary: str


class ProductState(BaseModel):
    """Everything the loop needs to resume from a checkpoint."""

    requirements: str = ""
    iteration: int = 0
    max_iterations: int = MAX_AUTO_ITERATIONS

    qa_report: QAReport | None = None
    history: list[IterationRecord] = Field(default_factory=list)

    # Accumulated instructions for the next build: QA blockers, and later human feedback.
    revision_notes: list[str] = Field(default_factory=list)

    approved: bool = False
    exhausted: bool = False

    def notes_for_prompt(self) -> str:
        """Render revision notes for interpolation into the task descriptions."""
        if not self.revision_notes:
            return "None - this is the first attempt."
        return "\n".join(f"- {note}" for note in self.revision_notes)


def _extract_report(result) -> QAReport | None:
    """Pull the QAReport out of a crew result, tolerating a missing one.

    A model can fail to produce valid structured output. That must read as "not verified"
    and send the loop round again, never as a silent pass.
    """
    if isinstance(getattr(result, "pydantic", None), QAReport):
        return result.pydantic
    for task_output in reversed(getattr(result, "tasks_output", []) or []):
        if isinstance(getattr(task_output, "pydantic", None), QAReport):
            return task_output.pydantic
    return None


@persist()
class ProductFlow(Flow[ProductState]):
    """Build → inspect → decide, bounded by :data:`MAX_AUTO_ITERATIONS`."""

    @start("revise")
    def build(self) -> str:
        """Run the hierarchical crew. Re-entered on "revise" with feedback in state."""
        self.state.iteration += 1

        # Only wipe the sandbox on the first attempt. A revision is meant to *fix* the
        # existing code — resetting here would throw away the work being corrected and
        # make every iteration start from nothing.
        if self.state.iteration == 1:
            reset_sandbox()

        result = EngineeringTeam().crew().kickoff(
            inputs={
                "requirements": self.state.requirements,
                "revision_notes": self.state.notes_for_prompt(),
            }
        )

        report = _extract_report(result)
        self.state.qa_report = report
        self.state.history.append(
            IterationRecord(
                iteration=self.state.iteration,
                passed=bool(report and report.verdict()),
                blocking_findings=len(report.blocking_findings) if report else 0,
                tests_passed=bool(report and report.tests_passed),
                summary=(
                    report.summary
                    if report
                    else "QA produced no structured report; treated as not verified."
                ),
            )
        )
        return "built"

    @router(build)
    def evaluate(self) -> str:
        """Decide the next branch from structured findings, not from prose."""
        report = self.state.qa_report

        if report is not None and report.verdict():
            self.state.approved = True
            return "approved"

        if self.state.iteration >= self.state.max_iterations:
            self.state.exhausted = True
            return "exhausted"

        # Carry the blockers forward so the next build knows what to fix.
        if report is not None:
            for finding in report.blocking_findings:
                self.state.revision_notes.append(
                    f"[{finding.severity.value}] {finding.file}: {finding.summary}"
                    + (f" ({finding.detail})" if finding.detail else "")
                )
            if not report.tests_run:
                self.state.revision_notes.append(
                    "[blocker] The unit tests were never actually executed. Run them."
                )
        else:
            self.state.revision_notes.append(
                "[blocker] QA returned no structured report. Re-inspect and emit a QAReport."
            )

        return "revise"

    @listen("approved")
    def finalize(self) -> str:
        message = (
            f"Approved after {self.state.iteration} "
            f"iteration{'s' if self.state.iteration != 1 else ''}."
        )
        print(f"\n{message}")
        return message

    @listen("exhausted")
    def stop_at_cap(self) -> str:
        """Stop honestly rather than looping. The cap is a feature, not a failure mode."""
        blocking = (
            len(self.state.qa_report.blocking_findings) if self.state.qa_report else 0
        )
        message = (
            f"Stopped at the {self.state.max_iterations}-iteration cap with "
            f"{blocking} blocking finding(s) outstanding. The build is NOT approved."
        )
        print(f"\n{message}")
        return message
