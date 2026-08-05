"""Flow-level orchestration: the outer loop around the build crew."""

from .product_flow import MAX_AUTO_ITERATIONS, ProductFlow, ProductState
from .supervisor import RaceOutcome, VariantResult, race, race_async

__all__ = [
    "MAX_AUTO_ITERATIONS",
    "ProductFlow",
    "ProductState",
    "RaceOutcome",
    "VariantResult",
    "race",
    "race_async",
]
