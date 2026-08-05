# Hierarchical + QA run — 2026-08-05

Output of the full `ProductFlow`: hierarchical crew (Engineering Lead as `manager_agent`),
independent QA Inspector, structured `QAReport`, bounded revision loop, human gate.

**Approved on the first iteration.** The revise branch never fired, so the build→QA→revise
loop is *not* exercised by this artifact — see "What this run does not prove" below.

## Cost

| Agent | Model | calls | in | out | USD |
|---|---|---|---|---|---|
| Frontend | `minimax-m3` | 38 | 698,325 | 31,160 | **0.2469** |
| Engineering Lead (manager) | `deepseek-v4-pro` | 23 | 352,998 | 39,241 | 0.1877 |
| QA Inspector | `deepseek-v4-pro` | 13 | 111,042 | 20,506 | 0.0661 |
| Backend | `deepseek-v4-flash-0731` | 19 | 115,298 | 10,783 | 0.0123 |
| Test | `deepseek-v4-flash-0731` | 9 | 43,965 | 12,943 | 0.0063 |
| **TOTAL** | | **102** | **1,321,628** | **114,633** | **0.5193** |

Against the sequential baseline of $0.2210, hierarchical + QA costs **2.35×**. That is the
price of the manager re-reasoning per delegation plus a fifth agent, and it was expected.
Still ~8× cheaper than the ~$4 original.

The manager line is the one to read: **$0.0292 sequential → $0.1877 hierarchical, a 6.4×
jump** on the same role. Sequential runs badly understate what a manager costs, which is
exactly why the model choice for that seat was re-decided on evidence rather than kept.

## Verification

The QA Inspector ran the tests itself rather than trusting the test engineer:

- 32 generated unit tests, **all passing** (20 executions observed across the run)
- All 9 original requirements checked off individually, including the three guardrails
- `app.py` imports and its Gradio `Blocks` constructs

32 sandbox executions total: 30 `[SUCCESS]`, 2 `[FAILED (exit code 1)]`. Those two failures
matter — before the phase 2 fix, a failing execution returned an empty string and the agent
had to guess. Here it got the exit code and the stderr traceback, recovered, and the next
execution succeeded.

## The severity design working

`qa_report.json` carries three findings, and **none of them blocked**:

| Severity | File | Finding |
|---|---|---|
| minor | `account_system.py` | `get_profit_loss()` formula differs from the design doc |
| minor | `test_account_system.py` | `get_total_withdrawals()` is untested |
| nit | `account_system.py` | docstring wording inconsistent with the requirement |

Only `blocker` and `major` fail a build. A pedantic inspector cannot trap the crew in a
rework loop over cosmetics, and `QAReport.verdict()` still recomputes the pass from the
findings rather than trusting the agent's own `passed` flag.

## What this run does not prove

- **The revise loop.** QA passed first time, so `revise` never fired live.
- **The human feedback round trip.** This was a CLI run, where pausing is disabled and
  `default_outcome="ship"` applies. `human_review → deliver` ran; the pause/resume path via
  `from_pending()` did not.
- **Racing.** Phase 7's supervisor is verified against synthetic results only.
