"""Run several ProductFlows at once and rank what comes back.

This is the high-level orchestration layer: N independent flows racing on the same
requirements, then a ranking over their QA reports. Best-of-N is a real technique — the
crew is nondeterministic, so a second attempt genuinely explores a different design — and
it is the honest way to get parallelism out of this problem.

**Why not parallelise the engineers inside one build.** The frontend imports the backend
and the tests test it, so those steps are genuinely sequential. Running them concurrently
would be theatre: three agents guessing at each other's interfaces and then reconciling.
The parallelism that actually exists here is between whole attempts.

Ranking is deliberately arithmetic — no LLM judge. Every input is already structured
(`QAReport.verdict()`, blocking-finding counts, iteration counts), so a judge would add
cost and a failure mode to reproduce a sort.

Cost scales linearly with the number of variants. :func:`race` therefore takes an explicit
``variants`` count and a tighter default iteration cap than a single run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .product_flow import ProductFlow


# A race multiplies spend, so it gets a tighter leash than a single run: the point is to
# compare first attempts, not to let every variant grind to the same answer.
RACE_MAX_ITERATIONS = 2
DEFAULT_CONCURRENCY = 3


@dataclass
class VariantResult:
    """What one flow in the race produced."""

    label: str
    run_id: str = ""
    approved: bool = False
    shipped: bool = False
    iterations: int = 0
    blocking_findings: int = 0
    tests_passed: bool = False
    qa_summary: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def rank_key(self) -> tuple:
        """Order variants best-first.

        A crashed variant sorts last regardless of anything else; then QA approval, then
        fewest blocking findings, then fewest iterations to get there, then fewest tokens
        as the tie-break. Cheaper only wins between otherwise equal results.
        """
        return (
            not self.ok,
            not self.approved,
            self.blocking_findings,
            self.iterations,
            self.total_tokens,
        )

    def render(self) -> str:
        if self.error:
            return f"{self.label:10} ERROR  {self.error[:70]}"
        verdict = "APPROVED" if self.approved else "not approved"
        return (
            f"{self.label:10} {verdict:13} "
            f"iterations={self.iterations} blocking={self.blocking_findings} "
            f"tokens={self.total_tokens:,} sandbox=sandbox/{self.run_id}"
        )


@dataclass
class RaceOutcome:
    results: list[VariantResult] = field(default_factory=list)

    @property
    def ranked(self) -> list[VariantResult]:
        return sorted(self.results, key=VariantResult.rank_key)

    @property
    def winner(self) -> VariantResult | None:
        ranked = self.ranked
        return ranked[0] if ranked and ranked[0].ok else None

    def summary(self) -> str:
        lines = ["", "=" * 78, "RACE RESULTS (best first)", "=" * 78]
        lines += [f"  {result.render()}" for result in self.ranked]

        winner = self.winner
        lines.append("-" * 78)
        if winner is None:
            lines.append("  No variant completed successfully.")
        else:
            lines.append(f"  Winner: {winner.label} -> sandbox/{winner.run_id}")
        totals = sum(r.total_tokens for r in self.results)
        lines.append(f"  Combined tokens across {len(self.results)} variant(s): {totals:,}")
        lines.append("=" * 78)
        return "\n".join(lines)


def _collect(label: str, flow: ProductFlow) -> VariantResult:
    state = flow.state
    report = state.qa_report
    return VariantResult(
        label=label,
        run_id=state.run_id,
        approved=state.approved,
        shipped=state.shipped,
        iterations=state.iteration,
        blocking_findings=len(report.blocking_findings) if report else 0,
        tests_passed=bool(report and report.tests_passed),
        qa_summary=report.summary if report else "No QA report was produced.",
        prompt_tokens=state.prompt_tokens,
        completion_tokens=state.completion_tokens,
        llm_calls=state.llm_calls,
    )


async def race_async(
    requirements: str,
    variants: int = 2,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_iterations: int = RACE_MAX_ITERATIONS,
) -> RaceOutcome:
    """Run `variants` flows concurrently on the same requirements and rank them.

    Args:
        requirements: What to build. Every variant gets the same text.
        variants: How many independent attempts to make. Cost scales with this.
        concurrency: How many may run at once. Each variant drives its own Docker
            containers, so this is bounded for the sake of the host, not the API.
        max_iterations: Per-variant cap on the automatic build/QA loop.
    """
    if variants < 1:
        raise ValueError("A race needs at least one variant.")

    limit = asyncio.Semaphore(max(1, concurrency))

    async def run_one(index: int) -> VariantResult:
        label = f"variant-{index + 1}"
        flow = ProductFlow()
        flow.state.max_iterations = max_iterations
        async with limit:
            try:
                await flow.kickoff_async(inputs={"requirements": requirements})
            except Exception as exc:  # noqa: BLE001 - one variant failing must not end the race
                result = _collect(label, flow)
                result.error = f"{type(exc).__name__}: {exc}"
                return result
        return _collect(label, flow)

    results = await asyncio.gather(*(run_one(i) for i in range(variants)))
    return RaceOutcome(results=list(results))


def race(
    requirements: str,
    variants: int = 2,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_iterations: int = RACE_MAX_ITERATIONS,
) -> RaceOutcome:
    """Blocking wrapper around :func:`race_async`."""
    return asyncio.run(
        race_async(
            requirements,
            variants=variants,
            concurrency=concurrency,
            max_iterations=max_iterations,
        )
    )
