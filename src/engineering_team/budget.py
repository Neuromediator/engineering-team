"""A spend ceiling for the deployed app.

A public demo where anyone can press "Build it" spends the *owner's* API credit. At
roughly $0.22 a sequential run, a handful of curious visitors can drain a balance, and
a crawler could do it faster. This is the stop.

Two independent limits, because they fail differently:

* a **daily** ceiling, which caps the damage from ordinary traffic;
* a **per-run** ceiling checked while the crew works, which catches a single run that
  goes wrong — the 40-minute tip calculator that kept writing scratch files would have
  tripped this long before a human noticed.

Spend is recorded in a small SQLite file rather than in memory, so a restart cannot
reset the day's total. That matters: Hugging Face Spaces restart on their own.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date
from pathlib import Path


DEFAULT_DAILY_LIMIT = 5.0
DEFAULT_RUN_LIMIT = 1.5

DB_PATH = Path(
    os.environ.get("BUDGET_DB")
    or Path.home() / ".local" / "share" / "engineering_team" / "budget.db"
)

_lock = threading.Lock()


def daily_limit() -> float:
    """USD per day across all runs. Set BUDGET_DAILY_USD=0 to disable."""
    return float(os.environ.get("BUDGET_DAILY_USD", DEFAULT_DAILY_LIMIT))


def run_limit() -> float:
    """USD for a single run before it is abandoned. Set BUDGET_RUN_USD=0 to disable."""
    return float(os.environ.get("BUDGET_RUN_USD", DEFAULT_RUN_LIMIT))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS spend (day TEXT PRIMARY KEY, usd REAL NOT NULL)"
    )
    return connection


def spent_today() -> float:
    with _lock, _connect() as connection:
        row = connection.execute(
            "SELECT usd FROM spend WHERE day = ?", (date.today().isoformat(),)
        ).fetchone()
    return float(row[0]) if row else 0.0


def record(amount: float) -> float:
    """Add a run's cost to today's total and return the new total."""
    if amount <= 0:
        return spent_today()
    today = date.today().isoformat()
    with _lock, _connect() as connection:
        connection.execute(
            "INSERT INTO spend (day, usd) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd",
            (today, float(amount)),
        )
        row = connection.execute(
            "SELECT usd FROM spend WHERE day = ?", (today,)
        ).fetchone()
    return float(row[0]) if row else 0.0


def remaining_today() -> float:
    limit = daily_limit()
    if limit <= 0:
        return float("inf")
    return max(0.0, limit - spent_today())


def check_can_start() -> tuple[bool, str]:
    """Return whether a new run may start, and why not if it may not."""
    limit = daily_limit()
    if limit <= 0:
        return True, ""

    spent = spent_today()
    if spent >= limit:
        return False, (
            f"Daily budget reached: ${spent:.2f} of ${limit:.2f} spent today. "
            f"This resets at midnight."
        )
    if remaining_today() < run_limit():
        return False, (
            f"Only ${remaining_today():.2f} left of today's ${limit:.2f} budget, "
            f"which is less than one run may cost. Not starting a build that would "
            f"be abandoned partway."
        )
    return True, ""


def status_line() -> str:
    limit = daily_limit()
    if limit <= 0:
        return "Budget: unlimited"
    return f"Budget today: ${spent_today():.2f} of ${limit:.2f}"


# Deployment gate. When BUILD_PASSPHRASE is set, a live build requires it; visitors
# still get the full UI and a real preserved run. Unset (local development) means no gate.
def build_passphrase() -> str:
    return os.environ.get("BUILD_PASSPHRASE", "").strip()


def passphrase_ok(supplied: str) -> tuple[bool, str]:
    """Whether a live build may start. Open when no passphrase is configured."""
    expected = build_passphrase()
    if not expected:
        return True, ""
    if (supplied or "").strip() == expected:
        return True, ""
    return False, (
        "Live builds are limited on this deployment — a build costs the owner real money "
        "and takes 20-50 minutes. Browse the packaged example instead; it is a genuine "
        "run with its real cost table, QA report and downloadable source."
    )
