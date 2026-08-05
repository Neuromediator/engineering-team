"""Per-run sandboxes and the tools agents use to work in them.

Each run gets its own workspace. That is what lets several flows run at once without one
crew overwriting another's ``account.py`` — required by the racing supervisor, and cheap
insurance against confusing cross-talk before then.

Tools are **bound to a Sandbox instance** rather than reading a global. A module-level
current-workspace would have to be a thread-local or context variable, and CrewAI executes
agent steps on pools whose propagation rules are not guaranteed; binding at construction
removes the question entirely.

Where the workspace actually lives is the backend's business — a local directory plus
Docker during development, a Firecracker microVM once deployed. See :mod:`.sandbox`.
"""

from crewai.tools import tool
from pathlib import Path
import uuid

from .sandbox import SandboxBackend, backend_name, make_backend


SANDBOX_ROOT = Path(__file__).parents[3] / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _never_cache(*_args, **_kwargs) -> bool:
    return False


class Sandbox:
    """One run's workspace, plus the tools that operate on it."""

    def __init__(
        self,
        root: Path | str | None = None,
        run_id: str | None = None,
        backend: SandboxBackend | None = None,
    ) -> None:
        self.run_id = run_id or (Path(root).name if root else new_run_id())
        self.root = Path(root) if root is not None else SANDBOX_ROOT / self.run_id
        self.backend = backend if backend is not None else make_backend(self.run_id, self.root)
        self._tools: list | None = None

    def __repr__(self) -> str:
        return f"Sandbox({self.backend.location})"

    @property
    def location(self) -> str:
        """Where this run's files actually are, for logs and the UI."""
        return self.backend.location

    # -- lifecycle ----------------------------------------------------------------

    def reset(self) -> None:
        """Create an empty workspace with gradio available, discarding anything prior."""
        self.backend.reset()

    def close(self) -> None:
        """Release remote resources. A no-op for the local backend."""
        self.backend.close()

    # -- operations, wrapped as tools below ---------------------------------------

    def list_files(self) -> str:
        names = self.backend.list_files()
        return "\n".join(names) if names else "The sandbox is empty."

    def read_file(self, filename: str) -> str:
        content = self.backend.read_file(filename)
        if content is None:
            return f"No such file in the sandbox: {filename}"
        return content

    def write_file(self, filename: str, content: str) -> str:
        written = self.backend.write_file(filename, content)
        return f"Wrote {written} characters to {filename}."

    def run_python(self, filename: str) -> str:
        return self.backend.run_python(filename).render()

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
            Execute a Python file from the sandbox in an isolated environment and
            return what happened.

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


__all__ = ["SANDBOX_ROOT", "Sandbox", "backend_name", "new_run_id"]
