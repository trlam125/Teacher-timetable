from __future__ import annotations

from app.models import User
from app.services.authentication.permissions import admin_can_manage_account
from app.services.authentication.sessions import current_user, db_session
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session


router = APIRouter()


@router.get("/account/avatar/{account_id}")
def account_avatar(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    account = db.get(User, account_id)
    if not account or (account.id != user.id and not admin_can_manage_account(user, account, db)):
        raise HTTPException(404, "Không tìm thấy avatar")
    if not account.avatar_image:
        raise HTTPException(404, "Không tìm thấy avatar")
    return Response(
        content=account.avatar_image,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
