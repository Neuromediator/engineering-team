"""Live activity log, fed from the CrewAI event bus.

The crew runs on a background thread while the UI polls; every read and write here is
therefore under a lock. Handlers are dispatched on a thread pool, so they must be cheap
and must never raise — an exception in a listener would surface as a confusing failure
inside an unrelated agent step.
"""

from __future__ import annotations

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
    ToolUsageStartedEvent,
)


MAX_LINES = 500


@dataclass(frozen=True)
class LogLine:
    at: datetime
    kind: str
    actor: str
    message: str

    def render(self) -> str:
        return f"{self.at:%H:%M:%S}  {self.kind:9} {self.actor:22.22} {self.message}"


def _first_line(text: object, limit: int = 90) -> str:
    """Roles are multi-line YAML blocks; the log needs one short line."""
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
        line = LogLine(
            at=datetime.now(timezone.utc),
            kind=kind,
            actor=_first_line(actor, 22),
            message=message,
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

        @event_bus.on(ToolUsageStartedEvent)
        def _tool_started(_source, event) -> None:
            self.log.add("tool", _role(event), f"→ {getattr(event, 'tool_name', '?')}")

        @event_bus.on(ToolUsageFinishedEvent)
        def _tool_done(_source, event) -> None:
            self.log.add("tool", _role(event), f"✓ {getattr(event, 'tool_name', '?')}")

        @event_bus.on(ToolUsageErrorEvent)
        def _tool_error(_source, event) -> None:
            self.log.add(
                "tool",
                _role(event),
                f"✗ {getattr(event, 'tool_name', '?')}: "
                f"{_first_line(getattr(event, 'error', ''))}",
            )


def _role(event: object) -> str:
    return (
        getattr(event, "agent_role", None)
        or getattr(getattr(event, "agent", None), "role", None)
        or "-"
    )
