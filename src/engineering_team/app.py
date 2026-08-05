"""Gradio front end for the engineering team.

Requirements go in at the top, the crew's activity streams in the middle, and the cost
panel updates live while it runs. When the automatic loop settles, the flow pauses and
asks whether to ship or revise.

Run locally::

    uv run serve
"""

from __future__ import annotations

import engineering_team.patch  # noqa: F401 — applies the CrewAI MCP monkey-patch

import gradio as gr

from engineering_team.capabilities import CAPABILITIES_MD
from engineering_team.model_config import models, price_for
from engineering_team.preflight import run_all
from engineering_team.ui.session import RunSession


PLACEHOLDER = (
    "Describe what you want built, in plain English.\n\n"
    "Be specific about the rules that matter — what must be prevented, what should be "
    "reported, what the edge cases are. The team builds what you describe, so vague "
    "requirements produce a vague product."
)

# Offered behind a button rather than pre-filled. Pre-filling made the page look like a
# demo of one fixed thing, and invited people to click Build on requirements they had
# not read — which costs real money.
EXAMPLE_REQUIREMENTS = """\
A simple account management system for a trading simulation platform.
The system should allow users to create an account, deposit funds, and withdraw funds.
The system should allow users to record that they have bought or sold shares, providing a quantity.
The system should calculate the total value of the user's portfolio, and the profit or loss from the initial deposit.
The system should be able to report the holdings of the user at any point in time.
The system should be able to report the profit or loss of the user at any point in time.
The system should be able to list the transactions that the user has made over time.
The system should prevent the user from withdrawing funds that would leave them with a negative balance, or
from buying more shares than they can afford, or selling shares that they don't have.
The system has access to a function get_share_price(symbol) which returns the current price of a share,
and includes a test implementation that returns fixed prices for AAPL, TSLA, GOOGL.
"""

POLL_SECONDS = 2.0

STATUS_LABEL = {
    "idle": "Idle",
    "running": "Running",
    "awaiting_feedback": "Waiting for your feedback",
    "finished": "Finished",
    "failed": "Failed",
}


# Gradio 6 moved `css` off the Blocks constructor onto launch(), same as `theme`.
CSS = """
/* Long model slugs and role names were being broken mid-word in narrow columns
   ("backend_eng/ineer"), which is unreadable. Let wide content scroll instead. */
.md table { table-layout: auto; }
.md td, .md th { word-break: normal; overflow-wrap: normal; hyphens: none; }
.md code { white-space: nowrap; font-size: 0.85em; }
#activity_log, #cost_panel, #models_panel { overflow-x: auto; }
"""


def _short(model: str) -> str:
    """Drop the routing prefix. Every model goes through OpenRouter, so it is noise."""
    return model.removeprefix("openrouter/")


def _model_table() -> str:
    rows = ["| Role | Model | $/M in | $/M out |", "|---|---|---:|---:|"]
    for role, model in sorted(models().items()):
        price = price_for(model)
        rows.append(
            f"| {role.replace('_', ' ')} | `{_short(model)}` | "
            f"{price.input if price else '?'} | {price.output if price else '?'} |"
        )
    return "\n".join(rows)


def _cost_table(snapshot: dict) -> str:
    by_agent = snapshot["by_agent"]
    if not by_agent:
        return "_No LLM calls yet._"

    rows = ["| Agent | Calls | In | Out | USD |", "|---|--:|--:|--:|--:|"]
    for name, totals in sorted(
        by_agent.items(), key=lambda kv: kv[1].cost, reverse=True
    ):
        rows.append(
            f"| {name[:38]} | {totals.calls} | {totals.prompt_tokens:,} | "
            f"{totals.completion_tokens:,} | ${totals.cost:.4f} |"
        )
    rows.append(f"| **TOTAL** | | | | **${snapshot['cost']:.4f}** |")
    return "\n".join(rows)


def _progress(snapshot: dict) -> str:
    state = snapshot["state"]
    if state is None:
        return "_Not started._"

    lines = [
        f"**Iteration {state.iteration} of {state.max_iterations}**",
        f"Sandbox: `sandbox/{state.run_id}`" if state.run_id else "",
        "",
    ]
    for record in state.history:
        mark = "✅" if record.passed else "❌"
        lines.append(
            f"{mark} **Iteration {record.iteration}** — "
            f"{record.blocking_findings} blocking, "
            f"tests {'passed' if record.tests_passed else 'not passing'}"
        )
        lines.append(f"   {record.summary}")

    if state.revision_notes:
        lines += ["", "**Outstanding notes**"]
        lines += [f"- {note}" for note in state.revision_notes[-12:]]

    return "\n".join(lines)


