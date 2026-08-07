"""Local backend: files on the host, execution in an ephemeral Docker container.

This is the development path. Files are ordinary host files bind-mounted into the
container, so reads and writes never leave the machine and only execution is containerised.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ...capabilities import GRADIO_REQUIREMENT
from .base import (
    EXIT_COULD_NOT_START,
    EXIT_TIMEOUT,
    ExecResult,
    valid_requirement,
)


RUNNER_IMAGE = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
EXEC_TIMEOUT = 300

# uv wants a writable HOME and cache. As a non-root user the image's default HOME is not
# writable, so point both somewhere that always is, and keep them out of the bind mount so
# they never show up as files the agents think they wrote.
_CONTAINER_ENV = [
    "-e", "HOME=/tmp",
    "-e", "UV_CACHE_DIR=/tmp/uv-cache",
    # The cache and the bind-mounted project are on different filesystems, so uv cannot
    # hardlink between them and warns on every run. Agents read that warning as an error
    # and try to "fix" it, so state the intent instead of paying for the confusion.
    "-e", "UV_LINK_MODE=copy",
]


def _container_user() -> list[str]:
    """Run containers as the host user so the workspace stays deletable.

    Docker defaults to root, and anything it writes into a bind mount is owned by root on
    the host. A later cleanup then fails with EPERM on files it does not own — which is
    exactly how a run once died before spending a cent.
    """
    if os.name != "posix":
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


class DockerBackend:
    """Implements :class:`SandboxBackend` against a local directory plus Docker."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def __repr__(self) -> str:
        return f"DockerBackend({self.root})"

    @property
    def location(self) -> str:
        return str(self.root)

    # -- lifecycle ----------------------------------------------------------------

    def _force_remove(self) -> None:
        try:
            shutil.rmtree(self.root)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            pass

        # Files a previous root container left behind, from before containers ran as the
        # host user. Borrow root the same way they got it: mount the parent and delete.
        subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{self.root.parent}:/parent",
                "busybox:latest",
                "rm", "-rf", f"/parent/{self.root.name}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

    def reset(self) -> None:
        if self.root.exists():
            self._force_remove()
        self.root.mkdir(parents=True)

        subprocess.run(
            ["uv", "init", "--bare", "--python", "3.13"], cwd=self.root, check=True
        )
        # Pinned, not latest: the agents are told this exact version in
        # CONSTRAINTS_PROMPT, and a floating install would make that statement false the
        # day a new release lands.
        subprocess.run(
            ["uv", "add", GRADIO_REQUIREMENT], cwd=self.root, check=True
        )

    def close(self) -> None:
        """Nothing to release: containers are removed with --rm as they finish."""

    # -- files --------------------------------------------------------------------

    def list_files(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir())

    def read_file(self, filename: str) -> str | None:
        path = self.root / filename
        if not path.is_file():
            return None
        return path.read_text()

    def write_file(self, filename: str, content: str) -> int:
        path = self.root / filename
        path.write_text(content)
        return len(content)

    # -- execution ----------------------------------------------------------------

    def add_package(self, package: str) -> ExecResult:
        """Add a dependency to the workspace's uv project."""
        if not valid_requirement(package):
            return ExecResult(
                EXIT_COULD_NOT_START,
                "",
                f"{package!r} is not a valid package requirement. Use a name, "
                f"optionally with extras and a version, e.g. 'pandas' or 'httpx>=0.27'.",
            )

        try:
            completed = subprocess.run(
                ["uv", "add", package.strip()],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                EXIT_TIMEOUT, "", f"Installing {package!r} exceeded {EXEC_TIMEOUT}s."
            )
        except OSError as exc:
            return ExecResult(EXIT_COULD_NOT_START, "", f"Could not run uv add: {exc}")

        return ExecResult(completed.returncode, completed.stdout, completed.stderr)

    def run_python(self, filename: str) -> ExecResult:
        try:
            completed = subprocess.run(
                [
                    "docker", "run", "--rm",
                    *_container_user(),
                    *_CONTAINER_ENV,
                    "-v", f"{self.root}:/workspace",
                    "-w", "/workspace",
                    RUNNER_IMAGE,
                    "uv", "run", filename,
                ],
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            # Raising here would surface as an opaque tool error; the agent needs to know
            # its code hung so it can look for a blocking call (a stray `.launch()`).
            stdout = exc.stdout
            return ExecResult(
                EXIT_TIMEOUT,
                stdout.decode() if isinstance(stdout, bytes) else (stdout or ""),
                f"Execution exceeded {EXEC_TIMEOUT}s and was killed. The script probably "
                f"blocks — check for input(), .launch(), or an infinite loop.",
            )
        except OSError as exc:
            return ExecResult(
                EXIT_COULD_NOT_START, "", f"Could not start the container: {exc}"
            )

        return ExecResult(completed.returncode, completed.stdout, completed.stderr)
