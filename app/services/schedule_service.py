"""Compatibility entry point; implementations live in focused modules."""
from app.services.schedule_operations.feasibility import (
    assignment_feasibility_context,
    assignment_completion_feasible,
    assignment_pattern_label,
)
from app.services.schedule_operations.blocks import (
    new_schedule_block_id,
    lesson_block_members,
    reconcile_assignment_lesson_blocks,
    normalize_assignment_fixed_rows,
    fixed_coverage_slots,
    add_generated_lessons,
)
from app.services.schedule_operations.validation import (
    _minimal_schedule_invalid_lesson_analysis,
    minimal_schedule_invalid_lessons,
    schedule_ui_validation_report,
    schedule_integrity_report,
)
from app.services.schedule_operations.placement import lesson_slot_error

__all__ = [
    'assignment_feasibility_context',
    'assignment_completion_feasible',
    'assignment_pattern_label',
    'new_schedule_block_id',
    'lesson_block_members',
    'reconcile_assignment_lesson_blocks',
    'normalize_assignment_fixed_rows',
    'fixed_coverage_slots',
    'add_generated_lessons',
    'minimal_schedule_invalid_lessons',
    'schedule_ui_validation_report',
    'schedule_integrity_report',
    'lesson_slot_error',
]
