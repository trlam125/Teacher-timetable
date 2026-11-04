"""Explicit compatibility exports for this package."""
from app.services.bootstrap.demo import ensure_demo, seed_project
from app.services.bootstrap.migrations.account_roles import migrate_account_roles
from app.services.bootstrap.migrations.accounts import migrate_accounts
from app.services.bootstrap.migrations.curriculum import migrate_curriculum
from app.services.bootstrap.migrations.entity_integrity import migrate_entity_integrity
from app.services.bootstrap.migrations.grade_locks import migrate_grade_locks
from app.services.bootstrap.migrations.legacy_projects import migrate_legacy_projects
from app.services.bootstrap.migrations.lesson_blocks import migrate_lesson_blocks
from app.services.bootstrap.migrations.lesson_integrity import migrate_lesson_integrity
from app.services.bootstrap.migrations.retire_school_locks import retire_school_locks
from app.services.bootstrap.migrations.schools_and_chat import migrate_schools_and_chat
from app.services.bootstrap.runtime import (
    acquire_database_bootstrap_lock,
    initialize_database,
    initialize_schema,
    run_database_bootstrap_step,
)
from app.services.bootstrap.schema import migrate_schema

__all__ = [
    'acquire_database_bootstrap_lock', 'ensure_demo', 'initialize_database',
    'initialize_schema', 'migrate_account_roles', 'migrate_accounts',
    'migrate_curriculum', 'migrate_entity_integrity', 'migrate_grade_locks',
    'migrate_legacy_projects', 'migrate_lesson_blocks', 'migrate_lesson_integrity',
    'migrate_schema', 'migrate_schools_and_chat', 'retire_school_locks',
    'run_database_bootstrap_step', 'seed_project',
]
