"""Public-facing Vietnamese answer hygiene with conservative failure handling.

Never replace an unknown code with a made-up explanation. An answer with
unresolved technical artifacts is replaced by a factual, local summary rather
than silently publishing misleading text.
"""
from __future__ import annotations

import re
from typing import Any


KNOWN_TERMS = {
    "max_two_consecutive": "quy tắc tối đa 2 tiết liền nhau của một môn trong một lớp trong mỗi buổi; nếu có 2 tiết thì chúng phải đứng cạnh nhau",
    "duplicate_assignments": "phân công trùng lặp",
    "coverage_checks": "kết quả kiểm tra phân công",
    "current_assignments": "danh sách phân công hiện tại",
    "scheduled_lessons": "các tiết đã xếp trên thời khóa biểu",
    "required_double": "bắt buộc xếp tiết đôi",
    "preferred_double": "ưu tiên xếp tiết đôi",
    "globally_blocked_slots": "các tiết bị khóa chung",
    "block_mode": "cách xếp tiết",
    "teacher_id": "giáo viên",
    "class_id": "lớp học",
    "subject_id": "môn học",
    "assignment_id": "phân công giảng dạy",
    "invalid_slot": "thời điểm không hợp lệ",
    "days_per_week": "số ngày học trong tuần",
    "sessions_per_day": "số buổi học trong ngày",
    "periods_per_session": "số tiết học trong mỗi buổi",
    "periods_per_day": "số tiết học mỗi ngày",
    "school_name": "tên trường",
    "project_data": "dữ liệu thời khóa biểu",
    "check": "kiểm tra",
    "slot": "thời điểm",
    "day": "thứ trong tuần",
    "session": "buổi học",
    "period": "tiết học",
    "teacher": "giáo viên",
    "subject": "môn học",
    "assignment": "phân công",
    "workload": "khối lượng giảng dạy",
}
_PHRASE_TRANSLATIONS = (
    (r"\s*\(\s*(?:optimization suggestions|suggested improvements|improvement suggestions|recommendations for optimization)\s*\)", ""),
    (r"\b(?:optimization suggestions|suggested improvements|improvement suggestions)\b", "gợi ý cải thiện"),
    (r"\b(?:teacher hot|hot teacher)\b", "giáo viên có lịch dạy dày"),
    (r"\b(?:one class|per class)\b", "một lớp"),
    (r"\bnull\s*/\s*empty\b", ""),  # Invalid factual conclusions are caught separately below.
    (r"\bfree\b", "xếp tiết linh hoạt"),
    (r"\b(?:debug|coding)\b", ""),
)
_UNKNOWN_CODE = re.compile(r"(?<![\w])`?[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+`?(?![\w])")
_UNRESOLVED = re.compile(
    r"(?:@@INLINE_?\d+@@|\uE000\d+\uE001|```|\b(?:check|slot|session|period|day|"
    r"optimization|hot teacher|one class|null|empty|json|frontend|backend|endpoint|"
    r"parser|raw_text|teacher_id|class_id)\b)",
    re.I,
)
_NOISY = re.compile(r"(?:thông tin liên quan\s*[,;:]\s*){2,}|(?:null\s*/\s*empty)", re.I)


