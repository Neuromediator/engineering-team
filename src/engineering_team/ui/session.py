"""Per-visitor build sessions, and the single lock that serialises them.

Each browser session gets its own :class:`RunSession`: its own requirements, flow,
sandbox, cost table and download. Nobody sees anybody else's work, and one visitor
starting a build cannot discard another's results.

**Only one build runs at a time**, enforced by a module-level lock. Two reasons, and the
second is the one that matters:

* a free-tier Space has 2 vCPU and a build spends fifteen minutes driving containers —
  two at once would not go faster, they would go wrong;
* CrewAI's event bus is **global**. Events carry ``agent_id`` but no session identity, so
  two concurrent builds would interleave into whichever recorder happened to be
  listening. Serialising runs makes the active session unambiguous, which is a more
  honest fix than guessing at attribution.

The listeners are therefore installed once, for the process, and forward into whichever
session currently holds the lock.
"""

from __future__ import annotations

import shutil
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from crewai.flow.async_feedback.types import HumanFeedbackPending

from .. import budget
from ..flows import ProductFlow
from ..flows.product_flow import REVISE_MARKER, SHIP_MARKER
from ..observability.recorder import CostListener, RunRecorder
from ..observability.stream import ActivityListener, RunLog
from ..tools.sandbox_tools import SANDBOX_ROOT
from .feedback_provider import clear_pending, enable_pausing


Status = Literal[
    "idle", "starting", "running", "awaiting_feedback", "finished", "failed", "cancelled"
]

# States in which the visitor's inputs are locked and Build it is dead. "starting" is in
# here for the same reason it exists at all: the checks that run before a build are slow
# enough to type into.
BUSY_STATUSES = frozenset({"starting", "running", "awaiting_feedback"})

BUSY_MESSAGE = (
    "Another build is running. Only one runs at a time on this hardware — "
    "try again in a few minutes."
)

# Held for the duration of an active build. Released when a run finishes, fails, or
# pauses for feedback, so a visitor who walks away mid-question cannot block everyone.
_run_lock = threading.Lock()

# The session the global listeners currently write into.
_active_lock = threading.Lock()
_active: "RunSession | None" = None


def _set_active(session: "RunSession | None") -> None:
    global _active
    with _active_lock:
        _active = session


def _current() -> "RunSession | None":
    with _active_lock:
        return _active


class _ActiveRecorder:
    """Forwards recorded calls to whichever session is currently building."""

    def record(self, call) -> None:
        session = _current()
        if session is not None:
            session.recorder.record(call)


class _ActiveLog:
    """Forwards log lines to whichever session is currently building."""

    def add(self, kind: str, actor: object, message: str) -> None:
        session = _current()
        if session is not None:
            session.log.add(kind, actor, message)


_listeners_installed = False
_install_lock = threading.Lock()
_cost_listener: CostListener | None = None
_activity_listener: ActivityListener | None = None


def install_listeners() -> None:
    """Attach the bus listeners exactly once for the process.

    A listener per session would mean every session recording every other session's
    calls, because the bus is global and offers no unsubscribe.
    """
    global _listeners_installed, _cost_listener, _activity_listener
    with _install_lock:
        if _listeners_installed:
            return
        # Kept in module globals so they outlive this call.
        _cost_listener = CostListener(_ActiveRecorder())
        _activity_listener = ActivityListener(_ActiveLog())
        enable_pausing(True)
        _listeners_installed = True


