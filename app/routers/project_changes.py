from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SECRET_KEY
from app.models import Assignment, ProjectChange, User
from app.services.authentication.sessions import current_user, db_session
from app.services.change_impact.engine import execute
from app.services.change_impact.report import build_report
from app.services.change_impact.notifications import record_change_notice
from app.services.change_impact.state import capture, encoded, fingerprint, restore, simulation
from app.services.projects import get_project, get_project_for_update
from app.services.schedule_operations.validation import schedule_integrity_report

router = APIRouter()
signer = URLSafeTimedSerializer(SECRET_KEY, salt="project-change-preview-v1")
PREVIEW_MAX_AGE = 15 * 60


class ChangeRequest(BaseModel):
    kind: Literal["assignment", "entity", "constraints", "grade_locks", "delete", "reset"]
    entity_type: Literal["assignment", "department", "teacher", "subject", "grade", "class"]
    entity_id: int = Field(gt=0)
    expected_token: str | None = None
    values: dict = Field(default_factory=dict)
    resolutions: dict[str, str | int] = Field(default_factory=dict)
    remove_lesson_ids: dict[str, list[int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_kind(self):
        allowed = {"assignment": {"assignment"}, "entity": {"department", "teacher", "subject", "grade", "class"},
                   "constraints": {"teacher", "class"}, "grade_locks": {"grade"},
                   "reset": {"assignment"},
                   "delete": {"assignment", "department", "teacher", "subject", "grade", "class"}}
        if self.entity_type not in allowed[self.kind]:
            raise ValueError("Loại dữ liệu không phù hợp với thao tác.")
        return self


class ApplyChange(BaseModel):
    request: ChangeRequest
    impact_token: str = Field(max_length=12000)


def preview_state(db, project, user, request, before):
    with simulation(before, project, user) as (sandbox, sandbox_project, actor):
        result = execute(sandbox, sandbox_project, actor, request)
        after = capture(sandbox, sandbox_project)
        report = build_report(before, after, request, sandbox.info.get("change_lesson_reasons"))
        missing = result.get("missing_grade_assignments", [])
        if missing:
            report["warnings"].append(f"Còn {len(missing)} phân công lớp–môn cần bổ sung giáo viên.")
        return report


def error_report(exc, before):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    lesson_ids = set(detail.get("lesson_ids", []))
    assignments = {row["id"]: row for row in before["tables"]["assignments"]}
    classes = {row["id"]: row["name"] for row in before["tables"]["classes"]}
    subjects = {row["id"]: row["name"] for row in before["tables"]["subjects"]}
    teachers = {row["id"]: row["name"] for row in before["tables"]["teachers"]}
    lessons = []
    for row in before["tables"]["lessons"]:
        if row["id"] not in lesson_ids:
            continue
        assignment = assignments.get(row["assignment_id"], {})
        lessons.append({"lesson_id": row["id"], "slot": row["slot"],
                        "class_name": classes.get(assignment.get("class_id"), ""),
                        "subject_name": subjects.get(assignment.get("subject_id"), ""),
                        "teacher_name": teachers.get(assignment.get("teacher_id"), "")})
    return {"can_apply": False, "changed": False, "blockers": [{**detail, "lessons": lessons}],
            "changes": [], "assignments": [], "lesson_actions": [], "warnings": [],
            "totals": {}, "removal_candidates": []}


@router.post("/api/projects/{pid}/changes/preview")
def preview_change(pid: int, request: ChangeRequest, user: User = Depends(current_user), db: Session = Depends(db_session)):
    # Acquire only while reading a consistent snapshot, never during user confirmation.
    project = get_project_for_update(pid, user, db)
    before = capture(db, project)
    try:
        report = preview_state(db, project, user, request, before)
    except HTTPException as exc:
        if exc.status_code not in {400, 409, 428}:
            raise
        return error_report(exc, before)
    if report["changed"]:
        report["impact_token"] = signer.dumps({
            "operation": str(uuid.uuid4()), "project": pid, "user": user.id,
            "state": fingerprint(before), "request": fingerprint(request.model_dump()),
            "report": fingerprint(report),
        })
    return report


def receipt_result(receipt):
    return json.loads(receipt.result_json)


@router.post("/api/projects/{pid}/changes/apply")
def apply_change(pid: int, payload: ApplyChange, user: User = Depends(current_user), db: Session = Depends(db_session)):
    project = get_project_for_update(pid, user, db)
    try:
        token = signer.loads(payload.impact_token)
    except BadSignature as exc:
        raise HTTPException(409, "Bản xem trước không hợp lệ. Hãy xem ảnh hưởng lại.") from exc
    request_hash = fingerprint(payload.request.model_dump())
    if token.get("project") != pid or token.get("user") != user.id or token.get("request") != request_hash:
        raise HTTPException(409, "Bản xem trước không khớp với thay đổi đang yêu cầu.")
    receipt = db.get(ProjectChange, token.get("operation"))
    if receipt is not None:
        if receipt.project_id != pid or receipt.user_id != user.id or receipt.request_hash != request_hash:
            raise HTTPException(409, "Mã thao tác không hợp lệ.")
        return {**receipt_result(receipt), "already_applied": True, "undone": receipt.undone_at is not None}
    try:
        signer.loads(payload.impact_token, max_age=PREVIEW_MAX_AGE)
    except SignatureExpired as exc:
        raise HTTPException(409, {"reason": "impact_stale", "message": "Bản xem trước đã hết hạn sau 15 phút. Hãy xem ảnh hưởng lại."}) from exc
    before = capture(db, project)
    if token.get("state") != fingerprint(before):
        raise HTTPException(409, {"reason": "impact_stale", "message": "Dữ liệu đã thay đổi từ lúc xem trước. Hãy xem lại ảnh hưởng trước khi áp dụng."})
    report = preview_state(db, project, user, payload.request, before)
    if token.get("report") != fingerprint(report):
        raise HTTPException(409, {"reason": "impact_stale", "message": "Phạm vi ảnh hưởng đã thay đổi. Hãy xem lại."})
    db.info["project_change_managed"] = True
    try:
        result = execute(db, project, user, payload.request)
        after = capture(db, project)
        actual = build_report(before, after, payload.request, db.info.get("change_lesson_reasons"))
        actual["warnings"] = report["warnings"]
        if fingerprint(actual) != token["report"]:
            raise HTTPException(409, "Kết quả áp dụng khác bản xem trước. Dữ liệu chưa được lưu; hãy xem lại.")
        totals = report["totals"]
        title = {"assignment": "Sửa phân công", "entity": "Sửa dữ liệu", "constraints": "Sửa tiết tránh",
                 "grade_locks": "Sửa khóa khối", "delete": "Xóa dữ liệu", "reset": "Reset phân công"}[payload.request.kind]
        messages = ["Đã xóa dữ liệu" if payload.request.kind == "delete" else "Đã đặt lại phân công" if payload.request.kind == "reset" else "Đã cập nhật dữ liệu"]
        for key, label in (("kept", "giữ"), ("to_tray", "đưa về kho"), ("surplus", "bỏ tiết dư"), ("deleted", "xóa cùng phân công")):
            if totals[key]:
                messages.append(f"{label}: {totals[key]} tiết")
        result.update({"ok": True, "change_id": token["operation"], "totals": totals,
                       "displaced_lessons": totals["to_tray"], "surplus_lessons": totals["surplus"],
                       "removed": totals["to_tray"], "message": "; ".join(messages) + "."})
        if payload.request.kind == "assignment":
            from app.services.edit_conflicts import current_edit_token
            result["edit_token"] = current_edit_token(db, "assignment", db.get(Assignment, payload.request.entity_id))
        elif payload.request.kind == "entity":
            from app.services.change_impact.engine import target
            from app.services.edit_conflicts import current_edit_token
            result["edit_token"] = current_edit_token(db, payload.request.entity_type, target(
                db, project, payload.request.entity_type, payload.request.entity_id))
        receipt = ProjectChange(id=token["operation"], project_id=pid, user_id=user.id, title=title,
                                created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                                request_hash=request_hash, before_hash=fingerprint(before), after_hash=fingerprint(after),
                                snapshot_json=encoded(before), audit_json=encoded(report), result_json=encoded(result))
        db.add(receipt)
        record_change_notice(db, project, before, after, result["message"])
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        for key in ("project_change_managed", "change_lesson_reasons", "change_remove_lesson_ids"):
            db.info.pop(key, None)


@router.get("/api/projects/{pid}/changes")
def list_changes(pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    project = get_project_for_update(pid, user, db)
    current = fingerprint(capture(db, project))
    rows = db.scalars(select(ProjectChange).where(ProjectChange.project_id == pid)
                      .order_by(ProjectChange.created_at.desc(), ProjectChange.id.desc())).all()
    latest = next((row for row in rows if row.undone_at is None), None)
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_({row.user_id for row in rows}))).all())
    from fastapi.responses import JSONResponse
    return JSONResponse({"retention": "Bản dự phòng được giữ cho đến khi xóa vĩnh viễn project.", "items": [
        {"id": row.id, "title": row.title, "created_at": row.created_at, "undone_at": row.undone_at,
         "actor_name": names.get(row.user_id) or "Tài khoản không còn tồn tại",
         "can_undo": row is latest and row.after_hash == current and row.undone_at is None,
         "message": receipt_result(row).get("message", ""),
         "totals": receipt_result(row).get("totals", {})}
        for row in rows
    ]}, headers={"Cache-Control": "no-store"})


