# Roadmap: from course project to autonomous product studio

## Why

This started as a follow-along from Ed Donner's Udemy Agentic AI course: a 4-agent
**sequential** CrewAI crew that turns a hardcoded requirements string into a backend, a Gradio
app and tests inside a local Docker sandbox. It works, but it reads as a lecture artifact —
hardcoded inputs, no UI, no feedback loop, no tests of its own.

The goal is to extend it into something that stands on its own: **hierarchical delegation, a
quality-inspection role, human-in-the-loop revision, multi-crew parallel orchestration, live
observability, and a public deployment** — while cutting per-run cost from ~$4 to under $0.50.

## Architecture

A CrewAI **Flow** owns the outer loop; a **hierarchical crew** does the building. Autonomy
where it adds value, determinism where reliability and a cost ceiling matter.

```
@start  analyze_requirements  → PO crew,    output_pydantic=ProductSpec
@listen build                 → BuildCrew (hierarchical, lead delegates freely)
@listen qa                    → QA crew,    output_pydantic=QAReport
@router                       → report.passed and iteration < MAX ? "review" : "build"
@human_feedback               → GradioFeedbackProvider, emit=["approved", "revise"]
@listen "revise"              → back to build, feedback carried in state
@listen "approved"            → finalize
```

Two things keep this from being a demo that loops forever: QA returns a **Pydantic** report so
the router branches on a boolean rather than parsed prose, and `MAX_AUTO_ITERATIONS` bounds the
automatic build↔QA cycle.

**Parallelism is variant racing**, not parallel engineers — the frontend genuinely depends on
the backend, so splitting those would be theatre. Instead N `ProductFlow`s run concurrently via
`asyncio.gather` over `kickoff_async()`, each on a different model profile, and a judge step
ranks them. This doubles as the cost-vs-quality benchmark. It requires per-run sandbox
isolation (`sandbox/<run_id>/`).

### New roles

| Agent | Purpose |
|---|---|
| **Product Owner** | Raw UI text → structured spec with acceptance criteria. Stops garbage-in. |
| **QA Inspector** | Reads the sandbox, runs tests, emits severity-ranked findings that drive the router. |

The Engineering Lead becomes `manager_agent`; engineers get `allow_delegation=False` to prevent
circular delegation.

### Models

`config/models.yaml` holds role→model mapping *and* per-model pricing, so the cost panel and the
LLM assignment cannot drift apart.

Current `budget` profile, every price verified against OpenRouter's live catalogue:

| Role | Model | $/M in | $/M out |
|---|---|---|---|
| Engineering Lead (manager) | `openrouter/z-ai/glm-5.2` | 0.76 | 2.42 |
| Backend / Test | `openrouter/deepseek/deepseek-v4-flash-0731` | 0.09 | 0.18 |
| Frontend | `openrouter/moonshotai/kimi-k2.6` | 0.589 | 2.48 |

These differ from the models first proposed, because the originals came from secondary
sources that were wrong. Querying `https://openrouter.ai/api/v1/models` directly showed:

- `deepseek-v4-flash` is **$0.14/$0.28**; the $0.09/$0.18 rate belongs to the dated
  `-0731` snapshot. Pinning it is 55% cheaper *and* reproducible for benchmarking.
- `glm-5` is **$0.95/$2.55**, not $0.60/$1.92. `glm-5.2` is cheaper, newer and has 1M
  context, so it wins on every axis.
- `gpt-5.4-mini` is **$0.75/$4.50**, not $0.25/$2.00.
- `kimi-k2.6` supersedes k2.5 ($0.589/$2.48 vs $0.57/$2.85); output dominates for code
  generation.

Lesson worth keeping: price claims from blogs and search results were wrong for three of
four models. `python -m engineering_team.model_config --check` re-verifies every committed
price against the live catalogue.

#### Measured, 2026-08-05 (budget profile, sequential, reference requirements)

| Agent | Model | calls | in | out | USD |
|---|---|---|---|---|---|
| Frontend | `kimi-k2.6` | 9 | 170,937 | 20,072 | **0.1505** |
| Engineering Lead | `glm-5.2` | 5 | 16,714 | 6,797 | 0.0292 |
| Backend | `v4-flash-0731` | 14 | 227,851 | 21,275 | 0.0243 |
| Test | `v4-flash-0731` | 9 | 179,244 | 5,018 | 0.0170 |
| **TOTAL** | | 37 | 594,746 | 53,162 | **0.2210** |

**~18× cheaper than the ~$4 baseline**, and the output is real: all 51 generated tests
pass, `app.py` compiles and `_validate.py` confirms the Gradio `Blocks` builds.

