from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from .common import ENTITY_MODELS
from app.models import (
    Assignment,
    FixedLesson,
    Lesson,
    User,
)
from app.services.authentication.sessions import current_user, db_session
from app.services.entities.deletion import (
    assignment_delete_confirmation,
    assignment_delete_impact,
    delete_entity_related_rows,
    entity_delete_dependency,
    entity_delete_dependency_ids,
)
from app.services.entities.schemas import AssignmentResetIn, BulkEntityDeleteIn, EntityDeleteIn
from app.services.projects import get_project_for_update
from app.services.change_impact.managed import require_preview

router = APIRouter()


@router.post("/api/projects/{pid}/assignments/reset")
def reset_assignments(
    pid: int,
    payload: AssignmentResetIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    require_preview(db)
    rows = db.scalars(
        select(Assignment).where(Assignment.project_id == pid).order_by(Assignment.id)
    ).all()
    ids = [row.id for row in rows]
    if not ids:
        return {"ok": True, "deleted": 0, "message": "Chưa có phân công để đặt lại."}

    impact = assignment_delete_impact(db, ids)
    confirmation = assignment_delete_confirmation(
        impact, payload, assignment_count=len(ids)
    )
    # Confirm the assignment list too, including assignments added since preview.
    if confirmation is not None or sorted(set(payload.confirmed_assignment_ids)) != ids:
        return JSONResponse(
            {
                "ok": False,
                "requires_confirmation": True,
                "assignment_ids": ids,
                "assignment_count": len(ids),
                **impact,
                "message": (
                    f"Reset sẽ xóa toàn bộ {len(ids)} phân công trong bộ thời khóa biểu này, "
                    f"kèm {len(impact['lesson_ids'])} tiết đã xếp và "
                    f"{len(impact['fixed_lesson_ids'])} tiết ghim liên quan. "
                    "Danh sách giáo viên, lớp, môn và chương trình khối được giữ nguyên. "
                    "Thao tác này không thể hoàn tác. Bạn có muốn tiếp tục?"
                ),
            },
            409,
        )

    # Delete dependent rows first, explicitly, before their assignments.
    for model in (Lesson, FixedLesson):
        db.execute(delete(model).where(model.project_id == pid, model.assignment_id.in_(ids)))
    db.execute(delete(Assignment).where(Assignment.project_id == pid, Assignment.id.in_(ids)))
    db.commit()
    return {"ok": True, "deleted": len(ids), "message": f"Đã đặt lại {len(ids)} phân công."}


@router.delete("/api/projects/{pid}/entity/{typ}/{eid}")
def delete_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityDeleteIn | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    require_preview(db)
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400)
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404)
    if typ == "assignment":
        impact = assignment_delete_impact(db, [eid])
        confirmation = assignment_delete_confirmation(impact, payload)
        if confirmation is not None:
            return confirmation
    if entity_delete_dependency(db, typ, eid) is not None:
        return JSONResponse(
            {"ok": False, "message": "Không thể xóa vì dữ liệu đang được sử dụng."}, 409
        )
    delete_entity_related_rows(db, typ, eid)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.delete("/api/projects/{pid}/entities/bulk")
def delete_entities_bulk(
    pid: int,
    payload: BulkEntityDeleteIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    """Xóa nhiều dòng cùng loại, nhưng không bỏ qua kiểm tra phụ thuộc."""
    get_project_for_update(pid, user, db)
    require_preview(db)
    typ = (payload.type or "").strip().lower()
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")

    ids = []
    seen = set()
    for raw_id in payload.ids:
        try:
            eid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if eid > 0 and eid not in seen:
            seen.add(eid)
            ids.append(eid)
    if not ids:
        raise HTTPException(400, "Chưa chọn dữ liệu để xóa")
    if len(ids) > 500:
        raise HTTPException(400, "Mỗi lần chỉ được xóa tối đa 500 mục")

    rows = db.scalars(
        select(model).where(model.project_id == pid, model.id.in_(ids))
    ).all()
    row_by_id = {row.id: row for row in rows}
    if typ == "assignment" and row_by_id:
        impact = assignment_delete_impact(db, list(row_by_id))
        confirmation = assignment_delete_confirmation(
            impact, payload, assignment_count=len(row_by_id)
        )
        if confirmation is not None:
            return confirmation
    blocked_ids = entity_delete_dependency_ids(db, typ, list(row_by_id))
    deleted_ids = []
    skipped = []
    for eid in ids:
        obj = row_by_id.get(eid)
        if obj is None:
            skipped.append(
                {"id": eid, "reason": "Không còn tồn tại trong bộ thời khóa biểu này."}
            )
            continue
        if eid in blocked_ids:
            skipped.append(
                {
                    "id": eid,
                    "name": str(getattr(obj, "name", "") or ""),
                    "reason": "Dữ liệu đang được sử dụng.",
                }
            )
            continue
        delete_entity_related_rows(db, typ, eid)
        db.delete(obj)
        deleted_ids.append(eid)

    if not deleted_ids:
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "deleted": 0,
                "skipped": skipped,
                "message": "Không có mục nào được xóa. Các mục đã chọn đang được sử dụng hoặc không còn tồn tại.",
            },
            409,
        )

    db.commit()
    message = f"Đã xóa {len(deleted_ids)} mục."
    if skipped:
        message += (
            f" Bỏ qua {len(skipped)} mục đang được sử dụng hoặc không còn tồn tại."
        )
    return {
        "ok": True,
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped": skipped,
        "message": message,
    }
