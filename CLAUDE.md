# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A CrewAI multi-agent system that turns plain-English product requirements into working,
tested software. It began as a follow-along from Ed Donner's Udemy Agentic AI course and is
being rewritten into a portfolio project — see `PLAN.md` for the roadmap and current phase.

The portfolio framing is a real constraint, not decoration. Prefer choices that are
**demonstrable and explainable** over ones that are merely clever, and prefer **bounded,
provable behaviour** (iteration caps, structured `output_pydantic` routing) over impressive
autonomy that can loop.

## Hard rules

- **Never read, `cat`, `grep` or print `.env`.** It holds live API keys, and tool output lands
  in the transcript. Verify credentials indirectly: `ls -la .env`, `[ -n "$VAR" ]`, or grep for
  key *names* only. `.env` lives in the **parent** directory
  (`crewai_engineering_team/.env`); `find_dotenv` resolves it from the project root, so it
  does not need moving.
- **Cost is a first-class constraint.** The original crew cost ~$4 per run on `gpt-5.5`. Never
  trigger a full crew run casually — check which models are configured first. Structural checks
  (imports, crew construction, unit tests) are free; use them by default.
- **`sandbox/` is wiped on every run** by `reset_sandbox()`. Never leave anything valuable
  there. Curated output belongs in `examples/`.

## Commands

```bash
uv sync                                          # install
uv run python -m unittest discover -s tests -v   # tests (stdlib unittest, no network)
uv run run_crew                                  # full crew run — COSTS MONEY
```

Running the crew locally also needs the Docker daemon up; agent code executes in an ephemeral
container.

## Layout

| Path | Purpose |
|---|---|
| `src/engineering_team/crew.py` | Crew, agent and task wiring |
| `src/engineering_team/config/*.yaml` | Agent and task definitions (YAML-first; keep the crew class thin) |
| `src/engineering_team/tools/sandbox_tools.py` | Sandbox file + execution tools given to agents |
| `src/engineering_team/patch.py` | Monkey-patch for an upstream CrewAI MCP bug |
| `tests/` | Tests for the orchestration code itself |
| `examples/` | Preserved sample output from real runs |
| `AGENTS.md` | Vendored CrewAI API reference |
| `.agents/skills/` | CrewAI's own skill files (`ask-docs`, `design-agent`, `design-task`) |

For CrewAI API questions, prefer `.agents/skills/ask-docs/SKILL.md` — fetch
`https://docs.crewai.com/llms.txt`, then the specific page — over general web search.

## Gotchas

**`patch.py` is load-bearing.** CrewAI sanitizes MCP tool names on discovery and then sends the
*sanitized* name back to the server, so hyphenated server-side tools (Context7's
`resolve-library-id`) are unreachable. Present in 1.14.4 through 1.15.10. Fixed upstream in
[crewAIInc/crewAI#6803](https://github.com/crewAIInc/crewAI/pull/6803); once that merges and is
released, delete `patch.py`, its import in `main.py`, and `tests/test_patch.py`.
`tests/test_patch.py::UpstreamDriftTest` fails deliberately when the patch becomes unnecessary.

**Verify CrewAI APIs against the installed package, not the docs.** The published docs have
drifted at least once (they advertise a `learn_limit` parameter on `@human_feedback` that does
not exist; the real signature has `learn_source`/`learn_strict`). Check
`.venv/lib/python3.13/site-packages/crewai/` when it matters.

**Human-in-the-loop must not block.** `@human_feedback` defaults to a console provider that
blocks on stdin — unusable from a web UI. Use a custom `HumanFeedbackProvider` that raises
`HumanFeedbackPending`, then resume via `Flow.from_pending(flow_id)` + `flow.resume(feedback)`.

**Hierarchical costs more than sequential.** The manager re-reasons on every delegation. Always
pair it with an iteration cap and cheap models.

## Conventions

- YAML-first for agents and tasks; keep `crew.py` to wiring.
- Structured outputs (`output_pydantic`) for anything another step branches on — never parse
  prose to make a control-flow decision.
- Tests use stdlib `unittest` and must not require network or API keys.
- Conventional-commit style messages; explain *why* in the body, not just what.
