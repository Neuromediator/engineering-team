"""Hugging Face Spaces entry point.

The Gradio SDK looks for `app.py` at the repository root and ignores
`[project.scripts]`, so this exists purely to bridge the two. Locally, prefer
`uv run serve`, which reaches the same function.
"""

from engineering_team.app import main

if __name__ == "__main__":
    main()
