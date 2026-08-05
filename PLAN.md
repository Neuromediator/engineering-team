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

`config/models.yaml` holds role→model mapping *and* per-model pricing, so the cost panel and
the LLM assignment cannot drift apart. **Three models, fixed** — no profile matrix, because
comparing configurations is not what this project is demonstrating.

| Role | Model | $/M in | $/M out | ctx |
|---|---|---|---|---|
| Engineering Lead (manager) | `deepseek/deepseek-v4-pro` | 0.435 | 0.870 | 1M |
| Backend / Test | `deepseek/deepseek-v4-flash-0731` | 0.09 | 0.18 | 1M |
| Frontend | `minimax/minimax-m3` | 0.30 | 1.20 | 1M |

**Manager — V4 Pro.** Manager cost is dominated by *input* tokens: it re-sends accumulated
context on every delegation, so context size and input price are the levers. 80.6% SWE-bench
Verified, the strongest open-weights score.

**Backend / Test — V4 Flash.** These roles work against a feedback loop — code runs in the
sandbox and errors come back — so cheap mistakes are observable and recoverable. The dated
`-0731` snapshot is pinned deliberately: 55% cheaper than the floating `deepseek-v4-flash`
($0.14/$0.28) and reproducible over time.

**Frontend — MiniMax M3**, chosen from benchmarks rather than assumption. Kimi K3 tops the
Arena.ai Frontend Code Arena (1679 Elo, winning six of seven frontend domains, ahead of
Claude Fable 5 at 1631 and GLM-5.2 at 1587) but costs $3/$15 — that one agent would be ~85%
of run cost. M3 scores 80.5% SWE-bench Verified, statistically tied with V4's leading 80.6%,
at $0.30/$1.20. It is also a different family from the DeepSeek manager and workers, so the
UI is not written by a model sharing the exact failure modes of the backend it wraps.

Sources: [Arena Frontend Code leaderboard](https://thenewstack.io/kimi-k3-open-weight-coding/),
[open-weights coding comparison](https://www.morphllm.com/best-open-source-coding-model-2026),
prices from `https://openrouter.ai/api/v1/models`.

#### Measured baseline, 2026-08-05

The first full run (sequential, reference requirements, on the earlier model set) cost
**$0.2210** — ~18× cheaper than the ~$4 original — and produced working output: 51/51
generated tests pass, `app.py` compiles, `_validate.py` builds the Gradio `Blocks`.

| Agent | calls | in | out | USD |
|---|---|---|---|---|
| Frontend | 9 | 170,937 | 20,072 | **0.1505** |
| Engineering Lead | 5 | 16,714 | 6,797 | 0.0292 |
| Backend | 14 | 227,851 | 21,275 | 0.0243 |
| Test | 9 | 179,244 | 5,018 | 0.0170 |
| **TOTAL** | 37 | 594,746 | 53,162 | **0.2210** |

Two things this measurement taught, both now folded into the table above:

- The frontend agent was **68% of total spend** while the backend engineer processed *more*
  input tokens for one sixth the cost. Paying a premium for the frontend role was not
  justified by anything measurable.
- That agent's spend was **67% input tokens** — it ingests large Context7 doc dumps. So input
  price and context window matter more than output price, which is the opposite of the
  assumption originally used to pick a frontend model.

Lesson worth keeping: price claims from blogs and search results were wrong for three of four
models on the first pass. `python -m engineering_team.model_config --check` re-verifies every
committed price against the live catalogue.

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
