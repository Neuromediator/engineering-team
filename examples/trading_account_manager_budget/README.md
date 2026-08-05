# Budget-profile run — 2026-08-05

Output of the unchanged sequential crew running the reference trading-account requirements
on `MODEL_PROFILE=budget`. Preserved because `sandbox/` is wiped on every run.

This is the **cost-reduction baseline**: same crew, same requirements, same prompts as the
original `examples/trading_account_manager/` run — only the models differ.

## Cost

| Agent | Model | calls | in | out | USD |
|---|---|---|---|---|---|
| Frontend | `moonshotai/kimi-k2.6` | 9 | 170,937 | 20,072 | **0.1505** |
| Engineering Lead | `z-ai/glm-5.2` | 5 | 16,714 | 6,797 | 0.0292 |
| Backend | `deepseek/deepseek-v4-flash-0731` | 14 | 227,851 | 21,275 | 0.0243 |
| Test | `deepseek/deepseek-v4-flash-0731` | 9 | 179,244 | 5,018 | 0.0170 |
| **TOTAL** | | **37** | **594,746** | **53,162** | **0.2210** |

**~18× cheaper than the ~$4 `premium` baseline.** Figures come from the event-bus recorder
(`observability/recorder.py`), priced from `config/models.yaml`.

## Verification

- `test_account.py` — **51/51 pass** (re-run independently in `python:3.12-slim`, not just
  taken from the agent's own report).
- `app.py` — compiles; `_validate.py` confirms `app.demo` is a `gradio.Blocks` that builds.

Worth noting what that second line does *not* cover: `_validate.py` only proves the UI
constructs, not that any of its 11 handlers behave. The most expensive artifact in the run is
also the least verified — which is the case for the QA Inspector role in Phase 3.

## What this run showed

The frontend agent is **68% of total spend**, while the backend engineer processed *more*
input tokens for one sixth the cost. The reasoning behind giving frontend the expensive model
(least verifiable output) did not survive measurement. See `PLAN.md` for the full account and
the follow-up experiment.
