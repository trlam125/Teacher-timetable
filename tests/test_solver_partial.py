import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment, Base, FixedLesson, Grade, Lesson, Project, SchoolClass, Subject,
    Teacher,
)
from app.scheduling.solver.api import solve, solve_missing, solve_rebuild


class PartialScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # DLL loading is startup work; keep it outside the per-search deadline.
        from ortools.sat.python import cp_model
        cp_model.CpModel()

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

    def test_rebuild_reuses_saved_positions_when_deadline_is_exhausted(self):
        self.project.periods_per_session = 4
        assignment = self.assignment(1)
        original = self.lesson(assignment, 3)

        result = solve_rebuild(self.db, self.project, deadline=time.monotonic() - 1)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual([row[:2] for row in result["lessons"]], [(assignment.id, 3)])
        self.assertEqual(result["reused_periods"], 1)
        self.assertEqual(list(self.db.scalars(select(Lesson))), [original])

    def test_rebuild_saved_doubles_follow_block_identity_among_adjacent_lessons(self):
        self.project.periods_per_session = 6
        assignment = self.assignment(5, block_mode="required_double")
        for slot, block_id, size in ((0, "single", 1), (1, "left", 2),
                                     (2, "left", 2), (3, "right", 2), (4, "right", 2)):
            self.lesson(assignment, slot, block_id=block_id, block_size=size)

        result = solve_rebuild(self.db, self.project, deadline=time.monotonic() - 1)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(result["reused_periods"], 5)
        groups = {}
        for _owner, slot, _locked, token in result["lessons"]:
            groups.setdefault(token, set()).add(slot)
        self.assertCountEqual(groups.values(), [{0}, {1, 2}, {3, 4}])

    def test_neighborhood_moves_blocker_and_freezes_unrelated_saved_task(self):
        from app.scheduling.solver.repair import repair_placements
        self.project.periods_per_session = 3
        blocker = self.assignment(1)
        self.db.get(Teacher, blocker.teacher_id).unavailable_json = "[2]"
        school_class = self.db.get(SchoolClass, blocker.class_id)
        missing = self.assignment(1, school_class=school_class)
        self.db.get(Teacher, missing.teacher_id).unavailable_json = "[1, 2]"
        unrelated = self.assignment(1)
        self.lesson(blocker, 0)
        self.lesson(unrelated, 2)
        pin_owner = self.assignment(1)
        pin = self.lesson(pin_owner, 1, locked=True)

        # Exercise CP-SAT's local repair when recursive relocation is exhausted.
        with patch("app.scheduling.solver.genetic.repair_placements",
                   side_effect=lambda *args, **kwargs: repair_placements(*args, **kwargs, node_limit=0)):
            result = self.run_solver(solve_rebuild)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(result["solver"], "cp_sat_neighborhood")
        self.assertEqual({row[:2] for row in result["lessons"]},
                         {(blocker.id, 1), (missing.id, 0), (unrelated.id, 2)})
        self.assertEqual(result["reused_periods"], 3)
        self.assertEqual(result["search_phases"][0]["movable_tasks"], 2)
        self.assertTrue(pin.locked)
        self.assertEqual(pin.slot, 1)

    def test_neighborhood_moves_required_double_without_splitting_it(self):
        from app.scheduling.solver.repair import repair_placements
        self.project.periods_per_session = 5
        self.project.blocked_slots_json = "[4]"
        blocker = self.assignment(2, block_mode="required_double")
        school_class = self.db.get(SchoolClass, blocker.class_id)
        missing = self.assignment(2, school_class=school_class, block_mode="required_double")
        self.db.get(Teacher, missing.teacher_id).unavailable_json = "[2, 3]"
        self.lesson(blocker, 0, block_id="old", block_size=2)
        self.lesson(blocker, 1, block_id="old", block_size=2)

        with patch("app.scheduling.solver.genetic.repair_placements",
                   side_effect=lambda *args, **kwargs: repair_placements(*args, **kwargs, node_limit=0)):
            result = self.run_solver(solve_rebuild)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(result["solver"], "cp_sat_neighborhood")
        groups = {}
        for owner, slot, _locked, token in result["lessons"]:
            groups.setdefault((owner, token), set()).add(slot)
        self.assertCountEqual(groups.values(), [{0, 1}, {2, 3}])
        self.assertEqual(len(groups), 2)
        from app.services.schedule_operations.blocks import add_generated_lessons
        from app.scheduling.rules import required_double_block_state
        for lesson in self.db.scalars(select(Lesson)).all():
            self.db.delete(lesson)
        self.db.flush()
        add_generated_lessons(self.db, self.project, result["lessons"])
        self.db.flush()
        for assignment in (blocker, missing):
            lessons = self.db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id)).all()
            state = required_double_block_state(self.project, assignment, lessons)
            self.assertTrue(state["valid"])
            self.assertEqual(state["missing_sizes"], [])

    def test_rebuild_removes_saved_hint_that_now_violates_teacher_availability(self):
        assignment = self.assignment(1)
        self.lesson(assignment, 0)
        self.db.get(Teacher, assignment.teacher_id).unavailable_json = "[0]"

        result = self.run_solver(solve_rebuild)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual([row[:2] for row in result["lessons"]], [(assignment.id, 1)])
        self.assertEqual(result["reused_periods"], 0)

    def test_partial_local_optimum_does_not_claim_global_maximum(self):
        from ortools.sat.python import cp_model
        from app.scheduling.solver.repair import repair_placements
        self.project.periods_per_session = 3
        blocker = self.assignment(1)
        missing = self.assignment(1, school_class=self.db.get(SchoolClass, blocker.class_id))
        self.db.get(Teacher, missing.teacher_id).unavailable_json = "[1, 2]"
        self.lesson(blocker, 0)
        over_capacity = self.assignment(4)
        for slot in range(3):
            self.lesson(over_capacity, slot)

        # Expire the request immediately after the first local solve, so a
        # later global solve cannot supply a separate proof of optimality.
        monotonic = time.monotonic
        original_solve = cp_model.CpSolver.Solve
        offset = [0]

        def solve_then_expire(solver, model):
            status = original_solve(solver, model)
            offset[0] = 100
            return status

        with patch("app.scheduling.solver.genetic.repair_placements",
                   side_effect=lambda *args, **kwargs: repair_placements(*args, **kwargs, node_limit=0)), \
             patch.object(cp_model.CpSolver, "Solve", solve_then_expire), \
             patch("app.scheduling.solver.genetic.time.monotonic",
                   side_effect=lambda: monotonic() + offset[0]):
            deadline = monotonic() + 3
            result = solve_rebuild(self.db, self.project, deadline=deadline)

        self.assertEqual(result["unscheduled"], 1)
        self.assertEqual(result["solver"], "cp_sat_neighborhood")
        self.assertFalse(result["maximum_placed"])
        self.assertFalse(result["optimal"])
        self.assertTrue(result["search_limited"])
        self.assertEqual(result["search_phases"][0]["status"], "OPTIMAL")

    def test_school_sized_rebuild_fills_ten_blocked_periods(self):
        self.project.days = 5
        self.project.sessions = 2
        self.project.periods_per_session = 5
        # A synthetic 498-period / 272-assignment project, with ten independent
        # displacement chains. This is not the user's exported project.
        pairs_to_split = 13
        for class_index in range(10):
            school_class = self.add(SchoolClass(
                project_id=self.project.id, name=f"Class {class_index}",
            ))
            missing = self.assignment(1, school_class=school_class)
            self.db.get(Teacher, missing.teacher_id).unavailable_json = str(list(range(1, 50)))
            blocker = self.assignment(2, school_class=school_class)
            # The missing lesson needs slot 0. Its blocker can move to slot 1.
            self.lesson(blocker, 0)
            self.lesson(blocker, 2)
            last_slot = 48 if class_index == 9 else 50
            remaining = list(range(3, last_slot))
            while remaining:
                size = 2 if len(remaining) >= 2 else 1
                if size == 2 and pairs_to_split:
                    size = 1
                    pairs_to_split -= 1
                    # Split both halves of this otherwise two-period group.
                    assignment = self.assignment(1, school_class=school_class)
                    self.lesson(assignment, remaining.pop(0))
                assignment = self.assignment(size, school_class=school_class)
                for _ in range(size):
                    self.lesson(assignment, remaining.pop(0))

        assignments = list(self.db.scalars(select(Assignment)))
        self.assertEqual(sum(a.periods_per_week for a in assignments), 498)
        self.assertEqual(len(assignments), 272)
        self.assertEqual(len(list(self.db.scalars(select(Lesson)))), 488)

        result = self.run_solver(solve_rebuild)

        self.assertEqual(result["unscheduled"], 0)
        self.assertEqual(len(result["lessons"]), 498)
        self.assertEqual(result["reused_periods"], 488)
        owners = {a.id: a for a in assignments}
        teacher_slots = set()
        class_slots = set()
        for owner_id, slot, *_ in result["lessons"]:
            owner = owners[owner_id]
            teacher_key = (owner.teacher_id, slot)
            class_key = (owner.class_id, slot)
            self.assertNotIn(teacher_key, teacher_slots)
            self.assertNotIn(class_key, class_slots)
            teacher_slots.add(teacher_key)
            class_slots.add(class_key)


if __name__ == "__main__":
    unittest.main()
