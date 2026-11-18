"""Retire device-OTP pages without promoting a pending challenge to a session."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.services.authentication.devices import PENDING_COOKIE, cancel_pending_login
from app.services.authentication.sessions import db_session

router = APIRouter()


@router.get("/auth/device")
@router.post("/auth/device/cancel")
@router.post("/auth/device/verify")
@router.post("/auth/device/complete")
@router.post("/auth/device/resend")
def retired_device_login(request: Request, db: Session = Depends(db_session)):
    if request.method == "POST":
        cancel_pending_login(request, db)
        db.commit()
    response = RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
    response.delete_cookie(PENDING_COOKIE)
    return response
