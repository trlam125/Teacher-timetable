"""Compatibility entry point; implementations live in focused modules."""
from app.services.entities.curriculum.capacity import (
    assignment_project_reference_issues,
    schedule_teacher_capacity_issues,
    schedule_class_capacity_issues,
)
from app.services.entities.curriculum.validation import (
    grade_requirement_assignment_issues,
    block_mode_text,
    grade_requirement_for_assignment,
    ensure_assignment_matches_grade_requirement,
)
from app.services.entities.curriculum.comparison import (
    grade_requirement_extra_assignments,
    grade_requirement_missing_assignments,
)
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements

__all__ = [
    'assignment_project_reference_issues',
    'schedule_teacher_capacity_issues',
    'schedule_class_capacity_issues',
    'grade_requirement_assignment_issues',
    'block_mode_text',
    'grade_requirement_for_assignment',
    'ensure_assignment_matches_grade_requirement',
    'grade_requirement_extra_assignments',
    'grade_requirement_missing_assignments',
    'sync_assignments_to_grade_requirements',
]
