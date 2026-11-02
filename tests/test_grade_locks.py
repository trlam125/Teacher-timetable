"""Regression coverage for inherited grade locks; no PostgreSQL server required.

Run with: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/timetable_test")
os.environ.setdefault("SECRET_KEY", "grade-lock-tests-only")

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Assignment, Base, FixedLesson, Grade, Lesson, Project, SchoolClass, Subject, Teacher, User
from app.routers.constraints import constraints, save_session_locks
from app.scheduling.rules import class_blocked_slots, class_grade_blocked_slots, parse_slots
from app.scheduling.solver import solve_rebuild
from app.services.bootstrap.migrations.grade_locks import migrate_grade_locks
from app.services.entities.schemas import ConstraintIn, SessionLocksIn
from app.services.entities.updates.school_class import update_class_fields
from app.services.entities.validation import class_week_capacity
from app.services.projects import project_data
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from app.services.schedule_operations.placement import lesson_slot_error
from app.services.schedule_operations.validation import minimal_schedule_invalid_lessons


class GradeLockTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.user = User(email="admin@example.com", password_hash="test", role="super_admin", is_superadmin=True)
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(owner_id=self.user.id, name="TKB", days=2, sessions=2, periods_per_session=3)
        self.db.add(self.project)
        self.db.flush()
        self.grade = Grade(project_id=self.project.id, name="Khối 10")
        self.other_grade = Grade(project_id=self.project.id, name="Khối 11")
        self.db.add_all([self.grade, self.other_grade])
        self.db.flush()
        self.school_class = SchoolClass(project_id=self.project.id, grade_id=self.grade.id, name="10A1")
        self.other_class = SchoolClass(project_id=self.project.id, grade_id=self.other_grade.id, name="11A1")
        self.subject = Subject(project_id=self.project.id, name="Toán", short_name="T", max_consecutive=3)
        self.teacher = Teacher(project_id=self.project.id, name="GV 1", short_name="GV1", max_periods_day=6)
        self.other_teacher = Teacher(project_id=self.project.id, name="GV 2", short_name="GV2", max_periods_day=6)
        self.db.add_all([self.school_class, self.other_class, self.subject, self.teacher, self.other_teacher])
        self.db.flush()
        self.assignment = Assignment(project_id=self.project.id, class_id=self.school_class.id,
            subject_id=self.subject.id, teacher_id=self.teacher.id, periods_per_week=2)
        self.other_assignment = Assignment(project_id=self.project.id, class_id=self.other_class.id,
            subject_id=self.subject.id, teacher_id=self.other_teacher.id, periods_per_week=2)
        self.db.add_all([self.assignment, self.other_assignment])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def save(self, **values):
        values.setdefault("grade_id", self.grade.id)
        return save_session_locks(self.project.id, SessionLocksIn(**values), self.user, self.db)

    def lesson(self, assignment=None, slot=0, locked=False, block_id=None, block_size=1):
        row = Lesson(project_id=self.project.id, assignment_id=(assignment or self.assignment).id,
            slot=slot, locked=locked, block_id=block_id, block_size=block_size)
        self.db.add(row)
        self.db.commit()
        return row

    def test_session_expands_only_for_selected_grade(self):
        self.save(sessions=[0], slots=[8])
        self.assertEqual(parse_slots(self.grade.blocked_slots_json), {0, 1, 2, 8})
        self.assertEqual(parse_slots(self.project.blocked_slots_json), set())
        self.assertEqual(class_grade_blocked_slots(self.other_class), set())
        self.assertIsNotNone(lesson_slot_error(self.db, self.project, self.assignment, 1))
        self.assertIsNone(lesson_slot_error(self.db, self.project, self.other_assignment, 1))

    def test_new_class_inherits_saved_grade_locks(self):
        self.save(slots=[1, 4])
        new_class = SchoolClass(project_id=self.project.id, grade_id=self.grade.id, name="10A2")
        self.db.add(new_class)
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(class_grade_blocked_slots(self.db.get(SchoolClass, new_class.id)), {1, 4})

    def test_confirmation_displaces_only_selected_grade(self):
        affected = self.lesson()
        untouched = self.lesson(self.other_assignment, locked=True)
        response = self.save(slots=[0])
        preview = json.loads(response.body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(preview["affected_lesson_ids"], [affected.id])
        self.assertIsNotNone(self.db.get(Lesson, affected.id))
        self.assertEqual(parse_slots(self.grade.blocked_slots_json), set())
        result = self.save(slots=[0], confirm_displacement=True,
            confirmed_affected_lesson_ids=preview["affected_lesson_ids"])
        self.assertEqual(result["removed"], 1)
        self.assertIsNotNone(self.db.get(Lesson, untouched.id))

    def test_stale_confirmation_does_not_remove_lessons(self):
        first = self.lesson(slot=0)
        second = self.lesson(slot=1)
        response = self.save(slots=[0, 1], confirm_displacement=True,
            confirmed_affected_lesson_ids=[first.id])
        self.assertTrue(json.loads(response.body)["requires_confirmation"])
        self.assertIsNotNone(self.db.get(Lesson, second.id))

    def test_fixed_and_locked_lessons_are_protected(self):
        for use_fixed in (False, True):
            with self.subTest(fixed_metadata=use_fixed):
                if use_fixed:
                    self.db.add(FixedLesson(project_id=self.project.id,
                        assignment_id=self.assignment.id, slot=0, group_size=1))
                    self.db.commit()
                else:
                    self.lesson(locked=True)
                response = self.save(slots=[0], confirm_displacement=True)
                self.assertEqual(response.status_code, 409)
                self.assertFalse(json.loads(response.body).get("requires_confirmation", False))

    def test_required_double_is_displaced_as_whole_block(self):
        self.assignment.block_mode = "required_double"
        first = self.lesson(slot=0, block_id="pair", block_size=2)
        second = self.lesson(slot=1, block_id="pair", block_size=2)
        preview = json.loads(self.save(slots=[1]).body)
        self.assertEqual(set(preview["affected_lesson_ids"]), {first.id, second.id})
        result = self.save(slots=[1], confirm_displacement=True,
            confirmed_affected_lesson_ids=preview["affected_lesson_ids"])
        self.assertEqual(result["removed"], 2)

    def test_grade_lock_cannot_split_a_partially_locked_double(self):
        self.assignment.block_mode = "required_double"
        self.lesson(slot=0, locked=True, block_id="pair", block_size=2)
        self.lesson(slot=1, block_id="pair", block_size=2)
        response = self.save(slots=[1])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(json.loads(response.body).get("requires_confirmation", False))

    def test_required_double_needs_adjacent_available_periods(self):
        self.assignment.block_mode = "required_double"
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.save(slots=[1, 4, 7, 10])
        self.assertEqual(parse_slots(self.grade.blocked_slots_json), set())

    def test_unlock_preserves_global_and_class_rules(self):
        self.project.blocked_slots_json = "[0]"
        self.school_class.unavailable_json = "[1]"
        self.db.commit()
        self.save(slots=[0, 1, 2])
        self.save(slots=[])
        self.assertEqual(class_blocked_slots(self.school_class), {1})
        self.assertEqual(parse_slots(self.project.blocked_slots_json), {0})
        self.assertEqual(class_week_capacity(self.project, self.school_class), 10)

    def test_class_editor_cannot_bypass_inherited_capacity(self):
        self.grade.blocked_slots_json = json.dumps(list(range(10)))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            constraints(self.project.id, ConstraintIn(entity_type="class", entity_id=self.school_class.id,
                slots=[10]), self.user, self.db)
        self.assertEqual(error.exception.status_code, 409)

    def test_excessive_grade_locks_are_rejected_without_mutation(self):
        with self.assertRaises(HTTPException):
            self.save(slots=list(range(11)))
        self.assertEqual(parse_slots(self.grade.blocked_slots_json), set())

    def test_global_locks_still_account_for_grade_capacity(self):
        self.save(slots=list(range(10)))
        with self.assertRaises(HTTPException):
            self.save(grade_id=None, slots=[10])
        self.assertEqual(parse_slots(self.project.blocked_slots_json), set())

    def test_foreign_grade_and_out_of_range_values_are_rejected(self):
        other_project = Project(owner_id=self.user.id, name="Other")
        self.db.add(other_project)
        self.db.flush()
        foreign = Grade(project_id=other_project.id, name="Foreign")
        self.db.add(foreign)
        self.db.commit()
        for values, code in (({"grade_id": foreign.id}, 404), ({"slots": [12]}, 400), ({"sessions": [4]}, 400)):
            with self.subTest(values=values), self.assertRaises(HTTPException) as error:
                self.save(**values)
            self.assertEqual(error.exception.status_code, code)

    def test_legacy_global_payload_is_supported(self):
        result = save_session_locks(self.project.id, SessionLocksIn(sessions=[1]), self.user, self.db)
        self.assertTrue(result["ok"])
        self.assertEqual(parse_slots(self.project.blocked_slots_json), {3, 4, 5})

    def test_feasibility_validation_and_solver_respect_grade_locks(self):
        self.save(slots=[0, 1, 3, 4])
        self.assertFalse(assignment_completion_feasible(self.db, self.project, self.assignment, [0]))
        row = self.lesson(slot=0)
        invalid = minimal_schedule_invalid_lessons(self.db, self.project,
            [self.assignment, self.other_assignment], [row])
        self.assertIn(row.id, {item.id for item in invalid})
        self.db.delete(row)
        self.db.commit()
        for mode in ("free", "required_double"):
            self.assignment.block_mode = mode
            self.db.commit()
            result = solve_rebuild(self.db, self.project, tries=1)
            self.assertEqual(result["unscheduled"], 0)
            for assignment_id, slot, *_ in result["lessons"]:
                if assignment_id == self.assignment.id:
                    self.assertNotIn(slot, {0, 1, 3, 4})

    def test_class_transfer_checks_new_grade_and_updates_inheritance(self):
        self.other_grade.blocked_slots_json = "[0]"
        self.db.commit()
        row = self.lesson(slot=0)
        with self.assertRaises(HTTPException):
            update_class_fields(self.db, self.project, self.school_class,
                {"grade_id": self.other_grade.id}, self.school_class.name, self.project.id)
        self.db.rollback()
        self.assertEqual(self.school_class.grade_id, self.grade.id)
        self.db.delete(row)
        self.db.commit()
        update_class_fields(self.db, self.project, self.school_class,
            {"grade_id": self.other_grade.id}, self.school_class.name, self.project.id)
        self.db.commit()
        self.assertEqual(class_grade_blocked_slots(self.school_class), {0})

    def test_project_data_exposes_grade_locks_separately(self):
        self.save(slots=[2])
        result = project_data(self.db, self.project)
        grade = next(row for row in result["grades"] if row["id"] == self.grade.id)
        self.assertEqual(grade["blocked_slots"], [2])
        school_class = next(row for row in result["classes"] if row["id"] == self.school_class.id)
        self.assertEqual(school_class["unavailable"], [])


class GradeLockMigrationTests(unittest.TestCase):
    def test_existing_schema_upgrade_is_idempotent(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE grades (id INTEGER PRIMARY KEY, name TEXT)")
            connection.exec_driver_sql("INSERT INTO grades (id, name) VALUES (1, '10')")
            migrate_grade_locks(connection, inspect(connection))
            migrate_grade_locks(connection, inspect(connection))
            self.assertEqual(connection.exec_driver_sql("SELECT blocked_slots_json FROM grades").scalar(), "[]")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
