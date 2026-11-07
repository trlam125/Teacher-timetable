"""Local regression checks; GitHub Actions continues to run syntax checks only."""
import json
import os
import unittest
from copy import deepcopy

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
os.environ.setdefault("SECRET_KEY", "isolated-regression-checks")

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.main import create_app  # Register all model tables without starting the app.
from app.models import (
    Assignment, Base, FixedLesson, Grade, GradeSubjectRequirement, Lesson, Project, School, SchoolClass,
    Subject, Teacher, TeacherSubject, User,
)
from app.routers.project_changes import (
    ApplyChange, ChangeRequest, apply_change, preview_change, undo_change,
)
from app.services.change_impact.notifications import record_change_notice
from app.services.change_impact.state import capture
from app.services.edit_conflicts import current_edit_token, edit_token
from app.services.notification_models import ScheduleNotification
from app.services.schedule_notifications import register_schedule_notifications
from app.services.schedule_operations.validation import schedule_integrity_report

register_schedule_notifications()


class ChangeImpactRegressions(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(email="test@example.invalid", password_hash="", name="Admin", role="super_admin")
        school = School(name="School")
        self.db.add_all([self.user, school])
        self.db.flush()
        self.project = Project(owner_id=self.user.id, school_id=school.id, name="Project", school_name=school.name)
        self.db.add(self.project)
        self.db.flush()
        self.subject = Subject(project_id=self.project.id, name="Toán", short_name="T")
        self.teachers = [Teacher(project_id=self.project.id, name=f"Teacher {i}", short_name=f"T{i}") for i in (1, 2)]
        self.classes = [SchoolClass(project_id=self.project.id, name=f"6A{i}") for i in (1, 2)]
        self.db.add_all([self.subject, *self.teachers, *self.classes])
        self.db.flush()
        self.db.add_all([TeacherSubject(project_id=self.project.id, teacher_id=t.id, subject_id=self.subject.id)
                         for t in self.teachers])
        self.assignment = self.add_assignment(self.classes[0], self.teachers[0], [0, 1], demand=4)
        self.db.commit()

    def add_assignment(self, school_class, teacher, slots, demand=None):
        row = Assignment(project_id=self.project.id, class_id=school_class.id, subject_id=self.subject.id,
                         teacher_id=teacher.id, periods_per_week=demand or len(slots), block_mode="free")
        self.db.add(row)
        self.db.flush()
        for slot in slots:
            self.db.add(Lesson(project_id=self.project.id, assignment_id=row.id, slot=slot,
                               block_id=f"a{row.id}s{slot}", block_size=1, locked=False))
        self.db.flush()
        return row

    def request(self, kind="assignment", obj=None, entity_type="assignment", **values):
        obj = obj or self.assignment
        return ChangeRequest(kind=kind, entity_type=entity_type, entity_id=obj.id,
                             expected_token=current_edit_token(self.db, entity_type, obj), values=values)

    def preview(self, request):
        return preview_change(self.project.id, request, self.user, self.db)

    def apply(self, request, report=None):
        report = report or self.preview(request)
        self.assertTrue(report["can_apply"], report)
        return apply_change(self.project.id, ApplyChange(request=request, impact_token=report["impact_token"]),
                            self.user, self.db)

    def latest_notice(self):
        return self.db.scalar(select(ScheduleNotification).order_by(ScheduleNotification.id.desc()))

    def test_conflict_is_returned_to_tray_when_reduced_demand_still_exceeds_schedule(self):
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        request = self.request(teacher_id=self.teachers[1].id, periods_per_week=3)
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertTrue(report["can_apply"])
        self.assertEqual((report["totals"]["surplus"], report["totals"]["to_tray"]), (0, 1))
        self.assertEqual(report["totals"]["tray_after"], 2)
        self.assertEqual(capture(self.db, self.project), before)
        result = self.apply(request, report)
        self.assertEqual(result["displaced_lessons"], 1)
        self.assertEqual(result["surplus_lessons"], 0)

    def test_reducing_a_fully_scheduled_assignment_counts_surplus(self):
        report = self.preview(self.request(periods_per_week=1))
        self.assertTrue(report["can_apply"])
        self.assertEqual((report["totals"]["surplus"], report["totals"]["to_tray"]), (1, 0))

    def test_explicit_surplus_is_classified_before_conflicting_lessons(self):
        self.db.add_all([Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=slot,
                               block_id=f"extra{slot}", block_size=1, locked=False) for slot in (2, 3)])
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        request = self.request(teacher_id=self.teachers[1].id, periods_per_week=3)
        selected = self.db.scalar(select(Lesson.id).where(Lesson.assignment_id == self.assignment.id, Lesson.slot == 3))
        request.remove_lesson_ids = {str(self.assignment.id): [selected]}
        report = self.preview(request)
        self.assertTrue(report["can_apply"])
        self.assertEqual(report["totals"]["surplus"], 1)
        self.assertEqual(report["totals"]["to_tray"], 1)
        self.assertEqual({row["slot"]: row["action"] for row in report["lesson_actions"]},
                         {0: "to_tray", 3: "surplus"})

    def test_recalculation_accepts_default_conflict_selection_and_can_apply_and_undo(self):
        for mode, demand in (("free", 1), ("required_double", 2)):
            with self.subTest(mode=mode):
                # Undo replaces business rows; load their current ORM identities.
                self.assignment = self.db.get(Assignment, self.assignment.id)
                self.teachers = [self.db.get(Teacher, row.id) for row in self.teachers]
                self.assignment.block_mode = mode
                if mode == "required_double":
                    for lesson in self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)):
                        lesson.block_id = "required-pair"
                        lesson.block_size = 2
                    self.db.add_all([Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=slot,
                                           block_id="other-required-pair", block_size=2, locked=False)
                                     for slot in (2, 3)])
                self.teachers[1].unavailable_json = "[0]"
                self.db.commit()
                before = capture(self.db, self.project)
                request = self.request(teacher_id=self.teachers[1].id, periods_per_week=demand)
                first = self.preview(request)
                self.assertTrue(first["can_apply"], first)
                selected = [lid for row in first["removal_candidates"] if row["selected"] and not row["protected"]
                            for lid in row["lesson_ids"]]
                self.assertEqual(len(selected), 1 if mode == "free" else 2)
                request.remove_lesson_ids = {str(self.assignment.id): selected}
                for _ in range(2):
                    recalculated = self.preview(request)
                    self.assertTrue(recalculated["can_apply"], recalculated)
                    self.assertEqual(recalculated["lesson_actions"], first["lesson_actions"])
                    self.assertEqual(recalculated["totals"], first["totals"])
                    self.assertEqual(capture(self.db, self.project), before)
                result = self.apply(request, recalculated)
                remaining = self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)).all()
                self.assertEqual(sorted(row.slot for row in remaining), [1] if mode == "free" else [2, 3])
                self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])
                undo_change(self.project.id, result["change_id"], self.user, self.db)
                self.assertEqual(capture(self.db, self.project), before)

    def test_selection_accepts_both_conflicting_and_additional_surplus_lessons(self):
        self.db.add_all([Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=slot,
                               block_id=f"extra{slot}", block_size=1, locked=False) for slot in (2, 3)])
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        request = self.request(teacher_id=self.teachers[1].id, periods_per_week=3)
        rows = self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id, Lesson.slot.in_([0, 3]))).all()
        request.remove_lesson_ids = {str(self.assignment.id): [row.id for row in rows]}
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertTrue(report["can_apply"], report)
        self.assertEqual({row["slot"]: row["action"] for row in report["lesson_actions"]},
                         {0: "to_tray", 3: "surplus"})
        self.assertIn("giáo viên mới", next(row["reason"] for row in report["lesson_actions"] if row["slot"] == 0))
        self.assertEqual(capture(self.db, self.project), before)
        self.apply(request, report)
        self.assertEqual(sorted(row.slot for row in self.db.scalars(select(Lesson))), [1, 2])

    def test_recalculation_still_rejects_missing_or_foreign_lesson_ids(self):
        other = self.add_assignment(self.classes[1], self.teachers[0], [2])
        foreign_id = self.db.scalar(select(Lesson.id).where(Lesson.assignment_id == other.id))
        conflicting_id = self.db.scalar(select(Lesson.id).where(Lesson.assignment_id == self.assignment.id, Lesson.slot == 0))
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        before = capture(self.db, self.project)
        for invalid in (foreign_id, 999999):
            with self.subTest(invalid=invalid):
                request = self.request(teacher_id=self.teachers[1].id, periods_per_week=1)
                request.remove_lesson_ids = {str(self.assignment.id): [conflicting_id, invalid]}
                report = self.preview(request)
                self.assertFalse(report["can_apply"])
                self.assertIn("không thuộc phân công", report["blockers"][0]["message"])
                self.assertEqual(capture(self.db, self.project), before)

    def test_conflicting_double_block_must_still_be_selected_in_full(self):
        self.assignment.block_mode = "required_double"
        rows = self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)).all()
        for row in rows:
            row.block_id, row.block_size = "required-pair", 2
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        before = capture(self.db, self.project)
        request = self.request(teacher_id=self.teachers[1].id, periods_per_week=2)
        request.remove_lesson_ids = {str(self.assignment.id): [rows[0].id]}
        report = self.preview(request)
        self.assertFalse(report["can_apply"])
        self.assertIn("toàn bộ block tiết đôi", report["blockers"][0]["message"])
        self.assertEqual(capture(self.db, self.project), before)

    def test_selected_conflicting_pinned_double_block_is_still_protected(self):
        self.assignment.block_mode = "required_double"
        rows = self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)).all()
        for row in rows:
            row.block_id, row.block_size, row.locked = "required-pair", 2, True
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        before = capture(self.db, self.project)
        request = self.request(teacher_id=self.teachers[1].id, periods_per_week=2)
        request.remove_lesson_ids = {str(self.assignment.id): [row.id for row in rows]}
        report = self.preview(request)
        self.assertFalse(report["can_apply"])
        self.assertEqual(report["blockers"][0]["reason"], "protected_lessons")
        self.assertEqual(capture(self.db, self.project), before)

    def paired_schedule(self):
        self.assignment.block_mode = "required_double"
        for row in self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)):
            row.block_id, row.block_size = "pair0", 2
        self.db.add_all([Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=slot,
                               block_id="pair1", block_size=2, locked=False) for slot in (2, 3)])
        self.db.commit()

    def pinned_single_schedule(self, mode):
        self.assignment.periods_per_week = 3
        self.assignment.block_mode = mode
        if mode == "required_double":
            for row in self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)):
                row.block_id, row.block_size = "unlocked-pair", 2
        self.db.add(Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=5,
                           block_id="pinned-single", block_size=1, locked=True))
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=5, group_size=1))
        self.db.commit()

    def assert_preserves_pinned_single(self, request):
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertTrue(report["can_apply"], report)
        self.assertEqual(report["lesson_actions"], [])
        self.assertEqual(capture(self.db, self.project), before)
        result = self.apply(request, report)
        after = capture(self.db, self.project)
        self.assertEqual(after["tables"]["fixed_lessons"], before["tables"]["fixed_lessons"])
        self.assertEqual([row for row in after["tables"]["lessons"] if row["locked"]],
                         [row for row in before["tables"]["lessons"] if row["locked"]])
        self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])
        undo_change(self.project.id, result["change_id"], self.user, self.db)
        self.assertEqual(capture(self.db, self.project), before)

    def test_required_to_free_reduction_removes_whole_pairs_from_initial_preview(self):
        self.paired_schedule()
        for mode in ("free", "preferred_double"):
            for demand in (1, 3):
                with self.subTest(mode=mode, demand=demand):
                    self.assignment = self.db.get(Assignment, self.assignment.id)
                    before = capture(self.db, self.project)
                    request = self.request(block_mode=mode, periods_per_week=demand)
                    first = self.preview(request)
                    self.assertTrue(first["can_apply"], first)
                    expected_slots = [0, 1, 2, 3] if demand == 1 else [2, 3]
                    self.assertEqual([row["slot"] for row in first["lesson_actions"]], expected_slots)
                    self.assertEqual(first["totals"]["to_tray"], 1)
                    self.assertEqual(first["totals"]["tray_after"], 1)
                    selected = [lid for row in first["removal_candidates"] if row["selected"] for lid in row["lesson_ids"]]
                    request.remove_lesson_ids = {str(self.assignment.id): selected}
                    semantic = lambda report: [{key: value for key, value in row.items() if key != "reason"}
                                               for row in report["lesson_actions"]]
                    for _ in range(2):
                        recalculated = self.preview(request)
                        self.assertTrue(recalculated["can_apply"], recalculated)
                        self.assertEqual(semantic(first), semantic(recalculated))
                        self.assertEqual(first["totals"], recalculated["totals"])
                        self.assertEqual(capture(self.db, self.project), before)
                    result = self.apply(request, recalculated)
                    remaining = self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id)).all()
                    self.assertEqual(sorted(row.slot for row in remaining), [] if demand == 1 else [0, 1])
                    self.assertTrue(all(row.block_size == 1 for row in remaining))
                    self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])
                    undo_change(self.project.id, result["change_id"], self.user, self.db)
                    self.assertEqual(capture(self.db, self.project), before)

    def test_pairing_unlocked_singles_preserves_pinned_odd_single(self):
        self.pinned_single_schedule("free")
        self.assert_preserves_pinned_single(self.request(block_mode="required_double"))

    def test_unpairing_unlocked_pair_preserves_pinned_odd_single(self):
        self.pinned_single_schedule("required_double")
        self.assert_preserves_pinned_single(self.request(block_mode="free"))

    def test_grade_curriculum_mode_change_preserves_pinned_odd_single(self):
        self.pinned_single_schedule("free")
        grade = Grade(project_id=self.project.id, name="Grade 6")
        self.db.add(grade)
        self.db.flush()
        self.classes[0].grade = grade
        self.db.add(GradeSubjectRequirement(project_id=self.project.id, grade_id=grade.id,
                                           subject_id=self.subject.id, periods_per_week=3, block_mode="free"))
        self.db.commit()
        request = self.request("entity", grade, "grade", name=grade.name, subject_requirements=[{
            "subject_id": self.subject.id, "periods_per_week": 3, "block_mode": "required_double",
        }])
        self.assert_preserves_pinned_single(request)

    def test_pinned_pair_cannot_be_split_or_removed_by_mode_change(self):
        self.paired_schedule()
        for row in self.db.scalars(select(Lesson).where(Lesson.assignment_id == self.assignment.id, Lesson.slot.in_([0, 1]))):
            row.locked = True
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=0, group_size=2))
        self.db.commit()
        before = capture(self.db, self.project)
        for demand in (1, 4):
            with self.subTest(demand=demand):
                report = self.preview(self.request(block_mode="free", periods_per_week=demand))
                self.assertFalse(report["can_apply"])
                self.assertIn("cố định", report["blockers"][0]["message"])
                self.assertEqual(capture(self.db, self.project), before)

    def test_pinned_single_cannot_be_repurposed_into_a_required_pair(self):
        self.assignment.periods_per_week = 2
        row = self.db.scalar(select(Lesson).where(Lesson.assignment_id == self.assignment.id, Lesson.slot == 1))
        row.locked = True
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=1, group_size=1))
        self.db.commit()
        before = capture(self.db, self.project)
        report = self.preview(self.request(block_mode="required_double"))
        self.assertFalse(report["can_apply"])
        self.assertIn("cố định", report["blockers"][0]["message"])
        self.assertEqual(capture(self.db, self.project), before)

    def test_rename_and_undo_preserve_preexisting_conflict(self):
        self.add_assignment(self.classes[1], self.teachers[0], [0])
        self.db.commit()
        self.assertFalse(schedule_integrity_report(self.db, self.project)["valid"])
        before = capture(self.db, self.project)
        request = self.request("entity", self.teachers[1], "teacher", name="New display name", short_name="T2")
        report = self.preview(request)
        self.assertTrue(report["can_apply"], report)
        self.assertFalse(report["requires_edit_mode"])
        result = self.apply(request, report)
        self.assertEqual(self.db.get(Teacher, self.teachers[1].id).name, "New display name")
        undo_change(self.project.id, result["change_id"], self.user, self.db)
        self.assertEqual(capture(self.db, self.project), before)
        self.assertNotIn("project_change_managed", self.db.info)

    def bulk_request(self):
        extra = [SchoolClass(project_id=self.project.id, name=f"6A{i}") for i in (3, 4)]
        self.db.add_all(extra)
        self.db.flush()
        a2 = self.add_assignment(self.classes[1], self.teachers[0], [0])
        self.add_assignment(extra[0], self.teachers[1], [5])
        a4 = self.add_assignment(extra[1], self.teachers[1], [5])
        self.db.commit()
        return ChangeRequest(kind="delete", entity_type="assignment", entity_id=a2.id,
                             values={"entity_ids": [a2.id, a4.id]}), [a2.id, a4.id]

    def test_bulk_delete_validates_final_state_and_deduplicates_ids(self):
        request, ids = self.bulk_request()
        request.values["entity_ids"].append(ids[0])
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertTrue(report["can_apply"], report)
        self.assertEqual(capture(self.db, self.project), before)
        result = self.apply(request, report)
        self.assertEqual(result["deleted"], 2)
        self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])
        self.assertTrue(all(self.db.get(Assignment, aid) is None for aid in ids))
        self.assertEqual(self.latest_notice().removed_count, 2)

    def test_bulk_delete_that_leaves_a_conflict_is_blocked_without_live_changes(self):
        request, ids = self.bulk_request()
        request.values["entity_ids"] = ids[:1]
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertFalse(report["can_apply"])
        self.assertEqual(report["blockers"][0]["reason"], "invalid_schedule")
        self.assertEqual(capture(self.db, self.project), before)

    def test_bulk_delete_keeps_protected_lessons(self):
        request, ids = self.bulk_request()
        lesson = self.db.scalar(select(Lesson).where(Lesson.assignment_id == ids[1]))
        lesson.locked = True
        self.db.commit()
        before = capture(self.db, self.project)
        report = self.preview(request)
        self.assertFalse(report["can_apply"])
        self.assertEqual(report["blockers"][0]["reason"], "protected_lessons")
        self.assertEqual(capture(self.db, self.project), before)

    def test_undo_notice_counts_restored_lessons_and_is_not_duplicated(self):
        self.teachers[1].unavailable_json = "[0,1]"
        self.db.commit()
        request = self.request(teacher_id=self.teachers[1].id)
        before = capture(self.db, self.project)
        report = self.preview(request)
        result = self.apply(request, report)
        self.assertEqual(self.latest_notice().removed_count, 2)
        self.assertEqual(len(self.latest_notice().details), 2)
        notice_count = self.db.scalar(select(func.count()).select_from(ScheduleNotification))
        # Retrying the same request must not create another edit or notification.
        self.assertTrue(self.apply(request, report)["already_applied"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ScheduleNotification)), notice_count)
        undo_change(self.project.id, result["change_id"], self.user, self.db)
        notice = self.latest_notice()
        self.assertEqual((notice.added_count, notice.removed_count), (2, 0))
        self.assertEqual(len(notice.details), 2)
        for detail in notice.details:
            self.assertEqual(detail.action, "restored")
            payload = json.loads(detail.payload_json)
            self.assertIsNone(payload["before"])
            self.assertEqual(payload["after"]["teacher_name"], self.teachers[0].name)
        self.assertEqual(capture(self.db, self.project), before)
        count = self.db.scalar(select(func.count()).select_from(ScheduleNotification))
        self.assertTrue(undo_change(self.project.id, result["change_id"], self.user, self.db)["already_undone"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ScheduleNotification)), count)

    def test_teacher_update_notice_includes_kept_and_removed_lessons_once(self):
        self.teachers[1].unavailable_json = "[0]"
        self.db.commit()
        self.apply(self.request(teacher_id=self.teachers[1].id))
        notice = self.latest_notice()
        self.assertEqual((notice.removed_count, notice.moved_count), (1, 1))
        self.assertEqual(sorted(detail.action for detail in notice.details), ["removed", "updated"])

    def test_transfer_between_teachers_with_same_name_still_records_changes(self):
        self.teachers[1].name = self.teachers[0].name
        self.db.commit()
        self.apply(self.request(teacher_id=self.teachers[1].id))
        notice = self.latest_notice()
        self.assertEqual(notice.moved_count, 2)
        self.assertEqual([detail.action for detail in notice.details], ["updated", "updated"])

    def test_scheduling_change_does_not_bypass_integrity_validation(self):
        self.add_assignment(self.classes[1], self.teachers[0], [0])
        self.db.commit()
        request = ChangeRequest(kind="constraints", entity_type="teacher", entity_id=self.teachers[1].id,
                                expected_token=edit_token("availability", self.teachers[1]),
                                values={"slots": [9]})
        report = self.preview(request)
        self.assertFalse(report["can_apply"])
        self.assertEqual(report["blockers"][0]["reason"], "invalid_schedule")

    def test_notice_limit_preserves_total_and_includes_add_remove_move_and_lock(self):
        before = capture(self.db, self.project)
        after = deepcopy(before)
        rows = after["tables"]["lessons"]
        rows[0]["slot"] = 2
        rows[1]["locked"] = True
        template = rows[0]
        rows.extend([{**template, "id": 1000 + i, "slot": i} for i in range(110)])
        record_change_notice(self.db, self.project, before, after, "Restored", restored=True)
        self.db.commit()
        notice = self.latest_notice()
        self.assertEqual((notice.added_count, notice.moved_count, notice.locked_count), (110, 1, 1))
        self.assertEqual(len(notice.details), 100)

    def test_unmanaged_lesson_edits_still_create_notifications(self):
        lesson = self.db.scalar(select(Lesson).where(Lesson.assignment_id == self.assignment.id))
        lesson.slot = 3
        self.db.commit()
        self.assertEqual(self.latest_notice().moved_count, 1)

    def test_changed_state_invalidates_preview_without_applying(self):
        request = self.request(periods_per_week=3)
        report = self.preview(request)
        self.teachers[1].name = "Concurrent change"
        self.db.commit()
        before = capture(self.db, self.project)
        with self.assertRaises(HTTPException) as raised:
            self.apply(request, report)
        self.assertEqual(raised.exception.detail["reason"], "impact_stale")
        self.assertEqual(capture(self.db, self.project), before)


if __name__ == "__main__":
    unittest.main()
