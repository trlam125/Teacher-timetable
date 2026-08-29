import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
