from __future__ import annotations

from app.services.runtime import *

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        if (
            request.url.path.startswith("/api/")
            or request.url.path.endswith("/export.xlsx")
            or request.headers.get("x-requested-with") == "XMLHttpRequest"
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Phiên đăng nhập đã hết hạn.",
                    "detail": "Phiên đăng nhập đã hết hạn.",
                },
                status_code=401,
            )
        return RedirectResponse("/login", 303)
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
        return JSONResponse(
            {"ok": False, "message": str(detail), "detail": str(detail)},
            status_code=exc.status_code,
        )
    if exc.status_code == 404:
        return HTMLResponse("<h1>404 - Không tìm thấy trang</h1>", status_code=404)
    return HTMLResponse(
        f"<h1>{exc.status_code} - Lỗi hệ thống</h1>", status_code=exc.status_code
    )

def register_exception_handlers(app):
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
