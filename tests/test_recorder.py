"""Tests for run cost accounting.

Feeds synthetic events rather than making LLM calls, so this is free and offline.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team.observability.recorder import (  # noqa: E402
    UNKNOWN_AGENT,
    CostListener,
    RunRecorder,
)


FLASH = "openrouter/deepseek/deepseek-v4-flash-0731"  # $0.09 / $0.18 per M
PRO = "openrouter/deepseek/deepseek-v4-pro"  # $0.435 / $0.870 per M

# Verbatim `role:` values from config/agents.yaml. The bus delivers these sentences, not
# tidy labels, and the backend one mentioning "engineering lead" is the whole reason the
# short-name patterns are order-sensitive.
BACKEND_ROLE = (
    "Python Backend Engineer who can write code to achieve the design described by"
    " the engineering lead"
)
TEST_ROLE = (
    "An engineer with python coding skills who can write unit tests for the given code,"
)


def _event(model=FLASH, agent_role=BACKEND_ROLE, usage=None):
    return SimpleNamespace(
        model=model,
        agent_role=agent_role,
        usage={"prompt_tokens": 1000, "completion_tokens": 500} if usage is None else usage,
    )


def _record(recorder, **kwargs):
    recorder.record(CostListener._to_call(_event(**kwargs)))


class UsageParsingTest(unittest.TestCase):
    def test_standard_key_names(self):
        call = CostListener._to_call(_event())
        self.assertEqual((call.prompt_tokens, call.completion_tokens), (1000, 500))

    def test_alternate_key_names_are_accepted(self):
        """Providers disagree on usage key spelling."""
        call = CostListener._to_call(
            _event(usage={"input_tokens": 7, "output_tokens": 3})
        )
        self.assertEqual((call.prompt_tokens, call.completion_tokens), (7, 3))

    def test_missing_usage_degrades_to_zero(self):
        call = CostListener._to_call(_event(usage={}))
        self.assertEqual(call.total_tokens, 0)

    def test_non_dict_usage_does_not_raise(self):
        call = CostListener._to_call(_event(usage=None))
        self.assertEqual(call.prompt_tokens, 1000)

    def test_missing_agent_role_is_labelled(self):
        call = CostListener._to_call(_event(agent_role=None))
        self.assertEqual(call.agent_role, UNKNOWN_AGENT)

    def test_real_role_sentences_map_to_short_names(self):
        """The recorder labels calls with the short name, not the role sentence.

        These are the actual `role:` values from agents.yaml, because the trap this
        guards lives in their wording. The backend engineer's role reads "…to achieve
        the design described by the engineering lead" — it *contains* "engineering
        lead". With the patterns matched in the wrong order every backend call is
        relabelled as the Lead, and the cost panel shows a run where the backend
        engineer never worked. Invented labels like "Backend Engineer" cannot catch
        that, which is why the previous version of this test did not.
        """
        for role, expected in (
            (
                "Python Backend Engineer who can write code to achieve the design"
                " described by the engineering lead",
                "Backend",
            ),
            (
                "Engineering Lead for the engineering team, directing the work of the"
                " engineers",
                "Engineering Lead",
            ),
            (
                "An engineer with python coding skills who can write unit tests for the"
                " given code,",
                "Test Engineer",
            ),
            (
                "Quality Inspector who independently verifies that the delivered code"
                " meets the requirements",
                "QA Inspector",
            ),
        ):
            with self.subTest(expected=expected):
                call = CostListener._to_call(_event(agent_role=role))
                self.assertEqual(call.agent_role, expected)

    def test_unrecognised_multiline_role_degrades_to_its_first_words(self):
        """An unknown role must not become a cut-off sentence in the cost table."""
        call = CostListener._to_call(
            _event(agent_role="Marketing Intern Extraordinaire\nwho writes copy\n")
        )
        self.assertEqual(call.agent_role, "Marketing Intern Extraordinaire")


class CostAggregationTest(unittest.TestCase):
    def setUp(self):
        self.recorder = RunRecorder()

    def test_single_call_cost(self):
        _record(self.recorder)
        # 1000 * 0.09/1e6 + 500 * 0.18/1e6
        self.assertAlmostEqual(self.recorder.total_cost(), 0.00018)

    def test_costs_accumulate_across_calls(self):
        _record(self.recorder)
        _record(self.recorder)
        self.assertAlmostEqual(self.recorder.total_cost(), 0.00036)

    def test_grouping_by_agent(self):
        """Calls group under the short name the panel displays.

        Keyed on the real role sentences for the same reason as above: the backend one
        mentions the engineering lead, so a grouping bug would silently move its spend
        onto another row rather than lose it — the kind of error a totals check passes
        straight over.
        """
        _record(self.recorder, agent_role=BACKEND_ROLE)
        _record(self.recorder, agent_role=BACKEND_ROLE)
        _record(self.recorder, agent_role=TEST_ROLE)

        by_agent = self.recorder.by_agent()
        self.assertEqual(set(by_agent), {"Backend", "Test Engineer"})
        self.assertEqual(by_agent["Backend"].calls, 2)
        self.assertEqual(by_agent["Test Engineer"].calls, 1)
        self.assertEqual(by_agent["Backend"].prompt_tokens, 2000)

    def test_grouping_by_model(self):
        _record(self.recorder, model=FLASH)
        _record(self.recorder, model=PRO)

        by_model = self.recorder.by_model()
        self.assertEqual(set(by_model), {FLASH, PRO})
        self.assertGreater(by_model[PRO].cost, by_model[FLASH].cost)

    def test_reset_clears_state(self):
        _record(self.recorder)
        self.recorder.reset()
        self.assertEqual(self.recorder.total_cost(), 0.0)
        self.assertEqual(self.recorder.calls, [])


class UnpricedModelTest(unittest.TestCase):
    """An unknown model must not crash the run or silently vanish."""

    def setUp(self):
        self.recorder = RunRecorder()

    def test_unpriced_call_has_no_cost(self):
        _record(self.recorder, model="some/unlisted-model")
        self.assertEqual(self.recorder.total_cost(), 0.0)

    def test_unpriced_model_is_reported(self):
        _record(self.recorder, model="some/unlisted-model")
        self.assertEqual(self.recorder.unpriced_models(), {"some/unlisted-model"})

    def test_unpriced_tokens_still_counted(self):
        _record(self.recorder, model="some/unlisted-model")
        self.assertEqual(self.recorder.by_model()["some/unlisted-model"].total_tokens, 1500)

    def test_summary_warns_about_understated_total(self):
        _record(self.recorder, model="some/unlisted-model")
        self.assertIn("WARNING", self.recorder.summary())

    def test_priced_and_unpriced_mix(self):
        _record(self.recorder, model=FLASH)
        _record(self.recorder, model="some/unlisted-model")
        self.assertAlmostEqual(self.recorder.total_cost(), 0.00018)
        self.assertEqual(self.recorder.by_model()["some/unlisted-model"].unpriced_calls, 1)


class SummaryRenderingTest(unittest.TestCase):
    def test_empty_run(self):
        self.assertEqual(RunRecorder().summary(), "No LLM calls recorded.")

    def test_summary_includes_agents_models_and_total(self):
        recorder = RunRecorder()
        _record(recorder, model=PRO, agent_role="Engineering Lead")
        _record(recorder, model=FLASH, agent_role="Backend Engineer")

        summary = recorder.summary()
        self.assertIn("Engineering Lead", summary)
        self.assertIn(PRO, summary)
        self.assertIn("TOTAL", summary)


class SettleTest(unittest.TestCase):
    """The event bus dispatches handlers on a thread pool, so totals can race."""

    def test_settles_immediately_when_nothing_is_in_flight(self):
        recorder = RunRecorder()
        _record(recorder)
        self.assertTrue(recorder.settle(timeout=3.0, quiet_period=0.1, min_wait=0.0))

    def test_waits_for_a_late_arriving_event(self):
        recorder = RunRecorder()

        def late():
            time.sleep(0.3)
            _record(recorder)

        threading.Thread(target=late, daemon=True).start()
        recorder.settle(timeout=5.0, quiet_period=0.2, min_wait=0.5)
        self.assertEqual(len(recorder.calls), 1)

    def test_returns_false_when_events_never_stop(self):
        recorder = RunRecorder()
        stop = threading.Event()

        def flood():
            while not stop.is_set():
                _record(recorder)
                time.sleep(0.02)

        t = threading.Thread(target=flood, daemon=True)
        t.start()
        try:
            self.assertFalse(recorder.settle(timeout=0.6, quiet_period=0.3, min_wait=0.0))
        finally:
            stop.set()
            t.join()


class ThreadSafetyTest(unittest.TestCase):
    def test_concurrent_records_are_all_retained(self):
        """Crews run in a background thread while the UI polls this object."""
        recorder = RunRecorder()

        def worker():
            for _ in range(200):
                _record(recorder)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(recorder.calls), 1600)


if __name__ == "__main__":
    unittest.main()
