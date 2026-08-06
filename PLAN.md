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

The Engineering Lead is now `manager_agent`; the four specialists get `allow_delegation=False`
so the manager cannot delegate to an engineer that delegates back.

Two constraints are enforced by CrewAI itself, verified against the installed 1.15.10 source
rather than the docs:

- The manager must not appear in `agents` (`Crew.check_manager_llm` raises
  `manager_agent_in_agents`), so `engineering_lead` is a plain method, not an `@agent`.
- **The manager must not have tools** — `Crew._create_manager_agent` raises outright. The lead
  therefore gave up the Context7 MCP it had as a normal agent. The frontend engineer keeps its
  own, which is where the Gradio 6 lookups were actually needed.

Cost is bounded by construction: `max_iter` 30 on the manager, 20 on workers, `max_rpm` 30.
An unbounded manager is an unbounded bill, so these caps are the feature, not a detail.

The **Product Owner** role is deferred to Phase 5, where it has something to do — turning free
text typed into the UI into a structured spec. Today's requirements are a fixed string, so a PO
crew would add cost and demo nothing.

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

#### Measured again, 2026-08-05 — hierarchical + QA, full flow

| Agent | Model | calls | in | out | USD |
|---|---|---|---|---|---|
| Frontend | `minimax-m3` | 38 | 698,325 | 31,160 | **0.2469** |
| Engineering Lead (manager) | `deepseek-v4-pro` | 23 | 352,998 | 39,241 | 0.1877 |
| QA Inspector | `deepseek-v4-pro` | 13 | 111,042 | 20,506 | 0.0661 |
| Backend | `deepseek-v4-flash-0731` | 19 | 115,298 | 10,783 | 0.0123 |
| Test | `deepseek-v4-flash-0731` | 9 | 43,965 | 12,943 | 0.0063 |
| **TOTAL** | | **102** | **1,321,628** | **114,633** | **0.5193** |

Approved on the first iteration: 32 generated tests passing, all 9 requirements checked
individually by an inspector that ran the tests itself, three findings — two minor, one nit —
none blocking. Still ~8× cheaper than the ~$4 original. Preserved in
`examples/trading_account_manager_hierarchical/`.

**Hierarchical costs 2.35× sequential** ($0.5193 vs $0.2210) — the manager re-reasoning per
delegation plus a fifth agent. Expected direction, now quantified.

**The manager line settles the question left open earlier.** The same role went from $0.0292
sequential to **$0.1877 hierarchical — 6.4×**. The sequential measurement understated it by
that much, which is precisely why that seat's model was re-decided on evidence rather than
left alone. On `glm-5.2` ($0.76/$2.42 vs $0.435/$0.870) the lead alone would have cost about
$0.36 instead of $0.19; the frontend on `kimi-k2.6` would have pushed the run to roughly $0.76.

**What this run does not prove:** QA passed first time, so the `revise` branch never fired
live; the CLI disables pausing, so the human pause/resume round trip is unexercised; and the
race supervisor is verified only against synthetic results.

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
| 2 | Sandbox execution feedback — surface exit code + stderr so agents can debug | **done** |
| 3 | Hierarchical + QA Inspector — `manager_agent`, `QAReport` Pydantic verdict | **done** |
| 4 | Flow — `ProductFlow` with router, iteration cap, `@persist` | **done** |
| 5 | Gradio UI + observability — requirements form, streaming log, HITL, live cost panel | **done** |
| 6 | Per-run sandbox isolation — `sandbox/<run_id>/`, concurrency-safe tools | **done** |
| 7 | Parallel supervisor — variant racing + ranking | **done** |
| 8 | Sandbox backend abstraction — `SandboxBackend` protocol, Docker + E2B | **done** |
| 9 | Deploy — HF Space, secrets, `SANDBOX_BACKEND=e2b` | **done** |
| 10 | Portfolio surface — README, architecture diagram, screenshots, demo link | **done** (README) |

Phases are numbered in the order they are actually built. The original Phase 2 bundled three
things that turned out to belong at three different times — execution feedback was urgent
(phase 2), per-run isolation is only needed once runs are concurrent (phase 6), and the
backend protocol should not be designed until deployment supplies its second implementation
(phase 8). They were split rather than left as one "partial" phase, so the numbering keeps
meaning what it says.

### Phase 2 notes (complete)

`run_sandbox_python` returned `result.stdout` and dropped stderr and the exit code — and
`unittest` writes its *entire* report to stderr, so every test run came back as an empty
string. Agents were debugging blind, and the QA Inspector added in phase 3, whose whole job
is to run the tests and report what failed, would have been judging builds on nothing.

