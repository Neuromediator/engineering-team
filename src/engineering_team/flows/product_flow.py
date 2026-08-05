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

from crewai.flow.flow import Flow, listen, or_, router, start
from crewai.flow.human_feedback import human_feedback
from crewai.flow.persistence import persist
from pydantic import BaseModel, Field

from ..budget import run_limit
from ..capabilities import CONSTRAINTS_PROMPT
from ..crew import EngineeringTeam
from ..model_config import llm_for
from ..schemas import QAReport
from ..tools.sandbox_tools import SANDBOX_ROOT, Sandbox, new_run_id
from ..ui.feedback_provider import PendingUIFeedbackProvider


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

    # This run's own sandbox. Kept in state so a flow resumed from a checkpoint returns
    # to the same directory instead of starting a fresh one and losing the build.
    run_id: str = ""

    qa_report: QAReport | None = None
    history: list[IterationRecord] = Field(default_factory=list)

    # Accumulated instructions for the next build: QA blockers, then human feedback.
    revision_notes: list[str] = Field(default_factory=list)

    # How many entries of the flow's human_feedback_history have already been folded into
    # revision_notes, so a resumed build cannot apply the same feedback twice.
    feedback_seen: int = 0

    # Per-flow token totals, summed from each crew result. The global cost recorder listens
    # on a shared event bus and cannot tell concurrent flows apart, so when several runs
    # race each other this is the only per-run accounting that is actually attributable.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0

    approved: bool = False
    exhausted: bool = False
    shipped: bool = False

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

    def _absorb_human_feedback(self) -> None:
        """Fold any new human feedback into the revision notes.

        A human explicitly asking for more work also grants a fresh automatic budget:
        the iteration cap exists to bound *unattended* looping, not to overrule someone
        who is sitting there watching it.
        """
        history = list(getattr(self, "human_feedback_history", []) or [])
        new = history[self.state.feedback_seen :]
        if not new:
            return

        for result in new:
            text = (getattr(result, "feedback", "") or "").strip()
            if text:
                self.state.revision_notes.append(f"[human] {text}")

        self.state.feedback_seen = len(history)
        self.state.approved = False
        self.state.exhausted = False
        self.state.max_iterations = self.state.iteration + MAX_AUTO_ITERATIONS

    def sandbox(self) -> Sandbox:
        """This run's sandbox, created once and reused for every iteration.

        Caching matters more than it looks. A revision iteration must see the code the
        previous one wrote, and with a remote backend a fresh object would mean a fresh
        microVM — empty, and leaking the one still running and still billing.
        """
        if not self.state.run_id:
            self.state.run_id = new_run_id()

        existing = getattr(self, "_sandbox", None)
        if existing is not None:
            return existing

        sandbox = Sandbox(SANDBOX_ROOT / self.state.run_id, run_id=self.state.run_id)
        self._sandbox = sandbox
        return sandbox

    def release_sandbox(self) -> None:
        """Release the workspace. A no-op locally; ends billing on a remote backend."""
        sandbox = getattr(self, "_sandbox", None)
        if sandbox is not None:
            sandbox.close()
            self._sandbox = None

    @start("revise")
    def build(self) -> str:
        """Run the hierarchical crew. Re-entered on "revise" with feedback in state."""
        self._absorb_human_feedback()
        self.state.iteration += 1

        sandbox = self.sandbox()

        # Only wipe the sandbox on the first attempt. A revision is meant to *fix* the
        # existing code — resetting here would throw away the work being corrected and
        # make every iteration start from nothing.
        if self.state.iteration == 1:
            sandbox.reset()

        result = EngineeringTeam(sandbox=sandbox).crew().kickoff(
            inputs={
                "requirements": self.state.requirements,
                "revision_notes": self.state.notes_for_prompt(),
                "constraints": CONSTRAINTS_PROMPT,
            }
        )

        usage = getattr(result, "token_usage", None)
        if usage is not None:
            self.state.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.state.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.state.llm_calls += getattr(usage, "successful_requests", 0) or 0

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

        # Money ceiling, checked between iterations. CrewAI exposes no cancellation hook,
        # so this cannot stop a crew mid-flight — the wall-clock caps in crew.py are what
        # bound a single iteration. What this does prevent is spending another whole
        # iteration once a run has already cost more than it should.
        probe = getattr(self, "_cost_probe", None)
        ceiling = run_limit()
        if probe is not None and ceiling > 0 and probe() >= ceiling:
            self.state.exhausted = True
            self.state.revision_notes.append(
                f"[budget] Stopped after ${probe():.2f}, over the ${ceiling:.2f} per-run "
                f"ceiling, with blocking findings outstanding."
            )
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

    @listen(or_(finalize, stop_at_cap))
    @human_feedback(
        message=(
            "Review the build. Reply with what you want changed, or say it looks good "
            "to ship it."
        ),
        emit=["ship", "revise"],
        # The decorator defaults this to "gpt-5.4-mini", which would route to OpenAI —
        # a key this project does not use and a fourth model outside the chosen three.
        llm=llm_for("engineering_lead"),
        # If nobody answers (a headless run, or a UI that went away), ship what we have
        # rather than hanging or silently looping.
        default_outcome="ship",
        provider=PendingUIFeedbackProvider(),
    )
    def human_review(self) -> dict:
        """Show the human what was built and let them send it back for another pass.

        Reaching here means the automatic loop has settled — either QA passed or the cap
        was hit. The human decides whether that is good enough. Emitting "revise" re-enters
        :meth:`build`, which is the same branch the router uses, so human and automatic
        revisions travel identical machinery.
        """
        report = self.state.qa_report
        return {
            "approved_by_qa": self.state.approved,
            "stopped_at_cap": self.state.exhausted,
            "iterations": self.state.iteration,
            "qa_summary": report.summary if report else "No QA report was produced.",
            "blocking_findings": [
                f"[{f.severity.value}] {f.file}: {f.summary}"
                for f in (report.blocking_findings if report else [])
            ],
        }

    @listen("ship")
    def deliver(self) -> str:
        self.state.shipped = True
        verdict = "QA-approved" if self.state.approved else "shipped with findings outstanding"
        message = f"Delivered after {self.state.iteration} iteration(s) — {verdict}."
        print(f"\n{message}")
        # Terminal step: nothing else will touch the workspace, so stop paying for it.
        # Deliberately not done in finalize/stop_at_cap — a human can still send those
        # back for another pass, and that pass needs the existing files.
        self.release_sandbox()
        return message
