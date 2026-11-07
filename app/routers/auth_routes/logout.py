from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from app.services.authentication.navigation import SHARE_RETURN_COOKIE


router = APIRouter()


@router.get("/logout")
def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("session")
    res.delete_cookie(SHARE_RETURN_COOKIE)
    return res
