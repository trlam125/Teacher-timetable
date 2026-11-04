import time
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment, Base, FixedLesson, Grade, Lesson, Project, SchoolClass, Subject,
    Teacher,
)
from app.scheduling.solver.api import solve, solve_missing, solve_rebuild


class PartialScheduleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.project = self.add(Project(
            owner_id=1, name="Regression", days=1, sessions=1,
            periods_per_session=2,
        ))

    def add(self, row):
        self.db.add(row)
        self.db.flush()
        return row

    def assignment(self, periods, *, teacher=None, school_class=None, **kwargs):
        teacher = teacher or self.add(Teacher(
            project_id=self.project.id, name="Teacher", short_name="T",
        ))
        school_class = school_class or self.add(SchoolClass(
            project_id=self.project.id, name="Class",
        ))
        subject = self.add(Subject(
            project_id=self.project.id, name="Subject", short_name="S",
        ))
        return self.add(Assignment(
            project_id=self.project.id, teacher_id=teacher.id,
            class_id=school_class.id, subject_id=subject.id,
            periods_per_week=periods, **kwargs,
        ))

    def lesson(self, assignment, slot, **kwargs):
        return self.add(Lesson(
            project_id=self.project.id, assignment_id=assignment.id,
            slot=slot, **kwargs,
        ))

    def run_solver(self, solver):
        return solver(self.db, self.project, deadline=time.monotonic() + 3)

    def test_missing_with_no_candidates_keeps_existing_and_counts_all_missing(self):
        assignment = self.assignment(4)
        before = [self.lesson(assignment, slot) for slot in (0, 1)]

        result = self.run_solver(solve_missing)

        self.assertEqual(result["unscheduled"], 2)
        self.assertEqual(result["lessons"], [])
        self.assertTrue(result["maximum_placed"])
        self.assertEqual(list(self.db.scalars(select(Lesson))), before)

    def test_empty_domain_does_not_discard_other_placeable_lessons(self):
        blocked = self.assignment(3)
        before = [self.lesson(blocked, slot) for slot in (0, 1)]
        available = self.assignment(1)

        result = self.run_solver(solve_missing)

        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual(len(result["lessons"]), 1)
        self.assertEqual(result["lessons"][0][0], available.id)
        self.assertTrue(result["maximum_placed"])
        self.assertEqual(list(self.db.scalars(select(Lesson))), before)

    def test_shared_teacher_infeasibility_returns_best_partial_schedule(self):
        self.project.periods_per_session = 3
        first = self.assignment(2)
        teacher = self.db.get(Teacher, first.teacher_id)
        self.assignment(2, teacher=teacher)
        self.lesson(first, 0)

        result = self.run_solver(solve_missing)

        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual(len(result["lessons"]), 2)
        slots = [row[1] for row in result["lessons"]]
        self.assertEqual(set(slots), {1, 2})
        self.assertTrue(result["maximum_placed"])

    def test_partial_search_places_available_required_double_as_one_block(self):
        self.project.periods_per_session = 3
        blocked = self.assignment(4)
        for slot in range(3):
            self.lesson(blocked, slot)
        double = self.assignment(2, block_mode="required_double")

        result = self.run_solver(solve_missing)

        self.assertEqual(result["unscheduled"], 1)
        lessons = result["lessons"]
        self.assertEqual(len(lessons), 2)
        self.assertEqual({row[0] for row in lessons}, {double.id})
        slots = sorted(row[1] for row in lessons)
        self.assertEqual(slots[1] - slots[0], 1)
        self.assertEqual(len({row[3] for row in lessons}), 1)

    def test_full_partial_schedule_respects_grade_and_teacher_blocked_slots(self):
        self.project.periods_per_session = 4
        grade = self.add(Grade(
            project_id=self.project.id, name="Grade", blocked_slots_json="[0]",
        ))
        school_class = self.add(SchoolClass(
            project_id=self.project.id, name="Class", grade=grade,
        ))
        assignment = self.assignment(3, school_class=school_class)
        self.db.get(Teacher, assignment.teacher_id).unavailable_json = "[1]"

        result = self.run_solver(solve)

        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual({row[1] for row in result["lessons"]}, {2, 3})

    def test_rebuild_preserves_pin_and_keeps_required_double_whole(self):
        self.project.periods_per_session = 3
        pinned = self.assignment(1)
        school_class = self.db.get(SchoolClass, pinned.class_id)
        pin = self.lesson(pinned, 1, locked=True)
        double = self.assignment(2, school_class=school_class, block_mode="required_double")

        result = self.run_solver(solve_rebuild)

        self.assertEqual(result["unscheduled"], 2)
        self.assertFalse(any(row[0] == double.id for row in result["lessons"]))
        self.assertEqual(list(self.db.scalars(select(Lesson))), [pin])
        self.assertTrue(pin.locked)

    def test_unavailable_forced_task_returns_without_missing_metadata_error(self):
        assignment = self.assignment(1)
        self.db.get(Teacher, assignment.teacher_id).unavailable_json = "[0]"
        self.add(FixedLesson(
            project_id=self.project.id, assignment_id=assignment.id,
            slot=0, group_size=1,
        ))

        result = self.run_solver(solve)

        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual(result["lessons"], [])
        self.assertFalse(result.get("maximum_placed", False))

    def test_feasible_missing_schedule_still_completes(self):
        assignment = self.assignment(2)
        pin = self.lesson(assignment, 0, locked=True)

        result = self.run_solver(solve_missing)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual([row[:2] for row in result["lessons"]], [(assignment.id, 1)])
        self.assertEqual(list(self.db.scalars(select(Lesson))), [pin])


if __name__ == "__main__":
    unittest.main()
