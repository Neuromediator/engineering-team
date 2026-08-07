"""Intake check: is this brief worth a build, and should it be built at all?

Runs before anything is created — before the sandbox, which on E2B means before a
microVM boots and pip-installs gradio. One call on the cheapest model, a few seconds and
a fraction of a cent against a run that costs $0.20 and takes 25 minutes.

Two verdicts, treated differently on purpose:

* ``buildable`` is **advisory**. A terse brief is still a brief, and the person clicking
  the button is the one paying, so a wrong "no" here must never be a dead end — the UI
  offers to build anyway. This is also the failure a cheap model is most likely to make.
* ``permitted`` is **binding**. It says no only where the evident purpose is harm. That
  mistake is rarer, and its cost lands on the owner's credit and account rather than on
  the person typing.

This does not contradict the rule against parsing prose for control flow. That rule came
from asking a model to infer something the interface already knew — the human had clicked
a button. Here free text is the only signal there is, and a model is the only thing that
can read it. What keeps the discipline is that nothing branches on the sentence: the
model returns :class:`BriefVerdict` and the code reads two booleans, exactly as the
router reads :meth:`QAReport.verdict`.
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from .model_config import llm_for
from .schemas import BriefVerdict


# Bounds on a step that must be cheap to be worth having. One pass, no tools, no
# delegation: it reads two sentences and returns two booleans.
REVIEWER_MAX_ITER = 3
REVIEWER_TIME_LIMIT = 90

# Long enough that nobody types a real brief under it, short enough that "hi" and "my
# name is Bob" never reach a model at all. Checked first because it is free.
MIN_BRIEF_CHARS = 15


def _accept(reason: str = "") -> BriefVerdict:
    return BriefVerdict(buildable=True, permitted=True, reason=reason)


def review_brief(requirements: str, config_dir=None) -> BriefVerdict:
    """Judge a typed brief. Never raises, and fails open.

    A triage step that can block a build by breaking is worse than no triage step: the
    person is left unable to spend their own money because a $0.0001 call timed out. Any
    failure therefore returns "buildable and permitted" and lets the run proceed — the
    budget ceiling and the passphrase are the bounds that actually hold.
    """
    text = (requirements or "").strip()

    if len(text) < MIN_BRIEF_CHARS:
        return BriefVerdict(
            buildable=False,
            permitted=True,
            reason="That is too short to build from.",
            suggestion=(
                "Describe what the tool should do and what rules matter — for example: "
                '"A tool to split shared costs in a group. Track who paid what, show '
                'each person\'s balance, and never let the balances drift from zero."'
            ),
        )

    try:
        return _run_reviewer(text)
    except Exception as exc:  # noqa: BLE001 - triage must never block a build
        print(f"Brief triage did not complete ({exc}); allowing the build.")
        return _accept()


def _run_reviewer(requirements: str) -> BriefVerdict:
    """One agent, one task, one structured answer."""
    # Read from the same YAML the crew uses, so agents.yaml and tasks.yaml stay the
    # single source for every role, this one included. Deliberately not built through
    # EngineeringTeam: that class wires a sandbox and five agents, and this step must
    # not create a workspace it has not yet decided is worth creating.
    agents_config, tasks_config = _load_config()

    reviewer = Agent(
        config=agents_config["brief_reviewer"],
        llm=llm_for("brief_reviewer"),
        verbose=False,
        allow_delegation=False,
        max_iter=REVIEWER_MAX_ITER,
        max_execution_time=REVIEWER_TIME_LIMIT,
    )
    task = Task(
        config=tasks_config["triage_task"],
        agent=reviewer,
        output_pydantic=BriefVerdict,
    )
    result = Crew(
        agents=[reviewer],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    ).kickoff(inputs={"requirements": requirements})

    verdict = getattr(result, "pydantic", None)
    if isinstance(verdict, BriefVerdict):
        return verdict
    # No structured answer means the check did not happen. Fail open, as above.
    return _accept()


def _load_config() -> tuple[dict, dict]:
    """Read the same YAML the crew uses, without constructing a crew."""
    from pathlib import Path

    import yaml

    config = Path(__file__).parent / "config"
    agents = yaml.safe_load((config / "agents.yaml").read_text(encoding="utf-8"))
    tasks = yaml.safe_load((config / "tasks.yaml").read_text(encoding="utf-8"))
    return agents, tasks
