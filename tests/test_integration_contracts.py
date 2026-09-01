import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "app" / "templates" / "workspace.html").read_text(encoding="utf-8")


class IntegrationContractTests(unittest.TestCase):
    def test_main_python_parses(self):
        ast.parse(MAIN)

    def test_revoke_no_longer_deletes_account(self):
        start = MAIN.index("def revoke_teacher_account")
        end = MAIN.index("def teacher_profiles_for_user", start)
        function_source = MAIN[start:end]
        self.assertNotIn("db.delete(account)", function_source)
        self.assertIn("revoke_last_teacher_profile(account)", function_source)

    def test_generate_requires_explicit_rebuild_confirmation(self):
        self.assertIn("requires_confirmation", MAIN)
        self.assertIn("allow_rebuild", MAIN)
        self.assertIn("Bạn có đồng ý xếp lại phần không cố định không?", JS)

    def test_remove_endpoint_uses_group_removal(self):
        start = MAIN.index("def remove_manual_lesson")
        end = MAIN.index("@app.delete(\"/api/projects/{pid}/assignments", start)
        function_source = MAIN[start:end]
        self.assertIn("required_double_removal_slots", function_source)
        self.assertIn("Cụm tiết đôi có tiết cố định", function_source)

    def test_bootstrap_admin_clears_teacher_links_and_identity(self):
        start = MAIN.index("def ensure_demo")
        function_source = MAIN[start:]
        self.assertIn("TeacherAccountLink.user_id == user.id", function_source)
        self.assertIn("db.delete(link)", function_source)
        self.assertIn("clear_teacher_identity(user)", function_source)

    def test_solver_rejects_unmatched_fixed_tasks(self):
        start = MAIN.index("def ga_schedule")
        end = MAIN.index("def solve_missing", start)
        function_source = MAIN[start:end]
        self.assertIn("pop_matching_fixed_task", function_source)
        self.assertIn("invalid_fixed_assignment_ids.add", function_source)
        self.assertIn('"invalid_fixed_assignments"', function_source)

    def test_fixed_lesson_uniqueness_is_migrated(self):
        self.assertIn('name="uq_fixed_lesson"', MAIN)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_lesson", MAIN)

    def test_stored_slots_use_non_strict_cleanup(self):
        self.assertIn("strict=False", MAIN)

    def test_legacy_demo_session_migration_remaps_slots_first(self):
        migration_start = MAIN.index("legacy_demo_projects =")
        migration_end = MAIN.index("migrate_schema()", migration_start)
        migration_source = MAIN[migration_start:migration_end]
        self.assertIn("remap_slot_for_session_expansion", migration_source)
        self.assertIn("remap_slots_for_session_expansion", migration_source)
        self.assertIn('"lessons", "fixed_lessons"', migration_source)
        self.assertIn('"teacher_preferences": ("preferred_json", "unavailable_json")', migration_source)
        self.assertLess(
            migration_source.index("remap_slot_for_session_expansion"),
            migration_source.rindex("UPDATE projects SET sessions=2 WHERE id=%s"),
        )

    def test_locked_lessons_win_over_movable_conflicts_during_revalidation(self):
        generate_start = MAIN.index("# Rà lại lịch cũ trước mỗi lần xếp")
        generate_end = MAIN.index("existing_counts=Counter", generate_start)
        generate_source = MAIN[generate_start:generate_end]
        self.assertIn("target_locked=bool(lesson.locked)", generate_source)
        self.assertIn("if lesson.locked:", generate_source)
        self.assertIn("lesson for lesson in assignment_lessons if not lesson.locked", generate_source)

    def test_generate_counts_missing_periods_per_assignment(self):
        generate_start = MAIN.index('def generate(pid:int')
        generate_end = MAIN.index('def lesson_slot_error', generate_start)
        generate_source = MAIN[generate_start:generate_end]
        self.assertIn(
            'existing_counts=Counter(lesson.assignment_id for lesson in existing)',
            generate_source,
        )
        self.assertIn(
            'max(0,assignment.periods_per_week-existing_counts[assignment.id])',
            generate_source,
        )
        self.assertNotIn('expected-len(existing)', generate_source)

    def test_pattern_candidates_do_not_pin_other_anchored_groups(self):
        start = MAIN.index("def pattern_completion_plan")
        end = MAIN.index("def remaining_pattern_groups", start)
        function_source = MAIN[start:end]
        self.assertIn("[(target_size,candidate)]", function_source)
        self.assertNotIn("target_anchored_index", function_source)

    def test_workspace_mutations_use_inline_action_states_instead_of_status_popup(self):
        self.assertIn("function operationHeaders(headers={})", JS)
        self.assertIn("function setInlineActionState(button,state", JS)
        self.assertIn("function setTrayActionStatus(state,message", JS)

        generate_start = JS.index("async function generateSchedule")
        generate_end = JS.index("function goToAssignments", generate_start)
        generate_source = JS[generate_start:generate_end]
        self.assertIn("setScheduleActionState('loading')", generate_source)
        self.assertIn("headers:operationHeaders({'Content-Type':'application/json'})", generate_source)
        self.assertIn("await refresh(true)", generate_source)
        self.assertNotIn("beginTrackedOperation", generate_source)
        self.assertNotIn("toast(", generate_source)

        tray_start = JS.index("async function removeLesson")
        tray_end = JS.index("async function dropToTray", tray_start)
        tray_source = JS[tray_start:tray_end]
        self.assertGreaterEqual(tray_source.count("headers:operationHeaders()"), 4)
        self.assertGreaterEqual(tray_source.count("await refresh(true)"), 4)
        self.assertIn("setTrayActionStatus('loading'", tray_source)
        self.assertNotIn("beginTrackedOperation", tray_source)
        self.assertNotIn("toast(", tray_source)

    def test_schedule_audit_supports_integrated_drag_drop_import(self):
        self.assertIn('id="scheduleAuditDropzone"', WORKSPACE)
        self.assertIn('id="scheduleAuditFileActions"', WORKSPACE)
        self.assertIn("scheduleAuditDropzone.addEventListener('drop'", JS)
        self.assertIn("selectScheduleAuditFile(file)", JS)
        self.assertIn("function clearScheduleAuditFile(", JS)
        self.assertIn("function scheduleAuditFileValidationError(file)", JS)
        self.assertIn("if(autoRun)runScheduleAudit()", JS)

    def test_file_drop_outside_audit_zone_is_prevented(self):
        self.assertIn("includes('Files')", JS)
        self.assertIn("event.target?.closest?.('#scheduleAuditDropzone')", JS)

    def test_schedule_audit_ignores_stale_async_results(self):
        self.assertIn("let scheduleAuditRunId=0", JS)
        self.assertIn("if(runId!==scheduleAuditRunId)return", JS)


if __name__ == "__main__":
    unittest.main()
