"""Regression coverage for editing, sharing and exporting incomplete schedules.

Run with: .venv/Scripts/python.exe -m unittest discover -s tests -v
All data is isolated in an in-memory SQLite database.
"""
from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@127.0.0.1/unused"
os.environ["SECRET_KEY"] = "isolated-schedule-tests"
os.environ["SCHEDULE_SOLVER_TIMEOUT_SECONDS"] = "3"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Assignment, Base, FixedLesson, Grade, GradeSubjectRequirement, Lesson,
    Project, SchoolClass, Subject, Teacher, TeacherSubject, User,
)
from app.routers import constraints, share_export
from app.routers.entities import assignment_updates
from app.routers.schedule import editor, fixed
from app.services.entities.schemas import GenerateScheduleIn
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements
from app.services.projects import project_data, public_project_data
from app.services.runtime import current_user, db_session
from app.services.schedule_generation import generate_schedule
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from app.services.schedule_operations.validation import schedule_integrity_report


class PartialScheduleEditingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.user = User(email="test@example.com", password_hash="unused", role="super_admin")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(
            owner_id=self.user.id, name="Test", days=1, sessions=1,
            periods_per_session=4,
        )
        self.db.add(self.project)
        self.db.flush()
        self.grade = Grade(project_id=self.project.id, name="Khối 8")
        self.db.add(self.grade)
        self.db.commit()
        app = FastAPI()
        for router in (editor.router, fixed.router, constraints.router, share_export.router, assignment_updates.router):
            app.include_router(router)
        app.dependency_overrides[current_user] = lambda: self.user
        app.dependency_overrides[db_session] = lambda: self.db
        self.client = TestClient(app)
        self.base = f"/api/projects/{self.project.id}"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def assignment(self, periods=4, mode="free", unavailable=(3,), teacher=None, school_class=None):
        subject = Subject(project_id=self.project.id, name="Môn test", short_name="MT")
        teacher = teacher or Teacher(
            project_id=self.project.id, name="GV", short_name="GV",
            unavailable_json=json.dumps(list(unavailable)),
        )
        school_class = school_class or SchoolClass(
            project_id=self.project.id, grade_id=self.grade.id, name="8A",
        )
        self.db.add_all([subject, teacher, school_class])
        self.db.flush()
        self.db.add(TeacherSubject(
            project_id=self.project.id, teacher_id=teacher.id, subject_id=subject.id,
        ))
        assignment = Assignment(
            project_id=self.project.id, subject_id=subject.id, teacher_id=teacher.id,
            class_id=school_class.id, periods_per_week=periods, block_mode=mode,
        )
        self.db.add(assignment)
        self.db.commit()
        return assignment

    def block(self, assignment, slots, locked=False, block_id="block"):
        rows = [Lesson(
            project_id=self.project.id, assignment_id=assignment.id, slot=slot,
            locked=locked, block_id=block_id, block_size=len(slots),
        ) for slot in slots]
        self.db.add_all(rows)
        self.db.commit()
        return rows

    def post(self, path, payload):
        return self.client.post(self.base + path, json=payload)

    def test_manual_add_is_allowed_even_when_assignment_cannot_be_completed(self):
        assignment = self.assignment()
        options = self.post("/placement-options", {"assignment_id": assignment.id}).json()
        self.assertEqual(options["valid_slots"], [0, 1, 2])
        response = self.post("/lessons", {"assignment_id": assignment.id, "slot": 0})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["added_lessons"]), 1)
        report = schedule_integrity_report(self.db, self.project)
        self.assertTrue(report["valid"])
        self.assertEqual(report["missing_periods"], 3)

    def test_manual_move_and_pin_work_on_partial_schedule(self):
        assignment = self.assignment()
        lesson = self.block(assignment, [0])[0]
        options = self.post("/placement-options", {"lesson_id": lesson.id}).json()
        self.assertEqual(options["valid_slots"], [1, 2])
        response = self.post("/move", {"lesson_id": lesson.id, "slot": 2})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.post("/fixed", {"assignment_id": assignment.id, "slot": 2})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["pinned"], 1)
        row = self.db.scalar(select(Lesson).where(Lesson.assignment_id == assignment.id))
        self.db.refresh(row)
        self.assertTrue(row.locked)
        response = self.post("/move", {"lesson_id": row.id, "slot": 1})
        self.assertEqual(response.status_code, 409)

    def test_required_pair_add_move_pin_stays_atomic_on_partial_schedule(self):
        assignment = self.assignment(mode="required_double")
        options = self.post("/placement-options", {"assignment_id": assignment.id}).json()
        self.assertEqual(options["valid_slots"], [0, 1])
        response = self.post("/lessons", {"assignment_id": assignment.id, "slot": 0})
        self.assertEqual(response.status_code, 200, response.text)
        pair = response.json()["added_lessons"]
        self.assertEqual(len(pair), 2)
        response = self.post("/move", {"lesson_id": pair[0]["id"], "slot": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row["slot"] for row in response.json()["moved_lessons"]], [1, 2])
        response = self.post("/fixed", {"assignment_id": assignment.id, "slot": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["pinned"], 2)
        self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])

    def test_partial_edit_rejects_collisions_unavailability_and_invalid_slots(self):
        assignment = self.assignment()
        other = self.assignment(periods=1, teacher=self.db.get(Teacher, assignment.teacher_id))
        self.block(other, [1])
        options = self.post("/placement-options", {"assignment_id": assignment.id}).json()
        self.assertEqual(options["valid_slots"], [0, 2])
        for slot in (1, 3, -1, 4):
            with self.subTest(slot=slot):
                response = self.post("/lessons", {"assignment_id": assignment.id, "slot": slot})
                self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(self.db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id)).all())

    def test_partial_edit_rejects_class_collision_and_grade_locks(self):
        assignment = self.assignment(unavailable=())
        other = self.assignment(periods=1, unavailable=(), school_class=self.db.get(SchoolClass, assignment.class_id))
        self.block(other, [1])
        self.grade.blocked_slots_json = "[2]"
        self.db.commit()
        options = self.post("/placement-options", {"assignment_id": assignment.id}).json()
        self.assertEqual(options["valid_slots"], [0, 3])
        for slot in (1, 2):
            response = self.post("/lessons", {"assignment_id": assignment.id, "slot": slot})
            self.assertEqual(response.status_code, 409)

    def test_partial_edit_rejects_broken_pairs_and_cross_session_moves(self):
        assignment = self.assignment(mode="required_double", unavailable=())
        pair = self.block(assignment, [0, 1])
        response = self.post("/move", {"lesson_id": pair[0].id, "slot": 3})
        self.assertEqual(response.status_code, 409)
        response = self.post("/move", {"lesson_id": pair[0].id, "slot": 2, "move_scope": "single"})
        self.assertEqual(response.status_code, 409)
        self.db.delete(pair[1])
        self.db.commit()
        response = self.post("/fixed", {"assignment_id": assignment.id, "slot": 0})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(schedule_integrity_report(self.db, self.project)["valid"])

    def test_no_extra_single_is_permitted_for_required_double(self):
        assignment = self.assignment(periods=5, mode="required_double", unavailable=())
        self.assertTrue(assignment_completion_feasible(self.db, self.project, assignment, [0, 1, 3], allow_partial=True))
        self.assertFalse(assignment_completion_feasible(self.db, self.project, assignment, [0, 2], allow_partial=True))

    def test_missing_fixed_coverage_cannot_be_replaced_by_manual_move(self):
        assignment = self.assignment()
        lesson = self.block(assignment, [0], locked=True)[0]
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=assignment.id, slot=0, group_size=1))
        self.db.commit()
        response = self.post("/move", {"lesson_id": lesson.id, "slot": 1})
        self.assertEqual(response.status_code, 409)
        response = self.client.delete(self.base + f"/lessons/{lesson.id}")
        self.assertEqual(response.status_code, 409)

    def test_grade_lock_can_leave_missing_periods_and_preserves_other_grades(self):
        assignment = self.assignment(unavailable=())
        self.db.add(GradeSubjectRequirement(project_id=self.project.id, grade_id=self.grade.id, subject_id=assignment.subject_id, periods_per_week=4))
        other_grade = Grade(project_id=self.project.id, name="Khối 9", blocked_slots_json="[2]")
        self.db.add(other_grade)
        self.db.commit()
        response = self.post("/session-locks", {"grade_id": self.grade.id, "slots": [3]})
        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(self.grade)
        self.db.refresh(other_grade)
        self.assertEqual(json.loads(self.grade.blocked_slots_json), [3])
        self.assertEqual(json.loads(other_grade.blocked_slots_json), [2])

    def test_rule_change_requires_exact_confirmation_and_returns_entire_pair(self):
        assignment = self.assignment(mode="required_double", unavailable=())
        pair = self.block(assignment, [0, 1])
        payload = {"grade_id": self.grade.id, "slots": [1, 3]}
        response = self.post("/session-locks", payload)
        self.assertEqual(response.status_code, 409, response.text)
        ids = response.json()["affected_lesson_ids"]
        self.assertEqual(ids, sorted(row.id for row in pair))
        response = self.post("/session-locks", {**payload, "confirm_displacement": True, "confirmed_affected_lesson_ids": ids[:1]})
        self.assertEqual(response.status_code, 409)
        response = self.post("/session-locks", {**payload, "confirm_displacement": True, "confirmed_affected_lesson_ids": ids})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.db.scalars(select(Lesson)).all())

    def test_entity_constraints_allow_partial_and_preserve_pins(self):
        for entity_type in ("teacher", "class"):
            with self.subTest(entity_type=entity_type):
                assignment = self.assignment()
                lesson = self.block(assignment, [0], block_id=entity_type)[0]
                response = self.post("/fixed", {"assignment_id": assignment.id, "slot": 0})
                self.assertEqual(response.status_code, 200, response.text)
                entity_id = assignment.teacher_id if entity_type == "teacher" else assignment.class_id
                payload = {"entity_type": entity_type, "entity_id": entity_id, "slots": [2, 3]}
                response = self.post("/constraints", payload)
                self.assertEqual(response.status_code, 200, response.text)
                response = self.post("/constraints", {**payload, "slots": [0, 2, 3]})
                self.assertEqual(response.status_code, 409)
                self.db.refresh(lesson)
                self.assertTrue(lesson.locked)

    def test_grade_lock_rejects_pinned_pair(self):
        assignment = self.assignment(mode="required_double")
        self.block(assignment, [0, 1])
        self.assertEqual(self.post("/fixed", {"assignment_id": assignment.id, "slot": 0}).status_code, 200)
        response = self.post("/session-locks", {"grade_id": self.grade.id, "slots": [1]})
        self.assertEqual(response.status_code, 409)
        self.db.refresh(self.grade)
        self.assertEqual(self.grade.blocked_slots_json, "[]")

    def test_grade_order_is_natural_and_stable_after_updates(self):
        self.db.add_all([Grade(project_id=self.project.id, name=name) for name in ("Khối 7", "Khối 10", "Khối 6", "Khối 9")])
        self.db.commit()
        expected = ["Khối 6", "Khối 7", "Khối 8", "Khối 9", "Khối 10"]
        for _ in range(3):
            for loader in (project_data, public_project_data):
                self.assertEqual([row["name"] for row in loader(self.db, self.project)["grades"]], expected)
            response = self.post("/session-locks", {"grade_id": self.grade.id, "slots": [1]})
            self.assertEqual(response.status_code, 200, response.text)

    def test_integrity_share_and_export_distinguish_missing_from_conflicts(self):
        assignment = self.assignment()
        self.block(assignment, [0])
        response = self.client.get(self.base + "/schedule-integrity")
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertTrue(report["valid"])
        self.assertTrue(report["partial"])
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_periods"], 3)
        self.assertEqual(report["issue_count"], 0)
        self.assertIn("Các tiết đã xếp hợp lệ", report["message"])
        response = self.client.get(f"/share/{self.project.share_token}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("3 tiết chưa xếp", response.text)
        response = self.client.get(f"/projects/{self.project.id}/export.xlsx")
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(io.BytesIO(response.content))
        self.assertIn("3 tiết chưa xếp", str(workbook.active.cell(3, 1).value))
        self.assertFalse(schedule_integrity_report(self.db, self.project, allow_partial=False)["valid"])

    def test_collision_remains_an_integrity_error_on_partial_schedule(self):
        assignment = self.assignment()
        other = self.assignment(teacher=self.db.get(Teacher, assignment.teacher_id))
        self.block(assignment, [0], block_id="one")
        self.block(other, [0], block_id="two")
        response = self.client.get(self.base + "/schedule-integrity")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["invalid_lesson_ids"])

    def test_excess_periods_remain_an_integrity_error(self):
        assignment = self.assignment(periods=1)
        self.block(assignment, [0], block_id="one")
        self.block(assignment, [1], block_id="two")
        response = self.client.get(self.base + "/schedule-integrity")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["count_errors"][0]["actual"], 2)

    def test_missing_pinned_period_remains_an_integrity_error(self):
        assignment = self.assignment()
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=assignment.id, slot=0, group_size=1))
        self.db.commit()
        response = self.client.get(self.base + "/schedule-integrity")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["fixed_errors"][0]["missing_slots"], [0])

    def test_missing_curriculum_assignment_is_reported_as_incomplete(self):
        subject = Subject(project_id=self.project.id, name="Toán", short_name="T")
        school_class = SchoolClass(project_id=self.project.id, name="8A", grade_id=self.grade.id)
        self.db.add_all([subject, school_class])
        self.db.flush()
        self.db.add(GradeSubjectRequirement(project_id=self.project.id, grade_id=self.grade.id, subject_id=subject.id, periods_per_week=2))
        self.db.commit()
        response = self.client.get(self.base + "/schedule-integrity")
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertTrue(report["partial"])
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_curriculum"], 1)

    def setup_partial_structure_change(self):
        assignment = self.assignment(unavailable=())
        other = self.assignment(periods=2, unavailable=(), teacher=self.db.get(Teacher, assignment.teacher_id))
        for slot in (0, 1):
            self.block(assignment, [slot], block_id=f"own-{slot}")
        for slot in (2, 3):
            self.block(other, [slot], block_id=f"other-{slot}")
        return assignment

    def test_assignment_mode_change_preserves_valid_partial_pair(self):
        assignment = self.setup_partial_structure_change()
        response = self.client.put(self.base + f"/assignments/{assignment.id}", json={
            "periods_per_week": 4, "block_mode": "required_double",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scheduled_preserved"], 2)
        self.assertFalse(response.json()["displaced_lessons"])
        self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])

    def test_curriculum_sync_preserves_valid_partial_pair(self):
        assignment = self.setup_partial_structure_change()
        changed = sync_assignments_to_grade_requirements(
            self.db, self.project, self.grade.id,
            [(assignment.subject_id, 4, "required_double")],
        )
        self.assertEqual(changed, 1)
        self.db.commit()
        self.assertTrue(schedule_integrity_report(self.db, self.project)["valid"])

    def test_complete_schedule_keeps_complete_status(self):
        assignment = self.assignment(periods=2, unavailable=())
        self.block(assignment, [0], block_id="one")
        self.block(assignment, [1], block_id="two")
        report = schedule_integrity_report(self.db, self.project)
        self.assertTrue(report["complete"])
        self.assertFalse(report["partial"])

    def test_solver_partial_result_can_be_edited_and_pinned(self):
        assignment = self.assignment(mode="required_double")
        result = generate_schedule(self.db, self.project, self.project.id, GenerateScheduleIn())
        self.assertIsInstance(result, dict, getattr(result, "body", result))
        self.assertTrue(result["partial"])
        self.assertEqual(result["scheduled"], 2)
        rows = self.db.scalars(select(Lesson)).all()
        options = self.post("/placement-options", {"lesson_id": rows[0].id}).json()
        self.assertTrue(options["valid_slots"])
        response = self.post("/move", {"lesson_id": rows[0].id, "slot": options["valid_slots"][0]})
        self.assertEqual(response.status_code, 200, response.text)
        start = response.json()["moved_lessons"][0]["slot"]
        response = self.post("/fixed", {"assignment_id": assignment.id, "slot": start})
        self.assertEqual(response.status_code, 200, response.text)

    def test_first_generation_completes_shared_class_without_manual_retry(self):
        assignment = self.assignment(periods=2, unavailable=())
        self.assignment(periods=2, unavailable=(), school_class=self.db.get(SchoolClass, assignment.class_id))
        result = generate_schedule(self.db, self.project, self.project.id, GenerateScheduleIn())
        self.assertIsInstance(result, dict)
        self.assertEqual(result["scheduled"], 4)
        self.assertEqual(result["unscheduled"], 0)
        self.assertFalse(result["partial"])
        self.assertFalse(result.get("can_rebuild", False))
        self.assertTrue(schedule_integrity_report(self.db, self.project)["complete"])

    def test_solver_continues_repair_after_unproven_partial_incumbent(self):
        from ortools.sat.python import cp_model
        from app.scheduling.solver.api import solve

        self.assignment(periods=2, unavailable=())
        real_solver = cp_model.CpSolver
        calls = []

        class LimitedSearch:
            def __init__(self):
                self.solver = real_solver()
                self.parameters = self.solver.parameters

            def Solve(self, model):
                calls.append(len(calls))
                if len(calls) == 1:
                    # Simulate a hard-feasibility timeout without a solution.
                    return cp_model.UNKNOWN
                if len(calls) == 2:
                    # Provide a real, valid partial incumbent, while simulating
                    # a time-limited solver that has not proved its count best.
                    omitted = [model.GetIntVarFromProtoIndex(i)
                               for i, var in enumerate(model.Proto().variables)
                               if var.name.endswith("_unscheduled")]
                    model.Add(sum(omitted) >= 1)
                    status = self.solver.Solve(model)
                    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                    return cp_model.FEASIBLE
                return self.solver.Solve(model)

            def Value(self, var):
                return self.solver.Value(var)

            def WallTime(self):
                return self.solver.WallTime()

        with patch.object(cp_model, "CpSolver", LimitedSearch):
            result = solve(self.db, self.project)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(len(result["lessons"]), 2)

    def test_optimization_timeout_retains_complete_incumbent(self):
        from ortools.sat.python import cp_model
        from app.scheduling.solver.api import solve

        self.assignment(periods=2, unavailable=())
        real_solver = cp_model.CpSolver
        calls = []

        class LimitedOptimization:
            def __init__(self):
                self.solver = real_solver()
                self.parameters = self.solver.parameters
                self.did_solve = False

            def Solve(self, model):
                calls.append(len(calls))
                if len(calls) == 1:
                    self.did_solve = True
                    return self.solver.Solve(model)
                return cp_model.UNKNOWN

            def Value(self, var):
                return self.solver.Value(var)

            def WallTime(self):
                return self.solver.WallTime() if self.did_solve else 0

        with patch.object(cp_model, "CpSolver", LimitedOptimization):
            result = solve(self.db, self.project)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(len(result["lessons"]), 2)
        self.assertFalse(result["optimal"])

    def test_partial_optimization_never_sacrifices_period_count(self):
        from app.scheduling.solver.api import solve

        self.assignment(periods=4, mode="preferred_double")
        result = solve(self.db, self.project)
        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual(len(result["lessons"]), 3)
        self.assertTrue(result["maximum_placed"])

    def test_first_generation_optimizes_distribution_after_completing_periods(self):
        from app.scheduling.solver.api import solve

        self.project.days = 2
        self.project.periods_per_session = 2
        self.db.commit()
        self.assignment(periods=2, unavailable=())
        result = solve(self.db, self.project)
        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(result["score"], 0)
        self.assertEqual(len({row[1] // 2 for row in result["lessons"]}), 2)
        self.assertTrue(result["optimal"])

    def test_final_retry_preserves_pinned_pair_when_full_schedule_is_impossible(self):
        assignment = self.assignment(mode="required_double")
        pair = self.block(assignment, [0, 1], locked=True)
        self.db.add(FixedLesson(project_id=self.project.id, assignment_id=assignment.id, slot=0, group_size=2))
        self.db.commit()
        result = generate_schedule(self.db, self.project, self.project.id, GenerateScheduleIn(
            allow_rebuild=True, confirmed_rebuild_lesson_ids=[],
        ))
        self.assertIsInstance(result, dict)
        self.assertEqual(result["scheduled"], 2)
        self.assertEqual(result["unscheduled"], 2)
        self.assertEqual([row.id for row in self.db.scalars(select(Lesson).order_by(Lesson.slot)).all()], [row.id for row in pair])

    def test_first_generation_has_a_working_fallback_without_cp_sat(self):
        import builtins
        from app.scheduling.solver.api import solve

        self.assignment(periods=2, unavailable=())
        original_import = builtins.__import__

        def without_cp_sat(name, *args, **kwargs):
            if name == "ortools.sat.python":
                raise ImportError("Simulated unavailable CP-SAT")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_cp_sat):
            result = solve(self.db, self.project)
        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(len(result["lessons"]), 2)


if __name__ == "__main__":
    unittest.main()
