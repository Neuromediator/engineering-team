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
import re
import uuid
import zipfile

from .sandbox import SandboxBackend, backend_name, make_backend


SANDBOX_ROOT = Path(__file__).parents[3] / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


# A launch *statement* — `demo.launch()`, indented under a __main__ guard or not. Written
# as a statement match rather than a substring search on purpose: a test file legitimately
# mentions ".launch(" while asserting the entry point is guarded, and refusing to run the
# test suite over that would be a worse bug than the one this prevents. `self.assertIn(
# ".launch(", source)` does not match; `    demo.launch()` does.
_LAUNCH_CALL = re.compile(r"^\s*[A-Za-z_][\w.]*\.launch\s*\(", re.MULTILINE)


def _calls_launch(source: str) -> bool:
    """Whether running this file would start a Gradio server and block."""
    return any(
        _LAUNCH_CALL.match(line)
        for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )


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
        sandbox_id: str = "",
    ) -> None:
        self.run_id = run_id or (Path(root).name if root else new_run_id())
        self.root = Path(root) if root is not None else SANDBOX_ROOT / self.run_id
        self.backend = (
            backend
            if backend is not None
            else make_backend(self.run_id, self.root, sandbox_id)
        )
        # Packages the crew installed, in order. Recorded so the archive can declare the
        # dependencies a downloaded build actually needs, rather than guessing at them.
        self.installed: list[str] = []
        self._tools: list | None = None

    def __repr__(self) -> str:
        return f"Sandbox({self.backend.location})"

    @property
    def sandbox_id(self) -> str:
        """The remote workspace's identity, if the backend has one.

        Empty for Docker, whose workspace is a directory that outlives the process
        anyway. Persisted by the flow so a resumed run reattaches to the same VM.
        """
        return getattr(self.backend, "sandbox_id", "") or ""

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

    # Skipped when exporting: machinery, not the product.
    EXPORT_SKIP = (".venv", "__pycache__", "uv.lock", ".python-version")

    def export_archive(self, dest_dir: Path | str) -> Path | None:
        """Zip this run's source files and return the archive path.

        Reads through the backend rather than the filesystem, so it works identically
        for a local directory and a remote microVM. That matters: with E2B the files
        live on a VM that gets killed, so unless they are pulled out first, a deployed
        run produces output nobody can obtain.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        archive = dest_dir / f"{self.run_id}.zip"

        written = 0
        names: list[str] = []
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name in self.backend.list_files():
                if name in self.EXPORT_SKIP or name.startswith("."):
                    continue
                content = self.backend.read_file(name)
                if content is None:  # a directory, or unreadable
                    continue
                bundle.writestr(name, content)
                names.append(name)
                written += 1

            if written:
                # Added here rather than asked of the crew. A downloaded build was not
                # runnable: no pyproject.toml meant `uv sync` failed outright and
                # `python app.py` failed on a missing gradio, so the reviewer the human
                # gate asks for a judgement had no way to form one.
                #
                # Generating them at export keeps the deliverable itself untouched.
                # File discipline is load-bearing prompt text — QA flags stray files as
                # findings, and it flagged a scratch script on the very run that
                # surfaced this — so adding files to what agents produce would mean
                # loosening that rule and paying tokens to restate a dependency list the
                # sandbox already knows exactly.
                bundle.writestr("pyproject.toml", self._generated_pyproject())
                bundle.writestr("HOW_TO_RUN.md", self._generated_readme(names))

        if not written:
            archive.unlink(missing_ok=True)
            return None
        return archive

    def _dependencies(self) -> list[str]:
        """What a downloaded build needs installed: gradio, plus whatever was added."""
        deps = ["gradio>=6"]
        deps.extend(p for p in self.installed if p.split("[")[0].strip() != "gradio")
        return deps

    def _generated_pyproject(self) -> str:
        requires = "\n".join(f'    "{dep}",' for dep in self._dependencies())
        return (
            "# Generated when this build was archived — not written by the crew.\n"
            "# The dependency list is what the sandbox actually installed.\n"
            "[project]\n"
            f'name = "generated-app"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.10"\n'
            "dependencies = [\n"
            f"{requires}\n"
            "]\n"
        )

    def _generated_readme(self, names: list[str]) -> str:
        tests = [n for n in names if n.startswith("test_") and n.endswith(".py")]
        test_cmd = (
            f"uv run python -m unittest {tests[0][:-3]} -v"
            if tests
            else "uv run python -m unittest discover -v"
        )
        listing = "\n".join(f"- `{n}`" for n in sorted(names))
        return f"""# How to run this build

