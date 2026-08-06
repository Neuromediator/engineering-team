"""Gradio UI for the gym class booking system.

Imports module never starts a server; running the file directly does.
"""

from __future__ import annotations

import gradio as gr

from backend import BookingSystem

system = BookingSystem()


def refresh_schedule() -> list[dict]:
    """Return the weekly schedule formatted for a gr.DataFrame."""
    rows = []
    for gc in system.get_weekly_schedule():
        rows.append(
            {
                "Class Name": gc.name,
                "Start": gc.start_time.strftime("%Y-%m-%d %H:%M"),
                "End": gc.end_time.strftime("%Y-%m-%d %H:%M"),
                "Capacity": gc.capacity,
                "Booked": len(gc.booked),
                "Waitlist": len(gc.waitlist),
            }
        )
    return rows


def _all_choices() -> list[tuple[str, str]]:
    return [
        (f"{gc.name} ({gc.start_time:%Y-%m-%d %H:%M})", gc.class_id)
        for gc in sorted(system.classes.values(), key=lambda gc: gc.start_time)
    ]


def refresh_all() -> tuple[list[dict], dict]:
    """Refresh the schedule table and the member dropdown choices."""
    return refresh_schedule(), gr.update(choices=_all_choices())


def do_book(member_name: str, class_id: str) -> str:
    if not member_name or not class_id:
        return "Error: please provide a member name and select a class."
    return system.book_class(member_name.strip(), class_id)


def do_cancel(member_name: str, class_id: str) -> str:
    if not member_name or not class_id:
        return "Error: please provide a member name and select a class."
    return system.cancel_booking(member_name.strip(), class_id)


def do_add_class(name: str, start_time, end_time, capacity) -> str:
    if not name or not start_time or not end_time:
        return "Error: name, start time and end time are required."
    if capacity is None or capacity <= 0:
        return "Error: capacity must be a positive number."
    if end_time <= start_time:
        return "Error: end time must be after start time."
    class_id = system.add_class(name, start_time, end_time, int(capacity))
    return f"Success: added class '{name}' ({class_id})."


def do_remove_class(class_id: str) -> str:
    if not class_id:
        return "Error: please select a class to remove."
    if system.remove_class(class_id):
        return "Success: class removed."
    return "Error: class not found."


def update_remove_choices(class_id_dd) -> dict:
    return gr.update(choices=_all_choices())


with gr.Blocks(title="Gym Class Booking") as demo:
    gr.Markdown("# Gym Class Booking")

    with gr.Tab("Member"):
        schedule = gr.Dataframe(
            headers=["Class Name", "Start", "End", "Capacity", "Booked", "Waitlist"],
            value=[],
            label="Weekly Schedule",
        )
        with gr.Row():
            member_name = gr.Textbox(label="Member Name")
            class_id = gr.Dropdown(label="Select Class", choices=[])
        with gr.Row():
            book_btn = gr.Button("Book")
            cancel_btn = gr.Button("Cancel")
            refresh_btn = gr.Button("Refresh")
        result = gr.Textbox(label="Result", interactive=False)

    with gr.Tab("Staff"):
        gr.Markdown("### Add Class")
        with gr.Row():
            new_name = gr.Textbox(label="Class Name")
            start_time = gr.DateTime(label="Start Time", type="datetime")
            end_time = gr.DateTime(label="End Time", type="datetime")
            capacity_input = gr.Number(label="Capacity", precision=0, value=20)
        add_btn = gr.Button("Add Class")
        add_result = gr.Textbox(label="Add Result", interactive=False)
        gr.Markdown("### Remove Class")
        remove_dropdown = gr.Dropdown(label="Select Class to Remove", choices=[])
        remove_btn = gr.Button("Remove Class")
        remove_result = gr.Textbox(label="Remove Result", interactive=False)

    refresh_btn.click(
        fn=refresh_all,
        inputs=[],
        outputs=[schedule, class_id],
    ).then(
        fn=lambda c: gr.update(choices=_all_choices()),
        inputs=[class_id],
        outputs=[remove_dropdown],
    )

    add_btn.click(
        fn=do_add_class,
        inputs=[new_name, start_time, end_time, capacity_input],
        outputs=add_result,
    ).then(
        fn=refresh_all,
        inputs=[],
        outputs=[schedule, class_id],
    ).then(
        fn=update_remove_choices,
        inputs=[class_id],
        outputs=[remove_dropdown],
    )

    remove_btn.click(
        fn=do_remove_class,
        inputs=remove_dropdown,
        outputs=remove_result,
    ).then(
        fn=refresh_all,
        inputs=[],
        outputs=[schedule, class_id],
    ).then(
        fn=update_remove_choices,
        inputs=[class_id],
        outputs=[remove_dropdown],
    )

    book_btn.click(
        fn=do_book,
        inputs=[member_name, class_id],
        outputs=result,
    )
    cancel_btn.click(
        fn=do_cancel,
        inputs=[member_name, class_id],
        outputs=result,
    )

    demo.load(
        fn=refresh_schedule,
        inputs=[],
        outputs=schedule,
    )


if __name__ == "__main__":
    demo.launch()