"""A preserved run, rendered instantly.

A live build takes 20–50 minutes and costs real money. Nobody browsing a public Space
will wait that long, and letting strangers spend the owner's API credit is its own
problem. So the deployed app opens on a real, completed run — genuine cost table, genuine
QA report, downloadable source — and live builds are gated.

This is not a mock. Every number and file under ``examples/gym_class_booking/`` came from
an actual run, including the human feedback round that fixed a waitlist bug.
"""

from __future__ import annotations

import json
import zipfile
from functools import lru_cache
from pathlib import Path

from .tools.sandbox_tools import SANDBOX_ROOT


EXAMPLE_DIR = SANDBOX_ROOT.parent / "examples" / "gym_class_booking"
DEMO_FILE = EXAMPLE_DIR / "demo.json"

# Files that are the product, as opposed to the run's own paperwork.
SOURCE_FILES = ("backend.py", "app.py", "test_booking.py", "_validate.py")


@lru_cache(maxsize=1)
def load() -> dict | None:
    """Return the preserved run, or None if it is not packaged."""
    if not DEMO_FILE.is_file():
        return None
    try:
        return json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


@lru_cache(maxsize=1)
def archive() -> str | None:
    """Build (once) a downloadable zip of the preserved source."""
    if not EXAMPLE_DIR.is_dir():
        return None
    target = EXAMPLE_DIR / "gym_class_booking.zip"
    if target.is_file():
        return str(target)

    names = [n for n in SOURCE_FILES if (EXAMPLE_DIR / n).is_file()]
    if not names:
        return None
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in names:
            bundle.write(EXAMPLE_DIR / name, arcname=name)
    return str(target)


def cost_table() -> str:
    data = load()
    if not data:
        return "_No example packaged._"
    rows = ["| Agent | Calls | In | Out | USD |", "|---|--:|--:|--:|--:|"]
    for row in data["by_agent"]:
        rows.append(
            f"| {row['agent']} | {row['calls']} | {row['in']:,} | "
            f"{row['out']:,} | ${row['usd']:.4f} |"
        )
    rows.append(f"| **TOTAL** | | | | **${data['total_usd']:.4f}** |")
    return "\n".join(rows)


def progress() -> str:
    data = load()
    if not data:
        return "_No example packaged._"
    # "Iteration 2 of 4" read as a run that might still go to 4. This one finished, and
    # the 4 was never a target: the cap started at 2 and only became 4 because asking
    # for changes grants a fresh budget. Reporting what happened avoids implying
    # headroom that stopped being meaningful the moment the run ended.
    count = data["iterations"]
    lines = [
        f"**{count} iteration{'s' if count != 1 else ''}** · "
        f"{data['process']} · {data['duration_minutes']} minutes",
        "",
    ]
    for record in data["history"]:
        mark = "✅" if record["passed"] else "❌"
        lines.append(
            f"{mark} **Iteration {record['iteration']}** — "
            f"{record['blocking']} blocking, "
            f"tests {'passed' if record['tests_passed'] else 'not passing'}"
        )
        # Markdown joins adjacent lines into one paragraph, so without these blanks
        # every iteration and its summary ran together into a single wall of text.
        lines.append("")
        lines.append(record["summary"])
        lines.append("")
    lines += [
        "",
        "**Human feedback between the iterations**",
        f"> {data['human_feedback']}",
    ]
    return "\n".join(lines)


def qa_findings() -> str:
    data = load()
    if not data:
        return "_No example packaged._"
    report = data["qa_report"]
    lines = [
        f"**Verdict: {'PASS' if report.get('passed') else 'FAIL'}** — "
        f"tests {'ran' if report.get('tests_run') else 'never ran'}, "
        f"{'all passed' if report.get('tests_passed') else 'not all passing'}",
        "",
        report.get("summary", ""),
    ]
    findings = report.get("findings") or []
    if findings:
        lines += ["", "| Severity | File | Finding |", "|---|---|---|"]
        for finding in findings:
            lines.append(
                f"| {finding['severity']} | `{finding['file']}` | {finding['summary']} |"
            )
        lines += [
            "",
            "_Note: the three findings about `design.md`, `test_summary.md` and "
            "`qa_report.json` were a false positive — those files are written by the "
            "system itself, but the inspector had been told the deliverable was four "
            "files and no others. The instruction was at fault, not the inspector, and "
            "it has since been corrected. It is left here because a QA report that "
            "quietly excluded its own mistakes would be worth less._",
        ]
    return "\n".join(lines)


def activity_log() -> str:
    """The preserved excerpt of the run's activity log, labelled as an excerpt.

    The run is real and every line here was transcribed from it, but the log itself
    was never written to disk — it lived in memory and stdout — so 11 of 134 lines are
    all that survived. Rendered bare in the same widget a live run streams into, an
    abridgement is indistinguishable from a complete log, and this one is unusually
    misleading: it contains no line from the frontend engineer or the test engineer,
    the two agents that between them made 37 of the run's 72 calls and, in the
    frontend's case, the largest share of its cost. A reader comparing this panel to
    the cost table beside it would conclude those agents never ran.

    So the omission is stated rather than left to be inferred. The alternative — an
    excerpt that reads as a full trace — is the kind of quiet overstatement this
    project's whole premise is against.
    """
    data = load()
    if not data:
        return "_No example packaged._"

    excerpt = data.get("activity_excerpt") or []
    if not excerpt:
        return "_No activity log was preserved for this run._"

    total = data.get("activity_total_lines", len(excerpt))
    elision_after = data.get("activity_elision_after", "")

    header = [
        f"# EXCERPT — {len(excerpt)} of {total} lines. The run is real; this record of",
        "# it is abridged, because the full log was never written to disk.",
        "",
    ]

    lines: list[str] = []
    for line in excerpt:
        lines.append(line)
        if elision_after and line.startswith(elision_after):
            lines.append(
                "     ⋮     37 minutes omitted: the frontend build, the test engineer,"
            )
            lines.append(
                "     ⋮     and the second iteration that followed the human feedback."
            )
    return "\n".join(header + lines)