It now returns exit status, stdout and stderr, clips each stream to 12k characters (agents
pay for tool output as input tokens on the very next call), and converts a timeout into a
readable message naming the likely cause — a stray `.launch()`, `input()`, or an infinite
loop — instead of raising an opaque tool error.

The two things originally bundled into this phase moved out to where they belong:
per-run `sandbox/<run_id>/` isolation is phase 6, because nothing needs it until runs are
concurrent; the `SandboxBackend` protocol and E2B backend are phase 8, because a protocol
designed before its second implementation exists is a guess.

### Phases 6 and 7 notes (complete)

**Per-run sandboxes.** Every run works in `sandbox/<run_id>/`. Tools are bound to a
`Sandbox` instance rather than reading a module global — the alternative, a thread-local or
context variable holding "the current sandbox", would depend on CrewAI's context propagation
across the pools it runs agent steps on, which is not guaranteed. Binding at construction
removes the question. `EngineeringTeam` takes the sandbox by injection; every agent in a crew
shares one instance, which is how they see each other's files. `run_id` lives in
`ProductState`, so a flow resumed from a checkpoint returns to the same directory.

This phase also fixed a bug that killed the first end-to-end run before it spent a cent:
Docker defaults to root, so everything a container wrote into the bind mount was root-owned
and the host user could not delete it on the next run. Containers now run as
`--user $(id -u):$(id -g)`, with uv's HOME and cache pointed at `/tmp` so they stay out of
the bind mount. `reset` keeps a root-container fallback for leftovers from before the change.

**Racing.** `uv run race [n]` runs N `ProductFlow`s concurrently via `kickoff_async` +
`asyncio.gather`, bounded by a semaphore, then ranks them.

Two decisions worth defending:

- *Racing whole attempts, not parallelising engineers.* The frontend imports the backend and
  the tests test it, so those steps are genuinely sequential; running them concurrently would
  be three agents guessing at each other's interfaces. The parallelism that actually exists
  in this problem is between independent attempts.
- *Arithmetic ranking, no LLM judge.* Every input is already structured — `QAReport.verdict()`,
  blocking-finding counts, iteration counts — so a judge would add cost and a new failure
  mode to reproduce a sort. Order is: crashes last, then QA approval, then fewest blocking
  findings, then fewest iterations, then fewest tokens. Cheaper only wins between otherwise
  equal results.

Per-variant cost needed new plumbing: the global cost recorder listens on a shared event bus
and cannot tell concurrent flows apart. `ProductState` therefore accumulates `token_usage`
from each crew result, which *is* attributable per flow. The dollar total for the race as a
whole still comes from the recorder.

A race multiplies spend, so `variants` is an explicit argument and the per-variant iteration
cap is tightened to 2.

### Phase 9 notes (live)

