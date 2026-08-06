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

from engineering_team import budget
from engineering_team.capabilities import CAPABILITIES_MD
from engineering_team.crew import VALID_PROCESSES, process_name
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
    "running": "Building",
    "awaiting_feedback": "Waiting for your feedback",
    "finished": "Finished",
    "failed": "Failed",
}

# Maps a status to the pill's CSS modifier.
STATUS_CLASS = {
    "idle": "idle",
    "running": "running",
    "awaiting_feedback": "awaiting",
    "finished": "finished",
    "failed": "failed",
}


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _status_html(status: str, error: str) -> str:
    """Render the status as a coloured pill, plus the traceback when one exists."""
    label = STATUS_LABEL.get(status, status)
    modifier = STATUS_CLASS.get(status, "idle")
    html = f'<span class="pill {modifier}"><span class="dot"></span>{label}</span>'
    if error:
        # Escaped: this is a traceback, and it must never be able to inject markup.
        html += f"<pre>{_escape(error[-2000:])}</pre>"
    return html


# The palette the frontend_engineer is told to use for the apps it builds
# (config/agents.yaml). Reusing it here means the orchestrator wears the same colours it
# asks its agents to wear.
AMBER = "#ecad0a"
BLUE = "#209dd7"
PURPLE = "#753991"

_BLUE_HUE = gr.themes.Color(
    c50="#e8f6fd", c100="#c5e9f8", c200="#9ed9f3", c300="#72c8ee",
    c400="#4bb8e9", c500=BLUE, c600="#1b86b8", c700="#166d95",
    c800="#115572", c900="#0c3c50", c950="#07242f",
)


def _theme() -> gr.themes.Base:
    """A restrained instrument-panel look: technical, dense, not decorated.

    Built from theme tokens rather than CSS overrides wherever possible, so light and
    dark mode both stay coherent without maintaining two stylesheets.
    """
    return gr.themes.Base(
        primary_hue=_BLUE_HUE,
        neutral_hue="slate",
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
        radius_size=gr.themes.sizes.radius_sm,
        spacing_size=gr.themes.sizes.spacing_md,
    ).set(
        block_border_width="1px",
        block_shadow="none",
        block_label_text_weight="600",
        button_primary_background_fill=f"linear-gradient(90deg, {BLUE}, {PURPLE})",
        button_primary_background_fill_hover=f"linear-gradient(90deg, {PURPLE}, {BLUE})",
        button_primary_text_color="#ffffff",
        input_border_width="1px",
    )


