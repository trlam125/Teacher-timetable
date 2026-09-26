from __future__ import annotations

from app.services.foundation import *

def read_schedule_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(400, "Hãy chọn file thời khóa biểu cần kiểm tra.")
    content = file.file.read(MAX_SCHEDULE_AUDIT_FILE_BYTES + 1)
    if not content:
        raise HTTPException(400, "File tải lên đang rỗng.")
    if len(content) > MAX_SCHEDULE_AUDIT_FILE_BYTES:
        raise HTTPException(413, "File quá lớn. Giới hạn kiểm tra là 15 MB.")
    return filename, content

def read_schedule_audit_report_json(report_json: str) -> dict:
    raw = str(report_json or "").strip()
    if not raw:
        raise HTTPException(400, "Thiếu dữ liệu thời khóa biểu đã chỉnh sửa.")
    if len(raw.encode("utf-8")) > MAX_SCHEDULE_AUDIT_FILE_BYTES:
        raise HTTPException(
            413, "Dữ liệu thời khóa biểu đã chỉnh sửa vượt quá giới hạn 15 MB."
        )
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise HTTPException(400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ.")
    viewer = report.get("viewer")
    if not isinstance(viewer, dict) or not isinstance(viewer.get("cells"), list):
        raise HTTPException(400, "Dữ liệu thời khóa biểu đã chỉnh sửa thiếu bảng lịch.")
    cells = viewer["cells"]
    if len(cells) > 50000:
        raise HTTPException(413, "Thời khóa biểu có quá nhiều ô để phân tích bằng AI.")
    try:
        days = int(viewer.get("days") or 0)
        sessions = int(viewer.get("sessions") or 0)
        periods = int(viewer.get("periods") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Kích thước thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc
    if not (1 <= days <= 7 and 1 <= sessions <= 4 and 1 <= periods <= 20):
        raise HTTPException(400, "Kích thước thời khóa biểu đã chỉnh sửa không hợp lệ.")
    from app.schedule_audit import recalculate_standalone_edited_report

    try:
        return recalculate_standalone_edited_report(report)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc


__all__ = [name for name in globals() if not name.startswith('__')]
