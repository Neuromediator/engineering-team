"""Runs a ProductFlow off the request thread and exposes its progress to the UI.

A build takes minutes and a Gradio callback cannot hold that long, so the flow runs on a
background thread and the UI polls this object with a ``gr.Timer``. Everything a poll can
touch is guarded, because the flow thread writes while the request thread reads.
"""

from __future__ import annotations

import shutil
import threading
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

from crewai.flow.async_feedback.types import HumanFeedbackPending

from .. import budget
from ..flows import ProductFlow
from ..observability.recorder import CostListener, RunRecorder
from ..observability.stream import ActivityListener, RunLog
from ..tools.sandbox_tools import SANDBOX_ROOT
from .feedback_provider import clear_pending, enable_pausing


Status = Literal["idle", "running", "awaiting_feedback", "finished", "failed"]


@dataclass
class RunSession:
    """One product build, from requirements to delivery."""

    recorder: RunRecorder = field(default_factory=RunRecorder)
    log: RunLog = field(default_factory=RunLog)

    status: Status = "idle"
    error: str = ""
    flow: ProductFlow | None = None
    flow_id: str = ""
    question: str = ""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Listeners register on the global bus, so they are attached once per session and
        # kept alive by these references.
        self._cost_listener = CostListener(self.recorder)
        self._activity_listener = ActivityListener(self.log)
        enable_pausing(True)

    # -- state the UI reads -------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            status, error, question = self.status, self.error, self.question
            flow = self.flow
        state = flow.state if flow is not None else None
        return {
            "status": status,
            "error": error,
            "question": question,
            "log": self.log.render(),
            "cost": self.recorder.total_cost(),
            "by_agent": self.recorder.by_agent(),
            "unattributed_models": self._unattributed_models(),
            "state": state,
        }

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

    # -- driving the flow ---------------------------------------------------------

    def discard(self) -> bool:
        """Delete the previous run's workspace and its archive.

        Deployed, this is a privacy and disk property rather than a nicety: a visitor's
        requirements and generated source should not outlive their visit, and a Space
        has a small ephemeral disk. Called when a new build starts and when the page is
        reloaded, so output lives exactly as long as the tab that produced it.

        A run in flight is never discarded.
        """
        if self.is_busy:
            return False
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
        self._set(flow=None, status="idle", error="", question="", flow_id="")
        return True

    def start(self, requirements: str, process: str = "") -> None:
        """Kick off a build. Does nothing if one is already in flight."""
        if self.is_busy:
            return

        # A new task replaces the old one entirely, including its files.
        self.discard()

        allowed, reason = budget.check_can_start()
        if not allowed:
            self._set(status="failed", error=reason)
            self.log.add("run", "budget", reason)
            return

        self.recorder.reset()
        self.log.reset()
        flow = ProductFlow()
        # Lets the flow's router stop before paying for another iteration.
        flow._cost_probe = self.recorder.total_cost
        self._set(flow=flow, status="running", error="", question="", flow_id="")
        self.log.add("run", "flow", f"starting ({process or 'default'} process)")

        self._spawn(
            lambda: flow.kickoff(
                inputs={"requirements": requirements, "process": process}
            )
        )

    def submit_feedback(self, feedback: str) -> None:
        """Resume a paused flow with the human's answer."""
        with self._lock:
            if self.status != "awaiting_feedback":
                return
            flow_id = self.flow_id
            self.status = "running"
            self.question = ""

        self.log.add("run", "human", f"feedback: {feedback[:60]}")
        clear_pending(flow_id)

        def resume() -> None:
            # Reload rather than reusing the in-memory object: the same path works after
            # a process restart, which is the point of persisting the pause.
            flow = ProductFlow.from_pending(flow_id)
            self._set(flow=flow)
            flow.resume(feedback)

        self._spawn(resume)

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
                return

            # resume() does NOT raise on a second pause — it *returns* the pending
            # object. Without this branch a multi-round conversation would report
            # "finished" the moment the flow asked its second question, which is the
            # whole point of the feature.
            if isinstance(result, HumanFeedbackPending):
                self._on_pending(result)
                return

            self.recorder.settle()
            # Record actual spend so the daily ceiling survives a restart.
            total = budget.record(self.recorder.total_cost())
            self.log.add("run", "budget", f"run cost ${self.recorder.total_cost():.4f}; today ${total:.2f}")
            self.log.add("run", "flow", "finished")
            self._set(status="finished")

        thread = threading.Thread(target=runner, daemon=True)
        self._thread = thread
        thread.start()

    def _on_pending(self, pending: HumanFeedbackPending) -> None:
        context = getattr(pending, "context", None)
        flow_id = getattr(context, "flow_id", "") or getattr(
            getattr(self.flow, "state", None), "id", ""
        )
        message = getattr(context, "message", "") or "Feedback requested."
        self.recorder.settle()
        self.log.add("run", "flow", "paused for human feedback")
        self._set(status="awaiting_feedback", flow_id=flow_id, question=message)