def humanize_teacher_answer(answer: str) -> str:
    """Convert only known terms. Never generically fill unknown labels."""
    text = str(answer or "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern, replacement in _PHRASE_TRANSLATIONS:
        # Preserve proper nouns; phrase matching is intentionally narrow.
        text = re.sub(pattern, replacement, text, flags=re.I)
    for code, description in KNOWN_TERMS.items():
        text = re.sub(
            rf"(?<![A-Za-z0-9_])`?{re.escape(code)}`?(?![A-Za-z0-9_])",
            lambda _m, label=description: label,
            text,
            flags=re.I,
        )
    text = re.sub(r"môn\s*/\s*một lớp", "môn ở một lớp", text, flags=re.I)
    text = re.sub(r"giáo\s+viên\s+[‘'\"]?hot[’'\"]?", "giáo viên có lịch dạy dày", text, flags=re.I)
    # Unknown identifiers cannot be explained reliably from their spelling.
    # The whole answer will fail the quality gate and fall back to verified
    # facts; the direct presentation helper must not leak them either.
    text = _UNKNOWN_CODE.sub("nội dung chưa xác định", text)
    # Markdown inline code is a presentation artifact in teacher replies.
    text = re.sub(r"`([^`\n]{1,100})`", r"\1", text)
    text = re.sub(r"@@INLINE_?\d+@@", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def answer_quality_issues(text: str, *, source_text: str = "") -> list[str]:
    """Checks for artifacts not safely reparable without changing meaning."""
    problems = []
    raw = str(source_text or text)
    if _NOISY.search(raw):
        problems.append("lặp từ vô nghĩa hoặc khẳng định từ dữ liệu trống")
    if any(match.group(0).strip("`").lower() not in KNOWN_TERMS for match in _UNKNOWN_CODE.finditer(raw)) or _UNKNOWN_CODE.search(text):
        problems.append("mã nội bộ chưa được giải nghĩa")
    if _UNRESOLVED.search(text):
        problems.append("từ hoặc ký hiệu kỹ thuật còn sót")
    if re.search(r"\b(?:free|mode|one class)\b", text, re.I):
        problems.append("thuật ngữ tiếng Anh chưa được xử lý")
    if re.search(r"(?:thông tin liên quan\s*[,;:]\s*){2,}", text, re.I):
        problems.append("cụm từ bị lặp")
    return problems


def _has_inaccurate_blanket_claim(answer: str, context: dict[str, Any]) -> bool:
    checks = context.get("kết quả đối chiếu tự động") or {}
    counts = context.get("số lượng") or {}
    if not counts.get("phân công"):
        return bool(re.search(r"(?:đầy đủ|không có lỗi|không phát hiện lỗi|tối ưu|hợp lý)", answer, re.I))
    if checks.get("giáo viên chưa được phân công") and re.search(r"(?:tất cả|mọi)\s+giáo viên[^\n.]{0,150}(?:có phân công|được phân công|đã được phân công|dạy đầy đủ)", answer, re.I):
        return True
    if checks.get("lớp chưa có phân công") and re.search(r"(?:mọi|tất cả|mỗi)\s+lớp.*?(?:đầy đủ|được phân công|đã được phân công)", answer, re.I | re.S):
        return True
    if checks.get("phân công chưa khớp định mức theo khối") and isinstance(checks.get("phân công chưa khớp định mức theo khối"), list) and re.search(r"(?:mọi|tất cả|mỗi)\s+lớp.*?(?:đầy đủ|đúng|đủ).{0,35}(?:tiết|định mức)", answer, re.I | re.S):
        return True
    if checks.get("phân công có số tiết đã xếp khác số tiết yêu cầu") and re.search(r"(?:mọi|tất cả|mỗi)\s+lớp.*?(?:đủ|đầy đủ)\s+tiết", answer, re.I | re.S):
        return True
    if checks.get("xung đột thời điểm đã phát hiện") and re.search(r"(?:không|chưa)\s+(?:có|phát hiện|ghi nhận)\s+(?:bất kỳ\s+)?(?:lỗi|mâu thuẫn|xung đột)", answer, re.I):
        return True
    if re.search(r"(?:giáo viên|thầy|cô).{0,60}(?:không bị quá tải|chắc chắn không quá tải)", answer, re.I):
        return True
    # Missing curriculum rules => do not assert every class meets regulations.
    if not isinstance(context.get("định mức theo khối"), list) and re.search(r"(?:mỗi|mọi|tất cả)\s+lớp.*?(?:đúng|đủ|đầy đủ).{0,30}(?:định mức|tiết)", answer, re.I | re.S):
        return True
    return False


def verified_teacher_summary(context: dict[str, Any]) -> str:
    """Safe fallback composed ONLY of server-counted evidence, never model guesses."""
    counts = context.get("số lượng") or {}
    checks = context.get("kết quả đối chiếu tự động") or {}
    lines = [
        "**Nhận xét từ dữ liệu thời khóa biểu hiện có**",
        f"- Hệ thống ghi nhận {counts.get('lớp', 0)} lớp, {counts.get('giáo viên', 0)} giáo viên, "
        f"{counts.get('phân công', 0)} phân công và {counts.get('tiết đã xếp', 0)} tiết đã xếp.",
    ]
    categories = (
        ("xung đột thời điểm đã phát hiện", "Các trường hợp cần kiểm tra về thời điểm"),
        ("phân công có số tiết đã xếp khác số tiết yêu cầu", "Các phân công chưa khớp số tiết đã xếp"),
        ("phân công chưa khớp định mức theo khối", "Các phân công chưa khớp định mức theo khối"),
        ("giáo viên chưa được phân công", "Giáo viên chưa có phân công"),
        ("lớp chưa có phân công", "Lớp chưa có phân công"),
    )
    for key, heading in categories:
        values = checks.get(key)
        if isinstance(values, list) and values:
            lines.append(f"**{heading} ({len(values)}):**")
            lines.extend(f"- {v}" for v in values[:30])
            if len(values) > 30:
                lines.append(f"- Còn {len(values) - 30} mục. Hãy hỏi về nhóm cụ thể để xem đầy đủ.")
    if not counts.get("tiết đã xếp"):
        lines.append("- Chưa có tiết nào được xếp nên chưa thể đánh giá xung đột giờ học.")
    elif not any(checks.get(k) for k, _ in categories):
        lines.append("- Chưa phát hiện trùng thời điểm hoặc thiếu tiết so với số tiết đã phân công trong dữ liệu đang có.")
    lines.append("**Lưu ý:** Một phần câu trả lời tự động chưa đủ rõ hoặc chưa được kiểm chứng nên tôi chỉ nêu kết quả đối chiếu trực tiếp. Đây không phải kết luận toàn bộ thời khóa biểu đã đúng mọi quy định. Bạn có thể hỏi cụ thể về lớp, giáo viên hoặc môn học để kiểm tra thêm.")
    return "\n\n".join(lines) if len(lines) < 3 else "\n".join(lines)


def present_teacher_answer(answer: str, context: dict[str, Any]) -> tuple[str, list[str]]:
    """Return a safe public answer, plus private reason codes for QA/logs."""
    clean = humanize_teacher_answer(answer)
    issues = answer_quality_issues(clean, source_text=answer)
    if _has_inaccurate_blanket_claim(clean, context):
        issues.append("khẳng định chưa được dữ liệu xác nhận")
    if not clean.strip():
        issues.append("câu trả lời trống")
    if issues:
        return verified_teacher_summary(context), issues
    return clean, []