#### What this measurement invalidates

The **frontend gets the strong model** decision does not survive contact with data. It is
68% of total spend, while the backend engineer processed *more* input tokens for one sixth
the cost. The rationale was that frontend output is the least verifiable — but `_validate.py`
only asserts the `Blocks` object constructs, and the backend's "safety net" is tests written
by the same cheap model, so neither half of that argument is as strong as claimed. Moving
frontend to V4 Flash projects to ~$0.09 (−60%).

The **manager model choice is not settled either**, but for the opposite reason: at 5 calls
it is only 13% of spend *because the crew is still sequential*. Hierarchical (Phase 3) makes
the manager re-reason per delegation, so this must be re-measured before judging. Honest
provenance: `glm-5.2` came from anchoring on the GLM family in a weakly-sourced draft and
then optimizing within it; the ~129 tool-capable models with ≥128k context in that price band
were never enumerated, and `deepseek/deepseek-v4-pro` ($0.435/$0.870, same 1M context) beats
it on both axes. **No capability benchmarks were run for any role** — the prices are verified,
the quality rankings are not. Phase 6's variant racing is what turns these into measurements.

### Stack decisions

- **Gradio 6** — already the sandbox's only dependency, deploys to HF Spaces in one push, and
  the observability panel needs a dashboard more than it needs chat polish.
- **HF Spaces + E2B** — Spaces cannot run Docker-in-Docker, so execution moves to E2B's
  Firecracker microVMs over HTTPS. Free tier covers a portfolio demo.
- **Tiered OpenRouter models** — see above.

## Phases

| # | Phase | Status |
|---|---|---|
| 0 | Upgrade & de-risk — git init, crewai 1.15.10, rewrite `patch.py`, smoke test | **done** |
| 1 | Cost floor — all roles onto OpenRouter via `config/models.yaml` | **done** |
| 2 | Sandbox abstraction — `SandboxBackend` protocol, Docker + E2B, per-run isolation | |
| 3 | Hierarchical + new roles — `manager_agent`, PO and QA crews with Pydantic outputs | |
| 4 | Flow — `ProductFlow` with router, iteration cap, `@persist` | |
| 5 | Gradio UI + observability — requirements form, streaming log, HITL, live cost panel | |
| 6 | Parallel supervisor — variant racing + comparison view | |
| 7 | Deploy — HF Space, secrets, `SANDBOX_BACKEND=e2b` | |
| 8 | Portfolio surface — README, architecture diagram, screenshots, demo link | |

### Phase 0 notes (complete)

- `crewai[tools]` 1.14.4 → 1.15.10. Every API the rewrite depends on verified present against
  the installed package: `HumanFeedbackProvider`, `PendingFeedbackContext`,
  `Flow.from_pending`/`resume`/`ask`, `BaseEventListener`, `LLMCallCompletedEvent`.
- The MCP tool-name bug is **not** fixed in 1.15.10 — confirmed by running discovery against
  Context7 with and without the patch. `patch.py` was rewritten to patch only the two points
  that lose the name, rather than overriding `_resolve_external` wholesale (which would have
  discarded the TTL schema cache, retry and timeouts that 1.15.x added).
- Fix submitted upstream: [crewAIInc/crewAI#6803](https://github.com/crewAIInc/crewAI/pull/6803).
- First tests in the project; `tests/` was previously empty.
- **Outstanding:** no paid end-to-end run yet. Folded into Phase 1 as the before/after cost
  measurement.

## Verification

- **Sandbox:** one contract test suite run against both Docker and E2B backends; assert non-zero
  exit codes and stderr surface (the original tool returned only stdout, so tracebacks came back
  empty and agents debugged blind).
- **Router:** synthetic `QAReport`s — passing, failing, cap-hit — asserting the correct branch
  and that the cap halts.
- **HITL:** kick a flow, assert `HumanFeedbackPending`; reload via `from_pending`, `resume(...)`,
  assert the revise branch runs with feedback in state.
- **End-to-end:** budget profile, total cost < $0.50 from the observability panel, generated
  app's `_validate.py` passes.

## Risks

| Risk | Mitigation |
|---|---|
| Hierarchical manager loops / burns budget | Iteration cap, `max_rpm`, cheap models, `allow_delegation=False` on engineers |
| Cheap model delegates poorly as manager | GLM-5 rather than V4 Flash for the lead; profile is configurable |
| Long runs exceed Space request timeouts | Flow runs in a background thread; UI polls via `gr.Timer` |
| E2B credit exhausted | Short-lived sandboxes, hard concurrency cap |