@dataclass
class RunSession:
    """One visitor's build, from requirements to downloadable source."""

    recorder: RunRecorder = field(default_factory=RunRecorder)
    log: RunLog = field(default_factory=RunLog)

    status: Status = "idle"
    error: str = ""
    flow: ProductFlow | None = None
    flow_id: str = ""
    question: str = ""
    notice: str = ""

    # Whether this visitor is looking at the packaged example run rather than one of
    # their own. It lives here, and not in the click handler, because the poll timer
    # writes to the same components: without a flag the timer re-rendered this idle
    # session about a second after the click and blanked the example.
    showing_demo: bool = False

    # Set when the visitor leaves the page. Checked by the flow between steps and by the
    # completion handlers, so a run that has been abandoned neither starts another
    # iteration nor overwrites its own cancelled status on the way out.
    cancelled: bool = False

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _holds_run_lock: bool = field(default=False, repr=False)
    _recorded_usd: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        install_listeners()

    # -- state the UI reads -------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            status, error, question = self.status, self.error, self.question
            notice, flow = self.notice, self.flow
            showing_demo = self.showing_demo
        state = flow.state if flow is not None else None
        return {
            "status": status,
            "error": error,
            "question": question,
            "notice": notice,
            "showing_demo": showing_demo,
            "log": self.log.render(),
            "cost": self.recorder.total_cost(),
            "by_agent": self.recorder.by_agent(),
            "unattributed_models": self._unattributed_models(),
            "unbanked": self.unbanked_cost,
            "state": state,
        }

    @property
    def unbanked_cost(self) -> float:
        """Spend this session has incurred but not yet charged to the daily total.

        Non-zero only while a run is in flight, since banking happens at every pause and
        ending. The budget line adds it so it agrees with the cost table beside it.
        """
        return max(self.recorder.total_cost() - self._recorded_usd, 0.0)

    def _unattributed_models(self) -> list[str]:
        """Models behind calls the bus could not attribute to an agent."""
        from ..observability.recorder import UNKNOWN_AGENT

        return sorted(
            {
                call.model
                for call in self.recorder.calls
                if call.agent_role == UNKNOWN_AGENT
            }
        )

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self.status == "running"

    def _set(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def _bank_spend(self) -> float:
        """Record what this run has cost since the last time we banked it.

        Called when a run finishes, fails, AND when it pauses for feedback. Recording
        only at the end meant a paused run's cost was invisible to the daily ceiling —
        and a visitor who never answered was never charged for the work at all.
        """
        total = self.recorder.total_cost()
        delta = total - self._recorded_usd
        if delta <= 0:
            return budget.spent_today()
        self._recorded_usd = total
        return budget.record(delta)

    # -- the shared run lock ------------------------------------------------------

    def _acquire_run_lock(self) -> bool:
        if self._holds_run_lock:
            return True
        if not _run_lock.acquire(blocking=False):
            return False
        self._holds_run_lock = True
        _set_active(self)
        return True

    def _release_run_lock(self) -> None:
        if not self._holds_run_lock:
            return
        self._holds_run_lock = False
        if _current() is self:
            _set_active(None)
        _run_lock.release()

    # -- lifecycle ----------------------------------------------------------------

    def discard(self) -> bool:
        """Delete this session's previous workspace and archive.

        Deployed, this is a privacy and disk property rather than a nicety: a visitor's
        requirements and generated source should not outlive their visit, and a Space
        has a small ephemeral disk. A run in flight is never discarded.
        """
        if self.is_busy:
            return False

        # Set before the early return below. The packaged example is not this session's
        # work, so there is no flow to discard when it is all the visitor is looking at
        # — but it is still what is on their screen, and a discard should stop showing
        # it. Leaving this until after the guard made it depend on start() clearing the
        # flag separately, which is true today and silently breaks the day it is not.
        self._set(showing_demo=False)

        flow = self.flow
        if flow is None:
            return False

        archive = getattr(flow.state, "archive_path", "")
        if archive:
            Path(archive).unlink(missing_ok=True)
        run_id = getattr(flow.state, "run_id", "")
        if run_id:
            shutil.rmtree(SANDBOX_ROOT / run_id, ignore_errors=True)

        self.log.reset()
        self.recorder.reset()
        self._recorded_usd = 0.0
        self._set(
            flow=None, status="idle", error="", question="", flow_id="", notice=""
        )
        return True

    def cancel(self, reason: str = "the page was closed or reloaded") -> None:
        """Stop a run because nobody is watching it any more.

        Called when the page unloads. What this can and cannot do is worth being precise
        about, because "stop the build" sounds more absolute than it is:

        * It kills the workspace immediately. On E2B that ends the microVM and its
          billing there and then, which is the largest continuing cost.
        * It stops the flow starting another iteration, so a run cancelled early in a
          two-iteration build saves most of its remaining spend.
        * It releases the run lock, so the next visitor is not locked out.

        It cannot interrupt an LLM call already in flight, and it cannot kill the crew
        mid-task: CrewAI exposes no cancellation hook and a Python thread cannot be
        killed from outside. The agent step in progress finishes and is billed. Stopping
        instantly would mean running the crew in a subprocess, which puts the event bus
        that feeds the cost panel and activity log on the far side of a process boundary.
        """
        with self._lock:
            if self.status not in BUSY_STATUSES or self.cancelled:
                return
            self.cancelled = True
            flow = self.flow

        self.log.add("run", "flow", f"cancelled — {reason}")
        # Printed as well as logged. The RunLog it writes to lives in the session the
        # visitor has just abandoned, so a reloaded page never shows it and a closed one
        # has nobody to show. That left a successful cancellation with no trace anywhere
        # a person could reach — the one feature whose whole point is happening while
        # nobody is watching. stdout reaches the Space log, which is where it can be
        # checked afterwards.
        run_id = getattr(getattr(flow, "state", None), "run_id", "") or "?"
        print(f"\n[cancel] {reason}; stopping run {run_id}")

        # First, because it is the one that keeps costing money while we tidy up.
        if flow is not None:
            try:
                flow.release_sandbox()
                print("[cancel] workspace released")
            except Exception as exc:  # noqa: BLE001 - teardown must not raise here
                print(f"[cancel] could not release the workspace: {exc}")

        self.recorder.settle()
        today = self._bank_spend()
        self.log.add(
            "run", "budget", f"spent ${self.recorder.total_cost():.4f}; today ${today:.2f}"
        )
        self._set(status="cancelled")
        self._release_run_lock()
        print(
            f"[cancel] done — spent ${self.recorder.total_cost():.4f}, "
            f"run lock released, no further iteration will start"
        )

    def _attach_probes(self, flow: ProductFlow) -> None:
        """Give a flow the two hooks back into this session.

        ``_cost_probe`` lets the router stop before paying for another iteration;
        ``_log_probe`` lets it write this run's activity log out beside the archive.
        Both are injected rather than imported, so the flow stays usable headlessly.

        Applied on resume as well as on start. A resumed flow is a fresh object loaded
        from the checkpoint, so the probes do not travel with it — and the cost ceiling
        silently stopped being enforced for exactly the runs a human had extended, which
        are the ones most likely to reach it.
        """
        flow._cost_probe = self.recorder.total_cost
        flow._log_probe = self.log.render
        flow._cancel_probe = lambda: self.cancelled

    def mark_starting(self) -> None:
        """Say the click landed, before the work that makes it look like it didn't.

        Two slow things happen between pressing Build it and a run existing: triage is
        an LLM call, and preflight talks to the sandbox backend. That is up to twenty
        seconds in which the page said "Idle", the Build button stayed live and no trace
        appeared — indistinguishable from a click that was dropped, so people pressed it
        again. This is a status rather than a one-off UI frame because the page polls
        every two seconds: a frame would be painted over by the next tick reading "idle"
        off this session, which is what it truthfully said.
        """
        if self.status in BUSY_STATUSES:
            return
        # `cancelled` is cleared here as well as in start(), because this is now the
        # first moment of an attempt and cancel() is reachable from it.
        self._set(
            status="starting", notice="", error="", showing_demo=False, cancelled=False
        )

    def clear_starting(self) -> None:
        """Undo :meth:`mark_starting` when the checks refuse the build."""
        if self.status == "starting":
            self._set(status="idle")

    def start(
        self, requirements: str, process: str = "", *, expect: Status | None = None
    ) -> None:
        """Kick off a build. Does nothing if this session already has one running.

        ``expect`` is the status the caller left the session in before doing the slow
        pre-build checks. If it has moved since, something happened during those checks —
        in practice the visitor closing the page — and starting now would spend a full
        build on nobody. It is passed rather than inferred because "cancelled" on its own
        cannot distinguish that from a cancelled run earlier in the same tab, and reading
        it as the latter is the bug this whole area already had once.
        """
        if self.is_busy:
            return
        if expect is not None and self.status != expect:
            return

        allowed, reason = budget.check_can_start()
        if not allowed:
            self._set(status="failed", error=reason)
            return

        if not self._acquire_run_lock():
            self._set(notice=BUSY_MESSAGE)
            return

        # A new task replaces this session's old one entirely, including its files.
        self.discard()

        flow = ProductFlow()
        self._attach_probes(flow)
        self._set(
            flow=flow,
            status="running",
            error="",
            question="",
            flow_id="",
            notice="",
            showing_demo=False,
            # Cleared here, and this line is load-bearing. `cancelled` was written as a
            # one-way latch, which is right for one run and wrong for a session, because
            # the session outlives the run: the gr.State holding it survives every build
            # the visitor starts in that tab. A stopped build therefore poisoned every
            # later one — the cancel probe fired at once so the flow stopped after a
            # single iteration, `_on_pending` and the completion branch both returned
            # early so the status never left "running", and cancel() short-circuited on
            # its own latch, so Stop did nothing and printed nothing. The UI sat on
            # "Building" forever with no way out.
            cancelled=False,
        )
        self.log.add("run", "flow", f"starting ({process or 'default'} process)")

        self._spawn(
            lambda: flow.kickoff(
                inputs={"requirements": requirements, "process": process}
            )
        )

    def submit_feedback(self, feedback: str, approve: bool = False) -> None:
        """Resume a paused flow with this visitor's answer.

        ``approve`` is the decision the person actually made by choosing a button. It is
        sent as a marker rather than left for a model to infer from their wording — an
        earlier version asked an LLM to classify the text and shipped a build whose
        feedback plainly asked for changes.
        """
        with self._lock:
            if self.status != "awaiting_feedback":
                return
            flow_id = self.flow_id

        if not self._acquire_run_lock():
            self._set(notice=BUSY_MESSAGE)
            return

        marker = SHIP_MARKER if approve else REVISE_MARKER
        decision = "ship" if approve else "revise"
        self._set(status="running", question="", notice="", showing_demo=False)
        # The request is the most consequential line in the log: it is what a reader
        # needs to connect the following iteration to. 60 characters cut it mid-sentence.
        shown = feedback if len(feedback) <= 400 else feedback[:400] + "…"
        self.log.add("run", "human", f"{decision}: {shown}")
        clear_pending(flow_id)

        def resume() -> None:
            # Reload rather than reusing the in-memory object: the same path works after
            # a process restart, which is the point of persisting the pause.
            flow = ProductFlow.from_pending(flow_id)
            self._attach_probes(flow)
            self._set(flow=flow)
            flow.resume(f"{marker} {feedback}".strip())

        self._spawn(resume)

    def _pending_request(self, result) -> object | None:
        """Detect a paused flow however the framework chose to report it.

        Three shapes, learned one at a time and all real:
          * kickoff() RAISES HumanFeedbackPending;
          * resume() RETURNS it when it reaches another feedback point;
          * resume() can also return normally while the framework records the pause,
            which stranded a run — the UI said "finished" in the same second a
            pending_feedback row was written.

        So the return value is checked, and then the flow itself is asked. Trusting any
        single signal has now been wrong twice.
        """
        if isinstance(result, HumanFeedbackPending):
            return result
        flow = self.flow
        return getattr(flow, "pending_feedback", None) if flow is not None else None

    def _spawn(self, work) -> None:
        def runner() -> None:
            try:
                result = work()
            except HumanFeedbackPending as pending:
                # kickoff() raises when it hits a feedback point.
                self._on_pending(pending)
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
                self.log.add("run", "flow", f"FAILED: {exc}")
                self._set(status="failed", error=traceback.format_exc())
                self._bank_spend()
                self._release_run_lock()
                return

            pending = self._pending_request(result)
            if pending is not None:
                self._on_pending(pending)
                return

            if self.cancelled:
                # cancel() has already banked the spend, released the lock and set
                # the status. The thread just unwinding is not a finished build.
                # The release is a no-op in that case; it is here so that no path out
                # of this thread can strand the lock, which is process-wide.
                self._release_run_lock()
                return
            self.recorder.settle()
            today = self._bank_spend()
            self.log.add(
                "run",
                "budget",
                f"run cost ${self.recorder.total_cost():.4f}; today ${today:.2f}",
            )
            self.log.add("run", "flow", "finished")
            self._set(status="finished")
            self._release_run_lock()

        thread = threading.Thread(target=runner, daemon=True)
        self._thread = thread
        thread.start()

    def _on_pending(self, pending: object) -> None:
        # A cancelled run may still reach the gate before the flow notices. Letting
        # it post a question nobody will answer would re-take the lock and show a
        # feedback box for a build the visitor has already walked away from.
        if self.cancelled:
            # Still release. This method owns the lock handed to it by the run thread,
            # and returning without releasing locked every visitor out of the Space
            # until it was restarted.
            self._release_run_lock()
            return
        # `pending` is either a HumanFeedbackPending (which carries .context) or the
        # context itself, depending on which of the three signals fired.
        context = getattr(pending, "context", None) or pending
        flow_id = getattr(context, "flow_id", "") or getattr(
            getattr(self.flow, "state", None), "id", ""
        )
        message = getattr(context, "message", "") or "Feedback requested."
        self.recorder.settle()
        today = self._bank_spend()
        self.log.add(
            "run", "budget", f"so far ${self.recorder.total_cost():.4f}; today ${today:.2f}"
        )
        self.log.add("run", "flow", "paused for human feedback")
        self._set(status="awaiting_feedback", flow_id=flow_id, question=message)
        # Released while waiting: a visitor who never answers must not block everyone.
        self._release_run_lock()
