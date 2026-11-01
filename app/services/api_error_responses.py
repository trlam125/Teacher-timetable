"""Safe, searchable API responses for unexpected backend failures.

Never send SQL statements, connection strings or tracebacks to the browser.
Those details belong only in the server-side log under a reference code.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError


logger = logging.getLogger("uvicorn.error")


def classify_unexpected_error(exc: Exception) -> tuple[int, str, str]:
    """Return HTTP status, safe category, and a user-facing explanation."""
    if isinstance(exc, IntegrityError):
        return (
            409,
            "database_integrity",
            "Không thể lưu vì có thông tin bị trùng hoặc liên quan đến dữ liệu đang sử dụng. "
            "Hãy kiểm tra tên môn, lớp và phân công rồi thử lại.",
        )
    if isinstance(exc, OperationalError):
        return (
            503,
            "database_unavailable",
            "Không thể hoàn tất vì hệ thống đang gián đoạn hoặc quá bận. "
            "Thay đổi của bạn có thể chưa được lưu; hãy thử lại sau ít phút.",
        )
    if isinstance(exc, ProgrammingError):
        return (
            500,
            "database_schema_or_query",
            "Không thể lưu do hệ thống chưa xử lý được dữ liệu hiện tại. "
            "Vui lòng liên hệ người quản lý và cung cấp mã hỗ trợ bên dưới.",
        )
    return (
        500,
        "internal_error",
        "Đã xảy ra sự cố khi thực hiện thao tác. Thay đổi có thể chưa được lưu; hãy tải lại trang để kiểm tra rồi thử lại.",
    )


async def unexpected_exception_handler(request: Request, exc: Exception):
    """Log the full exception; return only a safe reference to the client."""
    reference = uuid4().hex[:12].upper()
    status, category, explanation = classify_unexpected_error(exc)
    logger.error(
        "API_ERROR_ID=%s category=%s %s %s",
        reference,
        category,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {
                "ok": False,
                "error_id": reference,
                "error_type": category,
                "detail": f"{explanation} Mã hỗ trợ: {reference}.",
            },
            status_code=status,
            headers={"X-Error-ID": reference},
        )
    return HTMLResponse(
        "<h1>Trang hiện không thể mở. Vui lòng thử lại sau hoặc liên hệ người quản lý.</h1>",
        status_code=status,
    )
