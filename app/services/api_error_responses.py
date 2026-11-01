"""Human-readable, actionable API errors without exposing private server data.

Never send raw exception messages, SQL, connection strings or tracebacks to a
browser. The diagnostic reference remains in server logs/response headers only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, ProgrammingError


logger = logging.getLogger("uvicorn.error")


def _database_code(exc: Exception) -> str:
    """Extract a driver error *code*, not the SQL/error text."""
    original = getattr(exc, "orig", None)
    for source in (original, getattr(original, "diag", None)):
        if source is None:
            continue
        for attr in ("sqlstate", "pgcode", "sqlite_errorname"):
            value = getattr(source, attr, None)
            if isinstance(value, str) and value:
                return value
    return ""


def _constraint_name(exc: Exception) -> str:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    name = getattr(diag, "constraint_name", "") if diag else ""
    return name if isinstance(name, str) else ""


def _operation_name(path: str, method: str) -> str:
    if "/entity/grade/" in path:
        return "Không lưu được chương trình môn của khối"
    if "/entity/subject/" in path:
        return "Không lưu được thông tin môn học"
    if "/entity/teacher/" in path:
        return "Không lưu được thông tin giáo viên"
    if "/entity/class/" in path:
        return "Không lưu được thông tin lớp học"
    if "/entity/" in path:
        return "Không lưu được thông tin"
    if "/assignments/" in path:
        return "Không lưu được phân công giáo viên"
    if path.startswith("/api/schedule-audit"):
        return "Không kiểm tra được thời khóa biểu"
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "Không hoàn tất được thao tác lưu"
    return "Không tải được thông tin"


def classify_unexpected_error(exc: Exception) -> tuple[int, str, str]:
    """HTTP status, stable error category, explicit safe reason and next action."""
    code = _database_code(exc)
    if isinstance(exc, IntegrityError):
        if code in {"23505", "SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY"}:
            constraint = _constraint_name(exc).lower()
            if "grade_subject" in constraint:
                reason = "Môn học đang bị khai báo nhiều lần trong cùng một khối."
            elif "assignment_class_subject" in constraint:
                reason = "Lớp đã có phân công cho môn học này."
            else:
                reason = "Có thông tin trùng với dữ liệu đã lưu."
            return 409, "duplicate_data", reason + " Kiểm tra mục trùng trước khi lưu lại."
        if code in {"23503", "SQLITE_CONSTRAINT_FOREIGNKEY"}:
            return 409, "data_in_use", (
                "Một môn, lớp hoặc giáo viên đang được sử dụng trong phân công hay thời khóa biểu. "
                "Kiểm tra các thông tin liên quan trước khi thay đổi."
            )
        if code in {"23502", "SQLITE_CONSTRAINT_NOTNULL"}:
            return 400, "missing_required_data", (
                "Có thông tin bắt buộc bị bỏ trống. "
                "Kiểm tra tên khối, môn học và số tiết/tuần rồi lưu lại."
            )
        if code in {"23514", "SQLITE_CONSTRAINT_CHECK"}:
            return 400, "invalid_data", (
                "Có số tiết hoặc chế độ xếp chưa hợp lệ. "
                "Kiểm tra các giá trị trong bảng rồi lưu lại."
            )
        return 409, "database_integrity", (
            "Dữ liệu mới xung đột với thông tin đã lưu. "
            "Kiểm tra các môn và phân công đang được sử dụng rồi thử lại."
        )
    if isinstance(exc, OperationalError):
        # In SQLite an OperationalError can mean a missing table/column, not
        # a connection outage. Check only fixed diagnostic tokens, never echo SQL.
        if code == "SQLITE_ERROR":
            original = str(getattr(exc, "orig", "")).lower()
            if "no such table" in original:
                return 500, "database_table_missing", (
                    "Thiếu bảng dữ liệu cần thiết để lưu cấu hình khối. "
                    "Người quản lý cần cập nhật cấu trúc dữ liệu của hệ thống."
                )
            if "no such column" in original:
                return 500, "database_column_missing", (
                    "Thiếu cột dữ liệu cần thiết để lưu cấu hình khối. "
                    "Người quản lý cần cập nhật cấu trúc dữ liệu của hệ thống."
                )
            return 500, "database_query_error", (
                "Chương trình không xử lý được thao tác ghi dữ liệu. "
                "Người quản lý cần kiểm tra phần lưu cấu hình khối."
            )
        if code in {"55P03", "40P01", "SQLITE_BUSY", "SQLITE_LOCKED"}:
            return 503, "database_locked", (
                "Dữ liệu đang được một thao tác khác sử dụng nên chưa thể lưu. "
                "Đợi thao tác đó kết thúc rồi thử lại."
            )
        if code in {"57014"}:
            return 503, "database_timeout", (
                "Việc lưu dữ liệu mất quá nhiều thời gian nên đã bị dừng. "
                "Kiểm tra lại dữ liệu và thử lại khi hệ thống ít bận hơn."
            )
        if code in {"53300", "53400"}:
            return 503, "database_busy", (
                "Nơi lưu trữ đang quá tải và chưa nhận thêm thao tác. "
                "Thử lại sau ít phút."
            )
        return 503, "database_unavailable", (
            "Không kết nối được tới nơi lưu dữ liệu hoặc kết nối bị ngắt. "
            "Kiểm tra dịch vụ dữ liệu rồi thử lưu lại."
        )
    if isinstance(exc, ProgrammingError):
        if code in {"42P01", "SQLITE_ERROR_NO_SUCH_TABLE"}:
            return 500, "database_table_missing", (
                "Thiếu bảng dữ liệu cần thiết để lưu cấu hình khối. "
                "Người quản lý cần cập nhật cấu trúc dữ liệu của hệ thống."
            )
        if code == "42703":
            return 500, "database_column_missing", (
                "Thiếu cột dữ liệu cần thiết để lưu cấu hình khối. "
                "Người quản lý cần cập nhật cấu trúc dữ liệu của hệ thống."
            )
        return 500, "database_query_error", (
            "Chương trình không xử lý được thao tác lưu trong cơ sở dữ liệu. "
            "Người quản lý cần kiểm tra phần lưu cấu hình khối trên máy chủ."
        )
    if isinstance(exc, DataError):
        if code in {"22001", "22003"}:
            return 400, "value_out_of_range", (
                "Có thông tin vượt quá độ dài hoặc giới hạn cho phép. "
                "Kiểm tra tên và số tiết rồi thử lại."
            )
        return 400, "invalid_data_type", (
            "Có giá trị không đúng định dạng lưu trữ. "
            "Kiểm tra lại số tiết và các lựa chọn trước khi lưu."
        )
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return 503, "connection_interrupted", (
            "Kết nối bị gián đoạn khi đang lưu dữ liệu. "
            "Kiểm tra kết nối rồi thử lại."
        )
    if isinstance(exc, PermissionError):
        return 403, "permission_denied", (
            "Hệ thống không có quyền ghi dữ liệu tại vị trí cần thiết. "
            "Người quản lý cần kiểm tra quyền truy cập."
        )
    if isinstance(exc, KeyError):
        return 500, "missing_program_field", (
            "Chương trình thiếu một thông tin cần dùng khi xử lý cấu hình khối. "
            "Người quản lý cần kiểm tra chức năng lưu dữ liệu."
        )
    if isinstance(exc, (ValueError, TypeError)):
        return 500, "invalid_program_value", (
            "Chương trình gặp giá trị không phù hợp trong quá trình xử lý cấu hình. "
            "Người quản lý cần kiểm tra phần dữ liệu đang được đồng bộ."
        )
    return 500, "unexpected_program_error", (
        "Chương trình gặp lỗi chưa được nhận diện khi xử lý yêu cầu. "
        "Thao tác chưa hoàn tất; người quản lý cần kiểm tra nhật ký máy chủ để xác định nguyên nhân."
    )


async def unexpected_exception_handler(request: Request, exc: Exception):
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
        description = f"{_operation_name(request.url.path, request.method)}. {explanation}"
        return JSONResponse(
            {
                "ok": False,
                "message": description,
                "detail": description,
                "error_type": category,
                "error_id": reference,
            },
            status_code=status,
            headers={"X-Error-ID": reference},
        )
    return HTMLResponse(
        "<h1>Không mở được trang này. Hãy thử tải lại hoặc liên hệ người quản lý.</h1>",
        status_code=status,
    )
