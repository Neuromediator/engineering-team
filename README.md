---
title: Engineering Team
emoji: 🛠️
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
python_version: "3.12.12"
pinned: false
license: mit
short_description: Plain-English requirements to a tested Python product
---

# Engineering Team

A CrewAI system that turns plain-English requirements into a working, tested Python
product — designed, built, independently inspected, and revised until it passes or a human
says stop.

**On the [live Space](https://huggingface.co/spaces/Neuromediator/engineering-team), open
with "Show a finished run"** to see a real completed build in two seconds: its actual cost
table, its QA report, and the source to download — including the human feedback round that
fixed a waitlist-promotion bug. Nothing is invented, but one panel is partial: the activity
log was never written to disk, so 60 of its 134 lines were recovered from screenshots and
the gap is marked in place rather than quietly closed. A live build takes 20–50 minutes and
spends real money, so it is passphrase-gated on that deployment.

It began as a follow-along from Ed Donner's Udemy Agentic AI course: four agents in a fixed
sequence, a hardcoded requirements string, no UI, no tests of its own. What follows is what
changed, and — more usefully — **what measuring it revealed**, including the parts where my
first instinct was wrong.

```
  requirements ──► design ──► backend ──► frontend ──► tests ──► QA inspection
                                                                      │
                        ┌── revise ◄──── blocking findings? ◄─────────┘
                        │                       │
                        └──────────────► human gate ──► ship
```

---

## Quickstart

```bash
uv sync
uv run serve          # the web UI at http://127.0.0.1:7860
```

Needs an `OPENROUTER_API_KEY` in `.env` and a running Docker daemon. A preflight check
refuses to start otherwise — see [Bounds](#bounds-and-safety) for why that matters.

```bash
uv run run_crew       # same thing, on the command line
uv run run_once       # one crew pass, no review loop — the cheap "does it still work?"
uv run race 3         # three independent attempts in parallel, ranked
```

---

## What measuring it revealed

This is the part I would want a reader to look at. Every number below came from an actual
paid run, recorded live off the CrewAI event bus.

### Hierarchical delegation was the wrong tool here

The headline goal was replacing the fixed sequence with a manager that decides who does
what. It works — and it cost more for the same result:

| | LLM calls | Cost | Agents |
|---|--:|--:|---|
| Sequential | 37 | $0.2210 | 4 |
| Hierarchical + QA | 102 | $0.5193 | 5 |

Both produced a working, test-passing trading-account product from identical requirements.
The manager alone made 23 calls across 74 delegation exchanges, re-deriving a plan that was
already correct — because this pipeline's order is *known in advance*: design, backend,
frontend, tests.

**Caveat, stated plainly: this is not a controlled A/B.** Three things differed between
those runs — the process, the presence of the QA Inspector, and the models. The call counts
(37 vs 102) are the cleaner signal, since both built the same product, but part of the cost
increase is simply a fifth agent. The switch below exists so the comparison can be run
properly rather than argued about.

Hierarchical earns its cost when decomposition is genuinely unknown, or when rework must be
routed to whoever owns the broken file. **Sequential is the default; hierarchical is one
click away**, and the UI shows the cost of your choice as it accrues.

### Independent QA was the change that paid

The QA Inspector reads the sandbox and **runs the tests itself** rather than trusting the
agent that wrote them. On a gym-booking build it caught this:

> *"data is stored only in memory and does not survive a process restart, contrary to the
> explicit requirement. The design document acknowledges this gap but re-interprets the
> requirement as 'within the scope of a single execution', which does not match the plain
> meaning."*

The design had quietly redefined the requirement to match what got built. QA refused it,
the revision loop fed the finding back, and the next iteration implemented real
persistence. That is the loop doing the one thing that justifies its existence.

### Agents were debugging blind

`run_sandbox_python` returned only `stdout`. Python's `unittest` writes its **entire
report** to `stderr` — so every test run an agent did came back as an empty string. They
were guessing at failures they could not see. Fixing it also fixed the E2B backend, which
raises `CommandExitException` on any non-zero exit and would have reproduced the same bug
in production.

### An LLM classifier shipped a build that asked for changes

The human gate used CrewAI's `emit=["ship","revise"]`, which uses a model to classify free
text into an outcome. Given *"Reject invalid input in the backend, not just the UI"* it
chose **ship**.

The project's own design rule says never parse prose to make a control-flow decision — the
QA gate branches on a boolean from a structured `QAReport` precisely for this reason. Then
the human gate handed the same kind of decision to a model, for no reason, because the
interface already knew what the person meant. It is now two buttons and a marker the router
reads. No model is consulted.

### A revision was rebuilding the entire product

Asking to delete three files took over half an hour: every iteration re-ran all five tasks,
including a fresh design. Revisions now run a reduced crew — no design step, no context
chains, and an explicit *"this is a change, not a build"* instruction.

The tempting conclusion had been "the cheap model isn't good enough". It wasn't: the model
was being asked to redo everything. Swapping to a premium model would have made a
badly-scoped pipeline more expensive, not faster.

---

## Design decisions

**Autonomy inside a build, determinism about whether to keep spending.** A CrewAI `Flow`
owns the outer loop; the crew owns the work. The router branches on
`QAReport.verdict()` — a boolean recomputed from structured findings, which ignores an
agent's own `passed` flag if it contradicts them. An inspector that claims success while
reporting blockers, or that never ran the tests, cannot wave a build through.

**Severity that cannot trap the loop.** Only `blocker` and `major` fail a build; `minor`
and `nit` are advisory. A pedantic inspector cannot spend your money on cosmetics.

**Human feedback that does not block.** The provider raises `HumanFeedbackPending` instead
of reading stdin. Flow state is persisted, so the UI resumes with
`ProductFlow.from_pending(flow_id)` + `resume()` — the path that also survives a process
restart. A paused run costs nothing while it waits.

**Parallelism where it actually exists.** The frontend imports the backend and the tests
test it, so those steps are genuinely sequential; running them concurrently would be three
agents guessing at each other's interfaces. `uv run race N` instead races **whole attempts**
and ranks them arithmetically — no LLM judge, because every input is already structured.

**One sandbox per run.** Tools are bound to a `Sandbox` instance rather than reading a
global, because CrewAI runs agent steps on pools whose context propagation is not
guaranteed. Binding at construction removes the question.

---

## Models

Three models, fixed, in `src/engineering_team/config/models.yaml` — which also holds the pricing, so the cost
panel and the LLM assignment cannot drift apart.

| Role | Model | $/M in | $/M out |
|---|---|--:|--:|
| Engineering Lead | `deepseek/deepseek-v4-pro` | 0.435 | 0.870 |
| Backend, Test | `deepseek/deepseek-v4-flash-0731` | 0.09 | 0.18 |
| Frontend | `minimax/minimax-m3` | 0.30 | 1.20 |
| QA Inspector | `deepseek/deepseek-v4-pro` | | |

Chosen on evidence, and revised when the evidence contradicted the first attempt. The
original frontend model was Kimi K2.6, until a measured run showed that agent was **68% of
total spend** — and that 67% of its cost was *input* tokens, not output, which was the
opposite of the assumption behind picking it. MiniMax M3 scores 80.5% on SWE-bench Verified
(statistically tied with DeepSeek V4's leading 80.6%) at a fifth of the input price.

`uv run python -m engineering_team.model_config --check` re-verifies every committed price
against OpenRouter's live catalogue. Prices from blogs were wrong for three of four models
on the first pass.

---

## Bounds and safety

Autonomous agents with a credit card need limits that are provable, not hoped for.

| Bound | Why it exists |
|---|---|
| `MAX_AUTO_ITERATIONS` | caps the unattended build↔QA loop |
| `max_iter`, `max_execution_time` | an agent can burn unbounded *time* inside one iteration — this was found the hard way |
| `BUDGET_DAILY_USD`, `BUDGET_RUN_USD` | a public demo spends the owner's credit; stored in SQLite so a restart cannot reset it |
| Preflight | a run whose sandbox cannot execute still costs full price while producing code nobody verified |
| `allow_delegation=False` | stops a manager delegating to an engineer that delegates back |

The preflight check exists because of a specific mistake: `docker info` succeeded while
`PATH` resolved to the Windows `docker.exe` under WSL, whose bind mounts are silently
empty. Fourteen sandbox executions failed while the crew kept spending. It now runs a real
container against a real bind mount and refuses to start if the file does not read back.

---

## Observability

Cost, tokens and calls per agent, live, off the event bus — plus an activity log showing
what each tool did and what happened:

```
tool  Backend        write_sandbox_file  tip.py  → 2668 chars
tool  Test Engineer  run_sandbox_python_file  test_tip.py  → FAILED (exit code 1)
tool  Frontend       run_sandbox_python_file  _validate.py  → SUCCESS
```

Event handlers dispatch on a thread pool, so totals are settled before reporting — the
first version recorded zero calls because it read them too early.

---

## Upstream contribution

CrewAI sanitizes MCP tool names on discovery, then sends the *sanitized* name back to the
server, making hyphenated tools (Context7's `resolve-library-id`) unreachable. Fix submitted
as [crewAIInc/crewAI#6803](https://github.com/crewAIInc/crewAI/pull/6803). `patch.py` carries
it locally until that ships.

---

## What this does not do

- **Python only**, one flat directory, Gradio for the UI. Ask for a React dashboard and you
  get a confusing failure — the UI states the constraints before you spend anything.
- **Builds take 10–25 minutes per iteration**, and most take two, so 25–50 minutes is
  the honest range. Cost is the steadier number: $0.18–0.24 sequential. Not a chat toy.
- **Racing is verified against synthetic results**, not a live multi-variant run.
- **One build at a time.** Sessions are per-visitor, but the event bus is global and the
  hardware is not big enough to make concurrency honest.

---

## Layout

| Path | Purpose |
|---|---|
| `src/engineering_team/crew.py` | agents, tasks, and the sequential/hierarchical switch |
| `src/engineering_team/flows/product_flow.py` | the outer loop: build → inspect → decide |
| `src/engineering_team/flows/supervisor.py` | parallel variant racing |
| `src/engineering_team/schemas.py` | `QAReport` — the structured verdict the router reads |
| `src/engineering_team/tools/sandbox/` | `SandboxBackend` protocol, Docker and E2B |
| `src/engineering_team/observability/` | cost recorder and activity log |
| `src/engineering_team/app.py` | the Gradio UI |
| `src/engineering_team/config/models.yaml` | role → model, and pricing, in one file |
| `examples/` | preserved output from real runs, with their cost tables |
| `ARCHITECTURE.md` | how it fits together, and the invariants it is built on |
