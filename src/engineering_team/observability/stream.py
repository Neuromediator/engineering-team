"""Live activity log, fed from the CrewAI event bus.

The crew runs on a background thread while the UI polls; every read and write here is
therefore under a lock. Handlers are dispatched on a thread pool, so they must be cheap
and must never raise — an exception in a listener would surface as a confusing failure
inside an unrelated agent step.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from crewai.events import BaseEventListener
from crewai.events.event_bus import CrewAIEventsBus
from crewai.events.types.agent_events import (
    AgentExecutionCompletedEvent,
    AgentExecutionErrorEvent,
    AgentExecutionStartedEvent,
)
from crewai.events.types.task_events import (
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
)
from crewai.events.types.tool_usage_events import (
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
)


MAX_LINES = 500


@dataclass(frozen=True)
class LogLine:
    at: datetime
    kind: str
    actor: str
    message: str

    def render(self) -> str:
        return f"{self.at:%H:%M:%S}  {self.kind:6} {self.actor:16.16} {self.message}"


# Roles are full sentences in agents.yaml ("Quality Inspector who independently verifies
# that the delivered code meets the requirements"). Truncating those gives columns of
# "Quality Inspector who independently ve" — the distinguishing part is the first two or
# three words, so map them to names a person can scan.
#
# ORDER MATTERS, and getting it wrong is not cosmetic. The backend engineer's role reads
# "Python Backend Engineer who can write code to achieve the design described by the
# engineering lead" — it *contains* "engineering lead". With that pattern checked first,
# every backend call was relabelled as the Lead, in both the log and the cost table, and
# the UI showed a run where the backend engineer apparently never worked. The most
# specific patterns therefore come first and "engineering lead" is checked last.
ROLE_SHORT_NAMES = (
    ("backend engineer", "Backend"),
    ("gradio expert", "Frontend"),
    ("unit tests", "Test Engineer"),
    ("quality inspector", "QA Inspector"),
    ("engineering lead", "Engineering Lead"),
)


def short_role(role: object) -> str:
    """Map a verbose role sentence to a short, scannable name."""
    if role is None:
        return "-"
    text = str(role).strip()
    lowered = text.lower()
    for needle, name in ROLE_SHORT_NAMES:
        if needle in lowered:
            return name
    # Unknown role: fall back to the first few words rather than a cut-off sentence.
    words = text.split()
    return " ".join(words[:3]) if words else "-"


def _first_line(text: object, limit: int = 90) -> str:
    """Collapse a multi-line value to one short line."""
    if text is None:
        return "-"
    line = str(text).strip().splitlines()
    out = line[0] if line else "-"
    return out if len(out) <= limit else out[: limit - 1] + "…"


class RunLog:
    """Thread-safe bounded log of what the crew is doing."""

    def __init__(self, max_lines: int = MAX_LINES) -> None:
        self._lines: deque[LogLine] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def add(self, kind: str, actor: object, message: str) -> None:
        # One entry must render as exactly one line. A message containing newlines —
        # a pasted multi-line request, a traceback — otherwise spills into rows with no
        # timestamp or actor, breaking the column grid. The panel scrolls horizontally,
        # so a long single line is fine; a wrapped one is not.
        line = LogLine(
            at=datetime.now(timezone.utc),
            kind=kind,
            actor=_first_line(actor, 16),
            message=" ".join(str(message).split()),
        )
        with self._lock:
            self._lines.append(line)

    @property
    def lines(self) -> list[LogLine]:
        with self._lock:
            return list(self._lines)

    def render(self) -> str:
        return "\n".join(line.render() for line in self.lines)

    def reset(self) -> None:
        with self._lock:
            self._lines.clear()


class ActivityListener(BaseEventListener):
    """Translates bus events into human-readable log lines."""

    def __init__(self, log: RunLog) -> None:
        super().__init__()
        self.log = log

    def setup_listeners(self, event_bus: CrewAIEventsBus) -> None:
        @event_bus.on(TaskStartedEvent)
        def _task_started(_source, event) -> None:
            self.log.add("task", getattr(event, "task_name", None) or "task", "started")

        @event_bus.on(TaskCompletedEvent)
        def _task_done(_source, event) -> None:
            self.log.add("task", getattr(event, "task_name", None) or "task", "completed")

        @event_bus.on(TaskFailedEvent)
        def _task_failed(_source, event) -> None:
            self.log.add(
                "task",
                getattr(event, "task_name", None) or "task",
                f"FAILED: {_first_line(getattr(event, 'error', ''))}",
            )

        @event_bus.on(AgentExecutionStartedEvent)
        def _agent_started(_source, event) -> None:
            self.log.add("agent", _role(event), "thinking")

        @event_bus.on(AgentExecutionCompletedEvent)
        def _agent_done(_source, event) -> None:
            self.log.add("agent", _role(event), "done")

        @event_bus.on(AgentExecutionErrorEvent)
        def _agent_error(_source, event) -> None:
            self.log.add(
                "agent", _role(event), f"ERROR: {_first_line(getattr(event, 'error', ''))}"
            )

        # Only the finished event is logged. Logging both start and finish doubled every
        # line while adding nothing — the interesting facts (which file, what happened)
        # only exist once the call returns.
        @event_bus.on(ToolUsageFinishedEvent)
        def _tool_done(_source, event) -> None:
            self.log.add("tool", _role(event), _tool_detail(event))

        @event_bus.on(ToolUsageErrorEvent)
        def _tool_error(_source, event) -> None:
            self.log.add(
                "tool",
                _role(event),
                f"✗ {getattr(event, 'tool_name', '?')} — "
                f"{_first_line(getattr(event, 'error', ''))}",
            )


def _role(event: object) -> str:
    return short_role(
        getattr(event, "agent_role", None)
        or getattr(getattr(event, "agent", None), "role", None)
    )


def _args(event: object) -> dict:
    """Tool arguments, whether the event carries a dict or a JSON string."""
    raw = getattr(event, "tool_args", None)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _tool_detail(event: object) -> str:
    """One informative line: what the tool did, to what, and how it went.

    The previous log printed only tool names, which told you the crew was busy but
    nothing about what it was doing — the complaint that prompted this.
    """
    name = str(getattr(event, "tool_name", "?"))
    args = _args(event)
    output = str(getattr(event, "output", "") or "")

    target = (
        args.get("filename")
        or args.get("package")
        or args.get("coworker")
        or args.get("task")
        or ""
    )
    target = _first_line(target, 60) if target else ""

    # Sandbox execution already reports its own verdict in the first line of output.
    verdict = ""
    if output.startswith("["):
        verdict = output.split("]", 1)[0].lstrip("[")
    elif getattr(event, "failure", None):
        verdict = "failed"

    parts = [name]
    if target:
        parts.append(target)
    if verdict:
        parts.append(f"→ {verdict}")
    elif name.startswith("write") and "content" in args:
        parts.append(f"→ {len(str(args['content']))} chars")
    return "  ".join(parts)