Deployed at
[Neuromediator/engineering-team](https://huggingface.co/spaces/Neuromediator/engineering-team),
source at [github.com/Neuromediator/engineering-team](https://github.com/Neuromediator/engineering-team).

**Publishing is a git push, not `gradio deploy`.** That command calls `upload_folder()`
with no `ignore_patterns` (`deploy_space.py:313`), and `upload_folder`'s own docstring
states the `.gitignore` is not taken into account — so it would publish `.env`. No file
could have fixed that. A Space is a git repo, so adding it as a second remote makes
`.gitignore` the single exclusion rule for both destinations, which is what
`make_space.sh` was approximating by staging a clean directory.

**The ignore rule was wrong, and only git push could reveal it.** `sandbox/` is
unanchored, so git matched that directory name at *any* depth — including
`src/engineering_team/tools/sandbox/`. Phase 8's entire deliverable had never been
committed, and the first boot died on `ModuleNotFoundError: No module named
'engineering_team.tools.sandbox'`. Any clone of the repo was equally broken. It stayed
hidden because `make_space.sh` staged with `cp -r`, which copies what git ignores: the
two publication paths disagreed and only one was ever exercised. The rule is now
`/sandbox/`.

**Spaces reads `requirements.txt`, not `pyproject.toml`** — settled by the builder's own
Dockerfile rather than by argument:

    RUN --mount=target=/tmp/requirements.txt,source=requirements.txt \
        pip install --no-cache-dir -r /tmp/requirements.txt ...

No `pip install .`, no build backend. `pyproject.toml` *is* honoured on Spaces, but only
where a Docker SDK image runs `uv` itself — which is what every pyproject-only Space
found turns out to be. `gradio` is correctly absent from the file: the image installs
`gradio[oauth,mcp]==6.22.0` from `sdk_version`.

**Hosting is ZeroGPU because cpu-basic now returns 402.** "Static Spaces are free for
everyone, but hosting Gradio and Docker Spaces on free cpu-basic requires a PRO
subscription." Spaces created before that policy are grandfathered, which makes an
existing free cpu-basic Space misleading evidence. A free account may host two ZeroGPU
Spaces, and ZeroGPU is Gradio-only, so it is the only free tier this app fits. It refuses
to start without at least one `@spaces.GPU` function, so `app.py` carries a no-op — never
called, no quota consumed, since every model call leaves over HTTPS. `python_version` is
pinned to `3.12.12`; ZeroGPU accepts only that and `3.10.13`, and the default is `3.10`.

Verified live rather than assumed running: the boot log is clean, `view_api` lists the
real endpoints, and `/show_demo` returns the genuine cost table, QA verdict and a working
source download.

### Phase 9 notes (original plan)

A public Space cannot open on a 20–50 minute build that spends the owner's credit, so it
opens on a **real completed run** instead — the gym class-booking build, $0.2388 over two
iterations, with its genuine QA report and downloadable source, including the human
feedback round that fixed a waitlist-promotion overlap bug.

This claimed "nothing is mocked", which was not true of the activity panel: that log was
never persisted, and 11 transcribed lines of 134 were rendered in the same widget a live
run streams into, with no sign they were an excerpt. The omission was not neutral — it
dropped every line from the frontend and test engineers, the two agents responsible for
37 of 72 calls, so the panel contradicted the cost table beside it.

**Most of it was recoverable after all.** Screenshots taken while the run was on screen
carried lines 1-5 and 84-134 verbatim, which is 60 of 134 once the four previously
transcribed lines are counted — and, more to the point, the frontend and test engineers
are now visible doing the work they were billed for. The log lives in `demo.json` with the
rest of the packaged record, and the remaining gap is marked in place. Nothing is
reconstructed to fill it.

The lesson is upstream of the panel: **`RunLog` is never persisted**, so every finished run
loses its trace the moment the process ends. Curating an example into `examples/` should
write the log out with the source. Until it does, the next preserved run will need
screenshots too.

| Setting | Deployed value | Why |
|---|---|---|
| `SANDBOX_BACKEND` | `e2b` | Spaces has no Docker daemon |
| `MAX_AUTO_ITERATIONS` | `2` | a gym build used its full budget of 3 and took most of an hour |
| `BUILD_PASSPHRASE` | set | live builds cost the owner money; the UI stays fully browsable |
| `BUDGET_DAILY_USD` | `2` | backstop — but see the caveat below |

`app.py` at the repository root puts `src/` on `sys.path` explicitly rather than assuming
the package was installed: a Space may resolve dependencies without ever running
`pip install .`, and the failure would be a boot traceback with no other clue.

**Two things this phase has not proved.** E2B has never run a *complete* crew — the backend
is verified against the live service for files, execution, exit codes and the
`CommandExitException` trap, but the first full build through it will be the first one ever.
And `BUDGET_DAILY_USD` lives in SQLite on an ephemeral disk, so on Spaces it resets with the
container; `BUILD_PASSPHRASE` is the protection that actually holds there.

The bug worth remembering from this phase: `with gr.Blocks(...) as demo:` made `demo` a
local of `build_ui`, shadowing the `engineering_team.demo` module inside every handler in
that scope. `demo.load()` was calling `Blocks.load()` and returning something falsy, so the
demo button silently did nothing — no error, no warning. The Blocks object is now `page`.

### Phase 8 notes (complete)

`SANDBOX_BACKEND=docker|e2b` selects where a run's files live and its code executes.
Written now rather than in the original phase 2 precisely because there were finally two
implementations to compare — and the comparison moved the seam.

**The seam is files, not execution.** The obvious abstraction is "where does code run".
That is wrong here: Docker bind-mounts a host directory, so reads and writes are ordinary
filesystem calls, while E2B keeps everything on a remote microVM where every read and write
crosses the network. An abstraction over execution alone would have left the file operations
silently local and produced an E2B backend that ran code against an empty VM.

**The trap E2B set.** `commands.run` raises `CommandExitException` on *any* non-zero exit.
Unhandled, that would have recreated — in the deployed backend — the exact bug phase 2 fixed
locally: agents never seeing a failing test run. Worse, the exception subclasses
`SandboxException`, so a natural `except SandboxException` would catch it and mislabel every
test failure as "could not start the sandbox". It is caught first, and a non-zero exit is
returned as the *result* it is.

Verified against the real service, both backends producing identical output:

| Case | Docker | E2B |
|---|---|---|
| `print()` success | `[SUCCESS]` + stdout | `[SUCCESS]` + stdout |
| failing unittest | `[FAILED (exit code 1)]` + stderr traceback | `[FAILED (exit code 1)]` + stderr traceback |
| missing file read | "No such file" | "No such file" |

Two lifecycle problems the abstraction exposed, both invisible with Docker:

- `build()` created a fresh `Sandbox` per iteration. Locally harmless; on E2B that is a new
  empty microVM every revision, leaking the previous one *and still being billed for it*.
  The flow now caches one sandbox for the whole run.
- Nothing ever killed the VM. `deliver` now releases it — deliberately not `finalize` or
  `stop_at_cap`, because a human can still send those back for another pass that needs the
  existing files.

Preflight is backend-aware: it checks `E2B_API_KEY` instead of Docker when configured for
E2B. Spaces has no Docker daemon at all, so checking for one would have blocked every
deployed run.

### Phase 5 notes (complete)

`uv run serve` serves a Gradio 6 app: requirements in, live activity log, live cost panel,
QA findings table, and a human gate before anything ships.

**Human-in-the-loop without blocking.** `PendingUIFeedbackProvider` implements CrewAI's
`HumanFeedbackProvider` protocol structurally and raises `HumanFeedbackPending` instead of
reading stdin. The framework persists flow state at that moment, so the UI resumes with
`ProductFlow.from_pending(flow_id)` + `resume(feedback)` — reloading rather than reusing the
in-memory object, because that same path is what would work after a process restart. A paused
run costs nothing while it waits, which matters on a free tier that sleeps.

The flow graph, confirmed from the built `flow_definition`:

| Method | Trigger | Emits |
|---|---|---|
| `build` | `@start`, and `"revise"` | |
| `evaluate` | listens `build` | `approved` / `revise` / `exhausted` |
| `finalize` | listens `approved` | |
| `stop_at_cap` | listens `exhausted` | |
| `human_review` | listens `or_(finalize, stop_at_cap)` | `ship` / `revise` |
| `deliver` | listens `ship` | |

`human_review` emitting `"revise"` re-enters `build` — the same branch the router uses, so
human and automatic revisions travel identical machinery rather than parallel code paths.

Three traps worth recording:

- `@human_feedback`'s `llm` parameter **defaults to `"gpt-5.4-mini"`**, which would route to
  OpenAI — a provider this project has no key for, and a fourth model outside the chosen
  three. It is set explicitly to the manager's model.
- The documented way to read the result, `self.human_feedback`, **does not exist** on the
  instance. The real accessors are `last_human_feedback` and `human_feedback_history`. More
  doc drift; verified by introspection.
- Pausing is opt-in via `enable_pausing()`. The decorator is evaluated at import time, so one
  provider object serves both surfaces: the UI turns pausing on, a headless `run_crew` leaves
  it off and gets an empty answer that falls through to `default_outcome="ship"`. Without
  that switch a CLI run would pause forever with nobody to answer.

A human asking for another pass also grants a fresh iteration budget
(`max_iterations = iteration + MAX_AUTO_ITERATIONS`). The cap exists to bound *unattended*
looping, not to overrule someone watching it work.

Gradio 6 moved `theme` off the `Blocks` constructor onto `launch()`; the app is warning-clean
under `-W error::UserWarning`.

**Not yet exercised live.** The UI builds, all panels render against synthetic state, and the
flow graph is verified — but the full human-feedback round trip needs a paid run.

### Phase 4 notes (complete)

`ProductFlow` wraps the hierarchical crew in the loop that decides whether to go round again:

    @start / @start("revise")  build      -> run the hierarchical crew
    @router(build)             evaluate   -> "approved" | "revise" | "exhausted"
    @listen("approved")        finalize
    @listen("exhausted")       stop_at_cap

The division of labour is deliberate: autonomy inside a build (the manager genuinely should
choose who does what), determinism about whether to keep spending. `evaluate` is ordinary
Python branching on `QAReport.verdict()`.

Verified against synthetic reports, no API calls:

| Input | Branch |
|---|---|
| Clean pass | `approved` |
| Blocker or major finding | `revise` |
| Minor/nit only | `approved` — advisory severities cannot trap the loop |
| `passed=True` but tests never run | `revise` |
| Tests ran and failed | `revise` |
| No structured report at all | `revise` — fails safe, never a silent pass |
| Blocking finding at the cap | `exhausted` |

Blocking findings are carried into `state.revision_notes` and interpolated into the next
build's task descriptions, so a revision knows what to fix. The sandbox is reset only on
iteration 1 — resetting on a revision would discard the very code being corrected.

`@persist()` checkpoints to SQLite (`~/.local/share/engineering_team/flow_states.db`, *not*
in-project — matters for Phase 7, where Spaces storage is ephemeral). That is what will make
the Phase 5 human-feedback pause survivable via `Flow.from_pending(flow_id)` + `resume()`.

`run_crew` now drives the flow; `run_once` runs a single crew pass, which is the cheaper
thing to run when the question is "does the crew still work" rather than "is the product good".

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
