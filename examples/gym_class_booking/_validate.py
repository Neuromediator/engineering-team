"""Import app.py and verify the Gradio Blocks construct is exposed.

Importing app.py must NOT start a server; that only happens when the file
is run directly (guarded by `if __name__ == "__main__":`).
"""

import gradio as gr

import app


def main() -> None:
    assert isinstance(
        app.demo, gr.Blocks
    ), "app.demo must be a gr.Blocks instance"
    assert hasattr(app, "system"), "app must expose the system singleton"
    print("Validation OK: app.demo is a gr.Blocks instance")


if __name__ == "__main__":
    main()