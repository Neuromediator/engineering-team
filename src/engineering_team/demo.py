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
    lines = [
        f"**Iteration {data['iterations']} of {data['max_iterations']}** · "
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
        lines.append(f"   {record['summary']}")
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
    """A short, honest excerpt — the shape of the real log, not the whole 134 lines."""
    return "\n".join(
        [
            "13:33:56  run    flow             starting (sequential process)",
            "13:34:55  task   design_task      completed",
            "13:36:00  tool   Backend          add_sandbox_package gradio  → SUCCESS",
            "13:36:27  tool   Backend          write_sandbox_file  backend.py  → 7024 chars",
            "13:38:41  tool   Backend          run_sandbox_python_file  test_booking.py  → FAILED (exit code 1)",
            "13:39:09  tool   Backend          run_sandbox_python_file  test_booking.py  → SUCCESS",
            "14:16:51  task   qa_task          started",
            "14:18:34  tool   QA Inspector     run_sandbox_python_file  test_booking.py  → SUCCESS",
            "14:21:43  task   qa_task          completed",
            "14:21:44  run    budget           run cost $0.2388; today $0.37",
            "14:21:44  run    flow             finished",
        ]
    )
