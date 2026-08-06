"""What this system can and cannot build.

One source of truth, shared by the agent prompts and the UI. These constraints were
previously stated in six places across two YAML files and nowhere the user could see
them, so someone could reasonably ask for a React dashboard and get a confusing failure
instead of an answer.
"""

from __future__ import annotations


# Rendered into the UI so the person typing requirements knows the shape of the answer
# before spending money on it.
CAPABILITIES_MD = """\
**What this team builds**

A single-page Python application: a backend module, a Gradio web UI for it, and unit
tests — written, executed and reviewed in an isolated sandbox.

| | |
|---|---|
| Language | Python only |
| UI | Gradio (a web page — not a desktop, mobile or terminal app) |
| Packages | any from PyPI; the crew installs what it needs |
| Tests | stdlib `unittest` |
| Layout | one flat directory, no sub-packages |
| Persistence | files in the sandbox (`sqlite3`, JSON) survive an app restart, but the sandbox itself is discarded when a new build starts |

**Not supported:** JavaScript/React or any non-Python stack, long-running servers or
background workers, real databases, calls to external services needing credentials, or
anything that must outlive the sandbox.

Ask for a self-contained tool, simulation, calculator, tracker or data model and it
works well. Ask for a production service and it will build a plausible-looking sketch
of one.
"""

# The same constraints in the register the agents need, interpolated into task
# descriptions so the prompts and the UI cannot drift apart.
CONSTRAINTS_PROMPT = """\
Environment and constraints:
- Python only. The deliverable is a backend module, a Gradio UI in app.py, and a unit
  test file, all in ONE flat directory. No sub-directories or packages.
- Third-party packages ARE available, but must be installed with the Add Sandbox Package
  tool BEFORE any code imports them, and the install result must be checked.
- Gradio is already installed. Use it for the UI; do not build a UI in any other stack.
- Tests use the standard library `unittest` module, not pytest.
- Nothing persists beyond the run: no databases, no external services, no credentials.
  Where the requirements imply stored data, hold it in memory.
- Nothing may block: no servers, no `.launch()` in code that gets executed, no `input()`,
  no infinite loops. Anything that blocks will be killed and reported as a failure.

File discipline — the deliverable is exactly these files, and no others:
- one backend module, `app.py` for the Gradio UI, one test file, and `_validate.py`
  which imports app.py and checks the Blocks constructs.
- `app.py` must expose the Blocks object as a module-level `demo`, and end with
  `if __name__ == "__main__": demo.launch()`. The guard is what keeps it safe: importing
  the module (as `_validate.py` does) never starts a server, while running the file
  directly does. Never call `.launch()` at import time.
- Do NOT create extra scratch or verification scripts. If you need to check something,
  put the check in the existing test file and run that, or overwrite `_validate.py`.
  Files named like `_check.py`, `_check2.py`, `_runner.py`, `manual_check.py` or
  `edge_cases.py` are a sign of going in circles — write the assertion into the test
  file instead, where it stays useful.
- Reuse the same filenames. Two files testing the same module means neither is the
  test suite.
- When the tests pass and the UI validates, you are done. Stop and report; do not keep
  looking for more things to verify.
"""
