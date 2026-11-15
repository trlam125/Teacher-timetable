import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import delete, func, select

import test_compact_scheduler as scheduling_fixtures
from app.models import ChatbotErrorLog, Lesson, SystemIncidentLog, TeacherSubject
from app.services.entities.schemas import GenerateScheduleIn
from app.services.schedule_generation import generate_schedule
from app.services.system_incidents import incident_log_view, record_system_incident
from app.services.web import templates


class SystemIncidentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = scheduling_fixtures.CompactSchedulerTests()
        self.fixture.setUp()
        self.db = self.fixture.db
        self.project = self.fixture.project
        self.actor = SimpleNamespace(id=42, name='Admin', email='admin@example.invalid')

    def tearDown(self):
        self.fixture.tearDown()

    def logs(self):
        return self.db.scalars(select(SystemIncidentLog).order_by(SystemIncidentLog.id)).all()

    def generate(self, payload=None):
        return generate_schedule(self.db, self.project, 1, payload, actor=self.actor)

    def prepare_partial_problem(self):
        self.project.days = 1
        self.project.periods_per_session = 2
        self.fixture.assignment(1, periods=2)
        self.fixture.assignment(2, school_class=2, periods=2)
        self.db.commit()

    def test_partial_schedule_records_actor_search_and_remaining_periods(self):
        self.prepare_partial_problem()
        result = self.generate()
        self.assertTrue(result['saved'])
        self.assertEqual(result['unscheduled'], 2)
        self.assertNotIn('search_diagnostics', result)
        row, = self.logs()
        self.assertEqual(row.error_code, 'scheduler_partial')
        self.assertEqual((row.project_id, row.project_name), (1, 'Test'))
        self.assertEqual((row.user_id, row.user_name, row.user_email),
                         (42, 'Admin', 'admin@example.invalid'))
        detail = json.loads(incident_log_view(row)['details'])
        self.assertEqual(detail['outcome']['unscheduled'], 2)
        self.assertTrue(detail['outcome']['saved'])
        self.assertIn('search_phases', detail['search'])
        self.assertIn('cp_sat_available', detail['runtime'])

    def test_complete_schedule_does_not_create_an_incident(self):
        self.fixture.assignment(1)
        self.db.commit()
        result = self.generate()
        self.assertEqual(result['unscheduled'], 0)
        self.assertNotIn('search_diagnostics', result)
        self.assertEqual(self.logs(), [])

    def test_solver_exception_logs_once_and_preserves_previous_schedule(self):
        self.fixture.assignment(1)
        self.db.add(Lesson(project_id=1, assignment_id=1, slot=0, locked=False,
                           block_id='original', block_size=1))
        self.db.commit()
        with patch('app.services.schedule_generation.solve_missing', side_effect=RuntimeError('postgresql://secret')):
            with self.assertRaises(RuntimeError):
                self.generate()
        row, = self.logs()
        self.assertEqual(row.error_code, 'scheduler_error')
        self.assertNotIn('postgresql://secret', row.error_message)
        detail = json.loads(incident_log_view(row)['details'])
        self.assertEqual(detail['outcome']['exception_type'], 'RuntimeError')
        self.assertEqual([row.slot for row in self.db.scalars(select(Lesson))], [0])

    def test_invalid_generated_schedule_is_rolled_back_and_logged(self):
        self.fixture.assignment(1, periods=1)
        self.fixture.assignment(2, teacher=2, periods=1)
        self.db.commit()
        invalid = {'lessons':[(1,0,False),(2,0,False)], 'unscheduled':0, 'score':0}
        with patch('app.services.schedule_generation.solve', return_value=invalid):
            with self.assertLogs('smart_tkb', level='ERROR'):
                result = self.generate()
        self.assertEqual(result.status_code, 500)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Lesson)), 0)
        row, = self.logs()
        self.assertEqual(row.error_code, 'scheduler_rejected')
        detail = json.loads(incident_log_view(row)['details'])
        self.assertFalse(detail['outcome']['validation']['integrity']['valid'])

    def test_input_rejection_is_logged_before_solver_runs(self):
        self.fixture.assignment(1)
        self.db.execute(delete(TeacherSubject))
        self.db.commit()
        with patch('app.services.schedule_generation.solve') as solver:
            result = self.generate()
        solver.assert_not_called()
        self.assertEqual(result.status_code, 409)
        row, = self.logs()
        self.assertEqual(row.error_code, 'scheduler_blocked')
        self.assertIn('teacher_subject_mismatch', row.error_message)

    def test_rebuild_confirmation_does_not_create_an_incident(self):
        self.fixture.assignment(1)
        self.db.add(Lesson(project_id=1, assignment_id=1, slot=0, locked=False,
                           block_id='original', block_size=1))
        self.db.commit()
        result = self.generate(GenerateScheduleIn(allow_rebuild=True, confirmed_rebuild_lesson_ids=[]))
        self.assertEqual(result.status_code, 409)
        self.assertTrue(json.loads(result.body)['requires_confirmation'])
        self.assertEqual(self.logs(), [])

    def test_log_failure_does_not_discard_a_valid_partial_schedule(self):
        self.prepare_partial_problem()
        with patch('app.services.schedule_generation.record_scheduler_incident', side_effect=RuntimeError('logging failed')):
            with self.assertLogs('smart_tkb', level='ERROR'):
                result = self.generate()
        self.assertTrue(result['saved'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Lesson)), 2)

    def test_shared_retention_and_legacy_ai_rows(self):
        self.assertIs(ChatbotErrorLog, SystemIncidentLog)
        self.db.commit()
        with patch('app.services.system_incidents.MAX_SYSTEM_INCIDENT_LOGS', 3):
            for code in ('chatbot_error', 'provider_timeout', 'scheduler_partial', 'scheduler_error'):
                record_system_incident(self.db, error_code=code, message='Example')
            self.db.commit()
        rows = self.logs()
        self.assertEqual(len(rows), 3)
        self.assertEqual([incident_log_view(row)['source_label'] for row in rows],
                         ['Trợ lý AI', 'Bộ xếp lịch', 'Bộ xếp lịch'])

    def test_recording_an_incident_does_not_commit_callers_transaction(self):
        self.db.commit()
        record_system_incident(self.db, error_code='scheduler_error', message='Example')
        self.db.rollback()
        self.assertEqual(self.logs(), [])

    def test_history_renders_escaped_details_only_for_super_admin(self):
        row = record_system_incident(self.db, error_code='scheduler_error', message='<script>bad</script>',
                                     details={'status':'failed'})
        context = {
            'request':SimpleNamespace(url=SimpleNamespace(path='/admin/users')),
            'user':SimpleNamespace(id=42,role='super_admin',name='Admin',email='admin@example.invalid',avatar_url=''),
            'users':[], 'schools':[], 'greeting_name':'Admin',
            'system_incident_logs':[incident_log_view(row)], 'system_incident_log_count':1,
            'system_incident_log_limit':500,
        }
        rendered = templates.env.get_template('users.html').render(**context)
        self.assertIn('Nhật ký sự cố hệ thống', rendered)
        self.assertIn('Bộ xếp lịch', rendered)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', rendered)
        self.assertNotIn('<script>bad</script>', rendered)
        context['user'].role = 'admin'
        rendered = templates.env.get_template('users.html').render(**context)
        self.assertNotIn('id="system-logs"', rendered)


if __name__ == '__main__':
    unittest.main()
