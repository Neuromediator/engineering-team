"""Per-run sandboxes and the tools agents use to work in them.

Each run gets its own directory under ``sandbox/``. That is what lets several flows run
at once without one crew overwriting another's ``account.py`` — a prerequisite for the
variant racing in phase 7, and cheap insurance against confusing cross-talk before then.

Tools are **bound to a sandbox instance** rather than reading a global. A module-level
current-directory would have to be a thread-local or context variable, and CrewAI executes
agent steps on pools whose propagation rules are not guaranteed; binding at construction
removes the question entirely.
"""

from crewai.tools import tool
from pathlib import Path
import os
import shutil
import subprocess
import uuid


SANDBOX_ROOT = Path(__file__).parents[3] / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

RUNNER_IMAGE = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
EXEC_TIMEOUT = 300

# Agents pay for every character of tool output as input tokens on the next call, and a
# runaway loop can print megabytes. Keep the head and tail of each stream: the traceback
# that matters is almost always at one end or the other.
_STREAM_LIMIT = 12_000

# uv wants a writable HOME and cache. As a non-root user the image's default HOME is not
# writable, so point both somewhere that always is, and keep them out of the bind mount
# so they never show up as files the agents think they wrote.
_CONTAINER_ENV = [
    "-e", "HOME=/tmp",
    "-e", "UV_CACHE_DIR=/tmp/uv-cache",
    # The cache and the bind-mounted project are on different filesystems, so uv cannot
    # hardlink between them and warns on every run. Agents read that warning as an error
    # and try to "fix" it, so state the intent instead of paying for the confusion.
    "-e", "UV_LINK_MODE=copy",
]


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _container_user() -> list[str]:
    """Run containers as the host user so the sandbox stays deletable.

    Docker defaults to root, and anything it writes into a bind mount is owned by root
    on the host. A later cleanup then fails with EPERM trying to remove files it does not
    own — which is exactly how a run once died before spending a cent.
    """
    if os.name != "posix":
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def _clip(text: str, limit: int = _STREAM_LIMIT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - limit
    return f"{text[:half]}\n... [{dropped} characters omitted] ...\n{text[-half:]}"


def _format_result(returncode: int, stdout: str, stderr: str) -> str:
    """Render an execution result so an agent can actually debug from it."""
    status = "SUCCESS" if returncode == 0 else f"FAILED (exit code {returncode})"
    parts = [f"[{status}]"]
    parts.append(
        f"--- stdout ---\n{_clip(stdout).rstrip()}" if stdout.strip() else "--- stdout ---\n(empty)"
    )
    # unittest writes its entire report to stderr, so this is the important half.
    parts.append(
        f"--- stderr ---\n{_clip(stderr).rstrip()}" if stderr.strip() else "--- stderr ---\n(empty)"
    )
    return "\n".join(parts)


def _never_cache(*_args, **_kwargs) -> bool:
    return False


class Sandbox:
    """One run's working directory, plus the tools that operate on it."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else SANDBOX_ROOT / new_run_id()
        self._tools: list | None = None

    def __repr__(self) -> str:
        return f"Sandbox({self.root})"

    # -- lifecycle ----------------------------------------------------------------

    def _force_remove(self) -> None:
        """Remove the directory, falling back to root-in-a-container for old leftovers."""
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
        """Wipe the sandbox and re-initialize it as a fresh uv project with gradio."""
        if self.root.exists():
            self._force_remove()
        self.root.mkdir(parents=True)

        subprocess.run(
            ["uv", "init", "--bare", "--python", "3.13"], cwd=self.root, check=True
        )
        subprocess.run(["uv", "add", "gradio"], cwd=self.root, check=True)

    # -- operations, wrapped as tools below ---------------------------------------

    def list_files(self) -> str:
        names = sorted(p.name for p in self.root.iterdir())
        return "\n".join(names) if names else "The sandbox is empty."

    def read_file(self, filename: str) -> str:
        path = self.root / filename
        if not path.is_file():
            return f"No such file in the sandbox: {filename}"
        return path.read_text()

    def write_file(self, filename: str, content: str) -> str:
        path = self.root / filename
        path.write_text(content)
        return f"Wrote {len(content)} characters to {filename}."

    def run_python(self, filename: str) -> str:
        try:
            result = subprocess.run(
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
            return _format_result(
                124,
                exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                f"Execution exceeded {EXEC_TIMEOUT}s and was killed. The script probably "
                f"blocks — check for input(), .launch(), or an infinite loop.",
            )
        except OSError as exc:
            return _format_result(125, "", f"Could not start the container: {exc}")

        return _format_result(result.returncode, result.stdout, result.stderr)

    # -- tools --------------------------------------------------------------------

    def tools(self) -> list:
        """Return this sandbox's tools, built once and shared by every agent in the run."""
        if self._tools is not None:
            return self._tools

        sandbox = self

        @tool("List Sandbox Files")
        def list_sandbox_files() -> str:
            """
            List the filenames currently in the sandbox directory.

            Returns:
                A newline-separated list of filenames, or a message if the
                sandbox is empty.
            """
            return sandbox.list_files()

        @tool("Read Sandbox File")
        def read_sandbox_file(filename: str) -> str:
            """
            Read and return the text contents of a file in the sandbox directory.

            Args:
                filename: The name of the file to read (e.g. "solution.py").
            Returns:
                The file's contents, or a message if the file does not exist.
            """
            return sandbox.read_file(filename)

        @tool("Write Sandbox File")
        def write_sandbox_file(filename: str, content: str) -> str:
            """
            Write text to a file in the sandbox directory, replacing any existing
            file with the same name.

            Args:
                filename: The name of the file to write (e.g. "solution.py").
                content: The text content to write.
            Returns:
                A confirmation message.
            """
            return sandbox.write_file(filename, content)

        @tool("Run Sandbox Python File")
        def run_sandbox_python(filename: str) -> str:
            """
            Execute a Python file from the sandbox directory inside an ephemeral
            Docker container, with the sandbox mounted as the working directory,
            using a uv run to run the code in the uv project.

            Args:
                filename: The name of the Python file to run (e.g. "solution.py").
            Returns:
                The exit status, stdout and stderr of the run. Note that `unittest`
                reports its results on stderr, not stdout.
            """
            return sandbox.run_python(filename)

        built = [
            list_sandbox_files,
            read_sandbox_file,
            write_sandbox_file,
            run_sandbox_python,
        ]
        # Sandbox state changes between calls (files appear/change/run), so caching tool
        # results would feed agents stale data. Opt out of CrewAI's default tool caching.
        for built_tool in built:
            built_tool.cache_function = _never_cache

        self._tools = built
        return built
