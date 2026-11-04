"""Explicit compatibility exports for this package."""
from collections import Counter, defaultdict
from typing import Optional
from urllib.parse import quote
import asyncio
import io
import json
import os
import secrets
import time

from fastapi import (
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import SessionLocal
from app.logging_config import logger
from app.logic import normalize_slot_values
from app.models import (
    Assignment,
    ChatMessage,
    ChatbotErrorLog,
    Department,
    EmailChangeVerification,
    FixedLesson,
    Grade,
    GradeSubjectRequirement,
    Lesson,
    Project,
    School,
    SchoolClass,
    Subject,
    Teacher,
    TeacherPreference,
    TeacherSubject,
    User,
    UserSchool,
)
from app.scheduling.rules import (
    all_slots,
    assignment_requires_double,
    bounded_int,
    class_grade_blocked_slots,
    ensure_assignment_hard_feasible,
    fixed_row_size,
    next_required_double_block_size,
    normalized_block_mode,
    parse_slots,
    required_double_block_state,
    valid_slots,
)
from app.services.audit import read_schedule_audit_report_json, read_schedule_upload
from app.services.authentication.credentials import pwd
from app.services.authentication.permissions import (
    admin_can_manage_account,
    is_admin,
    is_super_admin,
    user_can_access_school,
    user_greeting_name,
    user_school_ids,
    user_schools,
)
from app.services.authentication.sessions import (
    current_user,
    db_session,
    public_base_url,
    set_session_cookie,
)
from app.services.entities.curriculum.validation import (
    block_mode_text,
    ensure_assignment_matches_grade_requirement,
    grade_requirement_for_assignment,
)
from app.services.entities.deletion import (
    assignment_delete_confirmation,
    assignment_delete_impact,
    delete_entity_related_rows,
    entity_delete_dependency,
    entity_delete_dependency_ids,
    required_text,
)
from app.services.entities.schemas import (
    AssignmentResetIn,
    BulkAssignmentIn,
    BulkAssignmentSubjectIn,
    BulkEntityDeleteIn,
    ConstraintIn,
    EntityDeleteIn,
    EntityIn,
    FixedIn,
    ManualLessonIn,
    MoveIn,
    PlacementOptionsIn,
    PreferenceReviewIn,
    SessionLocksIn,
)
from app.services.entities.validation import (
    class_assigned_periods,
    ensure_class_load_fits,
    ensure_unique_project_name,
    ensure_unique_teacher_short_name,
    replace_grade_requirements,
    replace_teacher_subjects,
    required_id,
    validated_subject_ids,
)
from app.services.preferences import preference_payload, teacher_own_preference_payload
from app.services.projects import (
    chatbot_project_data_for_user,
    chatbot_project_for_user,
    chatbot_ui_context,
    ensure_school_for_name,
    get_project,
    get_project_for_update,
    project_data,
    project_lessons_data,
    public_project_data,
    teacher_view_project,
    teacher_view_projects,
    validate_clone_source,
)
from app.services.realtime.manager import realtime_manager
from app.services.realtime.presence import _broadcast_delayed_offline, broadcast_school_presence
from app.services.realtime.utils import (
    _payload_school_id,
    _utc_now_iso,
    presence_recipients_for_user,
    presence_visible_user_ids,
    school_chat_user_ids,
    touch_user_last_seen,
    websocket_session_user,
)
from app.services.schedule_operations.blocks import (
    fixed_coverage_slots,
    lesson_block_members,
    new_schedule_block_id,
    normalize_assignment_fixed_rows,
)
from app.services.schedule_operations.feasibility import (
    assignment_completion_feasible,
    assignment_feasibility_context,
    assignment_pattern_label,
)
from app.services.schedule_operations.placement import lesson_slot_error
from app.services.schedule_operations.validation import schedule_integrity_report, schedule_ui_validation_report
from app.services.web import bounded_text, redirect_with_notice, templates
from app.settings import (
    APP_BASE_URL,
    DAYS,
    MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS,
    MAX_CHATBOT_ERROR_LOGS,
    MIN_PASSWORD_LENGTH,
)

__all__ = [
    'APP_BASE_URL', 'Assignment', 'AssignmentResetIn', 'BulkAssignmentIn',
    'BulkAssignmentSubjectIn', 'BulkEntityDeleteIn', 'ChatMessage', 'ChatbotErrorLog',
    'ConstraintIn', 'Counter', 'DAYS', 'Department', 'Depends',
    'EmailChangeVerification', 'EntityDeleteIn', 'EntityIn', 'File', 'FixedIn',
    'FixedLesson', 'Form', 'Grade', 'GradeSubjectRequirement', 'HTMLResponse',
    'HTTPException', 'JSONResponse', 'Lesson', 'MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS',
    'MAX_CHATBOT_ERROR_LOGS', 'MIN_PASSWORD_LENGTH', 'ManualLessonIn', 'MoveIn',
    'Optional', 'PlacementOptionsIn', 'PreferenceReviewIn', 'Project',
    'RedirectResponse', 'Request', 'School', 'SchoolClass', 'Session', 'SessionLocal',
    'SessionLocksIn', 'StarletteHTTPException', 'StreamingResponse', 'Subject',
    'Teacher', 'TeacherPreference', 'TeacherSubject', 'UploadFile', 'User',
    'UserSchool', 'WebSocket', 'WebSocketDisconnect', '_broadcast_delayed_offline',
    '_payload_school_id', '_utc_now_iso', 'admin_can_manage_account', 'all_slots',
    'assignment_completion_feasible', 'assignment_delete_confirmation',
    'assignment_delete_impact', 'assignment_feasibility_context',
    'assignment_pattern_label', 'assignment_requires_double', 'asyncio',
    'block_mode_text', 'bounded_int', 'bounded_text', 'broadcast_school_presence',
    'chatbot_project_data_for_user', 'chatbot_project_for_user', 'chatbot_ui_context',
    'class_assigned_periods', 'class_grade_blocked_slots', 'current_user',
    'db_session', 'defaultdict', 'delete', 'delete_entity_related_rows',
    'ensure_assignment_hard_feasible', 'ensure_assignment_matches_grade_requirement',
    'ensure_class_load_fits', 'ensure_school_for_name', 'ensure_unique_project_name',
    'ensure_unique_teacher_short_name', 'entity_delete_dependency',
    'entity_delete_dependency_ids', 'fixed_coverage_slots', 'fixed_row_size', 'func',
    'get_project', 'get_project_for_update', 'grade_requirement_for_assignment', 'io',
    'is_admin', 'is_super_admin', 'json', 'lesson_block_members', 'lesson_slot_error',
    'logger', 'new_schedule_block_id', 'next_required_double_block_size',
    'normalize_assignment_fixed_rows', 'normalize_slot_values',
    'normalized_block_mode', 'os', 'parse_slots', 'preference_payload',
    'presence_recipients_for_user', 'presence_visible_user_ids', 'project_data',
    'project_lessons_data', 'public_base_url', 'public_project_data', 'pwd', 'quote',
    'read_schedule_audit_report_json', 'read_schedule_upload', 'realtime_manager',
    'redirect_with_notice', 'replace_grade_requirements', 'replace_teacher_subjects',
    'required_double_block_state', 'required_id', 'required_text',
    'schedule_integrity_report', 'schedule_ui_validation_report',
    'school_chat_user_ids', 'secrets', 'select', 'set_session_cookie',
    'teacher_own_preference_payload', 'teacher_view_project', 'teacher_view_projects',
    'templates', 'time', 'touch_user_last_seen', 'user_can_access_school',
    'user_greeting_name', 'user_school_ids', 'user_schools', 'valid_slots',
    'validate_clone_source', 'validated_subject_ids', 'websocket_session_user',
]
