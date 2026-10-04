from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *
from .common import ENTITY_MODELS

router = APIRouter()


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
