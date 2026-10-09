from __future__ import annotations

from app.models import User
from app.services.authentication.credentials import signer
from app.services.authentication.permissions import is_admin
from app.services.authentication.sessions import db_session
from app.services.foundation import SESSION_TTL_SECONDS
from app.services.web import templates
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.orm import Session


router = APIRouter()


@router.head("/", include_in_schema=False)
def home_head():
    return HTMLResponse(content="", status_code=200)



@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    raw = request.cookies.get("session")
    if raw:
        try:
            data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
            user = db.get(User, int(data["uid"]))
            if user and int(data.get("sv", -1)) == user.session_version:
                destination = (
                    "/teacher"
                    if user.role == "teacher"
                    else ("/projects" if is_admin(user) else "/logout")
                )
                return RedirectResponse(destination, 303)
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
            pass
    return templates.TemplateResponse("landing.html", {"request": request})
