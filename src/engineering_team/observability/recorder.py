"""Per-run token and cost accounting, fed by the CrewAI event bus.

`LLMCallCompletedEvent` carries both `model` and `usage`, so spend can be attributed to
individual agents as a run proceeds rather than estimated afterwards. The same records
drive the CLI summary today and the live UI panel later.

Usage::

    recorder = RunRecorder()
    CostListener(recorder)          # registers on the global event bus
    EngineeringTeam().crew().kickoff(inputs=...)
    print(recorder.summary())
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from crewai.events import BaseEventListener
from crewai.events.event_bus import CrewAIEventsBus
from crewai.events.types.llm_events import LLMCallCompletedEvent

from engineering_team.model_config import cost_for


# litellm and the various providers disagree on usage key names.
_PROMPT_KEYS = ("prompt_tokens", "input_tokens", "promptTokens")
_COMPLETION_KEYS = ("completion_tokens", "output_tokens", "completionTokens")

UNKNOWN_AGENT = "(unattributed)"


def _first_int(usage: dict[str, object], keys: tuple[str, ...]) -> int:
    """Return the first key present in usage as an int, else 0."""
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


@dataclass(frozen=True)
class LLMCall:
    """One completed LLM call."""

    model: str
    agent_role: str
    prompt_tokens: int
    completion_tokens: int
    cost: float | None
    at: datetime

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Totals:
    """Aggregated usage for one grouping key."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    unpriced_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class RunRecorder:
    """Thread-safe collector of LLM calls for a single run.

    Crews may execute in a background thread while a UI polls this object, so every
    read and write is guarded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[LLMCall] = []

    def record(self, call: LLMCall) -> None:
        with self._lock:
            self._calls.append(call)

    @property
    def calls(self) -> list[LLMCall]:
        """A snapshot copy, safe to iterate while a run continues."""
        with self._lock:
            return list(self._calls)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()

    def settle(
        self,
        timeout: float = 10.0,
        quiet_period: float = 0.35,
        min_wait: float = 0.5,
    ) -> bool:
        """Wait for in-flight events to arrive before reading final totals.

        The event bus dispatches handlers on a thread pool, so a read taken
        immediately after the last LLM call can miss events that were emitted but
        not yet handled. Waits at least `min_wait`, then until no new call has been
        recorded for `quiet_period`.

        Best-effort: the bus exposes no way to query pending handlers, so this is a
        timing heuristic, not a barrier. `min_wait` exists because an empty recorder
        is indistinguishable from one whose events are still in flight — without it,
        this would return before the first event ever landed.

        Args:
            timeout: Maximum seconds to wait overall.
            quiet_period: Seconds of no new calls before considering the run settled.
            min_wait: Minimum seconds to wait regardless of apparent quiet.

        Returns:
            True if it settled, False if `timeout` was hit first.
        """
        start = time.monotonic()
        deadline = start + timeout
        last_count = -1
        stable_since = start

        while time.monotonic() < deadline:
            with self._lock:
                count = len(self._calls)

            if count != last_count:
                last_count = count
                stable_since = time.monotonic()
            elif (
                time.monotonic() - start >= min_wait
                and time.monotonic() - stable_since >= quiet_period
            ):
                return True
            time.sleep(0.05)
        return False

    def total_cost(self) -> float:
        """Total known spend in USD. Calls with no price contribute nothing."""
        return sum(c.cost for c in self.calls if c.cost is not None)

    def unpriced_models(self) -> set[str]:
        """Models seen that had no pricing entry, so the total understates spend."""
        return {c.model for c in self.calls if c.cost is None}

    def _group(self, key: str) -> dict[str, Totals]:
        totals: dict[str, Totals] = defaultdict(Totals)
        for call in self.calls:
            bucket = totals[getattr(call, key)]
            bucket.calls += 1
            bucket.prompt_tokens += call.prompt_tokens
            bucket.completion_tokens += call.completion_tokens
            if call.cost is None:
                bucket.unpriced_calls += 1
            else:
                bucket.cost += call.cost
        return dict(totals)

    def by_agent(self) -> dict[str, Totals]:
        return self._group("agent_role")

    def by_model(self) -> dict[str, Totals]:
        return self._group("model")

    def summary(self) -> str:
        """Render a plain-text cost report."""
        calls = self.calls
        if not calls:
            return "No LLM calls recorded."

        lines = ["", "=" * 78, "RUN COST SUMMARY", "=" * 78]

        for title, grouping in (("By agent", self.by_agent()), ("By model", self.by_model())):
            lines.append(f"\n{title}:")
            lines.append(
                f"  {'':<44} {'calls':>6} {'in':>10} {'out':>10} {'USD':>9}"
            )
            for name, t in sorted(grouping.items(), key=lambda kv: -kv[1].cost):
                lines.append(
                    f"  {name[:44]:<44} {t.calls:>6} {t.prompt_tokens:>10,} "
                    f"{t.completion_tokens:>10,} {t.cost:>9.4f}"
                )

        total_in = sum(c.prompt_tokens for c in calls)
        total_out = sum(c.completion_tokens for c in calls)
        lines.append("\n" + "-" * 78)
        lines.append(
            f"  {'TOTAL':<44} {len(calls):>6} {total_in:>10,} {total_out:>10,} "
            f"{self.total_cost():>9.4f}"
        )

        unpriced = self.unpriced_models()
        if unpriced:
            lines.append(
                f"\n  WARNING: no pricing for {sorted(unpriced)}; total understates spend."
            )
        lines.append("=" * 78)
        return "\n".join(lines)


class CostListener(BaseEventListener):
    """Feeds completed LLM calls into a :class:`RunRecorder`.

    Instantiating registers handlers on the global CrewAI event bus.
    """

    def __init__(self, recorder: RunRecorder) -> None:
        self._recorder = recorder
        super().__init__()

    def setup_listeners(self, crewai_event_bus: CrewAIEventsBus) -> None:
        @crewai_event_bus.on(LLMCallCompletedEvent)
        def _on_llm_call(_source: object, event: LLMCallCompletedEvent) -> None:
            self._recorder.record(self._to_call(event))

    @staticmethod
    def _to_call(event: LLMCallCompletedEvent) -> LLMCall:
        usage = event.usage if isinstance(event.usage, dict) else {}
        model = event.model or "(unknown)"
        prompt_tokens = _first_int(usage, _PROMPT_KEYS)
        completion_tokens = _first_int(usage, _COMPLETION_KEYS)

        return LLMCall(
            model=model,
            agent_role=(getattr(event, "agent_role", None) or UNKNOWN_AGENT)
            .strip()
            .splitlines()[0]
            if getattr(event, "agent_role", None)
            else UNKNOWN_AGENT,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost_for(model, prompt_tokens, completion_tokens),
            at=datetime.now(timezone.utc),
        )
