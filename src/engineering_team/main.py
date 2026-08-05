#!/usr/bin/env python
import sys
import warnings
from datetime import datetime

import engineering_team.patch  # noqa: F401 — applies CrewAI MCP monkey-patch on import
from engineering_team.crew import EngineeringTeam
from engineering_team.flows import ProductFlow, race
from engineering_team.model_config import models
from engineering_team.observability.recorder import CostListener, RunRecorder
from engineering_team.preflight import assert_ready
from .tools.sandbox_tools import SANDBOX_ROOT, Sandbox

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

requirements = """
A simple account management system for a trading simulation platform.
The system should allow users to create an account, deposit funds, and withdraw funds.
The system should allow users to record that they have bought or sold shares, providing a quantity.
The system should calculate the total value of the user's portfolio, and the profit or loss from the initial deposit.
The system should be able to report the holdings of the user at any point in time.
The system should be able to report the profit or loss of the user at any point in time.
The system should be able to list the transactions that the user has made over time.
The system should prevent the user from withdrawing funds that would leave them with a negative balance, or
 from buying more shares than they can afford, or selling shares that they don't have.
 The system has access to a function get_share_price(symbol) which returns the current price of a share, and includes a test implementation that returns fixed prices for AAPL, TSLA, GOOGL.
"""

def _announce() -> RunRecorder:
    """Fail before spending anything, then start cost accounting.

    A run whose sandbox cannot execute still costs full price while producing code
    nobody verified, so the preflight comes first.
    """
    assert_ready()

    print("\nModels:")
    for role, model in sorted(models().items()):
        print(f"  {role:20} {model}")

    recorder = RunRecorder()
    CostListener(recorder)
    return recorder


def _report(recorder: RunRecorder) -> None:
    # Event handlers run on a thread pool, so let in-flight events land before totalling.
    recorder.settle()
    print(recorder.summary())


def run():
    """Run the full product flow: build, inspect, revise until QA passes or the cap hits."""
    recorder = _announce()
    flow = ProductFlow()

    try:
        flow.kickoff(inputs={"requirements": requirements})
    except Exception as e:
        # Report what was already spent; a crash should not hide the cost.
        _report(recorder)
        raise Exception(f"An error occurred while running the flow: {e}")

    _report(recorder)

    state = flow.state
    print(f"\nSandbox: {SANDBOX_ROOT / state.run_id}")
    print(f"Iterations: {state.iteration} of {state.max_iterations}")
    for record in state.history:
        mark = "PASS" if record.passed else "FAIL"
        print(f"  [{mark}] iteration {record.iteration}: {record.summary}")
    if not state.approved:
        print("\nNot approved. Outstanding revision notes:")
        for note in state.revision_notes:
            print(f"  - {note}")


def run_race():
    """Race several independent attempts at the same requirements and rank them.

    Usage: `uv run race [variants]`. Cost scales with the number of variants, so it is
    an explicit argument rather than a default that surprises anyone.
    """
    variants = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    recorder = _announce()
    print(f"\nRacing {variants} variants — cost scales with this number.\n")

    try:
        outcome = race(requirements, variants=variants)
    except Exception as e:
        _report(recorder)
        raise Exception(f"An error occurred while racing: {e}")

    _report(recorder)
    print(outcome.summary())


def run_once():
    """Run the hierarchical crew a single time, with no outer review loop.

    Kept because it is the cheaper thing to run when the question is "does the crew
    still work", not "is the product good".
    """
    recorder = _announce()

    sandbox = Sandbox()
    print(f"Sandbox: {sandbox.root}")

    try:
        sandbox.reset()
        EngineeringTeam(sandbox=sandbox).crew().kickoff(
            inputs={
                "requirements": requirements,
                "revision_notes": "None - this is the first attempt.",
            }
        )
    except Exception as e:
        _report(recorder)
        raise Exception(f"An error occurred while running the crew: {e}")

    _report(recorder)


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        EngineeringTeam().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        EngineeringTeam().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }

    try:
        EngineeringTeam().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "topic": "",
        "current_year": ""
    }

    try:
        result = EngineeringTeam().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
