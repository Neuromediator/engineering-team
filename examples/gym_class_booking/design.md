# Design for Gym Class Booking System

## Overview
The system is built from three Python files in a single flat directory:
- `backend.py` – business logic and data model (in-memory).
- `app.py` – Gradio UI (exposes `demo` Blocks object).
- `test_booking.py` – unit tests using `unittest`.
- `_validate.py` – lightweight import check (already given).

All data is held in memory; a restart loses the state. The backend module provides a `BookingSystem` class that manages gym classes, bookings, waitlists, and overlap detection. The UI calls the backend without any persistence.

---

## 1. Backend Module (`backend.py`)

### 1.1 `GymClass` (data class)
Represents a single class occurrence.

**Attributes:**
- `class_id: str` – unique identifier (UUID).
- `name: str` – class name.
- `start_time: datetime` – start time.
- `end_time: datetime` – end time.
- `capacity: int` – maximum number of booked members.
- `booked: list[str]` – ordered list of member names who have a spot.
- `waitlist: list[str]` – ordered list of member names waiting for a spot.

**Methods:**
- `has_space() -> bool` – returns `True` if `len(booked) < capacity`.
- `add_booking(member_name: str) -> bool` – appends to `booked`; returns `True` (assumes space).
- `add_to_waitlist(member_name: str) -> None` – appends to `waitlist`.
- `remove_booking(member_name: str) -> bool` – removes from `booked`; returns `True` if found.
- `remove_from_waitlist(member_name: str) -> bool` – removes from `waitlist`; returns `True` if found.
- `promote_next() -> str | None` – if `has_space()` and `waitlist` non‑empty, pop first from waitlist, add to `booked`, and return the member name; otherwise `None`.

### 1.2 `BookingSystem` (coordinator)
Holds all classes and member bookings, enforces business rules.

**Attributes:**
- `classes: dict[str, GymClass]` – keyed by `class_id`.
- `member_bookings: dict[str, set[str]]` – maps member name to set of `class_id` they are currently booked in (actively booked, not waitlisted). Waitlist entries are not tracked here; they are tracked only inside each `GymClass`.

**Public methods:**

- `__init__(self) -> None`
- `add_class(name: str, start_time: datetime, end_time: datetime, capacity: int) -> str`  
  Creates a `GymClass`, stores it, returns `class_id`.

- `remove_class(class_id: str) -> bool`  
  Removes class and all its bookings/waitlist entries. Updates `member_bookings` accordingly. Returns `True` if class existed.

- `get_weekly_schedule() -> list[GymClass]`  
  Returns all classes whose `start_time` falls within the current week (from today 00:00:00 to today + 7 days). Uses `datetime.now()`.

- `book_class(member_name: str, class_id: str) -> str`  
  **Logic:**
  1. If `class_id` not in `classes`, return error message.
  2. If member already exists in the class’s `booked` list or `waitlist`, return error.
  3. Call `_check_overlap(member_name, start, end)` for the class’s time window. If overlapping, return error.
  4. If `has_space()`, add to `booked`, update `member_bookings`, return success.
  5. Otherwise, add to `waitlist`, return message indicating waitlist position.

- `cancel_booking(member_name: str, class_id: str) -> str`  
  **Logic:**
  1. If class not found, return error.
  2. If member is on `waitlist`: remove from waitlist, return success.
  3. If member is in `booked`:
     - Check if cancellation is allowed: `class.start_time - datetime.now() >= timedelta(hours=2)`. If not, return error.
     - Remove from `booked` and from `member_bookings`.
     - Call `_promote_from_waitlist(class_id)` to fill the spot.
     - Return success message.
  4. Otherwise, return error (member not in class).

**Private helpers:**
- `_check_overlap(member_name: str, new_start: datetime, new_end: datetime) -> bool`  
  Iterates over all `class_id` in `member_bookings[member_name]`, retrieves the `GymClass`, and returns `True` if `(new_start, new_end)` overlaps with the existing class’s interval (using standard interval overlap: `new_start < existing.end and new_end > existing.start`). Returns `False` otherwise.

- `_promote_from_waitlist(class_id: str) -> None`  
  Calls `classes[class_id].promote_next()`; if a member is promoted, updates `member_bookings`.

- `_get_class_by_id(class_id: str) -> GymClass | None` – convenience.

### 1.3 Helper (module-level)
- `generate_id() -> str` – `return str(uuid.uuid4())`.

