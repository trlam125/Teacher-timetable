"""Explicit compatibility exports for this package."""
from app.services.entities.curriculum.capacity import assignment_project_reference_issues, schedule_class_capacity_issues
from app.services.entities.curriculum.comparison import grade_requirement_extra_assignments, grade_requirement_missing_assignments
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements
from app.services.entities.curriculum.validation import (
    block_mode_text,
    ensure_assignment_matches_grade_requirement,
    grade_requirement_assignment_issues,
    grade_requirement_for_assignment,
)
from app.services.entities.deletion import (
    assignment_delete_confirmation,
    assignment_delete_impact,
    delete_entity_related_rows,
    entity_delete_dependency,
    entity_delete_dependency_ids,
    extra_assignment_removal_confirmation,
    required_text,
    schedule_displacement_confirmation,
)
from app.services.entities.schemas import (
    AssignmentResetIn,
    AssignmentUpdateIn,
    BulkAssignmentIn,
    BulkAssignmentSubjectIn,
    BulkEntityDeleteIn,
    ConstraintIn,
    EntityDeleteIn,
    EntityIn,
    FixedIn,
    GenerateScheduleIn,
    ManualLessonIn,
    MoveIn,
    PlacementOptionsIn,
    PreferenceReviewIn,
    SessionLocksIn,
)
from app.services.entities.validation import (
    class_assigned_periods,
    class_week_capacity,
    duplicate_assignment_issues,
    ensure_class_load_fits,
    ensure_grade_program_fits,
    ensure_unique_project_name,
    ensure_unique_teacher_short_name,
    normalized_grade_requirements,
    replace_grade_requirements,
    replace_teacher_subjects,
    required_id,
    validated_subject_ids,
)

__all__ = [
    'AssignmentResetIn', 'AssignmentUpdateIn', 'BulkAssignmentIn',
    'BulkAssignmentSubjectIn', 'BulkEntityDeleteIn', 'ConstraintIn', 'EntityDeleteIn',
    'EntityIn', 'FixedIn', 'GenerateScheduleIn', 'ManualLessonIn', 'MoveIn',
    'PlacementOptionsIn', 'PreferenceReviewIn', 'SessionLocksIn',
    'assignment_delete_confirmation', 'assignment_delete_impact',
    'assignment_project_reference_issues', 'block_mode_text', 'class_assigned_periods',
    'class_week_capacity', 'delete_entity_related_rows', 'duplicate_assignment_issues',
    'ensure_assignment_matches_grade_requirement', 'ensure_class_load_fits',
    'ensure_grade_program_fits', 'ensure_unique_project_name',
    'ensure_unique_teacher_short_name', 'entity_delete_dependency',
    'entity_delete_dependency_ids', 'extra_assignment_removal_confirmation',
    'grade_requirement_assignment_issues', 'grade_requirement_extra_assignments',
    'grade_requirement_for_assignment', 'grade_requirement_missing_assignments',
    'normalized_grade_requirements', 'replace_grade_requirements',
    'replace_teacher_subjects', 'required_id', 'required_text',
    'schedule_class_capacity_issues', 'schedule_displacement_confirmation',
    'sync_assignments_to_grade_requirements', 'validated_subject_ids',
]
