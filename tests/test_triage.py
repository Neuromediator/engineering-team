"""Tests for intake triage and run cancellation.

Both are about what happens when things go wrong, so both are tested without touching a
model or a sandbox: the LLM call is patched out, and cancellation is exercised against a
session whose flow is a stub.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team import triage  # noqa: E402
from engineering_team.schemas import BriefVerdict  # noqa: E402


class ShortBriefTest(unittest.TestCase):
    """The free path. Nothing this short should ever reach a paid model."""

    def test_greetings_are_rejected_without_calling_a_model(self):
        with mock.patch.object(triage, "_run_reviewer") as reviewer:
            for text in ("hi", "how are you", "my name is Bob", "", "   "):
                with self.subTest(text=text):
                    verdict = triage.review_brief(text)
                    self.assertFalse(verdict.buildable)
                    self.assertTrue(verdict.permitted)
                    self.assertTrue(verdict.reason)
        reviewer.assert_not_called()

    def test_a_short_rejection_suggests_what_to_type_instead(self):
        """A dead end with no example is how someone gives up on the tool."""
        self.assertIn("split shared costs", triage.review_brief("hi").suggestion)

    def test_a_real_brief_reaches_the_reviewer(self):
        expected = BriefVerdict(buildable=True, permitted=True)
        with mock.patch.object(triage, "_run_reviewer", return_value=expected) as run:
            verdict = triage.review_brief("A tool to track expenses for a small team.")
        run.assert_called_once()
        self.assertTrue(verdict.buildable)


class FailOpenTest(unittest.TestCase):
    """Triage that breaks must not stop someone spending their own money."""

    def test_an_exception_allows_the_build(self):
        with mock.patch.object(triage, "_run_reviewer", side_effect=RuntimeError("502")):
            verdict = triage.review_brief("A tool to track expenses for a small team.")
        self.assertTrue(verdict.buildable)
        self.assertTrue(verdict.permitted)

    def test_a_missing_structured_answer_allows_the_build(self):
        """No BriefVerdict means the check did not happen, not that it said no."""
        with mock.patch.object(triage, "_load_config", side_effect=RuntimeError("no yaml")):
            verdict = triage.review_brief("A tool to track expenses for a small team.")
        self.assertTrue(verdict.buildable)


class VerdictDefaultsTest(unittest.TestCase):
    def test_permitted_defaults_to_true(self):
        """The binding flag must default to allowing, never to refusing."""
        self.assertTrue(BriefVerdict(buildable=True).permitted)


class CancellationTest(unittest.TestCase):
    def setUp(self):
        from engineering_team.ui.session import RunSession

        self.session = RunSession()

    def test_cancelling_an_idle_session_does_nothing(self):
        self.session.cancel()
        self.assertFalse(self.session.cancelled)
        self.assertEqual(self.session.snapshot()["status"], "idle")

    def test_cancelling_a_running_session_stops_and_releases_the_sandbox(self):
        released = []

        class FakeFlow:
            state = None  # snapshot() reads it

            def release_sandbox(self_inner):
                released.append(True)

        self.session.status = "running"
        self.session.flow = FakeFlow()
        self.session.cancel()

        self.assertTrue(self.session.cancelled)
        self.assertEqual(self.session.snapshot()["status"], "cancelled")
        self.assertEqual(released, [True], "the workspace must stop billing at once")

    def test_a_failing_release_still_cancels(self):
        """Losing the sandbox teardown must not leave the run marked as live."""

        class BrokenFlow:
            state = None  # snapshot() reads it

            def release_sandbox(self_inner):
                raise RuntimeError("vm already gone")

        self.session.status = "running"
        self.session.flow = BrokenFlow()
        self.session.cancel()
        self.assertEqual(self.session.snapshot()["status"], "cancelled")

    def test_cancelling_twice_is_harmless(self):
        self.session.status = "running"
        self.session.cancel()
        self.session.cancel()
        self.assertEqual(self.session.snapshot()["status"], "cancelled")

    def test_a_stopped_session_can_build_again(self):
        """The flag is per run, not per session, and the session outlives the run.

        It was a one-way latch, and the gr.State holding a session survives every build
        started in that tab. So one Stop poisoned the tab: the next build stopped after
        an iteration, never left "running", and could not be stopped again — the UI sat
        on "Building" with no way out.
        """
        self.session.status = "running"
        self.session.cancel()
        self.assertTrue(self.session.cancelled)

        started = []
        self.session._spawn = lambda work: started.append(work)
        self.session.start("an expense tracker")

        self.assertFalse(
            self.session.cancelled, "a new build must not inherit the last one's stop"
        )
        self.assertEqual(self.session.snapshot()["status"], "running")
        self.assertEqual(len(started), 1)
        self.assertFalse(
            self.session.flow._cancelled(),
            "the cancel probe must not fire on the first step of a fresh build",
        )
        self.session.cancel()  # release the run lock this test just took

    def test_reaching_the_gate_while_cancelled_releases_the_run_lock(self):
        """The lock is process-wide: leaking it locks every visitor out of the Space."""
        from engineering_team.ui.session import _run_lock

        self.assertTrue(self.session._acquire_run_lock())
        self.session.cancelled = True
        self.session._on_pending(object())

        self.assertFalse(_run_lock.locked(), "the next visitor must not be locked out")


class FlowCancellationTest(unittest.TestCase):
    """The flow must stop looping, which is where the money actually is."""

    def setUp(self):
        from engineering_team.flows.product_flow import ProductFlow

        self.flow = ProductFlow()

    def test_no_probe_means_never_cancelled(self):
        """Headless runs have no session to walk away from."""
        self.assertFalse(self.flow._cancelled())

    def test_build_does_not_run_the_crew_when_cancelled(self):
        self.flow._cancel_probe = lambda: True
        with mock.patch.object(self.flow, "_run_crew") as crew:
            self.flow.build()
        crew.assert_not_called()
        self.assertEqual(self.flow.state.iteration, 0, "no iteration should be counted")

    def test_evaluate_stops_rather_than_revising(self):
        self.flow._cancel_probe = lambda: True
        self.assertEqual(self.flow.evaluate(), "exhausted")


if __name__ == "__main__":
    unittest.main()
