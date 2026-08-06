"""Unit tests for the gym class booking backend."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from backend import BookingSystem, GymClass, generate_id

FIXED_NOW = datetime(2025, 1, 6, 10, 0, 0)  # Monday 10:00


class TestBookingSystem(unittest.TestCase):
    def setUp(self):
        self.system = BookingSystem()
        # Classes starting later today / this week, all within the week window.
        self.class_a = self.system.add_class(
            "Yoga",
            FIXED_NOW + timedelta(hours=2),
            FIXED_NOW + timedelta(hours=3),
            2,
        )
        self.class_b = self.system.add_class(
            "Spin",
            FIXED_NOW + timedelta(days=1, hours=9),
            FIXED_NOW + timedelta(days=1, hours=10),
            1,
        )
        self.class_c = self.system.add_class(
            "HIIT",
            FIXED_NOW + timedelta(days=2, hours=9),
            FIXED_NOW + timedelta(days=2, hours=10),
            2,
        )

    def test_generate_id(self):
        self.assertTrue(generate_id())

    def test_add_class(self):
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            schedule = self.system.get_weekly_schedule()
        class_ids = [gc.class_id for gc in schedule]
        self.assertIn(self.class_a, class_ids)
        gc = self.system.classes[self.class_a]
        self.assertEqual(gc.name, "Yoga")
        self.assertEqual(gc.capacity, 2)
        self.assertEqual(gc.start_time, FIXED_NOW + timedelta(hours=2))
        self.assertEqual(gc.end_time, FIXED_NOW + timedelta(hours=3))
        self.assertEqual(gc.booked, [])
        self.assertEqual(gc.waitlist, [])

    def test_remove_class(self):
        self.system.book_class("Alice", self.class_a)
        self.assertTrue(self.system.remove_class(self.class_a))
        self.assertNotIn(self.class_a, self.system.classes)
        self.assertNotIn("Alice", self.system.member_bookings)
        self.assertFalse(self.system.remove_class(self.class_a))

    def test_book_success(self):
        result = self.system.book_class("Alice", self.class_a)
        self.assertIn("Success", result)
        gc = self.system.classes[self.class_a]
        self.assertIn("Alice", gc.booked)
        self.assertIn(self.class_a, self.system.member_bookings["Alice"])

    def test_book_full_capacity(self):
        self.system.classes[self.class_b].capacity = 1
        self.system.book_class("Alice", self.class_b)
        result = self.system.book_class("Bob", self.class_b)
        self.assertIn("waitlist", result.lower())
        self.assertIn("position 1", result.lower())
        gc = self.system.classes[self.class_b]
        self.assertIn("Bob", gc.waitlist)
        self.assertEqual(gc.waitlist.index("Bob"), 0)

    def test_book_duplicate_in_same_class(self):
        self.system.book_class("Alice", self.class_a)
        result = self.system.book_class("Alice", self.class_a)
        self.assertIn("already", result.lower())

    def test_book_duplicate_waitlisted(self):
        self.system.classes[self.class_b].capacity = 1
        self.system.book_class("Alice", self.class_b)
        self.system.book_class("Bob", self.class_b)
        result = self.system.book_class("Bob", self.class_b)
        self.assertIn("already", result.lower())

    def test_overlap_prevention(self):
        self.system.book_class("Alice", self.class_a)
        # Overlaps with class_a (class_a is 12:00-13:00 on Monday).
        overlapping = self.system.add_class(
            "Pilates",
            FIXED_NOW + timedelta(hours=2, minutes=30),
            FIXED_NOW + timedelta(hours=4),
            2,
        )
        result = self.system.book_class("Alice", overlapping)
        self.assertIn("overlap", result.lower())

    def test_non_overlapping_allowed(self):
        self.system.book_class("Alice", self.class_a)
        result = self.system.book_class("Alice", self.class_b)
        self.assertIn("Success", result)

    def test_cancel_before_deadline(self):
        self.system.classes[self.class_b].capacity = 1
        self.system.book_class("Alice", self.class_b)
        self.system.book_class("Bob", self.class_b)  # waitlisted
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_b)
        self.assertIn("Success", result)
        gc = self.system.classes[self.class_b]
        self.assertIn("Bob", gc.booked)
        self.assertNotIn("Bob", gc.waitlist)
        self.assertIn(self.class_b, self.system.member_bookings["Bob"])

    def test_cancel_after_deadline(self):
        # Start of class_a is exactly 2 hours after FIXED_NOW; cancel within 2h
        # must be rejected. Use a now that is 1 hour before start.
        self.system.book_class("Alice", self.class_a)
        now = FIXED_NOW + timedelta(hours=1)  # 1 hour before start
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_a)
        self.assertIn("Error", result)
        gc = self.system.classes[self.class_a]
        self.assertIn("Alice", gc.booked)

    def test_cancel_at_deadline_exact(self):
        # exactly 2 hours before start -> allowed (difference >= 2h)
        self.system.book_class("Alice", self.class_a)
        now = self.system.classes[self.class_a].start_time - timedelta(hours=2)
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_a)
        self.assertIn("Success", result)

    def test_cancel_from_waitlist(self):
        self.system.classes[self.class_b].capacity = 1
        self.system.book_class("Alice", self.class_b)
        self.system.book_class("Bob", self.class_b)
        result = self.system.cancel_booking("Bob", self.class_b)
        self.assertIn("waitlist", result.lower())
        gc = self.system.classes[self.class_b]
        self.assertNotIn("Bob", gc.waitlist)

    def test_promotion_chain(self):
        self.system.classes[self.class_b].capacity = 1
        self.system.book_class("Alice", self.class_b)
        self.system.book_class("Bob", self.class_b)  # waitlisted
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_b)
        self.assertIn("Bob promoted", result)

    def test_waitlist_promotion_skips_overlap(self):
        """A waitlisted member who booked an overlapping class must not be
        auto-promoted into a conflict when a spot opens up."""
        # Full class: fit capacity 1, fill with Alice, Bob waitlisted.
        self.system.classes[self.class_a].capacity = 1
        self.system.book_class("Alice", self.class_a)  # 12:00-13:00 Monday
        self.system.book_class("Bob", self.class_a)  # waitlisted

        # Bob then books an overlapping class (12:30-14:00).
        overlapping = self.system.add_class(
            "Pilates",
            FIXED_NOW + timedelta(hours=2, minutes=30),
            FIXED_NOW + timedelta(hours=4),
            1,
        )
        result = self.system.book_class("Bob", overlapping)
        self.assertIn("Success", result)

        # Alice cancels -> a spot opens in class_a, but Bob overlaps.
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_a)

        gc = self.system.classes[self.class_a]
        # Bob must NOT be auto-promoted into a conflict.
        self.assertNotIn("Bob", gc.booked)
        self.assertIn("Bob", gc.waitlist)
        self.assertNotIn("Alice", gc.booked)

    def test_waitlist_promotion_non_overlapping(self):
        """A waitlisted member who booked only non-overlapping classes is
        promoted normally."""
        self.system.classes[self.class_a].capacity = 1
        self.system.book_class("Alice", self.class_a)  # 12:00-13:00 Monday
        self.system.book_class("Bob", self.class_a)  # waitlisted
        # Bob books a non-overlapping class (class_b is day+1 9:00-10:00).
        self.system.book_class("Bob", self.class_b)

        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = self.system.cancel_booking("Alice", self.class_a)

        gc = self.system.classes[self.class_a]
        self.assertIn("Bob", gc.booked)
        self.assertNotIn("Bob", gc.waitlist)
        self.assertIn(self.class_a, self.system.member_bookings["Bob"])

    def test_book_nonexistent_class(self):
        result = self.system.book_class("Alice", "does-not-exist")
        self.assertIn("Error", result)

    def test_cancel_nonexistent_class(self):
        result = self.system.cancel_booking("Alice", "does-not-exist")
        self.assertIn("Error", result)

    def test_cancel_not_booked(self):
        result = self.system.cancel_booking("Alice", self.class_c)
        self.assertIn("Error", result)

    def test_weekly_schedule_filter(self):
        # Add a class outside the current week window.
        outside_week = self.system.add_class(
            "Zumba",
            FIXED_NOW + timedelta(days=8),
            FIXED_NOW + timedelta(days=8, hours=1),
            2,
        )
        # A class starting exactly at day 7 boundary is outside (>=).
        boundary = self.system.add_class(
            "Boundary",
            (FIXED_NOW.replace(hour=0, minute=0, second=0, microsecond=0))
            + timedelta(days=7),
            (FIXED_NOW.replace(hour=0, minute=0, second=0, microsecond=0))
            + timedelta(days=7, hours=1),
            2,
        )
        with patch("backend.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            schedule = self.system.get_weekly_schedule()
        ids = [gc.class_id for gc in schedule]
        self.assertNotIn(outside_week, ids)
        self.assertNotIn(boundary, ids)
        self.assertIn(self.class_a, ids)
        self.assertIn(self.class_b, ids)

    def test_gym_class_methods(self):
        gc = GymClass("c1", "Test", FIXED_NOW, FIXED_NOW, 2)
        self.assertTrue(gc.has_space())
        gc.add_booking("A")
        self.assertTrue(gc.has_space())
        gc.add_booking("B")
        self.assertFalse(gc.has_space())
        gc.add_to_waitlist("W")
        self.assertIsNone(gc.promote_next())  # no space
        self.assertFalse(gc.remove_booking("Z"))
        self.assertTrue(gc.remove_booking("A"))
        gc.add_to_waitlist("W2")
        promoted = gc.promote_next()  # now has space
        self.assertEqual(promoted, "W")
        self.assertIn("W", gc.booked)
        self.assertFalse(gc.remove_from_waitlist("Z"))
        self.assertTrue(gc.remove_from_waitlist("W2"))


if __name__ == "__main__":
    unittest.main()
