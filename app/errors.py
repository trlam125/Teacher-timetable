from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.api_error_responses import unexpected_exception_handler
from app.services.error_pages import render_error_page
from app.services.authentication.csrf import FormSecurityError


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc, FormSecurityError):
        if (request.url.path.startswith("/api/")
                or request.headers.get("x-requested-with") == "XMLHttpRequest"):
            return JSONResponse({"ok": False, "code": exc.code,
                                 "message": exc.detail, "detail": exc.detail},
                                status_code=403, headers={"Cache-Control": "no-store"})
        return render_error_page(request, 403, form_error=exc, headers=exc.headers)
    if exc.status_code == 401:
        if (
            request.url.path.startswith("/api/")
            or request.url.path.endswith("/export.xlsx")
            or request.headers.get("x-requested-with") == "XMLHttpRequest"
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Vui lòng đăng nhập lại để tiếp tục.",
                    "detail": "Vui lòng đăng nhập lại để tiếp tục.",
                },
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        from app.services.authentication.navigation import login_redirect
        return login_redirect(request)
    if request.url.path.startswith("/api/"):
        detail = (
            exc.detail
            if exc.detail
            else (
                "Không tìm thấy tài nguyên yêu cầu."
                if exc.status_code == 404
                else "Yêu cầu không hợp lệ."
            )
        )
        structured = detail if isinstance(detail, dict) else {}
        return JSONResponse(
            {"ok": False, **structured, "message": structured.get("message", str(detail)), "detail": detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    return render_error_page(request, exc.status_code, headers=exc.headers)


def register_exception_handlers(app):
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