# Gradio 6 moved `css` off the Blocks constructor onto launch(), same as `theme`.
# Everything here uses Gradio's own CSS variables so it follows light/dark automatically.
CSS = f"""
/* Long model slugs and role names were being broken mid-word in narrow columns
   ("backend_eng/ineer"), which is unreadable. Let wide content scroll instead. */
.md table {{ table-layout: auto; border-collapse: collapse; width: 100%; }}
.md td, .md th {{ word-break: normal; overflow-wrap: normal; hyphens: none; }}
.md code {{ white-space: nowrap; font-size: 0.85em; }}
#activity_log, #cost_panel, #models_panel, #qa_panel {{ overflow-x: auto; }}

/* Tables read as data, not prose: quiet rules, right-aligned numbers, zebra rows. */
.md th {{
  text-align: left;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  opacity: 0.7;
  border-bottom: 1px solid var(--border-color-primary);
  padding: 6px 10px;
}}
.md td {{ padding: 6px 10px; border-bottom: 1px solid var(--border-color-primary); }}
.md tbody tr:nth-child(even) {{ background: var(--background-fill-secondary); }}
.md tbody tr:last-child td {{ font-weight: 600; }}

/* Masthead */
#masthead {{
  border-left: 3px solid {BLUE};
  padding: 2px 0 2px 14px;
  margin-bottom: 4px;
}}
#masthead h1 {{ margin: 0 0 4px 0; font-size: 1.45rem; letter-spacing: -0.01em; }}
#masthead p {{ margin: 0; opacity: 0.75; font-size: 0.93rem; max-width: 62ch; }}

/* Status pill: the one thing that must be readable from across the room. */
.pill {{
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 999px;
  font-weight: 600; font-size: 0.9rem;
  border: 1px solid currentColor;
}}
.pill .dot {{
  width: 8px; height: 8px; border-radius: 50%;
  background: currentColor;
}}
.pill.running .dot {{ animation: pulse 1.2s ease-in-out infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.25; }} }}
.pill.idle {{ color: var(--body-text-color-subdued); }}
.pill.running {{ color: {BLUE}; }}
.pill.awaiting {{ color: {AMBER}; }}
.pill.finished {{ color: #2e9e6b; }}
.pill.failed {{ color: #d4483b; }}

#status_panel pre {{
  margin-top: 10px; padding: 10px; border-radius: 6px;
  background: var(--background-fill-secondary);
  border: 1px solid var(--border-color-primary);
  font-size: 0.78rem; max-height: 220px; overflow: auto; white-space: pre-wrap;
}}

/* Activity log: dense, monospace, no syntax-highlight noise. */
#activity_log .cm-editor {{ font-size: 0.8rem; line-height: 1.45; }}

/* The cost figure is the number people actually watch. */
#cost_panel table tbody tr:last-child {{ color: {AMBER}; }}
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

    # "(unattributed)" means the event bus reported an LLM call with no agent_role —
    # a call CrewAI made outside an agent's execution. Naming the model makes it
    # identifiable instead of mysterious.
    unattributed = snapshot.get("unattributed_models") or []
    if unattributed:
        rows.append("")
        rows.append(
            "_(unattributed) = a call CrewAI made outside any agent: "
            + ", ".join(f"`{_short(m)}`" for m in sorted(unattributed))
            + "_"
        )
    return "\n".join(rows)


def _progress(snapshot: dict) -> str:
    state = snapshot["state"]
    if state is None:
        return "_Not started._"

    lines = [
        f"**Iteration {state.iteration} of {state.max_iterations}** "
        f"· {state.process or process_name()}",
        f"Sandbox: `sandbox/{state.run_id}`" if state.run_id else "",
        "",
    ]
    for record in state.history:
        crashed = record.summary.startswith("The build did not complete")
        mark = "⚠️" if crashed else ("✅" if record.passed else "❌")
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
        if snapshot["status"] == "running":
            return (
                "_The inspector reports once it has read the sandbox and run the tests "
                "itself — so this stays empty until the build is complete._"
            )
        return "_No QA report yet._"

    stale = getattr(state, "last_iteration_failed", False)
    from_iteration = getattr(state, "qa_report_iteration", 0)
    lines = []
    if stale:
        lines += [
            f"> ⚠️ **This report is from iteration {from_iteration}.** The most recent "
            f"attempt failed before QA could run — see Progress for the reason.",
            "",
        ]
    lines += [
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
    # One RunSession per browser session, held in gr.State. A module-level session
    # would be shared by every visitor: one person pressing "Build it" would discard
    # another's finished results and overwrite their cost table.
    def _ensure(session: RunSession | None) -> RunSession:
        return session if session is not None else RunSession()

    def refresh(session: RunSession | None):
        session = _ensure(session)
        snapshot = session.snapshot()
        status = snapshot["status"]
        awaiting = status == "awaiting_feedback"
        state = snapshot["state"]
        archive = getattr(state, "archive_path", "") or None

        return (
            _status_html(status, snapshot["error"]),
            snapshot["log"] or "_Nothing yet._",
            _cost_table(snapshot),
            _progress(snapshot),
            _qa_findings(snapshot),
            gr.update(visible=awaiting, label=snapshot["question"] or "Your feedback"),
            gr.update(visible=awaiting),
            gr.update(visible=awaiting),
            gr.update(interactive=status not in {"running", "awaiting_feedback"}),
            f"_{budget.status_line()}_",
            gr.update(value=archive, visible=bool(archive)),
            session,
        )

    def start(requirements: str, process: str, session: RunSession | None):
        session = _ensure(session)
        if not requirements.strip():
            gr.Warning("Describe what you want built first.")
            return refresh(session)
        failures = [check for check in run_all() if not check.ok]
        if failures:
            # Same reasoning as the CLI preflight: a run whose sandbox cannot execute
            # still costs full price while producing code nobody verified.
            gr.Warning("Preflight failed: " + "; ".join(c.detail for c in failures))
            return refresh(session)
        session.start(requirements, process)
        if session.snapshot()["notice"]:
            gr.Warning(session.snapshot()["notice"])
        return refresh(session)

    def request_changes(feedback: str, session: RunSession | None):
        session = _ensure(session)
        if not (feedback or "").strip():
            gr.Warning("Describe what you want changed, then request changes.")
            return refresh(session)
        session.submit_feedback(feedback, approve=False)
        return refresh(session)

    def approve_and_ship(feedback: str, session: RunSession | None):
        session = _ensure(session)
        session.submit_feedback(feedback or "", approve=True)
        return refresh(session)

    # Gradio 6 moved `theme` off the Blocks constructor onto launch().
    with gr.Blocks(title="Engineering Team") as demo:
        session_state = gr.State(None)
        gr.HTML(
            "<div id='masthead'>"
            "<h1>Engineering Team</h1>"
            "<p>A CrewAI crew that designs, builds, tests and <em>independently "
            "inspects</em> a Python product from plain-English requirements — with a "
            "bounded revision loop and a human gate before it ships. The delegation "
            "model is yours to choose below; the measured difference is the point.</p>"
            "</div>"
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
                process_choice = gr.Radio(
                    choices=list(VALID_PROCESSES),
                    value=process_name(),
                    label="Delegation model",
                    info=(
                        "sequential: a fixed pipeline, 37 LLM calls, ~$0.22. "
                        "hierarchical: the Engineering Lead manages and delegates, "
                        "102 calls, ~$0.52. Same product for a pipeline this "
                        "predictable — which is the finding."
                    ),
                )
                with gr.Row():
                    run_button = gr.Button("Build it", variant="primary", scale=2)
                    example_button = gr.Button("Load example", scale=1)
                    clear_button = gr.Button("Clear", scale=1)
                gr.Markdown(
                    "_Measured: **$0.22 / ~10 min** sequential, **$0.52 / ~30 min** hierarchical. "
                    "Asking for changes afterwards starts another build._"
                )

            with gr.Column(scale=2):
                status_box = gr.HTML(
                    _status_html("idle", ""), elem_id="status_panel"
                )
                gr.Markdown("### Cost")
                cost_box = gr.Markdown("_No LLM calls yet._", elem_id="cost_panel")
                budget_box = gr.Markdown(f"_{budget.status_line()}_")

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
                download_box = gr.File(
                    label="Finished source", visible=False, interactive=False
                )
                gr.Markdown(
                    "_Download it while you are here — the files are deleted when you "
                    "reload the page or start another build._"
                )

        feedback_box = gr.Textbox(
            label="Your feedback", lines=3, visible=False,
            placeholder="Describe what you want changed.",
        )
        # Two buttons, not one. The decision is the person's, so the interface records
        # it directly — an earlier version sent one free-text answer and asked an LLM to
        # infer intent, which shipped a build whose feedback plainly asked for changes.
        with gr.Row():
            revise_button = gr.Button(
                "Request changes", variant="primary", visible=False
            )
            ship_button = gr.Button("Approve & ship", visible=False)

        outputs = [
            status_box, log_box, cost_box, progress_box, qa_box,
            feedback_box, revise_button, ship_button, run_button, budget_box,
            download_box, session_state,
        ]

        run_button.click(
            start, inputs=[requirements, process_choice, session_state], outputs=outputs
        )
        revise_button.click(
            request_changes, inputs=[feedback_box, session_state], outputs=outputs
        )
        ship_button.click(
            approve_and_ship, inputs=[feedback_box, session_state], outputs=outputs
        )
        example_button.click(lambda: EXAMPLE_REQUIREMENTS, outputs=requirements)
        clear_button.click(lambda: "", outputs=requirements)

        # The flow runs on a background thread; this is how its progress reaches the page.
        gr.Timer(POLL_SECONDS).tick(
            refresh, inputs=session_state, outputs=outputs
        )

        def on_page_load(session: RunSession | None):
            # A reload ends this visitor's previous result; a run in flight is left
            # alone, and other visitors are untouched.
            session = _ensure(session)
            session.discard()
            return refresh(session)

        demo.load(on_page_load, inputs=session_state, outputs=outputs)

    return demo


def main() -> None:
    build_ui().launch(theme=_theme(), css=CSS)


if __name__ == "__main__":
    main()