@router.get("/api/projects/{pid}/changes/{change_id}")
def change_details(pid: int, change_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    get_project(pid, user, db)
    receipt = db.get(ProjectChange, change_id)
    if receipt is None or receipt.project_id != pid:
        raise HTTPException(404, "Không tìm thấy lịch sử thay đổi.")
    from fastapi.responses import JSONResponse
    return JSONResponse({"audit": json.loads(receipt.audit_json)}, headers={"Cache-Control": "no-store"})


@router.post("/api/projects/{pid}/changes/{change_id}/undo")
def undo_change(pid: int, change_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    project = get_project_for_update(pid, user, db)
    receipt = db.get(ProjectChange, change_id)
    if receipt is None or receipt.project_id != pid:
        raise HTTPException(404, "Không tìm thấy bản dự phòng.")
    if receipt.undone_at is not None:
        return {"ok": True, "already_undone": True, "message": "Thay đổi này đã được hoàn tác."}
    latest = db.scalar(select(ProjectChange).where(ProjectChange.project_id == pid, ProjectChange.undone_at.is_(None))
                       .order_by(ProjectChange.created_at.desc(), ProjectChange.id.desc()).limit(1))
    if latest.id != receipt.id or fingerprint(capture(db, project)) != receipt.after_hash:
        raise HTTPException(409, "Project đã có thay đổi mới. Không thể hoàn tác đè lên dữ liệu hiện tại.")
    try:
        before = capture(db, project)
        restore(db, project, json.loads(receipt.snapshot_json))
        report = schedule_integrity_report(db, project, allow_partial=True)
        if not report["valid"]:
            raise HTTPException(409, "Bản dự phòng không vượt qua kiểm tra toàn vẹn. Dữ liệu hiện tại được giữ nguyên.")
        receipt.undone_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        record_change_notice(db, project, before, capture(db, project), "Đã phục hồi dữ liệu trước lần chỉnh sửa.", restored=True)
        from app.services.schedule_live import _mark_projects
        _mark_projects(db.connection(), {pid})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "message": "Đã phục hồi dữ liệu trước thay đổi. Liên kết chia sẻ được giữ nguyên."}
