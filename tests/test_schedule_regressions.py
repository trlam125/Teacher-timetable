"""Regression tests for curriculum, pinning and exact deletion confirmation.

Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
os.environ.setdefault("SECRET_KEY", "schedule-regressions-only")

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Assignment, Base, FixedLesson, Grade, GradeSubjectRequirement, Lesson, Project, SchoolClass, Subject, Teacher, User
from app.routers.constraints import constraints, save_session_locks
from app.services.entities.schemas import ConstraintIn, SessionLocksIn
from app.services.entities.updates.grade import update_grade_fields
from app.services.entities.updates.school_class import update_class_fields
from app.services.projects import public_project_data
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from app.services.schedule_operations.validation import schedule_integrity_report


class ScheduleRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.user = User(email="regression@example.com", password_hash="test", role="super_admin", is_superadmin=True)
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(owner_id=self.user.id, name="Review", days=2, sessions=2, periods_per_session=3)
        self.db.add(self.project)
        self.db.flush()
        self.grade = Grade(project_id=self.project.id, name="10")
        self.other_grade = Grade(project_id=self.project.id, name="11")
        self.db.add_all([self.grade, self.other_grade])
        self.db.flush()
        self.school_class = SchoolClass(project_id=self.project.id, grade_id=self.grade.id, name="10A1")
        self.subject = Subject(project_id=self.project.id, name="Toán", short_name="T")
        self.extra_subject = Subject(project_id=self.project.id, name="Văn", short_name="V")
        self.teacher = Teacher(project_id=self.project.id, name="GV", short_name="GV")
        self.db.add_all([self.school_class, self.subject, self.extra_subject, self.teacher])
        self.db.flush()
        self.assignment = Assignment(project_id=self.project.id, class_id=self.school_class.id, subject_id=self.subject.id, teacher_id=self.teacher.id, periods_per_week=2)
        self.db.add(self.assignment)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def requirement(self, grade, subject, periods):
        self.db.add(GradeSubjectRequirement(project_id=self.project.id, grade_id=grade.id, subject_id=subject.id, periods_per_week=periods, block_mode="free"))
        self.db.commit()

    def extra_assignment(self, periods=1):
        row = Assignment(project_id=self.project.id, class_id=self.school_class.id, subject_id=self.extra_subject.id, teacher_id=self.teacher.id, periods_per_week=periods)
        self.db.add(row)
        self.db.commit()
        return row

    def pin(self, assignment=None, slot=1, with_lesson=True):
        assignment = assignment or self.assignment
        if with_lesson:
            self.db.add(Lesson(project_id=self.project.id, assignment_id=assignment.id, slot=slot, locked=True, block_id=f"pin-{assignment.id}-{slot}", block_size=1))
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=assignment.id, slot=slot, group_size=1))
        self.db.commit()

    def save_locks(self, **kwargs):
        kwargs.setdefault("grade_id", self.grade.id)
        return save_session_locks(self.project.id, SessionLocksIn(**kwargs), self.user, self.db)

    def grade_payload(self):
        return {"subject_requirements": [{"subject_id": self.subject.id, "periods_per_week": 2, "block_mode": "free"}]}

    def test_new_pin_invalidates_previous_deletion_confirmation(self):
        extra = self.extra_assignment()
        self.requirement(self.grade, self.subject, 2)
        self.requirement(self.grade, self.extra_subject, 1)
        payload = self.grade_payload()
        preview = update_grade_fields(self.db, self.project, self.grade, payload, self.grade.name, self.project.id)
        first = json.loads(preview.body)
        self.pin(extra, slot=3)
        payload.update(remove_extra_assignments=True, confirmed_extra_assignments_fingerprint=first["removal_fingerprint"])
        response = update_grade_fields(self.db, self.project, self.grade, payload, self.grade.name, self.project.id)
        second = json.loads(response.body)
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(first["removal_fingerprint"], second["removal_fingerprint"])
        self.assertEqual(second["affected_fixed_lessons"], 1)
        self.assertIsNotNone(self.db.get(Assignment, extra.id))
        self.assertEqual(len(self.db.scalars(select(Lesson)).all()), 1)
        payload["confirmed_extra_assignments_fingerprint"] = second["removal_fingerprint"]
        result = update_grade_fields(self.db, self.project, self.grade, payload, self.grade.name, self.project.id)
        self.db.commit()
        self.assertEqual(result[2], 1)
        self.assertEqual(self.db.scalars(select(FixedLesson)).all(), [])

    def test_assignment_edit_invalidates_confirmation_without_new_lesson_ids(self):
        extra = self.extra_assignment()
        self.requirement(self.grade, self.subject, 2)
        self.requirement(self.grade, self.extra_subject, 1)
        payload = self.grade_payload()
        first = json.loads(update_grade_fields(self.db, self.project, self.grade, payload, self.grade.name, self.project.id).body)
        extra.periods_per_week = 2
        self.db.commit()
        payload.update(remove_extra_assignments=True, confirmed_extra_assignments_fingerprint=first["removal_fingerprint"])
        response = update_grade_fields(self.db, self.project, self.grade, payload, self.grade.name, self.project.id)
        self.assertEqual(response.status_code, 409)

    def test_class_transfer_checks_final_load_after_confirmed_removal(self):
        extra = self.extra_assignment(periods=6)
        self.other_grade.blocked_slots_json = "[0,1,2,3,4,5]"
        self.requirement(self.other_grade, self.subject, 4)
        payload = {"grade_id": self.other_grade.id}
        preview = update_class_fields(self.db, self.project, self.school_class, payload, self.school_class.name, self.project.id)
        self.assertEqual(self.school_class.grade_id, self.grade.id)
        payload.update(remove_extra_assignments=True, confirmed_extra_assignments_fingerprint=json.loads(preview.body)["removal_fingerprint"])
        result = update_class_fields(self.db, self.project, self.school_class, payload, self.school_class.name, self.project.id)
        self.db.commit()
        self.assertEqual(result[2], 1)
        self.assertEqual(self.assignment.periods_per_week, 4)
        self.assertEqual(self.school_class.grade_id, self.other_grade.id)
        self.assertIsNone(self.db.get(Assignment, extra.id))

    def test_failed_transfer_rolls_back_confirmed_removal(self):
        extra = self.extra_assignment(periods=6)
        self.other_grade.blocked_slots_json = "[0,1,2,3,4,5]"
        self.requirement(self.other_grade, self.subject, 4)
        self.pin(slot=0)
        payload = {"grade_id": self.other_grade.id}
        preview = update_class_fields(self.db, self.project, self.school_class, payload, self.school_class.name, self.project.id)
        payload.update(remove_extra_assignments=True, confirmed_extra_assignments_fingerprint=json.loads(preview.body)["removal_fingerprint"])
        with self.assertRaises(HTTPException):
            update_class_fields(self.db, self.project, self.school_class, payload, self.school_class.name, self.project.id)
        self.db.rollback()
        self.assertIsNotNone(self.db.get(Assignment, extra.id))
        self.assertEqual(self.school_class.grade_id, self.grade.id)

    def test_curriculum_counts_union_of_global_and_grade_locks(self):
        self.project.blocked_slots_json = "[0,1]"
        self.grade.blocked_slots_json = "[1,2,3,4,5]"
        self.db.commit()
        with self.assertRaises(HTTPException):
            update_grade_fields(self.db, self.project, self.grade, {"subject_requirements": [{"subject_id": self.subject.id, "periods_per_week": 8}]}, self.grade.name, self.project.id)
        result = update_grade_fields(self.db, self.project, self.grade, {"subject_requirements": [{"subject_id": self.subject.id, "periods_per_week": 6}]}, self.grade.name, self.project.id)
        self.assertEqual(result[0], 1)

    def test_lock_rejects_unassigned_curriculum_over_capacity(self):
        self.db.delete(self.assignment)
        self.requirement(self.grade, self.subject, 8)
        for scope in (self.grade.id, None):
            with self.subTest(scope=scope), self.assertRaises(HTTPException):
                self.save_locks(grade_id=scope, slots=list(range(6)))
        self.assertEqual(self.grade.blocked_slots_json, "[]")
        self.assertEqual(self.project.blocked_slots_json, "[]")

    def test_grade_and_global_locks_cannot_strand_pinned_singleton(self):
        self.assignment.periods_per_week = 3
        self.assignment.block_mode = "required_double"
        self.pin()
        for scope in (self.grade.id, None):
            with self.subTest(scope=scope), self.assertRaises(HTTPException):
                self.save_locks(grade_id=scope, slots=list(range(3, 12)))
        self.assertEqual(self.grade.blocked_slots_json, "[]")

    def test_teacher_and_class_rules_cannot_strand_pinned_singleton(self):
        self.assignment.periods_per_week = 3
        self.assignment.block_mode = "required_double"
        self.pin()
        for entity_type, entity in (("teacher", self.teacher), ("class", self.school_class)):
            with self.subTest(entity_type=entity_type), self.assertRaises(HTTPException):
                constraints(self.project.id, ConstraintIn(entity_type=entity_type, entity_id=entity.id, slots=list(range(3, 12))), self.user, self.db)

    def test_missing_lesson_pin_metadata_still_constrains_new_locks(self):
        self.assignment.periods_per_week = 3
        self.assignment.block_mode = "required_double"
        self.pin(with_lesson=False)
        with self.assertRaises(HTTPException):
            self.save_locks(slots=list(range(3, 12)))

    def test_class_transfer_cannot_strand_pinned_singleton(self):
        self.assignment.periods_per_week = 3
        self.assignment.block_mode = "required_double"
        self.other_grade.blocked_slots_json = json.dumps(list(range(3, 12)))
        self.pin()
        with self.assertRaises(HTTPException):
            update_class_fields(self.db, self.project, self.school_class,
                                {"grade_id": self.other_grade.id}, self.school_class.name, self.project.id)
        self.db.rollback()
        self.assertEqual(self.school_class.grade_id, self.grade.id)

    def test_movable_lessons_do_not_cause_false_lock_rejection(self):
        self.assignment.block_mode = "required_double"
        extra = self.extra_assignment()
        self.db.add(Lesson(project_id=self.project.id, assignment_id=extra.id, slot=1, locked=False, block_id="movable", block_size=1))
        self.db.commit()
        result = self.save_locks(slots=list(range(3, 12)))
        self.assertTrue(result["ok"])

    def test_valid_pin_and_other_grade_stay_untouched(self):
        self.pin(slot=0)
        self.other_grade.blocked_slots_json = "[5]"
        self.db.commit()
        result = self.save_locks(slots=[3])
        self.assertTrue(result["ok"])
        self.assertEqual(self.other_grade.blocked_slots_json, "[5]")
        self.assertTrue(assignment_completion_feasible(self.db, self.project, self.assignment, [0]))

    def test_public_payload_exposes_inherited_grade_locks(self):
        self.grade.blocked_slots_json = "[2]"
        self.db.commit()
        result = public_project_data(self.db, self.project)
        self.assertEqual(result["classes"][0]["grade_id"], self.grade.id)
        self.assertEqual(result["grades"][0]["blocked_slots"], [2])

    def test_integrity_includes_detailed_conflicts(self):
        self.grade.blocked_slots_json = "[2]"
        self.db.add(Lesson(project_id=self.project.id, assignment_id=self.assignment.id, slot=2, block_id="invalid", block_size=1, locked=False))
        self.db.commit()
        report = schedule_integrity_report(self.db, self.project)
        self.assertEqual(len(report["invalid_lesson_conflicts"]), 1)
        self.assertEqual(report["invalid_lesson_conflicts"][0]["assignment_id"], self.assignment.id)
        self.assertTrue(report["invalid_lesson_conflicts"][0]["message"])


if __name__ == "__main__":
    unittest.main()
