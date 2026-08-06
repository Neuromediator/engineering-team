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

from engineering_team.app import main  # noqa: E402

if __name__ == "__main__":
    main()
