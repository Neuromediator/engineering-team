"""Hugging Face Spaces entry point.

The Gradio SDK looks for `app.py` at the repository root and ignores
`[project.scripts]`, so this exists purely to bridge the two. Locally, prefer
`uv run serve`, which reaches the same function.

`src/` is put on the path explicitly rather than assuming the package was installed:
a Space may resolve dependencies from `requirements.txt` without ever running
`pip install .`, and then `import engineering_team` would fail on boot with nothing
in the logs but a traceback.
"""

import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    import spaces
except ImportError:  # not on Spaces — the package is only preinstalled there
    spaces = None

if spaces is not None:
    # This Space is hosted on ZeroGPU, which is not a performance choice: hosting a
    # Gradio Space on free cpu-basic now returns 402 and requires PRO, while a free
    # account may host two ZeroGPU Spaces. ZeroGPU refuses to start unless at least
    # one function is decorated, so this exists to satisfy that check and nothing
    # else. No crew work is GPU work — every model call leaves over HTTPS — so this
    # is never called and no GPU quota is ever consumed. Wrapping a provider call in
    # the decorator would reserve a slot for the whole duration to do an HTTP
    # request, which is the anti-pattern this comment exists to warn the next reader
    # away from.
    @spaces.GPU(duration=1)
    def _zerogpu_hosting_probe() -> None:
        pass


from engineering_team.app import main  # noqa: E402

if __name__ == "__main__":
    main()
