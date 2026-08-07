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

import os

from crewai.flow.flow import Flow, listen, or_, router, start
from crewai.flow.human_feedback import human_feedback
from crewai.flow.persistence import persist
from pydantic import BaseModel, Field

from ..budget import run_limit
from ..capabilities import CONSTRAINTS_PROMPT, REVISION_PROMPT
from ..crew import EngineeringTeam
from ..schemas import QAReport
from ..tools.sandbox_tools import SANDBOX_ROOT, Sandbox, new_run_id
from ..ui.feedback_provider import PendingUIFeedbackProvider


# The cost ceiling. Each iteration is a full crew run, so this number is the difference
# between a bounded demo and an unbounded bill. Deployed, 2 is the sane value: a gym
# booking build used its full budget of 3 and took most of an hour.
MAX_AUTO_ITERATIONS = int(os.environ.get("MAX_AUTO_ITERATIONS", "3"))

# The UI states the human's decision explicitly by prefixing their feedback with one of
# these. It is a sentinel, not natural language, because the branch must be decided by
# reading a marker the interface set — never by asking a model to interpret prose.
SHIP_MARKER = "[[SHIP]]"
REVISE_MARKER = "[[REVISE]]"


def strip_marker(feedback: str) -> str:
    """Return the human's actual words, without the decision sentinel."""
    text = (feedback or "").strip()
    for marker in (SHIP_MARKER, REVISE_MARKER):
        if text.startswith(marker):
            return text[len(marker):].strip()
    return text