---

## 2. Gradio UI (`app.py`)

### 2.1 Singleton instance
At module level, create a `BookingSystem` instance:
```python
system = BookingSystem()
```

### 2.2 `demo` Blocks object
Build a `gr.Blocks` called `demo` containing two tabs: **Member** and **Staff**.

#### Member Tab
- **View Schedule**: A `gr.DataFrame` that shows the weekly schedule (columns: Class Name, Start, End, Capacity, Booked, Waitlist). Populated by a function `refresh_schedule() -> list[dict]` that calls `system.get_weekly_schedule()` and formats data.
- **Booking Form**:
  - `member_name` (Textbox)
  - `class_id` (Dropdown, choices populated from schedule)
  - `book_btn` (Button) → calls `system.book_class(member_name, class_id)` and displays result in an output `Textbox`.
  - `cancel_btn` (Button) → calls `system.cancel_booking(member_name, class_id)` and displays result.
- **Refresh Button** to update the schedule and dropdown choices.

#### Staff Tab
- **Add Class**:
  - `name` (Textbox)
  - `date` (Textbox/Datepicker, but Gradio’s DateTime component could be used; we’ll use `gr.DateTime` for both start and end, or separate date/time pickers. For simplicity, specify `start_time` and `end_time` using `gr.DateTime` with `type="datetime"`).
  - `capacity` (Number)
  - `add_btn` (Button) → calls `system.add_class(...)` and shows confirmation.
- **Remove Class**:
  - `class_id` (Dropdown of all classes)
  - `remove_btn` (Button) → calls `system.remove_class(class_id)` and shows result.

The UI uses `gr.update` for choices and dataframe refreshing. All event handlers are defined inside the `with demo:` block.

### 2.3 Graceful launch protection
The file ends with:
```python
if __name__ == "__main__":
    demo.launch()
```
No server is started on import.

---

## 3. Unit Tests (`test_booking.py`)

### 3.1 Test class `TestBookingSystem(unittest.TestCase)`
**Setup:**
- In `setUp`, create a fresh `BookingSystem` and add several classes with future times (using `datetime` offsets). Optionally, mock `datetime.now()` to a fixed point for deterministic tests.

**Test cases:**

- `test_add_class` – class appears in schedule; correct attributes.
- `test_remove_class` – removes class and its bookings; member_bookings updated.
- `test_book_success` – member books a class with space; membership tracked.
- `test_book_full_capacity` – booking is waitlisted; waitlist position message.
- `test_book_duplicate_in_same_class` – error when already booked or waitlisted.
- `test_overlap_prevention` – booking a second class overlapping with an existing booking fails.
- `test_cancel_before_deadline` – cancellation succeeds, waitlist promoted.
- `test_cancel_after_deadline` – cancellation rejected (mock time to within 2 hours of start).
- `test_cancel_from_waitlist` – member removed from waitlist.
- `test_promotion_chain` – cancel a spot, waitlist member gets booked, further cancellations work.
- `test_book_nonexistent_class` – error.
- `test_weekly_schedule_filter` – mock `datetime.now()` and add classes just outside the week; only within-week classes returned.

### 3.2 Mocking
Use `unittest.mock.patch` to control `datetime.now()` in the backend module for time-sensitive tests (cancellation deadline, weekly schedule window). Ensure that `backend.py` uses `datetime.now()` directly (not a cached import) so mocking works.

---

## 4. `_validate.py`
Already provided; it imports `app` and checks that `demo` is a `gr.Blocks` instance. No changes needed.

---

## 5. Engineer Work Delegation

- **Backend Engineer** (`backend.py`): Implement `GymClass`, `BookingSystem`, and the `generate_id` helper exactly as designed. Ensure all public methods are complete and handle edge cases.
- **Frontend Engineer** (`app.py`): Build the Gradio UI with the two tabs, using the `system` singleton. Wire up buttons to backend methods, implement refresh logic, and ensure dropdowns update. Do not call `launch()` at import.
- **Test Engineer** (`test_booking.py`): Write all unit tests listed above, using `unittest` and mocking where necessary. Ensure coverage of the critical paths (booking, cancellation, overlap, waitlist promotion, and time-sensitive constraints).
- **QA Inspector** (`_validate.py` and final review): Verify that `app.py` exposes `demo` correctly, that the whole system works together, and report any blocking issues.