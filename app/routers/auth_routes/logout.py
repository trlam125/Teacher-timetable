from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AccountDevice
from app.services.authentication.csrf import require_form_token
from app.services.authentication.devices import PENDING_COOKIE, cancel_pending_login, pending_login_candidate
from app.services.authentication.navigation import SHARE_RETURN_COOKIE
from app.services.authentication.sessions import browser_secret, db_session, lock_account, secret_hash, session_user
from app.services.web import templates


router = APIRouter()


@router.get("/logout")
def logout_page(request: Request):
    return templates.TemplateResponse("logout.html", {"request": request})


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(""), db: Session = Depends(db_session)):
    require_form_token(request, csrf_token)
    user = session_user(request.cookies, db)
    pending = pending_login_candidate(request, db)
    # Account switching can leave an active account and another pending account.
    # Acquire both account locks in a deterministic order before revoking either.
    account_ids = {row.user_id for row in [pending] if row is not None}
    if user:
        account_ids.add(user.id)
    for account_id in sorted(account_ids):
        lock_account(db, account_id)
    cancel_pending_login(request, db)
    if user:
        db.expire_all()
        user = session_user(request.cookies, db)
        if user:
            device = db.scalar(select(AccountDevice).where(
                AccountDevice.user_id == user.id,
                AccountDevice.browser_hash == secret_hash(browser_secret(request))))
            device.session_hash = None
            device.session_expires_at = 0
    db.commit()
    res = RedirectResponse("/", 303)
    res.delete_cookie("session")
    res.delete_cookie(SHARE_RETURN_COOKIE)
    res.delete_cookie(PENDING_COOKIE)
    return res
