"""Tests for model profile selection and cost calculation.

No network and no API keys — the live-price check is a separate opt-in command
(``python -m engineering_team.model_config --check``).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team import model_config as mc  # noqa: E402


class ProfileSelectionTest(unittest.TestCase):
    def test_default_profile_is_budget(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            mc._raw_config.cache_clear()
            import os

            os.environ.pop("MODEL_PROFILE", None)
            self.assertEqual(mc.active_profile_name(), "budget")

    def test_env_var_overrides_default(self):
        with mock.patch.dict("os.environ", {"MODEL_PROFILE": "premium"}):
            self.assertEqual(mc.active_profile_name(), "premium")

    def test_unknown_profile_lists_available_ones(self):
        with self.assertRaises(KeyError) as ctx:
            mc.profile("does-not-exist")
        self.assertIn("budget", str(ctx.exception))

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(KeyError) as ctx:
            mc.llm_for("marketing_intern", "budget")
        self.assertIn("marketing_intern", str(ctx.exception))

    def test_every_profile_defines_all_four_roles(self):
        expected = {
            "engineering_lead",
            "backend_engineer",
            "frontend_engineer",
            "test_engineer",
        }
        for name in mc._raw_config()["profiles"]:
            with self.subTest(profile=name):
                self.assertEqual(set(mc.profile(name)), expected)


class PricingCoverageTest(unittest.TestCase):
    def test_every_configured_model_has_a_price(self):
        """A profile referencing an unpriced model would silently break cost reporting."""
        for name in mc._raw_config()["profiles"]:
            for role, model in mc.profile(name).items():
                with self.subTest(profile=name, role=role):
                    self.assertIsNotNone(
                        mc.price_for(model),
                        f"{name}.{role} uses {model!r}, which has no pricing entry",
                    )


class SlugNormalizationTest(unittest.TestCase):
    """OpenRouter routes several spellings of one model; pricing must not miss on them."""

    def test_dot_and_hyphen_versions_are_equivalent(self):
        self.assertEqual(
            mc.price_for("openrouter/anthropic/claude-opus-4.7"),
            mc.price_for("openrouter/anthropic/claude-opus-4-7"),
        )

    def test_provider_prefix_is_optional(self):
        self.assertEqual(
            mc.price_for("openrouter/z-ai/glm-5.2"), mc.price_for("z-ai/glm-5.2")
        )

    def test_latest_alias_tilde_is_stripped(self):
        self.assertEqual(
            mc.price_for("~z-ai/glm-5.2"), mc.price_for("z-ai/glm-5.2")
        )

    def test_case_is_ignored(self):
        self.assertEqual(
            mc.price_for("Z-AI/GLM-5.2"), mc.price_for("z-ai/glm-5.2")
        )


class CostCalculationTest(unittest.TestCase):
    def test_cost_is_per_million_tokens(self):
        price = mc.Price(input=1.0, output=2.0)
        self.assertAlmostEqual(price.cost(1_000_000, 1_000_000), 3.0)

    def test_input_and_output_priced_separately(self):
        price = mc.Price(input=0.09, output=0.18)
        self.assertAlmostEqual(price.cost(2_000_000, 1_000_000), 0.36)

    def test_zero_tokens_cost_nothing(self):
        self.assertAlmostEqual(mc.Price(input=5.0, output=30.0).cost(0, 0), 0.0)

    def test_cost_for_known_model(self):
        cost = mc.cost_for("openrouter/deepseek/deepseek-v4-flash-0731", 1_000_000, 0)
        self.assertAlmostEqual(cost, 0.09)

    def test_unknown_model_degrades_to_none_rather_than_raising(self):
        """Cost reporting must never take down a crew run."""
        self.assertIsNone(mc.price_for("some/unlisted-model"))
        self.assertIsNone(mc.cost_for("some/unlisted-model", 100, 100))


class BudgetProfileIntentTest(unittest.TestCase):
    def test_budget_is_materially_cheaper_than_premium(self):
        """Guards the whole point of Phase 1."""

        def blended(name: str) -> float:
            models = mc.profile(name).values()
            prices = [mc.price_for(m) for m in models]
            return sum(p.output for p in prices if p) / len(prices)

        self.assertLess(blended("budget"), blended("premium") / 5)

    def test_manager_is_not_the_cheapest_model_in_budget(self):
        """Weak managers delegate badly; the lead deliberately keeps a capable model."""
        prices = {
            role: mc.price_for(model).output
            for role, model in mc.profile("budget").items()
        }
        self.assertGreater(prices["engineering_lead"], prices["backend_engineer"])


if __name__ == "__main__":
    unittest.main()