def _qa_findings(snapshot: dict) -> str:
    state = snapshot["state"]
    report = getattr(state, "qa_report", None) if state else None
    if report is None:
        return "_No QA report yet._"

    lines = [
        f"**Verdict: {'PASS' if report.verdict() else 'FAIL'}** — "
        f"tests {'ran' if report.tests_run else 'never ran'}, "
        f"{'all passed' if report.tests_passed else 'not all passing'}",
        "",
        report.summary,
    ]
    if report.findings:
        lines += ["", "| Severity | File | Finding |", "|---|---|---|"]
        for finding in report.findings:
            lines.append(
                f"| {finding.severity.value} | `{finding.file}` | {finding.summary} |"
            )
    return "\n".join(lines)


def build_ui() -> gr.Blocks:
    session = RunSession()

    def refresh():
        snapshot = session.snapshot()
        status = snapshot["status"]
        awaiting = status == "awaiting_feedback"

        header = f"### {STATUS_LABEL.get(status, status)}"
        if snapshot["error"]:
            header += "\n\n```\n" + snapshot["error"][-1500:] + "\n```"

        return (
            header,
            snapshot["log"] or "_Nothing yet._",
            _cost_table(snapshot),
            _progress(snapshot),
            _qa_findings(snapshot),
            gr.update(visible=awaiting, label=snapshot["question"] or "Your feedback"),
            gr.update(visible=awaiting),
            gr.update(interactive=status not in {"running", "awaiting_feedback"}),
        )

    def start(requirements: str):
        if not requirements.strip():
            gr.Warning("Describe what you want built first.")
            return refresh()
        failures = [check for check in run_all() if not check.ok]
        if failures:
            # Same reasoning as the CLI preflight: a run whose sandbox cannot execute
            # still costs full price while producing code nobody verified.
            gr.Warning("Preflight failed: " + "; ".join(c.detail for c in failures))
            return refresh()
        session.start(requirements)
        return refresh()

    def send_feedback(feedback: str):
        session.submit_feedback(feedback or "")
        return refresh()

    # Gradio 6 moved `theme` off the Blocks constructor onto launch().
    with gr.Blocks(title="Engineering Team") as demo:
        gr.Markdown(
            "# Engineering Team\n"
            "A hierarchical CrewAI crew that designs, builds, tests and inspects a "
            "product from plain-English requirements — with a bounded revision loop "
            "and a human gate before it ships."
        )

        # Reference material spans the full width and starts closed: in a narrow column
        # its tables wrapped mid-word, and open by default it pushed the input offscreen.
        with gr.Accordion("What this team can build — worth reading first", open=False):
            gr.Markdown(CAPABILITIES_MD, elem_id="capabilities_panel")

        with gr.Row():
            with gr.Column(scale=3):
                requirements = gr.Textbox(
                    label="Requirements",
                    placeholder=PLACEHOLDER,
                    lines=12,
                )
                with gr.Row():
                    run_button = gr.Button("Build it", variant="primary", scale=2)
                    example_button = gr.Button("Load example", scale=1)
                gr.Markdown(
                    "_A full build costs roughly **$0.50** and takes several minutes. "
                    "Asking for changes afterwards starts another one._"
                )

            with gr.Column(scale=2):
                status_box = gr.Markdown("### Idle")
                gr.Markdown("### Cost")
                cost_box = gr.Markdown("_No LLM calls yet._", elem_id="cost_panel")

        with gr.Accordion("Models and pricing", open=False):
            gr.Markdown(_model_table(), elem_id="models_panel")

        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### Activity")
                log_box = gr.Code(
                    label="", language=None, lines=20, elem_id="activity_log"
                )
            with gr.Column(scale=2):
                gr.Markdown("### Progress")
                progress_box = gr.Markdown("_Not started._")
                gr.Markdown("### QA report")
                qa_box = gr.Markdown("_No QA report yet._", elem_id="qa_panel")

        feedback_box = gr.Textbox(
            label="Your feedback", lines=3, visible=False,
            placeholder="Say what to change, or that it looks good.",
        )
        feedback_button = gr.Button("Send feedback", variant="primary", visible=False)

        outputs = [
            status_box, log_box, cost_box, progress_box, qa_box,
            feedback_box, feedback_button, run_button,
        ]

        run_button.click(start, inputs=requirements, outputs=outputs)
        feedback_button.click(send_feedback, inputs=feedback_box, outputs=outputs)
        example_button.click(lambda: EXAMPLE_REQUIREMENTS, outputs=requirements)

        # The flow runs on a background thread; this is how its progress reaches the page.
        gr.Timer(POLL_SECONDS).tick(refresh, outputs=outputs)

    return demo


def main() -> None:
    build_ui().launch(theme=gr.themes.Soft(), css=CSS)


if __name__ == "__main__":
    main()