# Finished source is archived here so it outlives the sandbox.
EXPORTS_DIR = SANDBOX_ROOT.parent / "exports"


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

    # The remote workspace's identity, for backends that have one. The run_id above is
    # enough for Docker, whose directory is still on disk after a pause — but an E2B
    # microVM is only reachable by its own id, and a resumed flow that did not have it
    # started an empty VM, archived nothing, and deleted the archive of the build a
    # human had just approved.
    sandbox_id: str = ""

    # "sequential" or "hierarchical". Empty means take the CREW_PROCESS default. Kept in
    # state so a resumed run keeps the process it started with.
    process: str = ""

    # Where the finished source was archived. Set before the sandbox is released,
    # because with a remote backend the files die with the VM.
    archive_path: str = ""

    # Where this run's activity log was written. The log lives in memory on the event
    # bus and dies with the process, so a finished run used to lose its own trace: the
    # packaged example had to be recovered from screenshots after the fact.
    log_path: str = ""

    qa_report: QAReport | None = None

    # Which iteration produced `qa_report`, and whether the newest attempt crashed before
    # producing one. A failed iteration must not be routed on a stale verdict — but
    # throwing the verdict away left the panel blank and the human with nothing to read.
    qa_report_iteration: int = 0
    last_iteration_failed: bool = False
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
            text = strip_marker(getattr(result, "feedback", "") or "")
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

        # `_sandbox` is an instance attribute and does not survive @persist, so a flow
        # rebuilt by from_pending() arrives here with nothing. state.sandbox_id is how
        # it finds the workspace it already had.
        sandbox = Sandbox(
            SANDBOX_ROOT / self.state.run_id,
            run_id=self.state.run_id,
            sandbox_id=self.state.sandbox_id,
        )
        self._sandbox = sandbox
        return sandbox

    def _remember_sandbox(self) -> None:
        """Record the remote workspace's id, once the backend has one to record.

        Called after work rather than at construction: E2B starts its VM lazily on the
        first operation, so asking before then returns an empty string.
        """
        sandbox = getattr(self, "_sandbox", None)
        if sandbox is None:
            return
        current = sandbox.sandbox_id
        if current and current != self.state.sandbox_id:
            self.state.sandbox_id = current

    def release_sandbox(self) -> None:
        """Release the workspace. A no-op locally; ends billing on a remote backend."""
        sandbox = getattr(self, "_sandbox", None)
        if sandbox is not None:
            sandbox.close()
            self._sandbox = None

    def _cancelled(self) -> bool:
        """Whether the visitor has walked away from this run.

        Injected like the cost and log probes, so the flow keeps working headlessly
        where there is no session and nothing to walk away from.
        """
        probe = getattr(self, "_cancel_probe", None)
        return bool(probe and probe())

    def _run_crew(self, sandbox):
        """One crew pass. Split out so :meth:`build` can guard it."""
        revising = self.state.iteration > 1
        constraints = CONSTRAINTS_PROMPT + (REVISION_PROMPT if revising else "")
        return EngineeringTeam(
            sandbox=sandbox,
            process=self.state.process or None,
            revision=revising,
        ).crew().kickoff(
            inputs={
                "requirements": self.state.requirements,
                "revision_notes": self.state.notes_for_prompt(),
                "constraints": constraints,
            }
        )

    @start("revise")
    def build(self) -> str:
        """Run the hierarchical crew. Re-entered on "revise" with feedback in state."""
        if self._cancelled():
            # Reached when a cancel lands between steps. Returning without running
            # the crew is the whole saving: the next iteration is the expensive
            # thing, and it never starts.
            print("\nCancelled before iteration; not starting the crew.")
            return "built"

        self._absorb_human_feedback()
        self.state.iteration += 1

        sandbox = self.sandbox()

        # Only wipe the sandbox on the first attempt. A revision is meant to *fix* the
        # existing code — resetting here would throw away the work being corrected and
        # make every iteration start from nothing.
        if self.state.iteration == 1:
            sandbox.reset()

        try:
            result = self._run_crew(sandbox)
        except Exception as exc:  # noqa: BLE001 - an iteration may fail; a run must not
            # A crew that raises — an agent hitting its wall-clock backstop, a provider
            # error — is a failed *iteration*, not a crashed run. Treating it as fatal
            # threw away a completed iteration's work and left the human nothing to act
            # on. Record it, let evaluate() decide whether another attempt is affordable.
            reason = f"{type(exc).__name__}: {exc}"
            print(f"\nIteration {self.state.iteration} failed: {reason}")
            # Keep the previous report for display, but mark it stale so evaluate()
            # cannot approve on the strength of a verdict this attempt never earned.
            self.state.last_iteration_failed = True
            self.state.history.append(
                IterationRecord(
                    iteration=self.state.iteration,
                    passed=False,
                    blocking_findings=0,
                    tests_passed=False,
                    summary=f"The build did not complete: {reason[:400]}",
                )
            )
            self.state.revision_notes.append(
                f"[blocker] The previous attempt failed before finishing ({reason[:200]}). "
                f"Work in smaller steps and re-run the tests as you go."
            )
            self._remember_sandbox()
            return "built"

        usage = getattr(result, "token_usage", None)
        if usage is not None:
            self.state.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.state.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.state.llm_calls += getattr(usage, "successful_requests", 0) or 0

        report = _extract_report(result)
        self.state.last_iteration_failed = False
        if report is not None:
            self.state.qa_report = report
            self.state.qa_report_iteration = self.state.iteration
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
        self._remember_sandbox()
        return "built"

    @router(build)
    def evaluate(self) -> str:
        """Decide the next branch from structured findings, not from prose."""
        if self._cancelled():
            # Not "approved" and not another attempt. The session has already
            # settled the cost and released the lock; this just stops the loop.
            self.state.exhausted = True
            return "exhausted"

        report = self.state.qa_report

        # A crashed attempt never earned a verdict, whatever the last good report said.
        if self.state.last_iteration_failed:
            report = None

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

    def _export_source(self) -> None:
        """Archive the current source so a human can actually read what they are judging.

        Called before the human gate, not only on the way out of it. Asking someone to
        "review the build" while the only download appears *after* they approve it gives
        them a choice they have no basis to make — and on the E2B backend the files are
        on a remote microVM, so there is nothing else to open.

        Re-run on delivery because a revision changes the files after this point. A
        failed export must never fail the run: the archive is a convenience, and losing
        it is not worth losing the build.
        """
        try:
            archive = self.sandbox().export_archive(EXPORTS_DIR)
            if archive is not None:
                self.state.archive_path = str(archive)
                print(f"Source archived to {archive}")
        except Exception as exc:  # noqa: BLE001 - a failed export must not fail the run
            print(f"Could not archive the source: {exc}")

        self._export_log()

    def _export_log(self) -> None:
        """Write this run's activity log next to its archive.

        The log lives in memory on the event bus and dies with the process, so until now
        a finished run lost its own trace the moment it ended — the packaged example had
        to be reconstructed from screenshots taken while it was still on screen, and only
        60 of its 134 lines came back.

        Fed by an injected callable rather than by reaching for the UI's session, for the
        same reason the cost probe is: the flow must not depend on the surface that
        launched it, and a headless run simply has no log to write.
        """
        probe = getattr(self, "_log_probe", None)
        if probe is None or not self.state.run_id:
            return
        try:
            text = probe()
            if not (text or "").strip():
                return
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            path = EXPORTS_DIR / f"{self.state.run_id}.log"
            path.write_text(text, encoding="utf-8")
            self.state.log_path = str(path)
            print(f"Activity log written to {path}")
        except Exception as exc:  # noqa: BLE001 - losing the log must not fail the run
            print(f"Could not write the activity log: {exc}")

    @listen("approved")
    def finalize(self) -> str:
        message = (
            f"Approved after {self.state.iteration} "
            f"iteration{'s' if self.state.iteration != 1 else ''}."
        )
        print(f"\n{message}")
        self._export_source()
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
        # Especially here. A build that stopped with findings outstanding is the one a
        # reviewer most needs to open before deciding whether it ships anyway.
        self._export_source()
        return message

    @listen(or_(finalize, stop_at_cap))
    @human_feedback(
        message=(
            "Review the build. Reply with what you want changed, or say it looks good "
            "to ship it."
        ),
        # Deliberately NO `emit`. With emit, CrewAI collapses the human's free text into
        # an outcome using an LLM — and it got it wrong: "Reject invalid input in the
        # backend, not just the UI" was classified as "ship" and the build was delivered
        # unchanged. That is precisely the failure this project claims to avoid: never
        # parse prose to make a control-flow decision. The interface already knows what
        # the person clicked, so :meth:`decide` reads that instead of inferring it.
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

    @router(human_review)
    def decide(self) -> str:
        """Route on the marker the UI set, not on what the feedback appears to mean."""
        latest = getattr(self, "last_human_feedback", None)
        feedback = (getattr(latest, "feedback", "") or "").strip()

        if feedback.startswith(REVISE_MARKER):
            return "revise"
        if feedback.startswith(SHIP_MARKER):
            return "ship"

        # No marker: a headless run, or a UI that went away without answering. Empty
        # feedback ships what exists; anything else is treated as a change request,
        # because silently shipping a build somebody commented on is the worse mistake.
        return "ship" if not strip_marker(feedback) else "revise"

    @listen("ship")
    def deliver(self) -> str:
        self.state.shipped = True
        verdict = "QA-approved" if self.state.approved else "shipped with findings outstanding"
        message = f"Delivered after {self.state.iteration} iteration(s) — {verdict}."
        print(f"\n{message}")

        # Pull the source out BEFORE releasing. With the E2B backend the files live on a
        # microVM that close() destroys, so exporting afterwards would archive nothing.
        # Repeated from the pre-gate export because a revision changes the files between
        # the two, and delivering the version the reviewer saw first would be wrong.
        self._export_source()

        # Terminal step: nothing else will touch the workspace, so stop paying for it.
        # Deliberately not done in finalize/stop_at_cap — a human can still send those
        # back for another pass, and that pass needs the existing files.
        self.release_sandbox()
        return message
