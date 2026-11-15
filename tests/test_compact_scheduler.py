import time
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.models import (Assignment, Base, FixedLesson, Grade, Lesson, Project,
                        SchoolClass, Subject, Teacher, TeacherSubject)
from app.scheduling.solver.context import SearchBudget
from app.scheduling.solver.backtracking import exact_search
from app.scheduling.solver.cp_sat import solve_cp_sat
from app.scheduling.solver.cp_sat_compact import compact_task_groups
from app.scheduling.solver.genetic import GeneticSearch
from app.scheduling.solver.problem import build_problem
from app.scheduling.solver.repair import repair_placements
from app.scheduling.rules import normalized_block_mode, ensure_assignment_hard_feasible
from app.services.change_impact.reconcile import remove_consecutive_conflicts
from app.services.schedule_operations.blocks import add_generated_lessons
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from app.services.schedule_operations.validation import (
    minimal_schedule_invalid_lessons, schedule_integrity_report,
)
from app.services.schedule_validation import fixed_lesson_definition_issues
from app.services.schedule_generation import generate_schedule


class CompactSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.project = Project(id=1, owner_id=1, name='Test', days=2,
                               sessions=1, periods_per_session=3, blocked_slots_json='[]')
        self.db.add(self.project)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def assignment(self, aid, teacher=1, school_class=1, periods=2, mode='free'):
        if self.db.get(Teacher, teacher) is None:
            self.db.add(Teacher(id=teacher, project_id=1, name=f'T{teacher}',
                                short_name=f'T{teacher}', unavailable_json='[]'))
        if self.db.get(SchoolClass, school_class) is None:
            self.db.add(SchoolClass(id=school_class, project_id=1, name=f'C{school_class}'))
        self.db.add(Subject(id=aid, project_id=1, name=f'S{aid}', short_name=f'S{aid}'))
        self.db.add(TeacherSubject(project_id=1, teacher_id=teacher, subject_id=aid))
        assignment = Assignment(id=aid, project_id=1, teacher_id=teacher,
                                class_id=school_class, subject_id=aid,
                                periods_per_week=periods, block_mode=mode)
        self.db.add(assignment)
        self.db.flush()
        return assignment

    def solve(self, *, partial=False, mode='rebuild'):
        problem = build_problem(self.db, self.project, mode)
        self.assertNotIsInstance(problem, dict)
        phases = []
        result = solve_cp_sat(problem, SearchBudget(time.monotonic() + 3),
                              allow_partial=partial, search_phases=phases)
        self.assertIsNotNone(result)
        return problem, result, phases

    def assert_valid(self, result, *, complete=True):
        add_generated_lessons(self.db, self.project, result['lessons'])
        self.db.flush()
        report = schedule_integrity_report(self.db, self.project, allow_partial=not complete)
        self.assertTrue(report['valid'], report)
        self.assertEqual(report['complete'], complete, report)

    def test_rebuild_obeys_grade_teacher_and_consecutive_constraints(self):
        self.assignment(1, periods=3, mode='max_two_consecutive')
        self.assignment(2, teacher=2, school_class=1, periods=1)
        self.assignment(3, teacher=1, school_class=2, periods=1)
        self.db.get(Teacher, 1).unavailable_json = '[0]'
        grade = Grade(id=1, project_id=1, name='G', blocked_slots_json='[5]')
        self.db.add(grade)
        self.db.get(SchoolClass, 1).grade_id = 1
        self.db.flush()
        problem, result, phases = self.solve()
        self.assertEqual(result['unscheduled'], 0)
        self.assertTrue(phases[0]['phase'].startswith('cp_sat_compact'))
        self.assertEqual(len({(row[0], row[1]) for row in result['lessons']}), 5)
        decoded = GeneticSearch(problem).evaluate(result['genes'])
        self.assertEqual(decoded['unscheduled'], 0)
        self.assertEqual({row[:2] for row in decoded['lessons']},
                         {row[:2] for row in result['lessons']})
        self.assert_valid(result)

    def test_missing_preserves_locked_single_and_task_genes(self):
        self.assignment(1, periods=3, mode='max_two_consecutive')
        self.db.add(Lesson(project_id=1, assignment_id=1, slot=0, locked=True,
                           block_id='existing', block_size=1))
        self.db.flush()
        problem, result, _ = self.solve(mode='missing')
        self.assertEqual(len(result['genes']), len(problem.task_rows))
        self.assertNotIn(0, result['genes'])
        self.assert_valid(result)
        self.assertTrue(self.db.scalar(select(Lesson).where(Lesson.block_id=='existing')).locked)

    def test_full_infeasible_and_partial_maximum_under_teacher_collision(self):
        self.project.days = 1
        self.project.periods_per_session = 2
        self.assignment(1, periods=2)
        self.assignment(2, school_class=2, periods=2)
        _, full, _ = self.solve()
        self.assertTrue(full['proven_infeasible'])
        _, partial, _ = self.solve(partial=True)
        self.assertEqual(partial['unscheduled'], 2)
        self.assertTrue(partial['maximum_placed'])
        self.assert_valid(partial, complete=False)

    def test_partial_respects_max_two_consecutive(self):
        self.project.days = 1
        self.assignment(1, periods=3, mode='max_two_consecutive')
        _, result, _ = self.solve(partial=True)
        self.assertEqual(result['unscheduled'], 1)
        self.assertTrue(result['maximum_placed'])
        self.assert_valid(result, complete=False)

    def test_required_double_uses_task_solver_and_preserves_atomic_blocks(self):
        self.assignment(1, periods=3, mode='required_double')
        problem, result, phases = self.solve()
        self.assertIsNone(compact_task_groups(problem))
        self.assertEqual(result['unscheduled'], 0)
        self.assertFalse(any('compact' in phase['phase'] for phase in phases))
        self.assert_valid(result)

    def test_fixed_single_uses_task_solver_and_keeps_pin(self):
        self.assignment(1, periods=2, mode='preferred_double')
        self.db.add(FixedLesson(project_id=1, assignment_id=1, slot=1, group_size=1))
        self.db.flush()
        problem, result, _ = self.solve()
        self.assertIsNone(compact_task_groups(problem))
        self.assertIn((1, 1, True), [row[:3] for row in result['lessons']])
        self.assert_valid(result)

    def test_task_solver_partial_keeps_required_double_whole(self):
        self.project.days = 1
        self.project.periods_per_session = 2
        self.assignment(1, periods=2, mode='required_double')
        self.assignment(2, school_class=2, periods=2, mode='required_double')
        _, result, _ = self.solve(partial=True)
        self.assertEqual(result['unscheduled'], 2)
        self.assertTrue(result['maximum_placed'])
        self.assert_valid(result, complete=False)

    def test_preferred_double_keeps_canonical_objective(self):
        self.assignment(1, periods=2, mode='preferred_double')
        _, result, _ = self.solve()
        # One adjacent pair costs 8 for same-day spread and no pair penalty.
        self.assertEqual(result['score'], 8)
        self.assert_valid(result)

    def test_manual_edit_accepts_only_single_or_adjacent_pair_in_each_session(self):
        self.project.days = 2
        self.project.sessions = 2
        self.project.periods_per_session = 5
        assignment = self.assignment(1, periods=4, mode='max_two_consecutive')
        # Check every pattern within one session, as used by move/add/pin APIs.
        for mask in range(1 << 5):
            positions = [i for i in range(5) if mask & (1 << i)]
            expected = len(positions) <= 1 or len(positions) == 2 and positions[1] - positions[0] == 1
            with self.subTest(positions=positions):
                self.assertEqual(assignment_completion_feasible(
                    self.db, self.project, assignment, positions, allow_partial=True,
                ), expected)
        for positions in ([0, 1, 5, 6], [0, 1, 10, 11], [4, 5], [0, 5, 10, 15]):
            with self.subTest(separate_sessions=positions):
                self.assertTrue(assignment_completion_feasible(
                    self.db, self.project, assignment, positions, allow_partial=True,
                ))

    def test_weekly_capacity_is_at_most_two_per_session_and_allows_odd_total(self):
        self.project.days = 1
        self.project.sessions = 2
        self.project.periods_per_session = 5
        assignment = self.assignment(1, mode='max_two_consecutive')
        subject = self.db.get(Subject, assignment.subject_id)
        for total in (1, 3, 4):
            self.assertEqual(normalized_block_mode(
                'max_two_consecutive', total, subject, self.project,
            ), 'max_two_consecutive')
        with self.assertRaises(ValueError):
            normalized_block_mode('max_two_consecutive', 5, subject, self.project)

    def test_availability_counts_separated_free_slots_as_only_one(self):
        self.project.days = 1
        self.project.periods_per_session = 5
        assignment = self.assignment(1, mode='max_two_consecutive')
        teacher = self.db.get(Teacher, 1)
        teacher.unavailable_json = '[1,3,4]'
        with self.assertRaises(HTTPException) as error:
            ensure_assignment_hard_feasible(
                self.project, teacher, self.db.get(SchoolClass, 1),
                self.db.get(Subject, 1), 2, assignment.block_mode,
            )
        self.assertEqual(error.exception.status_code, 409)
        ensure_assignment_hard_feasible(
            self.project, teacher, self.db.get(SchoolClass, 1),
            self.db.get(Subject, 1), 1, assignment.block_mode,
        )

    def test_both_cp_models_reject_separated_slots_and_allow_single_partial(self):
        self.project.days = 1
        self.project.periods_per_session = 5
        assignment = self.assignment(1, mode='max_two_consecutive')
        self.db.get(Teacher, 1).unavailable_json = '[1,3,4]'
        for forced in (False, True):
            with self.subTest(task_model=forced):
                if forced:
                    self.db.add(FixedLesson(project_id=1, assignment_id=1, slot=0, group_size=1))
                    self.db.flush()
                _, full, _ = self.solve()
                self.assertTrue(full['proven_infeasible'])
                problem, partial, phases = self.solve(partial=True)
                self.assertEqual(partial['unscheduled'], 1)
                self.assertTrue(partial['maximum_placed'])
                self.assertEqual(compact_task_groups(problem) is None, forced)
                self.assert_valid(partial, complete=False)
                self.db.execute(delete(Lesson))
                self.db.flush()

    def test_second_pair_in_one_session_is_forbidden(self):
        self.project.days = 1
        self.project.periods_per_session = 5
        self.assignment(1, periods=4, mode='max_two_consecutive')
        self.db.get(Teacher, 1).unavailable_json = '[2]'
        _, partial, _ = self.solve(partial=True)
        self.assertEqual(partial['unscheduled'], 2)
        self.assert_valid(partial, complete=False)

    def test_solver_can_place_a_pair_in_both_morning_and_afternoon(self):
        self.project.days = 1
        self.project.sessions = 2
        self.project.periods_per_session = 5
        self.assignment(1, periods=4, mode='max_two_consecutive')
        _, result, _ = self.solve()
        self.assertEqual(result['unscheduled'], 0)
        self.assert_valid(result)

    def test_fallback_searches_obey_new_session_rule(self):
        self.project.days = 1
        self.project.periods_per_session = 5
        self.assignment(1, mode='max_two_consecutive')
        self.db.get(Teacher, 1).unavailable_json = '[1,3,4]'
        problem = build_problem(self.db, self.project, 'rebuild')
        genetic = GeneticSearch(problem).evaluate([0, 2])
        self.assertEqual(genetic['unscheduled'], 1)
        repair = repair_placements(
            problem.task_rows, problem.task_candidates, [0, None], problem.existing,
            problem.assignment_by_id, project=self.project, deadline=time.monotonic()+2,
        )
        self.assertEqual(repair['unscheduled'], 1)
        result, exhausted, _ = exact_search(problem, SearchBudget(time.monotonic()+2), 1000)
        self.assertIsNone(result)
        self.assertTrue(exhausted)

    def test_static_candidates_can_only_extend_single_to_adjacent_pair(self):
        self.project.periods_per_session = 5
        self.assignment(1, periods=3, mode='max_two_consecutive')
        self.db.add(Lesson(project_id=1, assignment_id=1, slot=1, locked=True,
                           block_id='pin', block_size=1))
        self.db.flush()
        problem = build_problem(self.db, self.project, 'missing')
        starts = {row[0] for row in problem.task_candidates[0]}
        self.assertIn(0, starts)
        self.assertIn(2, starts)
        self.assertNotIn(3, starts)
        self.assertNotIn(4, starts)
        self.db.add(Lesson(project_id=1, assignment_id=1, slot=2, locked=True,
                           block_id='pin2', block_size=1))
        self.db.flush()
        problem = build_problem(self.db, self.project, 'missing')
        self.assertTrue(all(row[0] >= 5 for row in problem.task_candidates[0]))

    def test_integrity_rejects_old_separated_singles_and_second_pair(self):
        self.project.days = 1
        self.project.periods_per_session = 5
        self.assignment(1, periods=4, mode='max_two_consecutive')
        for slots in ([0, 2], [0, 1, 3], [0, 1, 3, 4]):
            with self.subTest(slots=slots):
                add_generated_lessons(self.db, self.project, [(1, slot, False) for slot in slots])
                self.db.flush()
                report = schedule_integrity_report(self.db, self.project, allow_partial=True)
                self.assertFalse(report['valid'], report)
                self.assertTrue(report['invalid_lesson_ids'])
                self.db.execute(delete(Lesson))
                self.db.flush()

    def test_legacy_reconciliation_keeps_largest_adjacent_pair(self):
        self.project.periods_per_session = 5
        assignment = self.assignment(1, periods=3, mode='max_two_consecutive')
        add_generated_lessons(self.db, self.project, [(1, slot, False) for slot in (0, 2, 3)])
        self.db.flush()
        rows = self.db.scalars(select(Lesson).order_by(Lesson.slot)).all()
        invalid = minimal_schedule_invalid_lessons(self.db, self.project, [assignment], rows)
        self.assertEqual([row.slot for row in invalid], [0])
        kept = remove_consecutive_conflicts(self.db, self.project, assignment, rows)
        self.assertEqual([row.slot for row in kept], [2, 3])

    def test_legacy_reconciliation_preserves_single_pin(self):
        self.project.periods_per_session = 5
        assignment = self.assignment(1, periods=3, mode='max_two_consecutive')
        add_generated_lessons(self.db, self.project, [(1, slot, slot == 0) for slot in (0, 2, 3)])
        self.db.flush()
        rows = self.db.scalars(select(Lesson).order_by(Lesson.slot)).all()
        kept = remove_consecutive_conflicts(self.db, self.project, assignment, rows)
        self.assertEqual([(row.slot, row.locked) for row in kept], [(0, True)])

    def test_incompatible_pins_are_reported_and_never_removed(self):
        self.project.periods_per_session = 5
        assignment = self.assignment(1, periods=3, mode='max_two_consecutive')
        add_generated_lessons(self.db, self.project, [(1, slot, True) for slot in (0, 2)])
        for slot in (0, 2):
            self.db.add(FixedLesson(project_id=1, assignment_id=1, slot=slot, group_size=1))
        self.db.flush()
        rows = self.db.scalars(select(Lesson)).all()
        self.assertTrue(fixed_lesson_definition_issues(self.db, self.project, [assignment]))
        self.assertFalse(assignment_completion_feasible(
            self.db, self.project, assignment, [0, 2], allow_partial=True,
        ))
        invalid = minimal_schedule_invalid_lessons(self.db, self.project, [assignment], rows)
        self.assertTrue(any(row.locked for row in invalid))
        with self.assertRaises(HTTPException) as error:
            remove_consecutive_conflicts(self.db, self.project, assignment, rows)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.db.scalars(select(Lesson)).all()), 2)

    def test_generation_revalidates_old_schedule_and_fills_missing_in_another_session(self):
        self.project.periods_per_session = 5
        self.assignment(1, periods=3, mode='max_two_consecutive')
        add_generated_lessons(self.db, self.project, [(1, slot, False) for slot in (0, 2, 3)])
        self.db.flush()
        result = generate_schedule(self.db, self.project, 1, None)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['unscheduled'], 0)
        self.assertEqual(result['scheduled'], 3)
        self.assertTrue(schedule_integrity_report(self.db, self.project)['complete'])
        rows = self.db.scalars(select(Lesson).order_by(Lesson.slot)).all()
        self.assertEqual([row.slot for row in rows[:2]], [2, 3])
        self.assertGreaterEqual(rows[-1].slot, 5)

    def test_generation_rejects_conflicting_locked_singles_without_removing_them(self):
        self.project.periods_per_session = 5
        self.assignment(1, periods=3, mode='max_two_consecutive')
        add_generated_lessons(self.db, self.project, [(1, slot, True) for slot in (0, 2)])
        self.db.flush()
        result = generate_schedule(self.db, self.project, 1, None)
        self.assertEqual(result.status_code, 409)
        self.assertEqual([(row.slot, row.locked) for row in self.db.scalars(
            select(Lesson).order_by(Lesson.slot)).all()], [(0, True), (2, True)])


if __name__ == '__main__':
    unittest.main()
