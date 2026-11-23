"""Conservative editorial warnings, not a factual verification service."""
import re

PAGE_REFERENCE = re.compile(r"(?:sgk|sách|tài liệu).{0,90}\btrang\s*\d+", re.IGNORECASE)


def content_review(manifest, profile):
    if not manifest:
        return []
    issues = []
    if not profile.get("sources"):
        issues.append({"code": "NO_INPUT_SOURCES", "severity": "info", "slide_id": None,
                       "message": "Bài được soạn không có tài liệu đầu vào. Giáo viên cần đối chiếu kiến thức trước khi dạy."})
    for slide in manifest.get("slides", []):
        text = "\n".join([slide.get("title", ""), *slide.get("bullets", []),
                          slide.get("speaker_notes", ""), slide.get("question", ""),
                          *slide.get("options", []), slide.get("explanation", ""),
                          slide.get("teacher_action", ""), slide.get("student_action", "")])
        base = {"slide_id": slide["id"]}
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
