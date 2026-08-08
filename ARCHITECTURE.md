# Architecture

How the system is put together and why the seams fall where they do. For what it produces
and what measuring it revealed, see [README.md](README.md).

The organising idea is one sentence: **autonomy inside a build, determinism around it.**
Agents decide how to write the code; ordinary Python decides whether to spend money on
another attempt. Every decision that costs money or ends a run is made by code branching on
a Pydantic field, never by a model reading prose.

---

## Layers

```
  Gradio UI  ──  app.py, ui/session.py
       │         one RunSession per browser tab; the flow runs on a background thread
       ▼
  Triage     ──  triage.py                      one cheap call, before anything exists
       ▼
  Flow       ──  flows/product_flow.py          the outer loop, bounded, checkpointed
       ▼
  Crew       ──  crew.py + config/*.yaml        five agents, five tasks
       ▼
  Sandbox    ──  tools/sandbox/                 Docker locally, E2B when deployed
```

Every layer is usable without the one above it: the flow runs headless (`uv run run_crew`),
the crew runs without the flow (`uv run run_once`), and the sandbox backends are a Protocol
with two implementations. Nothing imports the UI.

---

## The flow — outer loop

`ProductFlow` is a CrewAI `Flow` over a Pydantic `ProductState`. `@persist()` checkpoints to
SQLite after every step, which is what lets a run pause for a human and be resumed later
from a different HTTP request.

```
@start / @start("revise")   build        → run the crew; QA emits output_pydantic=QAReport
@router(build)              evaluate     → "approved" | "revise" | "exhausted"
@listen("approved")         finalize     → archive the source for the reviewer
@listen("exhausted")        stop_at_cap  → archive it too, findings outstanding
@listen(or_(…))             human_review → @human_feedback; pauses here
@router(human_review)       decide       → "ship" | "revise"
@listen("ship")             deliver      → re-archive, release the workspace
```

Three things stop this being a demo that loops forever:

- **`MAX_AUTO_ITERATIONS`** bounds the automatic build↔QA cycle.
- **`evaluate` branches on `QAReport.verdict()`** — a boolean derived from severity-ranked
  findings, not from the inspector's summary text.
- **A cost probe and a cancel probe** are injected by the session, so the router can stop
  before paying for another iteration and an abandoned page ends the run.

`human_review` carries **no `emit`**. CrewAI's version asks a model to collapse free text
into an outcome, and it got it wrong — "Reject invalid input in the backend, not just the
UI" was classified as *ship* and delivered unchanged. The interface already knows which
button was pressed, so `decide` reads a marker the UI prefixes to the feedback.

**Parallelism is variant racing, not parallel engineers.** The frontend genuinely depends
on the backend, so splitting those would be theatre. `flows/supervisor.py` instead runs N
`ProductFlow`s concurrently via `asyncio.gather` over `kickoff_async()` and ranks what comes
back. The ranking is **arithmetic, not an LLM judge** — every input is already structured
(`QAReport.verdict()`, blocking-finding counts, iteration counts), so a judge would add cost
and a failure mode to reproduce a `sorted()` call.

---

## The crew — inner loop

Five agents and five tasks, defined in `config/agents.yaml` and `config/tasks.yaml`.
`crew.py` is wiring only. (The sixth agent and task in those files are the Brief Reviewer,
which runs on its own one-agent crew before this one — see Triage.)

| Agent | Does |
|---|---|
| Engineering Lead | Writes the design: modules, signatures, what the tests must cover |
| Backend Engineer | Implements it in the sandbox |
| Frontend Engineer | Writes `app.py` and validates that it constructs — the only agent with Context7 MCP |
| Test Engineer | Writes and runs `unittest` tests |
| QA Inspector | Re-reads the files, re-runs the tests, emits a `QAReport` |

**Sequential is the default**, with hierarchical available as a comparison. Under
hierarchical the Engineering Lead becomes `manager_agent` and two constraints are enforced
by CrewAI itself: the manager must not appear in `agents`, and the manager must not have
tools — which is why the lead has no MCP and the frontend engineer does.

The QA task is **inspect-and-report only**. An earlier version told the inspector to fix
what it found and re-verify until clean; under sequential there is no manager to delegate
to, so it looped to its wall clock and cost double. Findings go back through the flow's
bounded loop instead — the outer loop is bounded, a loop inside a task is not.

Cost is bounded by construction: `max_iter` 12 on the manager, 15 on workers, `max_rpm` 120.

---

## Triage — before anything exists

`review_brief()` runs one call on the cheapest model and returns a `BriefVerdict` with two
independent booleans:

- **`buildable` is advisory.** A terse brief is still a brief and the person clicking is
  paying, so a wrong "no" offers *Build it anyway* rather than a wall.
- **`permitted` is binding.** It refuses only where the evident purpose is harm, and judges
  purpose rather than vocabulary.

