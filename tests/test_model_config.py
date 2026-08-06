"""Tests for model assignment and cost calculation.

No network and no API keys — the live-price check is a separate opt-in command
(``python -m engineering_team.model_config --check``).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team import model_config as mc  # noqa: E402


def _agent_roles() -> set[str]:
    """The roles that actually exist, read from the agent definitions."""
    config = Path(__file__).resolve().parents[1] / "src/engineering_team/config"
    text = (config / "agents.yaml").read_text(encoding="utf-8")
    return {
        line.split(":", 1)[0]
        for line in text.splitlines()
        if line and not line[0].isspace() and not line.startswith("#") and ":" in line
    }


class RoleAssignmentTest(unittest.TestCase):
    def test_every_agent_has_a_model(self):
        """Every role in agents.yaml must be assigned a model, and no more than that.

        Derived from agents.yaml rather than a hardcoded list. The previous version named
        four roles literally and went red the moment the QA Inspector was added in phase
        3 — a test that fails for doing the thing the roadmap says to do next teaches
        people to ignore it. This one stays quiet when a role is added and fails only
        when one is added *without* a model, which is the mistake worth catching: an
        unassigned role raises at crew construction, after the run has been paid for.
        """
        self.assertEqual(set(mc.models()), _agent_roles())

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(KeyError) as ctx:
            mc.llm_for("marketing_intern")
        self.assertIn("marketing_intern", str(ctx.exception))


class PricingCoverageTest(unittest.TestCase):
    def test_every_configured_model_has_a_price(self):
        """An unpriced model would silently understate the cost panel."""
        for role, model in mc.models().items():
            with self.subTest(role=role):
                self.assertIsNotNone(
                    mc.price_for(model),
                    f"{role} uses {model!r}, which has no pricing entry",
                )


class SlugNormalizationTest(unittest.TestCase):
    """OpenRouter routes several spellings of one model; pricing must not miss on them."""

    def test_provider_prefix_is_optional(self):
        self.assertEqual(
            mc.price_for("openrouter/minimax/minimax-m3"),
            mc.price_for("minimax/minimax-m3"),
        )

    def test_latest_alias_tilde_is_stripped(self):
        self.assertEqual(
            mc.price_for("~minimax/minimax-m3"), mc.price_for("minimax/minimax-m3")
        )

    def test_case_is_ignored(self):
        self.assertEqual(
            mc.price_for("MiniMax/MiniMax-M3"), mc.price_for("minimax/minimax-m3")
        )

    def test_dot_and_hyphen_versions_are_equivalent(self):
        self.assertEqual(
            mc.price_for("deepseek/deepseek-v4-flash-0731"),
            mc.price_for("deepseek/deepseek-v4.flash-0731"),
        )


class CostCalculationTest(unittest.TestCase):
    def test_cost_is_per_million_tokens(self):
        price = mc.Price(input=1.0, output=2.0)
        self.assertAlmostEqual(price.cost(1_000_000, 1_000_000), 3.0)

    def test_input_and_output_priced_separately(self):
        price = mc.Price(input=0.09, output=0.18)
        self.assertAlmostEqual(price.cost(2_000_000, 1_000_000), 0.36)

    def test_cost_for_known_model(self):
        cost = mc.cost_for("openrouter/deepseek/deepseek-v4-flash-0731", 1_000_000, 0)
        self.assertAlmostEqual(cost, 0.09)

    def test_unknown_model_degrades_to_none_rather_than_raising(self):
        """Cost reporting must never take down a crew run."""
        self.assertIsNone(mc.price_for("some/unlisted-model"))
        self.assertIsNone(mc.cost_for("some/unlisted-model", 100, 100))


if __name__ == "__main__":
    unittest.main()
