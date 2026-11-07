"""Standalone error pages that do not need a user session or database access."""

from fastapi import Request

from app.services.web import templates


def render_error_page(request: Request, status_code: int, *, headers=None):
    if status_code == 404:
        title = "Không tìm thấy trang"
        description = (
            "Trang bạn cần mở có thể đã được di chuyển, không còn tồn tại "
            "hoặc bạn chưa có quyền truy cập."
        )
        hint = "Hãy kiểm tra lại đường dẫn hoặc về trang chủ để tiếp tục."
    elif status_code == 403:
        title = "Bạn chưa có quyền truy cập"
        description = "Tài khoản hiện tại chưa được cấp quyền mở nội dung này."
        hint = "Hãy liên hệ người quản lý nếu bạn cần được cấp quyền."
    elif status_code >= 500:
        title = "Tạm thời không thể mở trang"
        description = "Hệ thống đang gặp sự cố khi xử lý yêu cầu của bạn."
        hint = "Vui lòng thử lại sau ít phút hoặc liên hệ người quản lý."
    else:
        title = "Không thể mở trang này"
        description = "Yêu cầu truy cập chưa hợp lệ hoặc không còn khả dụng."
        hint = "Hãy quay lại trang trước hoặc về trang chủ để tiếp tục."

    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": status_code,
            "title": title,
            "description": description,
            "hint": hint,
        },
        status_code=status_code,
        headers=headers,
    )
