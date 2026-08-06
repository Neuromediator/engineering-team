"""The contract every sandbox backend honours.

Deliberately written *after* there were two implementations to compare, rather than up
front. The seam is not "where does code execute" — it is "where do the files live", which
is what actually differs: Docker bind-mounts a host directory, so reads and writes are
ordinary filesystem calls, while E2B keeps everything on a remote microVM where every
read and write crosses the network. Abstracting only execution would have left the file
operations silently local and produced an E2B backend that ran code against nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# A PEP 508 requirement, restricted to what this project needs: name, optional extras,
# optional version specifier. Deliberately strict — the E2B backend runs its install
# through a shell, and the string comes from a language model, so anything that could
# carry a `;` or a backtick must never reach it.
_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"      # package name
    r"(?:\[[A-Za-z0-9,._-]+\])?"                          # optional extras
    r"(?:\s*(?:[<>=!~]=|[<>])\s*[A-Za-z0-9._*+!-]+)?$"  # optional version pin
)


def valid_requirement(package: str) -> bool:
    """Return whether a package string is safe to pass to an installer."""
    return bool(_REQUIREMENT.match(package.strip()))


# Agents pay for every character of tool output as input tokens on the next call, and a
# runaway loop can print megabytes. Keep the head and tail of each stream: the traceback
# that matters is almost always at one end or the other.
STREAM_LIMIT = 12_000

# Exit codes this project assigns to conditions the process never got to report itself.
EXIT_TIMEOUT = 124
EXIT_COULD_NOT_START = 125


def clip(text: str, limit: int = STREAM_LIMIT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - limit
    return f"{text[:half]}\n... [{dropped} characters omitted] ...\n{text[-half:]}"


@dataclass(frozen=True)
class ExecResult:
    """The outcome of running one file, in the form an agent can debug from."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def render(self) -> str:
        status = "SUCCESS" if self.ok else f"FAILED (exit code {self.exit_code})"
        parts = [f"[{status}]"]
        parts.append(
            f"--- stdout ---\n{clip(self.stdout).rstrip()}"
            if self.stdout.strip()
            else "--- stdout ---\n(empty)"
        )
        # unittest writes its entire report to stderr, so this is the important half.
        parts.append(
            f"--- stderr ---\n{clip(self.stderr).rstrip()}"
            if self.stderr.strip()
            else "--- stderr ---\n(empty)"
        )
        return "\n".join(parts)


@runtime_checkable
class SandboxBackend(Protocol):
    """Where a run's files live and where its code executes.

    Implementations must be safe to use from several threads belonging to *different*
    runs at once, which in practice means holding no module-level state — each backend
    instance owns exactly one run's workspace.
    """

    @property
    def location(self) -> str:
        """Human-readable identity of the workspace, for logs and the UI."""
        ...

    def reset(self) -> None:
        """Create an empty workspace with gradio available, discarding anything prior."""
        ...

    def list_files(self) -> list[str]:
        """Return the filenames in the workspace."""
        ...

    def read_file(self, filename: str) -> str | None:
        """Return a file's contents, or None when it does not exist."""
        ...

    def write_file(self, filename: str, content: str) -> int:
        """Write a file, replacing any existing one. Returns characters written."""
        ...

    def run_python(self, filename: str) -> ExecResult:
        """Execute a file in the workspace and report status, stdout and stderr.

        Must not raise for ordinary failure — a non-zero exit, a timeout or a workspace
        that will not start are all results the agent needs to read and act on.
        """
        ...

    def add_package(self, package: str) -> ExecResult:
        """Install a third-party package into the workspace.

        Without this the crew can only ever produce stdlib code, which makes it useless
        for most real requirements. Installing is safe because the workspace is already
        isolated — an ephemeral container or a microVM — but it is still generated code
        choosing what to install, so implementations must validate the name rather than
        interpolate it into a shell.
        """
        ...

    def close(self) -> None:
        """Release remote resources. A no-op for local backends."""
        ...