This directory was produced by an automated engineering crew and archived as-is. The
`pyproject.toml` beside it was generated at download time, not by the crew, so that
these commands work without you assembling an environment first.

## Run the app

```bash
uv run app.py
```

`uv` reads `pyproject.toml`, creates the virtual environment and installs the
dependencies on the first run. Gradio prints a local URL to open.

Without `uv`:

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install {" ".join(self._dependencies())}
python app.py
```

## Run the tests

```bash
{test_cmd}
```

## Check the UI builds without starting a server

```bash
uv run _validate.py
```

This imports `app.py` and inspects the Gradio `Blocks` object. Useful because running
`app.py` starts a real web server that serves until you stop it.

## What is here

{listing}

`design.md`, `test_summary.md` and `qa_report.json` are written by the system, not by
the crew — they are the design it worked from and the report it was judged against.

If you downloaded this on Windows, files named `*:Zone.Identifier` may appear alongside
the real ones. Those are the "mark of the web" your browser attaches, not part of the
build; `find . -name '*:Zone.Identifier' -delete` removes them.
"""

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
        refusal = self._refuse_to_launch_a_server(filename)
        if refusal is not None:
            return refusal
        return self.backend.run_python(filename).render()

    def _refuse_to_launch_a_server(self, filename: str) -> str | None:
        """Block executing the Gradio entry point, which would block until killed.

        The prompt already forbids this. A prompt is advice, and on the run that forced
        this guard the frontend engineer ran ``app.py`` twice anyway:

            21:45:02  tool  Frontend  run_sandbox_python_file  app.py  → FAILED (exit code 124)
            21:45:03  tool  Frontend  run_sandbox_python_file  app.py  → FAILED (exit code 124)

        Exit 124 is the execution timeout: ``demo.launch()`` starts a real web server
        that serves until something kills it. Two of those burned ten minutes of wall
        clock and produced nothing, and the sandbox expired shortly after.

        So the rule moves from the prompt into the tool, which is this project's general
        preference: bounded behaviour that can be proved over instructions that can be
        ignored. The refusal names the alternative, because a bare "no" just invites the
        agent to try a variation of the same thing.
        """
        name = (filename or "").strip().rsplit("/", 1)[-1]
        if not name:
            return None
        try:
            source = self.backend.read_file(name)
        except Exception:  # noqa: BLE001 - let the real run report a missing file
            return None
        if not isinstance(source, str) or not _calls_launch(source):
            return None
        return (
            f"REFUSED: {name} calls .launch(), which starts a web server and blocks "
            f"until it is killed — the run would burn the whole execution timeout and "
            f"return nothing. This is not a failure of your code.\n\n"
            f"To check the UI, run _validate.py, which imports {name} and inspects the "
            f"`demo` Blocks object without starting a server. If _validate.py does not "
            f"exist yet, write it first."
        )

    def add_package(self, package: str) -> str:
        result = self.backend.add_package(package).render()
        # Remembered so the archive can declare what a downloaded build needs. The crew
        # is never asked to write a dependency list: the sandbox already knows it
        # exactly, and asking a model to restate a fact the system holds is how the two
        # drift apart.
        name = (package or "").strip()
        if name and name not in self.installed and "[SUCCESS]" in result:
            self.installed.append(name)
        return result

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

        @tool("Add Sandbox Package")
        def add_sandbox_package(package: str) -> str:
            """
            Install a third-party Python package into the sandbox so the code you
            write can import it. Install a package BEFORE writing code that imports
            it, and check the result — an install can fail.

            Args:
                package: A package requirement, e.g. "pandas" or "httpx>=0.27".
                    One package per call. Do not pass a command line.
            Returns:
                The exit status and output of the install.
            """
            return sandbox.add_package(package)

        built = [
            list_sandbox_files,
            read_sandbox_file,
            write_sandbox_file,
            run_sandbox_python,
            add_sandbox_package,
        ]
        # Sandbox state changes between calls (files appear/change/run), so caching tool
        # results would feed agents stale data. Opt out of CrewAI's default tool caching.
        for built_tool in built:
            built_tool.cache_function = _never_cache

        self._tools = built
        return built


__all__ = ["SANDBOX_ROOT", "Sandbox", "backend_name", "new_run_id"]
