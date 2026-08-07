"""Sandbox backends: where a run's files live and where its code executes."""

from __future__ import annotations

import os
from pathlib import Path

from .base import ExecResult, SandboxBackend
from .docker_backend import DockerBackend
from .e2b_backend import E2BBackend


BACKEND_ENV_VAR = "SANDBOX_BACKEND"
DEFAULT_BACKEND = "docker"


def backend_name() -> str:
    return (os.environ.get(BACKEND_ENV_VAR) or DEFAULT_BACKEND).strip().lower()


def make_backend(run_id: str, root: Path, sandbox_id: str = "") -> SandboxBackend:
    """Build the configured backend for one run.

    Args:
        run_id: This run's identifier, used to label the remote sandbox.
        root: Local directory for the Docker backend. Ignored by E2B, whose files live
            on the VM.
        sandbox_id: An existing remote sandbox to reattach to rather than create.
            Ignored by Docker, whose workspace is a directory that simply still exists.

    Raises:
        ValueError: If ``SANDBOX_BACKEND`` names something that does not exist.
    """
    name = backend_name()
    if name == "docker":
        return DockerBackend(root)
    if name == "e2b":
        return E2BBackend(run_id, sandbox_id=sandbox_id)
    raise ValueError(
        f"Unknown {BACKEND_ENV_VAR}={name!r}. Valid options are 'docker' and 'e2b'."
    )


__all__ = [
    "BACKEND_ENV_VAR",
    "DockerBackend",
    "E2BBackend",
    "ExecResult",
    "SandboxBackend",
    "backend_name",
    "make_backend",
]
