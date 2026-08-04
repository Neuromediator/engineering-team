# Example output — Trading Simulation Account Manager

Artifacts from a successful run of the **original sequential crew** (crewAI 1.14.4), preserved
as a baseline before the rewrite. The agent sandbox is wiped on every run, so this is a snapshot
rather than live output.

| File | Author agent | Model |
|---|---|---|
| `design.md` | engineering_lead | `openai/gpt-5.5` |
| `backend.py`, `prices.py` | backend_engineer | `openrouter/google/gemini-3.1-pro-preview` |
| `app.py`, `_validate.py` | frontend_engineer | `openrouter/anthropic/claude-opus-4-7` |
| `test_backend.py`, `test_summary.md` | test_engineer | `openai/gpt-5.4-mini` |

Approximate cost of this single run: **~$4**, dominated by `gpt-5.5` at $5/M input and
$30/M output against a 2,500-line design document.

## Known defects in this baseline

Worth keeping visible, because they motivate the rewrite:

1. **`test_summary.md` contains raw test source, not a summary.** The task declared
   `output_file: sandbox/test_summary.md` and asked for "a summary of the results of the unit
   tests"; the agent wrote the test file's contents there instead. Nothing in the sequential
   pipeline inspects task output against its `expected_output`, so the mistake shipped silently.
   This is precisely what the new QA Inspector role and `output_pydantic` structured outputs
   are meant to catch.

2. **No verification that the design was actually followed.** The design specifies
   `get_holdings_report`, `get_transaction_report` and `get_account_summary`; nothing in the
   pipeline confirms they exist with the specified signatures.
