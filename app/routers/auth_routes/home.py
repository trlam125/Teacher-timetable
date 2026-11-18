from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.services.authentication.permissions import is_admin
from app.services.authentication.sessions import db_session, session_user
from app.services.web import templates


router = APIRouter()


@router.head("/", include_in_schema=False)
def home_head():
    return HTMLResponse(content="", status_code=200)



@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    user = session_user(request.cookies, db)
    if user:
        destination = "/teacher" if user.role == "teacher" else ("/projects" if is_admin(user) else "/logout")
        return RedirectResponse(destination, 303)
    return templates.TemplateResponse("landing.html", {"request": request})
