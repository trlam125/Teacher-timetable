import unittest
from types import SimpleNamespace

from app.logic import (
    clear_teacher_identity,
    fixed_group_validation_error,
    normalize_slot_values,
    parse_integer_set,
    pop_matching_fixed_task,
    required_double_removal_slots,
    revoke_last_teacher_profile,
)


class RequiredDoubleRemovalTests(unittest.TestCase):
    def test_removes_both_periods_of_double(self):
        self.assertEqual(
            required_double_removal_slots([1, 2, 8, 9], 2, sessions=2, periods_per_session=5),
            {1, 2},
        )

    def test_does_not_cross_session_boundary(self):
        # Slot 4 is the last morning period; slot 5 is the first afternoon period.
        self.assertEqual(
            required_double_removal_slots([4, 5], 4, sessions=2, periods_per_session=5),
            {4},
        )

    def test_isolated_odd_remainder_is_removed_alone(self):
        self.assertEqual(
            required_double_removal_slots([0, 1, 7], 7, sessions=2, periods_per_session=5),
            {7},
        )

    def test_legacy_malformed_run_is_removed_whole(self):
        self.assertEqual(
            required_double_removal_slots([1, 2, 3], 2, sessions=2, periods_per_session=5),
            {1, 2, 3},
        )


class RevokeTeacherAccountTests(unittest.TestCase):
    def test_last_profile_preserves_account_and_revokes_access(self):
        account = SimpleNamespace(
            teacher_id=12,
            role="teacher",
            requested_teacher_name="Old request",
            requested_project_id=8,
            session_version=3,
        )
        revoke_last_teacher_profile(account)
        self.assertIsNone(account.teacher_id)
        self.assertEqual(account.role, "pending")
        self.assertIsNone(account.requested_teacher_name)
        self.assertIsNone(account.requested_project_id)
        self.assertEqual(account.session_version, 4)

    def test_missing_session_version_is_initialized(self):
        account = SimpleNamespace(
            teacher_id=12,
            role="teacher",
            requested_teacher_name=None,
            requested_project_id=None,
            session_version=None,
        )
        revoke_last_teacher_profile(account)
        self.assertEqual(account.session_version, 1)


class AdminPromotionCleanupTests(unittest.TestCase):
    def test_teacher_identity_is_cleared_before_admin_promotion(self):
        account = SimpleNamespace(
            teacher_id=12,
            requested_teacher_name="Nguyen Van A",
            requested_project_id=8,
        )
        clear_teacher_identity(account)
        self.assertIsNone(account.teacher_id)
        self.assertIsNone(account.requested_teacher_name)
        self.assertIsNone(account.requested_project_id)


class SlotParsingTests(unittest.TestCase):
    def test_bad_item_does_not_discard_other_valid_slots(self):
        self.assertEqual(parse_integer_set('[0, "bad", 2, true, 3.5]'), {0, 2})

    def test_invalid_json_still_returns_empty_set(self):
        self.assertEqual(parse_integer_set('[0,'), set())

    def test_out_of_range_input_is_rejected_in_strict_mode(self):
        with self.assertRaisesRegex(ValueError, "khoảng từ 0 đến 4"):
            normalize_slot_values([-1, 0, 4, 5], 5)

    def test_legacy_out_of_range_values_can_be_sanitized(self):
        self.assertEqual(
            normalize_slot_values([-1, 0, 4, 5], 5, strict=False),
            [0, 4],
        )


class FixedLessonValidationTests(unittest.TestCase):
    def test_excess_fixed_group_is_rejected(self):
        error = fixed_group_validation_error(
            [2],
            [(0, 2), (3, 2)],
            days=1,
            sessions=1,
            periods_per_session=5,
        )
        self.assertIn("vượt số lượng", error)

    def test_overlapping_fixed_groups_are_rejected(self):
        error = fixed_group_validation_error(
            [2, 2],
            [(0, 2), (1, 2)],
            days=1,
            sessions=1,
            periods_per_session=5,
        )
        self.assertIn("trùng nhau", error)

    def test_fixed_group_cannot_cross_session_boundary(self):
        error = fixed_group_validation_error(
            [2],
            [(4, 2)],
            days=1,
            sessions=2,
            periods_per_session=5,
        )
        self.assertIn("ranh giới buổi", error)

    def test_matching_fixed_task_is_consumed(self):
        pending = [
            {"size": 2, "anchor_slots": (), "candidate_starts": None},
            {"size": 1, "anchor_slots": (), "candidate_starts": None},
        ]
        item = pop_matching_fixed_task(pending, 3, 2)
        self.assertEqual(item["size"], 2)
        self.assertEqual([row["size"] for row in pending], [1])

    def test_unmatched_fixed_task_is_not_silently_consumed(self):
        pending = [{"size": 1, "anchor_slots": (), "candidate_starts": None}]
        self.assertIsNone(pop_matching_fixed_task(pending, 3, 2))
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
