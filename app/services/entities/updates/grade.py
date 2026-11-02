from __future__ import annotations

from app.models import Assignment, Grade, GradeSubjectRequirement, Project
from app.services.entities.curriculum.comparison import (
    grade_requirement_extra_assignments,
    grade_requirement_missing_assignments,
)
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements
from app.services.entities.deletion import delete_entity_related_rows, extra_assignment_removal_confirmation
from app.services.entities.validation import (
    ensure_unique_project_name,
    normalized_grade_requirements,
    replace_grade_requirements,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_grade_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    ensure_unique_project_name(db, Grade, pid, name, "Khối lớp", exclude_id=obj.id)
    if "subject_requirements" in d:
        proposed_configs = normalized_grade_requirements(
            db, project, d.get("subject_requirements", []), grade_id=obj.id
        )
        current_rows = db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == pid,
                GradeSubjectRequirement.grade_id == obj.id,
            )
        ).all()
        current_configs = sorted(
            (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
            for row in current_rows
        )
        if sorted(proposed_configs) != current_configs:
            # Save the curriculum first so its new subjects can be assigned.
            # Generate/share/export still reject an incomplete curriculum.
            missing_grade_assignments = grade_requirement_missing_assignments(
                db, project, obj.id, proposed_configs
            )

            extra_assignments = grade_requirement_extra_assignments(
                db,
                project,
                obj.id,
                configs=proposed_configs,
            )
            confirmation = extra_assignment_removal_confirmation(
                db, extra_assignments, d, reason="grade_program_extra_assignments",
            )
            if confirmation is not None:
                return confirmation

            for item in extra_assignments:
                assignment = db.get(Assignment, item["assignment_id"])
                if not assignment or assignment.project_id != pid:
                    continue
                delete_entity_related_rows(db, "assignment", assignment.id)
                db.delete(assignment)
                removed_extra_assignments += 1
            db.flush()
            synced_assignments += sync_assignments_to_grade_requirements(
                db,
                project,
                obj.id,
                proposed_configs,
                displaced_lesson_ids=displaced_lesson_ids,
            )
        replace_grade_requirements(
            db, project, obj.id, d.get("subject_requirements", [])
        )
    obj.name = name
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