Briefs under 15 characters never reach a model, and the whole step **fails open** — triage
that blocks a build by breaking is worse than no triage.

This is not a violation of "never branch on prose": free text is the only signal there is,
and what the code branches on is two booleans off a Pydantic model.

---

## Sandbox

`SandboxBackend` is a Protocol — list, read, write, run, install, reset, close. Two
implementations, chosen by `SANDBOX_BACKEND`:

- **Docker** locally: an ephemeral container, so generated code never runs on the host.
- **E2B** when deployed: a microVM. Its lease is renewed on every operation rather than set
  once, because a lifetime timeout killed builds mid-run; its `sandbox_id` is kept in flow
  state so a resumed flow reattaches to the same VM instead of shipping an empty one.

Each run gets `sandbox/<run_id>/`, reset only at the start of its own run. Source is
archived to `exports/<run_id>.zip` and the activity log to `exports/<run_id>.log` **before**
the workspace is released — on a remote backend those are the only copies that survive.
Both are written at the human gate as well as on delivery, so a reviewer can read what they
are being asked to judge.

---

## Observability and cost

Two `BaseEventListener`s on CrewAI's event bus, installed once per process and forwarded to
whichever session is currently building:

- `CostListener` → `RunRecorder`: tokens and dollars per agent, priced from
  `config/models.yaml`, which holds role→model mapping *and* pricing so the cost panel and
  the LLM assignment cannot drift apart.
- `ActivityListener` → `RunLog`: what each tool did and what came back.

Handlers dispatch on a thread pool, so totals are settled before reporting. `budget.py`
keeps a daily ceiling in SQLite; spend is banked when a run finishes, fails, is cancelled,
**and** when it pauses for feedback, so a run nobody comes back to is still counted.

---

## UI and session lifecycle

One `RunSession` per browser tab, held in `gr.State`. A module-level session would let one
visitor discard another's results. A process-wide lock allows one live build at a time and
is released whenever the run is not actually executing — including at the human gate, so a
visitor who never answers cannot lock everyone out.

The flow runs on a background thread; a hidden `gr.Timer` polls session state every two
seconds. Statuses are `idle → starting → running → awaiting_feedback → finished | failed |
cancelled`. `starting` exists because triage and preflight take up to twenty seconds before
a run exists, and a page that says "Idle" through that reads as a dropped click.

**Human-in-the-loop must not block.** CrewAI's default feedback provider reads stdin, which
is unusable from a web UI. `PendingUIFeedbackProvider` raises `HumanFeedbackPending`
instead; the UI resumes via `Flow.from_pending(flow_id)` and `flow.resume(feedback)`.

**Stopping** kills the workspace immediately, banks the spend, and stops the next iteration
starting. It cannot interrupt an LLM call in flight — CrewAI exposes no cancellation hook
and a thread cannot be killed from outside — so the step in progress finishes and is billed.
`cancelled` is cleared at the start of every attempt: it was once a one-way latch, and a
session outlives a run, so a single Stop silently poisoned every later build in that tab.

---

## Module map

| Path | Purpose |
|---|---|
| `app.py` | Gradio UI: handlers, polling, gating |
| `ui/session.py` | Per-visitor run lifecycle, cancellation, the run lock |
| `ui/feedback_provider.py` | Non-blocking human-feedback provider |
| `flows/product_flow.py` | The outer loop |
| `flows/supervisor.py` | Variant racing: N flows via `asyncio.gather`, ranked arithmetically |
| `crew.py` | Crew, agent and task wiring |
| `config/*.yaml` | Agents, tasks, models and pricing |
| `schemas.py` | `QAReport`, `Finding`, `BriefVerdict` — everything control flow reads |
| `triage.py` | Intake review |
| `tools/sandbox_tools.py` | The tools agents actually call |
| `tools/sandbox/` | `SandboxBackend` Protocol, Docker and E2B backends |
| `observability/` | Cost recorder and activity log, off the event bus |
| `budget.py` | Daily ceiling, run limit, build passphrase |
| `capabilities.py` | What the built app may use; pinned Gradio version |
| `preflight.py` | Refuses to start when the sandbox or keys are not ready |
| `patch.py` | Local carry of [crewAIInc/crewAI#6803](https://github.com/crewAIInc/crewAI/pull/6803) |

---

## Invariants

These are the rules the design is actually built on. Breaking one is how this stops being
demonstrable.

1. **Never branch on prose.** Anything another step decides on is `output_pydantic`.
2. **Every loop is bounded**, and the bound lives outside the thing being bounded.
3. **YAML-first.** Agents and tasks are configuration; `crew.py` is wiring.
4. **Nothing generated runs on the host.** Only in the sandbox.
5. **Artefacts are written before the workspace is released**, not after.
6. **Verify CrewAI against the installed package, not the docs** — they have drifted.
7. **Tests use stdlib `unittest`** and require no network and no API keys.
