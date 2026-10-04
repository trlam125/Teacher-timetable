from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.schedule_service import *


class EntityIn(BaseModel):
    type: str
    data: dict


class BulkAssignmentSubjectIn(BaseModel):
    subject_id: int
    periods_per_week: int = 1
    block_mode: str = "free"


class BulkAssignmentIn(BaseModel):
    teacher_id: int
    class_ids: list[int]
    subjects: list[BulkAssignmentSubjectIn] = Field(default_factory=list)
    # Tương thích với client cũ trong lúc nâng cấp. Giao diện mới dùng subjects.
    subject_ids: list[int] = Field(default_factory=list)
    periods_per_week: int = 1
    block_mode: str = "free"


class AssignmentUpdateIn(BaseModel):
    periods_per_week: int
    block_mode: str = "free"
    confirm_displacement: bool = False
    confirmed_displaced_lesson_ids: list[int] | None = None


class EntityDeleteIn(BaseModel):
    confirm_assignment_cascade: bool = False
    confirmed_lesson_ids: list[int] = Field(default_factory=list)
    confirmed_fixed_lesson_ids: list[int] = Field(default_factory=list)


class BulkEntityDeleteIn(EntityDeleteIn):
    type: str
    ids: list[int]


class ConstraintIn(BaseModel):
    entity_type: str
    entity_id: int
    slots: list[int]
    confirm_displacement: bool = False
    confirmed_affected_lesson_ids: list[int] | None = None


class SessionLocksIn(BaseModel):
    sessions: list[int] = Field(default_factory=list)
    slots: list[int] = Field(default_factory=list)
    confirm_displacement: bool = False
    confirmed_affected_lesson_ids: list[int] | None = None


class FixedIn(BaseModel):
    assignment_id: int
    slot: int


class GenerateScheduleIn(BaseModel):
    allow_rebuild: bool = False
    confirmed_rebuild_lesson_ids: list[int] | None = None


class MoveIn(BaseModel):
    lesson_id: int
    slot: int
    move_scope: str = "group"


class PlacementOptionsIn(BaseModel):
    assignment_id: Optional[int] = None
    lesson_id: Optional[int] = None
    move_scope: str = "single"


class ManualLessonIn(BaseModel):
    assignment_id: int
    slot: int


class PreferenceReviewIn(BaseModel):
    action: str


__all__ = [name for name in globals() if not name.startswith("__")]
