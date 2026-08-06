"""Deployed backend: a Firecracker microVM per run, reached over HTTPS.

This exists because Hugging Face Spaces cannot run Docker-in-Docker. E2B gives the same
guarantee the local backend does — untrusted generated code never executes in the process
that orchestrates it — over an API that works from inside a container.

The important difference from Docker is that files live *on the VM*. Every read and write
crosses the network, which is why the backend protocol covers file operations and not just
execution: an abstraction over execution alone would have left reads and writes pointing at
a local directory the running code cannot see.
"""

from __future__ import annotations

import os

from .base import (
    EXIT_COULD_NOT_START,
    EXIT_TIMEOUT,
    ExecResult,
    valid_requirement,
)


# Absolute, because commands run with an explicit cwd and agents refer to bare filenames.
WORKDIR = "/home/user/workspace"

# A sandbox is billed while alive, so it is created per run and killed on close. This is
# now an IDLE timeout, not a lifetime: `_require` renews it on every operation, so it
# bounds how long an abandoned VM keeps billing rather than how long a build may take.
# As a lifetime it was a bug — 900s against 20-50 minute builds meant the workspace
# vanished mid-run, taking the deliverable with it.
SANDBOX_TIMEOUT = 900
EXEC_TIMEOUT = 300


class E2BBackend:
    """Implements :class:`SandboxBackend` against an E2B sandbox.

    The VM is created lazily on :meth:`reset` rather than in ``__init__`` so that merely
    constructing a backend — which the crew does while wiring agents — never starts
    billing.
    """

    def __init__(self, run_id: str, timeout: int = SANDBOX_TIMEOUT) -> None:
        self.run_id = run_id
        self.timeout = timeout
        self._sandbox = None

    def __repr__(self) -> str:
        return f"E2BBackend({self.run_id}, sandbox={self.sandbox_id or 'not started'})"

    @property
    def sandbox_id(self) -> str:
        return getattr(self._sandbox, "sandbox_id", "") if self._sandbox else ""

    @property
    def location(self) -> str:
        return f"e2b:{self.sandbox_id or 'pending'}:{WORKDIR}"

    # -- lifecycle ----------------------------------------------------------------

    def _require(self):
        """Return the live sandbox, creating it if a tool is used before reset().

        Every operation renews the lease. E2B kills a VM when its timeout expires
        counting from *creation*, not from last use, so a fixed 900s ceiling meant the
        workspace disappeared 15 minutes into every build — and this project's own
        README says a build takes 20-50 minutes. A run measured at 21:30:01 lost its
        sandbox at 21:45:06 and every tool call after that failed:

            ✗ write_sandbox_file — The sandbox was not found: This error is likely due
              to sandbox timeout.

        QA then reported two blockers for a deliverable it could not read, which is the
        correct behaviour reporting on an incorrect situation. Renewing here converts
        the ceiling into an idle timeout: the VM outlives any build that is still
        working, and still shuts down 15 minutes after one stops — which is what keeps
        an abandoned run from billing indefinitely.
        """
        if self._sandbox is None:
            self._start()
        else:
            try:
                self._sandbox.set_timeout(self.timeout)
            except Exception:  # noqa: BLE001 - renewal is best effort
                # Losing a renewal is not fatal on its own; the operation about to run
                # may still succeed, and if the VM is truly gone it will say so with a
                # far better message than one raised from here.
                pass
        return self._sandbox

    def _start(self) -> None:
        if not os.environ.get("E2B_API_KEY"):
            raise RuntimeError(
                "E2B_API_KEY is not set. Either set it or run with SANDBOX_BACKEND=docker."
            )
        # Imported here so the package is only required when this backend is selected.
        from e2b_code_interpreter import Sandbox

        self._sandbox = Sandbox.create(
            timeout=self.timeout,
            metadata={"project": "engineering_team", "run_id": self.run_id},
        )
        self._sandbox.files.make_dir(WORKDIR)

    def reset(self) -> None:
        """Start a fresh VM with gradio installed, discarding any previous one."""
        self.close()
        self._start()

        # A failed install raises rather than returning non-zero, and unlike generated
        # code this one really is fatal: the frontend cannot be validated without gradio.
        from e2b.sandbox.commands.command_handle import CommandExitException

        try:
            self._sandbox.commands.run("pip install --quiet gradio", timeout=600)
        except CommandExitException as exit_error:
            raise RuntimeError(
                "Could not install gradio in the E2B sandbox: "
                f"{(exit_error.stderr or '')[:500]}"
            ) from exit_error

    def close(self) -> None:
        if self._sandbox is None:
            return
        try:
            self._sandbox.kill()
        except Exception:  # noqa: BLE001 - teardown must not mask the real failure
            pass
        finally:
            self._sandbox = None

    # -- files --------------------------------------------------------------------

    def _path(self, filename: str) -> str:
        return f"{WORKDIR}/{filename}"

    def list_files(self) -> list[str]:
        entries = self._require().files.list(WORKDIR)
        return sorted(entry.name for entry in entries)

    def read_file(self, filename: str) -> str | None:
        from e2b.exceptions import NotFoundException

        try:
            return self._require().files.read(self._path(filename))
        except NotFoundException:
            return None

    def write_file(self, filename: str, content: str) -> int:
        self._require().files.write(self._path(filename), content)
        return len(content)

    # -- execution ----------------------------------------------------------------

    def add_package(self, package: str) -> ExecResult:
        """Install a dependency into the microVM."""
        from e2b.exceptions import SandboxException, TimeoutException
        from e2b.sandbox.commands.command_handle import CommandExitException

        # This string reaches a shell, so the validation above is load-bearing, not
        # cosmetic: it is the only thing between a generated name and command injection.
        if not valid_requirement(package):
            return ExecResult(
                EXIT_COULD_NOT_START,
                "",
                f"{package!r} is not a valid package requirement. Use a name, "
                f"optionally with extras and a version, e.g. 'pandas' or 'httpx>=0.27'.",
            )

        try:
            result = self._require().commands.run(
                f"pip install --quiet {package.strip()}", timeout=EXEC_TIMEOUT
            )
        except CommandExitException as exit_error:
            return ExecResult(
                exit_error.exit_code, exit_error.stdout or "", exit_error.stderr or ""
            )
        except TimeoutException:
            return ExecResult(
                EXIT_TIMEOUT, "", f"Installing {package!r} exceeded {EXEC_TIMEOUT}s."
            )
        except SandboxException as exc:
            return ExecResult(EXIT_COULD_NOT_START, "", f"Could not install: {exc}")

        return ExecResult(
            getattr(result, "exit_code", 0) or 0,
            getattr(result, "stdout", "") or "",
            getattr(result, "stderr", "") or "",
        )

    def run_python(self, filename: str) -> ExecResult:
        from e2b.exceptions import SandboxException, TimeoutException
        from e2b.sandbox.commands.command_handle import CommandExitException

        try:
            result = self._require().commands.run(
                f"python {filename}",
                cwd=WORKDIR,
                timeout=EXEC_TIMEOUT,
            )
        except CommandExitException as exit_error:
            # E2B treats a non-zero exit as an exception. For this project it is the most
            # important *result* there is — a failing test run is what the agent has to
            # read to fix its code. Letting this propagate would recreate, in the deployed
            # backend, the exact bug that made agents debug blind locally.
            #
            # It must be caught before SandboxException, which it also subclasses.
            return ExecResult(
                exit_error.exit_code,
                exit_error.stdout or "",
                exit_error.stderr or "",
            )
        except TimeoutException:
            return ExecResult(
                EXIT_TIMEOUT,
                "",
                f"Execution exceeded {EXEC_TIMEOUT}s and was killed. The script probably "
                f"blocks — check for input(), .launch(), or an infinite loop.",
            )
        except SandboxException as exc:
            return ExecResult(
                EXIT_COULD_NOT_START, "", f"Could not run in the E2B sandbox: {exc}"
            )

        return ExecResult(
            getattr(result, "exit_code", 0) or 0,
            getattr(result, "stdout", "") or "",
            getattr(result, "stderr", "") or "",
        )
