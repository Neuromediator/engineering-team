"""Model assignment and pricing, loaded from ``config/models.yaml``.

One file drives both which model each role calls and what that model costs, so the
observability panel can never report prices for a model the crew is not actually using.

Verify the committed prices against OpenRouter's live catalogue::

    uv run python -m engineering_team.model_config --check
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).parent / "config" / "models.yaml"

# OpenRouter accepts several spellings of the same model: `claude-opus-4-7` and
# `claude-opus-4.7` both route, and `~vendor/model-latest` aliases a snapshot. Pricing
# is keyed on a normalized form so a lookup cannot miss on punctuation alone.
_PROVIDER_PREFIX = "openrouter/"


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Return the USD cost of a call with the given token counts."""
        return (
            prompt_tokens * self.input + completion_tokens * self.output
        ) / 1_000_000


def _normalize(model: str) -> str:
    """Reduce a model slug to a form stable across OpenRouter's accepted spellings."""
    slug = model.strip().lower().lstrip("~")
    if slug.startswith(_PROVIDER_PREFIX):
        slug = slug[len(_PROVIDER_PREFIX) :]
    return slug.replace(".", "-")


@lru_cache(maxsize=1)
def _raw_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def models() -> dict[str, str]:
    """Return the role-to-model mapping."""
    return dict(_raw_config()["models"])


def llm_for(role: str) -> str:
    """Return the model string configured for an agent role.

    Raises:
        KeyError: If the role has no model configured.
    """
    configured = models()
    if role not in configured:
        raise KeyError(
            f"No model configured for role {role!r}. Have: {sorted(configured)}"
        )
    return configured[role]


@lru_cache(maxsize=1)
def _price_table() -> dict[str, Price]:
    return {
        _normalize(model): Price(input=float(p["input"]), output=float(p["output"]))
        for model, p in _raw_config()["pricing"].items()
    }


def price_for(model: str) -> Price | None:
    """Return the price of a model, or None if it is not in the table.

    Returns None rather than raising so that cost reporting degrades to "unknown"
    instead of taking down a crew run.
    """
    return _price_table().get(_normalize(model))


def cost_for(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return the USD cost of one call, or None when the model has no price."""
    price = price_for(model)
    if price is None:
        return None
    return price.cost(prompt_tokens, completion_tokens)


def _check() -> int:
    """Compare committed prices against OpenRouter's live catalogue."""
    import json
    import urllib.request

    with urllib.request.urlopen(
        "https://openrouter.ai/api/v1/models", timeout=60
    ) as response:
        catalogue = json.load(response)["data"]

    live = {
        _normalize(entry["id"]): (
            float(entry["pricing"]["prompt"]) * 1e6,
            float(entry["pricing"]["completion"]) * 1e6,
        )
        for entry in catalogue
    }

    problems = 0
    for model, price in sorted(_price_table().items()):
        if model not in live:
            print(f"  MISSING  {model}: not in OpenRouter catalogue")
            problems += 1
            continue
        live_in, live_out = live[model]
        if abs(live_in - price.input) > 1e-6 or abs(live_out - price.output) > 1e-6:
            print(
                f"  STALE    {model}: committed {price.input}/{price.output}, "
                f"live {live_in}/{live_out}"
            )
            problems += 1
        else:
            print(f"  ok       {model}: {price.input}/{price.output}")

    for role, model in sorted(models().items()):
        if price_for(model) is None:
            print(f"  NO PRICE {role}: {model}")
            problems += 1

    print(f"\n{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(_check())
    for role, model in sorted(models().items()):
        price = price_for(model)
        detail = f"${price.input}/${price.output} per M" if price else "no price"
        print(f"  {role:20} {model:46} {detail}")
