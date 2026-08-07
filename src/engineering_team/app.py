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

from engineering_team import budget, demo
from engineering_team.capabilities import CAPABILITIES_MD
from engineering_team.crew import VALID_PROCESSES, process_name
from engineering_team.model_config import models, price_for
from engineering_team.preflight import run_all
from engineering_team.triage import review_brief
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
    "cancelled": "Stopped — you left the page",
}

# Maps a status to the pill's CSS modifier.
STATUS_CLASS = {
    "idle": "idle",
    "running": "running",
    "awaiting_feedback": "awaiting",
    "finished": "finished",
    "failed": "failed",
    # Reuses the idle colour on purpose: nothing went wrong, the run was
    # abandoned, and a red pill would read as a defect in the system.
    "cancelled": "idle",
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
/* gr.Timer is a real component in Gradio 6 and renders as a number stepper. It is pure
   plumbing — it polls the background run — so it has no business being on the page,
   where it showed up as a pair of arrows flickering every couple of seconds. */
#poll_timer {{ display: none !important; }}

/* Why a build did not start. Amber rather than red: none of these is a fault, they are
   all things the person can fix in a few seconds — and it must be impossible to miss,
   which the gr.Warning toast it replaced very much was not. */
#gate_notice {{
  border-left: 3px solid {AMBER};
  background: var(--background-fill-secondary);
  padding: 10px 14px;
  border-radius: 4px;
  margin-top: 4px;
}}
#gate_notice p {{ margin: 0 0 6px 0; }}
#gate_notice p:last-child {{ margin-bottom: 0; }}

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

    def _demo_view(session: RunSession, data: dict, with_requirements: bool):
        """Render the packaged example run.

        Shared by the button and the poll timer. The timer writes to these same
        components every couple of seconds, so if it did not know about this view it
        would immediately overwrite it with the visitor's own (empty) session — which
        is exactly what it used to do.

        ``with_requirements`` is False on a timer tick: re-sending the value would
        overwrite anything the visitor has since typed into the box, the same reason
        :func:`refresh` never sends one.
        """
        return (
            _status_html("finished", ""),
            demo.activity_log(),
            demo.cost_table(),
            demo.progress(),
            demo.qa_findings(),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(interactive=True),
            f"_{budget.status_line()}_",
            gr.update(value=demo.archive(), visible=bool(demo.archive())),
            gr.update(value=data["requirements"], interactive=True)
            if with_requirements
            else gr.update(interactive=True),
            session,
        )

    def refresh(session: RunSession | None):
        session = _ensure(session)
        snapshot = session.snapshot()

        # A visitor reading the packaged run has no run of their own; rendering this
        # session's empty state over it is what made the example vanish a second after
        # they asked for it.
        if snapshot["showing_demo"]:
            data = demo.load()
            if data:
                return _demo_view(session, data, with_requirements=False)

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
            # In-flight spend included, so this line and the cost table above it cannot
            # disagree about the same money while a build is running.
            f"_{budget.status_line(snapshot['unbanked'])}_",
            gr.update(
                value=archive,
                visible=bool(archive),
                # At the gate the build is the thing being judged, not a finished
                # article; calling it "Finished source" there would tell the reviewer the
                # decision was already made.
                label=(
                    "Source under review — download it before you decide"
                    if awaiting
                    else "Finished source"
                ),
            ),
            # No `value`: sending one would overwrite whatever the visitor is typing on
            # the next poll. Only the lock state changes.
            gr.update(interactive=status not in {"running", "awaiting_feedback"}),
            session,
        )

    # The gate panel is not part of the shared outputs tuple. Only the handlers that
    # raise and clear it touch it, so the poll timer leaves a message alone instead of
    # wiping it two seconds after it appears.
    _GATE_CLEAR = (gr.update(value="", visible=False), gr.update(visible=False))

    def _blocked(message: str, offer_override: bool = False) -> tuple:
        """Say why the build did not start, and leave it said."""
        return (
            gr.update(value=message, visible=True),
            gr.update(visible=offer_override),
        )

    def start(requirements: str, process: str, key: str, session: RunSession | None):
        """Checks that must pass before anything is created, cheapest first."""
        session = _ensure(session)

        allowed, why = budget.passphrase_ok(key)
        if not allowed:
            # Named explicitly. "Nothing happened" after pressing Build is the same
            # experience whether the key is wrong, the box is empty or preflight failed,
            # and leaving someone to guess between those is how a working deployment
            # looks broken.
            message = (
                "**That build key is not right.** Check it and try again — tick "
                '"Show key" if you want to see what you typed.'
                if (key or "").strip()
                else f"**A build key is needed to start a live build here.**\n\n{why}"
            )
            return (*_blocked(message), *refresh(session))

        if not requirements.strip():
            return (
                *_blocked("**Describe what you want built first.** The box above is empty."),
                *refresh(session),
            )

        # Intake triage runs before preflight and before the sandbox: on E2B the sandbox
        # means a microVM boot and a pip install, which is a lot to spend on "how are
        # you". Two verdicts, treated differently — see triage.py for why.
        verdict = review_brief(requirements)
        if not verdict.permitted:
            return (
                *_blocked(
                    "**Not something this system will build.**\n\n"
                    + (verdict.reason or "")
                ),
                *refresh(session),
            )
        if not verdict.buildable:
            # Advisory only. The person clicking is the one paying, and a wrong "no"
            # here must not be a dead end, so the panel offers to build anyway.
            body = f"**{verdict.reason}**"
            if verdict.suggestion:
                body += f"\n\n{verdict.suggestion}"
            return (*_blocked(body, offer_override=True), *refresh(session))

        return _attempt(requirements, process, session)

    def _attempt(requirements: str, process: str, session: RunSession) -> tuple:
        """Preflight, then hand off. Reports a refusal in the panel, not a toast."""
        failures = [check for check in run_all() if not check.ok]
        if failures:
            # Same reasoning as the CLI preflight: a run whose sandbox cannot execute
            # still costs full price while producing code nobody verified. The specific
            # check is named, because "preflight failed" alone is unactionable.
            detail = "\n".join(f"- `{c.name}`: {c.detail}" for c in failures)
            return (
                *_blocked(f"**The environment is not ready to build.**\n\n{detail}"),
                *refresh(session),
            )

        session.start(requirements, process)
        notice = session.snapshot()["notice"]
        if notice:
            return (*_blocked(f"**{notice}**"), *refresh(session))
        return (*_GATE_CLEAR, *refresh(session))

    def build_anyway(requirements: str, process: str, session: RunSession | None):
        """The override. Triage said no, the person said yes, and they are paying."""
        return _attempt(requirements, process, _ensure(session))

    def show_demo(session: RunSession | None):
        """Render a real completed run without spending anything."""
        data = demo.load()
        session = _ensure(session)
        if not data:
            gr.Warning("No example is packaged with this build.")
            return refresh(session)
        # Recorded on the session so the poll timer redraws this view instead of
        # replacing it. Cleared as soon as the visitor starts work of their own.
        session.showing_demo = True
        return _demo_view(session, data, with_requirements=True)

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
    # NOT named `demo`: that would shadow the engineering_team.demo module inside
    # every handler defined in this scope, and `demo.load()` would silently call
    # Blocks.load() instead of loading the packaged example.
    with gr.Blocks(title="Engineering Team") as page:
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

        # Whether this deployment requires a key to start a live build. Read once here
        # rather than per component, so the field, its wording and the button emphasis
        # below cannot disagree about which deployment they are describing.
        gated = bool(budget.build_passphrase())

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
                    # Plain Enter must stay a newline — requirements are multi-line by
                    # nature — so Ctrl/Cmd+Enter submits, which is the usual convention.
                    info=(
                        "Ctrl+Enter to build. The box locks while a build is running, "
                        "and closing or reloading this page stops it."
                    ),
                )
                # Gated deployments must say so before the click, not after it. The old
                # label read "Build key" over an empty box with "Live builds are limited
                # on the public deployment" beneath — which never says the field is
                # required, that a visitor almost certainly cannot fill it, or what to do
                # instead. The failure arrived as a warning after typing requirements and
                # pressing the primary button, which is the worst moment to learn it.
                passphrase = gr.Textbox(
                    label="Build key — needed to start a live build here",
                    type="password",
                    visible=gated,
                    placeholder='No key? Use "Show a finished run" — it needs nothing.',
                    info=(
                        "A live build spends the owner's money and takes 20–50 minutes, "
                        "so starting one on the public deployment is gated. Everything "
                        "else is open: the packaged run below is a real build, with its "
                        "own cost table, QA report and downloadable source."
                    ),
                )
                # A masked field you cannot check is a field you mistype. There is no
                # account to lock and no shoulder-surfing risk worth the trade here —
                # the alternative is pressing Build repeatedly and guessing why nothing
                # happens, which is exactly what it caused.
                show_key = gr.Checkbox(
                    label="Show key",
                    value=False,
                    visible=gated,
                    container=False,
                )
                process_choice = gr.Radio(
                    choices=list(VALID_PROCESSES),
                    value=process_name(),
                    label="Delegation model",
                    info=(
                        "sequential: a fixed pipeline, 37 LLM calls, ~$0.22. "
                        "hierarchical: the Engineering Lead manages and delegates, "
                        "102 calls, ~$0.52, and noticeably more wall clock — 30 minutes "
                        "went on a brief sequential finishes quickly. Same product for a "
                        "pipeline this predictable, which is the finding."
                    ),
                )
                # Every reason a build does not start lands here, and stays on screen.
                # It used to be a gr.Warning toast — which is indistinguishable from
                # nothing happening if you look away for three seconds, so pressing Build
                # and seeing no response gave no clue whether the key was wrong, the
                # requirements were empty, triage objected or preflight failed.
                gate_notice = gr.Markdown(visible=False, elem_id="gate_notice")
                triage_confirm = gr.Button(
                    "Build it anyway", variant="stop", visible=False
                )

                # Emphasis follows what the visitor can actually do. Gated, "Build it" is
                # a button almost nobody in the audience can use, so making it the primary
                # call to action invites the one interaction guaranteed to fail. Ungated
                # (local development) the emphasis flips back, because then building is
                # exactly the point.
                with gr.Row():
                    run_button = gr.Button(
                        "Build it",
                        variant="secondary" if gated else "primary",
                        scale=2,
                    )
                    demo_button = gr.Button(
                        "Show a finished run",
                        variant="primary" if gated else "secondary",
                        scale=2,
                    )
                with gr.Row():
                    example_button = gr.Button("Load example requirements", scale=1)
                    clear_button = gr.Button("Clear", scale=1)
                # Restated after more runs. "$0.22 / ~10 min" came from a single
                # single-iteration build on an easy brief and quietly generalised it:
                # wall clock scales with iterations, and most builds take two. Cost is
                # the stable number, time is not, so the line now says which is which.
                gr.Markdown(
                    "_Measured, sequential: **$0.18–0.24** a build, **10–25 minutes per "
                    "iteration**, and most take two. Hierarchical cost **2.4× more** for "
                    "the same product and runs longer again. Asking for changes starts "
                    "another iteration._"
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
                # Label is set per refresh, not fixed here: this component now appears at
                # the human gate too, where "Finished source" would be a lie — nothing
                # has shipped and the reviewer may yet send it back.
                download_box = gr.File(
                    label="Source", visible=False, interactive=False
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
            download_box, requirements, session_state,
        ]

        # Only the handlers that raise or clear the triage question write to these, so a
        # poll tick cannot dismiss a question the person has not answered.
        gate_outputs = [gate_notice, triage_confirm, *outputs]

        run_button.click(
            start,
            inputs=[requirements, process_choice, passphrase, session_state],
            outputs=gate_outputs,
        )
        requirements.submit(
            start,
            inputs=[requirements, process_choice, passphrase, session_state],
            outputs=gate_outputs,
        )
        triage_confirm.click(
            build_anyway,
            inputs=[requirements, process_choice, session_state],
            outputs=gate_outputs,
        )
        revise_button.click(
            request_changes, inputs=[feedback_box, session_state], outputs=outputs
        )
        ship_button.click(
            approve_and_ship, inputs=[feedback_box, session_state], outputs=outputs
        )
        show_key.change(
            lambda shown: gr.update(type="text" if shown else "password"),
            inputs=show_key,
            outputs=passphrase,
        )
        example_button.click(lambda: EXAMPLE_REQUIREMENTS, outputs=requirements)
        demo_button.click(show_demo, inputs=session_state, outputs=outputs)
        clear_button.click(lambda: "", outputs=requirements)

        # The flow runs on a background thread; this is how its progress reaches the page.
        #
        # Wrapped and hidden by CSS: Gradio 6 renders gr.Timer as a visible number
        # spinner, so the page carried a pair of stepper arrows that flickered on every
        # tick. Timer takes neither `visible` nor `elem_id`, so the container is what
        # gets the id.
        with gr.Row(elem_id="poll_timer"):
            gr.Timer(POLL_SECONDS).tick(
                refresh, inputs=session_state, outputs=outputs
            )

        # Which visitor owns which session. Needed because gr.Blocks.unload takes no
        # inputs at all — it cannot be handed the gr.State the way every other handler
        # is — so the leaving browser is identified by the session hash on its request
        # and looked up here instead.
        sessions_by_hash: dict[str, RunSession] = {}

        def on_page_load(session: RunSession | None, request: gr.Request):
            # A reload ends this visitor's previous result; a run in flight is left
            # alone, and other visitors are untouched.
            session = _ensure(session)
            token = getattr(request, "session_hash", "") or ""
            if token:
                sessions_by_hash[token] = session
            session.discard()
            return refresh(session)

        page.load(on_page_load, inputs=session_state, outputs=outputs)

        def on_unload(request: gr.Request):
            """Stop a build the visitor has walked away from.

            Takes a gr.Request and nothing else. An earlier version declared the session
            as a parameter, which Gradio cannot supply here — unload registers with
            `inputs=None`, so the argument arrived as None on every close and the cancel
            never ran. It announced itself as "UserWarning: Unexpected argument. Filling
            with None." and was otherwise completely silent, which is the failure mode a
            cleanup handler is worst placed to have.

            Fires on a reload as well as a close, and the two are indistinguishable from
            the server. A reload therefore ends the run — which is the intent, since a
            reloaded page gets a fresh session and could not have followed the old build
            anyway. The requirements box says so above the button.
            """
            session = sessions_by_hash.pop(getattr(request, "session_hash", "") or "", None)
            if session is not None:
                session.cancel()

        page.unload(on_unload)

    return page


def main() -> None:
    build_ui().launch(theme=_theme(), css=CSS)


if __name__ == "__main__":
    main()
