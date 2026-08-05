"""A human-feedback provider that pauses the flow instead of blocking on it.

CrewAI's default provider reads from stdin. That is fine for a terminal and useless
behind a web UI: it would pin a worker thread for as long as the person takes to answer,
and lose everything if the process restarts.

This provider instead raises :class:`HumanFeedbackPending`. The framework persists flow
state at that point, so the run can be picked up later — even in a different process —
with ``Flow.from_pending(flow_id)`` followed by ``flow.resume(feedback)``. The pause
costs nothing while it waits, which is what makes it usable on a free-tier deployment
that may sleep between the question and the answer.
"""

from __future__ import annotations

import threading
from typing import Any

from crewai.flow.async_feedback.types import (
    HumanFeedbackPending,
    PendingFeedbackContext,
)


# Flows pause in a worker thread and the UI reads from a request thread, so the registry
# of who is waiting is shared mutable state.
_lock = threading.Lock()
_pending: dict[str, PendingFeedbackContext] = {}

# Pausing is opt-in. The decorator that installs this provider is evaluated at import
# time, so the same object serves both surfaces: the UI turns pausing on, while a headless
# CLI run leaves it off and gets an empty answer, which falls through to `default_outcome`.
# Without this a `run_crew` would pause forever with nobody to answer it.
_pause_enabled = False


def enable_pausing(enabled: bool = True) -> None:
    """Let the flow pause for a human. Called by the UI, not by CLI runs."""
    global _pause_enabled
    _pause_enabled = enabled


def pending_context(flow_id: str) -> PendingFeedbackContext | None:
    """Return the pending request for a flow, if it is waiting on a human."""
    with _lock:
        return _pending.get(flow_id)


def clear_pending(flow_id: str) -> None:
    """Forget a request once it has been answered."""
    with _lock:
        _pending.pop(flow_id, None)


class PendingUIFeedbackProvider:
    """Records what the human was asked, then pauses the flow.

    Implements CrewAI's ``HumanFeedbackProvider`` protocol structurally — the protocol
    is satisfied by having ``request_feedback``, so there is no base class to inherit.
    """

    def request_feedback(
        self,
        context: PendingFeedbackContext,
        flow: Any,
    ) -> str:
        """Pause for a human when a UI is attached; otherwise decline to ask.

        Returns:
            An empty string when pausing is disabled, which makes the framework fall
            back to the configured ``default_outcome``.

        Raises:
            HumanFeedbackPending: When pausing is enabled. The framework persists state
                in response, so the run can be resumed later from its ``flow_id``.
        """
        if not _pause_enabled:
            return ""

        with _lock:
            _pending[context.flow_id] = context

        raise HumanFeedbackPending(
            context=context,
            callback_info={"surface": "gradio", "flow_id": context.flow_id},
        )
