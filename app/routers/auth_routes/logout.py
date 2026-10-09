from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse


router = APIRouter()


@router.get("/logout")
def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("session")
    return res
