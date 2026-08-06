"""Backend business logic and data model for the gym class booking system.

All data is held in memory; a restart loses the state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta


def generate_id() -> str:
    """Return a unique identifier string."""
    return str(uuid.uuid4())


@dataclass
class GymClass:
    """A single class occurrence."""

    class_id: str
    name: str
    start_time: datetime
    end_time: datetime
    capacity: int
    booked: list[str] = field(default_factory=list)
    waitlist: list[str] = field(default_factory=list)

    def has_space(self) -> bool:
        """Return True if there is room to book."""
        return len(self.booked) < self.capacity

    def add_booking(self, member_name: str) -> bool:
        """Append member to booked (assumes space available)."""
        self.booked.append(member_name)
        return True

    def add_to_waitlist(self, member_name: str) -> None:
        """Append member to waitlist."""
        self.waitlist.append(member_name)

    def remove_booking(self, member_name: str) -> bool:
        """Remove member from booked; return True if found."""
        if member_name in self.booked:
            self.booked.remove(member_name)
            return True
        return False

    def remove_from_waitlist(self, member_name: str) -> bool:
        """Remove member from waitlist; return True if found."""
        if member_name in self.waitlist:
            self.waitlist.remove(member_name)
            return True
        return False

    def promote_next(self) -> str | None:
        """If space and waitlist non-empty, promote the front of the waitlist."""
        if self.has_space() and self.waitlist:
            member = self.waitlist.pop(0)
            self.booked.append(member)
            return member
        return None


class BookingSystem:
    """Coordinates classes and member bookings, enforcing business rules."""

    def __init__(self) -> None:
        self.classes: dict[str, GymClass] = {}
        self.member_bookings: dict[str, set[str]] = {}

    def add_class(
        self, name: str, start_time: datetime, end_time: datetime, capacity: int
    ) -> str:
        """Create and store a GymClass, returning its class_id."""
        class_id = generate_id()
        gym_class = GymClass(
            class_id=class_id,
            name=name,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
        )
        self.classes[class_id] = gym_class
        return class_id

    def remove_class(self, class_id: str) -> bool:
        """Remove a class and all its bookings/waitlist entries."""
        gym_class = self.classes.get(class_id)
        if gym_class is None:
            return False
        for member in gym_class.booked:
            bookings = self.member_bookings.get(member)
            if bookings is not None:
                bookings.discard(class_id)
                if not bookings:
                    del self.member_bookings[member]
        del self.classes[class_id]
        return True

    def get_weekly_schedule(self) -> list[GymClass]:
        """Return classes whose start_time falls within the current week."""
        now = datetime.now()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        return [
            gc
            for gc in self.classes.values()
            if week_start <= gc.start_time < week_end
        ]

    def book_class(self, member_name: str, class_id: str) -> str:
        """Book a member into a class or waitlist them."""
        gym_class = self.classes.get(class_id)
        if gym_class is None:
            return "Error: class not found."
        if (
            member_name in gym_class.booked
            or member_name in gym_class.waitlist
        ):
            return "Error: member is already booked or waitlisted in this class."
        if self._check_overlap(
            member_name, gym_class.start_time, gym_class.end_time
        ):
            return "Error: booking overlaps with an existing class."
        if gym_class.has_space():
            gym_class.add_booking(member_name)
            self.member_bookings.setdefault(member_name, set()).add(class_id)
            return f"Success: {member_name} booked into {gym_class.name}."
        gym_class.add_to_waitlist(member_name)
        position = len(gym_class.waitlist)
        return (
            f"Class is full. {member_name} added to waitlist "
            f"(position {position})."
        )

    def cancel_booking(self, member_name: str, class_id: str) -> str:
        """Cancel a booking or remove a member from a waitlist."""
        gym_class = self.classes.get(class_id)
        if gym_class is None:
            return "Error: class not found."
        if member_name in gym_class.waitlist:
            gym_class.remove_from_waitlist(member_name)
            return "Success: removed from waitlist."
        if member_name in gym_class.booked:
            if gym_class.start_time - datetime.now() < timedelta(hours=2):
                return (
                    "Error: cancellation not allowed within 2 hours "
                    "of the class start."
                )
            gym_class.remove_booking(member_name)
            bookings = self.member_bookings.get(member_name)
            if bookings is not None:
                bookings.discard(class_id)
                if not bookings:
                    del self.member_bookings[member_name]
            promoted = self._promote_from_waitlist(class_id)
            msg = f"Success: {member_name}'s booking cancelled."
            if promoted:
                msg += f" {promoted} promoted from the waitlist."
            return msg
        return "Error: member is not booked in this class."

    def _check_overlap(
        self, member_name: str, new_start: datetime, new_end: datetime
    ) -> bool:
        """Return True if the new interval overlaps any existing booking."""
        for class_id in self.member_bookings.get(member_name, set()):
            existing = self.classes.get(class_id)
            if existing is not None:
                if (
                    new_start < existing.end_time
                    and new_end > existing.start_time
                ):
                    return True
        return False

    def _promote_from_waitlist(self, class_id: str) -> str | None:
        """Promote the front of the waitlist if possible.

        A member is only promoted if their own active bookings do not overlap
        with this class. Skipped (overlapping) members remain on the waitlist,
        so promotion never creates a double-booking.
        """
        gym_class = self.classes.get(class_id)
        if gym_class is None:
            return None
        if not gym_class.has_space():
            return None
        for i, member in enumerate(gym_class.waitlist):
            if self._check_overlap(
                member, gym_class.start_time, gym_class.end_time
            ):
                continue
            gym_class.waitlist.pop(i)
            gym_class.booked.append(member)
            self.member_bookings.setdefault(member, set()).add(class_id)
            return member
        return None

    def _get_class_by_id(self, class_id: str) -> GymClass | None:
        """Convenience accessor for a class by id."""
        return self.classes.get(class_id)
