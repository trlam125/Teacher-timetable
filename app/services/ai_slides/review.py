"""Conservative editorial warnings, not a factual verification service."""
import re
from .grounding import proof_valid

PAGE_REFERENCE = re.compile(r"(?:sgk|sách|tài liệu).{0,90}\btrang\s*\d+|(?:bài tập|đọc|xem|tham khảo).{0,35}(?:sgk|sách giáo khoa)", re.IGNORECASE)


def content_review(manifest, profile):
    if not manifest:
        return []
    issues = []
    if any('(OCR,' in source.get('name', '') for source in profile.get('sources', [])):
        issues.append({'code': 'OCR_SOURCE_REVIEW', 'severity': 'warning', 'slide_id': None,
                       'message': 'Có nguồn từ OCR. Đối chiếu trích đoạn chỉ so với văn bản đã sửa, không xác nhận chữ/công thức khớp ảnh gốc. Kiểm tra lại trước khi dạy.'})
    if not profile.get("sources"):
        issues.append({"code": "NO_INPUT_SOURCES", "severity": "info", "slide_id": None,
                       "message": "Bài được soạn không có tài liệu đầu vào. Giáo viên cần đối chiếu kiến thức trước khi dạy."})
    for slide in manifest.get("slides", []):
        text = "\n".join([slide.get("title", ""), *slide.get("bullets", []),
                          slide.get("speaker_notes", ""), slide.get("question", ""),
                          *slide.get("options", []), slide.get("explanation", ""),
                          slide.get("teacher_action", ""), slide.get("student_action", "")])
        base = {"slide_id": slide["id"]}
        if slide.get('manual_resource'):
            issues.append({**base, 'code': 'USER_LINK_UNVERIFIED', 'severity': 'warning',
                           'message': 'Liên kết do giáo viên cung cấp; chưa xác minh nội dung, quyền sử dụng hoặc khả năng truy cập. Hãy mở xem trước khi dạy.'})
        if profile.get("grounding") in {'strict', 'verified_expansion'} and not proof_valid(slide, profile):
            issues.append({**base, "code": "UNVERIFIED_GROUNDING", "severity": "warning",
                           "message": "Slide chưa có đối chiếu trích đoạn hợp lệ, hoặc đã được chỉnh tay. Hãy kiểm tra từng ý với nguồn trước khi tải."})
        if profile.get('grounding') == 'verified_expansion' and any(source['id'] in slide.get('source_ids', []) and source.get('role') == 'reference' for source in profile.get('sources', [])):
            issues.append({**base, 'code': 'SUPPLEMENTARY_SOURCE', 'severity': 'info',
                           'message': 'Slide dùng nguồn tham khảo bổ sung do giáo viên chọn. Đối chiếu trích đoạn không xác nhận tính đúng của nguồn.'})
        if PAGE_REFERENCE.search(text):
            issues.append({**base, "code": "UNVERIFIED_REFERENCE", "severity": "warning",
                           "message": "Có tham chiếu sách/số trang trong nội dung. Hãy đối chiếu nguồn gốc; hệ thống chưa xác minh tham chiếu này."})
        if any(len(value) > 180 for value in slide.get("bullets", [])):
            issues.append({**base, "code": "DENSE_SLIDE", "severity": "warning",
                           "message": "Một số ý quá dài, có thể làm chữ nhỏ. Nên rút gọn và chuyển chi tiết sang ghi chú."})
        chart = slide.get("chart_data")
        if chart and chart.get("data_origin") == "example":
            issues.append({**base, "code": "EXAMPLE_DATA", "severity": "info",
                           "message": "Biểu đồ dùng số liệu minh họa, không phải kết quả đo hoặc thống kê thực."})
    return issues
