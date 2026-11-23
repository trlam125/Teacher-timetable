"""Conservative recognition of explicit headings and differing symbolic formulas.

No LLM, OCR, semantic fact checking or execution of document text. Evidence always
comes from the selected excerpts. A teacher's choice is precedence, not truth.
"""
import ast
import hashlib
import json
import re
import unicodedata


LABELS = {"subject": "Môn học", "grade": "Khối / lớp", "lesson_title": "Tên bài", "duration_minutes": "Thời lượng"}
SUBJECTS = {"vat li": "Vật lí", "vat ly": "Vật lí", "toan": "Toán", "ngu van": "Ngữ văn",
            "khoa hoc tu nhien": "Khoa học tự nhiên", "khoa hoc": "Khoa học", "hoa hoc": "Hóa học",
            "sinh hoc": "Sinh học", "lich su": "Lịch sử", "dia li": "Địa lí", "dia ly": "Địa lí",
            "tieng anh": "Tiếng Anh", "tieng viet": "Tiếng Việt", "tin hoc": "Tin học", "cong nghe": "Công nghệ"}
HEADING = re.compile(r"^(?:bài|chủ đề|lesson|unit)\s+\d+[a-z]?(?:\s*[.:：)\-–—]\s*|\s+)\S.*$", re.I)
OPERAND = r"(?:[A-Za-zΑ-Ωα-ω]{1,8}|\d+(?:\.\d+)?|\([^()\n]{1,60}\))"
FORMULA = re.compile(r"(?<![\w])([A-Za-zΑ-Ωα-ω]{1,8})\s*=\s*(" + OPERAND + r"(?:\s*[+*/×÷:^−-]\s*" + OPERAND + r"){0,8})")


def normalized(value):
    return " ".join(unicodedata.normalize("NFD", str(value).replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().casefold().split())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]


def comparable(field, value):
    text = normalized(value)
    if field == "lesson_title":
        text = re.sub(r"^(?:bai|chu de|lesson|unit)\s+\d+[a-z]?\s*[.:)\-]*\s*", "", text)
    if field == "subject":
        return normalized(SUBJECTS.get(text, value))
    if field == "grade":
        return re.sub(r"^(?:lop|khoi)\s*", "", text)
    return text


def evidence(source, quote, value, field):
    data = {"source_id": source["id"], "name": source["name"], "page": source.get("page"),
            "quote": quote, "value": value, "teacher_field": None}
    return {"id": digest([field, data]), **data}


def symbolic(text):
    """Canonicalize a tiny bounded expression grammar, never eval document input."""
    text = text.strip(" .").replace("×", "*").replace("÷", "/").replace(":", "/").replace("^", "**").replace("−", "-")
    if len(text) > 100:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(list(ast.walk(tree))) > 40 or not any(isinstance(node, ast.Name) for node in ast.walk(tree)):
        return None

    def visit(node):
        if isinstance(node, ast.Name) and len(node.id) <= 8:
            return node.id
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return str(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Mult)):
                left, right = sorted((left, right))
            return f"{type(node.op).__name__}({left},{right})"
        raise ValueError
    try:
        return visit(tree.body)
    except (ValueError, RecursionError):
        return None


def analyze_sources(profile):
    sources = profile.get("sources", [])
    signature = digest([sources, {key: profile.get(key) for key in (*LABELS, "locked_fields")}])
    metadata = {key: [] for key in LABELS}
    formulas = {}
    overflow = False
    for source in sources:
        # Metadata only from explicit early headings; do not infer subject from equations.
        lines = [line.strip() for line in source["text"][:2400].splitlines() if line.strip()][:30]
        for line in lines:
            folded = normalized(line)
            subject = re.sub(r"^(?:mon(?: hoc)?)\s*[:：\-]?\s*", "", folded)
            if subject in SUBJECTS:
                metadata["subject"].append(evidence(source, line, SUBJECTS[subject], "subject"))
            grade = re.fullmatch(r"(?:lớp|khối)\s*[:：]?\s*(\d{1,2})(?:\s*[a-z]\d*)?", line, re.I)
            if grade and 1 <= int(grade[1]) <= 12:
                metadata["grade"].append(evidence(source, line, "Lớp " + str(int(grade[1])), "grade"))
            if HEADING.fullmatch(line) and len(line) <= 240 and not re.search(r"\.{3,}|…", line):
                metadata["lesson_title"].append(evidence(source, line, line, "lesson_title"))
            duration = re.fullmatch(r"(?:thời lượng|thời gian)\s*[:：]?\s*(\d{1,3})\s*phút[.]?", line, re.I)
            if duration and 10 <= int(duration[1]) <= 240:
                metadata["duration_minutes"].append(evidence(source, line, int(duration[1]), "duration_minutes"))
        for match in FORMULA.finditer(source["text"]):
            expression = symbolic(match[2])
            if expression is not None:
                if match[1] not in formulas and len(formulas) >= 64:
                    overflow = True
                    continue
                entries = formulas.setdefault(match[1], [])
                if any(prior == expression for prior, _ in entries):
                    continue
                if len(entries) >= 50:
                    overflow = True
                    continue
                entries.append((expression, evidence(source, match[0].strip(), match[0].strip(), "formula")))

    conflicts = []

    def conflict(kind, key, items):
        unique = {item["id"]: item for item in items}
        # Bound response size, but never truncate alternative values silently.
        entries = list(unique.values())
        identifier = digest([signature, kind, key, sorted(unique)])
        conflicts.append({"id": identifier, "kind": kind, "field": key,
                          "label": LABELS.get(key, "Công thức " + key), "evidence": entries})

    for field, items in metadata.items():
        # Duplicate headings on multiple pages stay one suggestion per distinct value.
        metadata[field] = list({comparable(field, item["value"]): item for item in items}.values())
        values = {comparable(field, item["value"]) for item in items}
        teacher = profile.get(field)
        if teacher not in (None, ""):
            data = {"source_id": None, "name": "Thông tin giáo viên", "page": None,
                    "quote": str(teacher), "value": teacher, "teacher_field": field}
            items = [*items, {"id": digest([field, data]), **data}]
            values.add(comparable(field, teacher))
        if len(values) > 1:
            conflict("metadata", field, items)
    for name, entries in formulas.items():
        if len({expression for expression, _ in entries}) > 1:
            conflict("formula", name, [item for _, item in entries])
    decisions = {item["conflict_id"]: item["evidence_id"] for item in profile.get("source_resolutions", [])}
    for item in conflicts:
        for entry in item["evidence"]:
            entry["selectable"] = item["kind"] != "metadata" or comparable(item["field"], entry["value"]) == comparable(item["field"], profile.get(item["field"], ""))
        selected = next((entry for entry in item["evidence"] if entry["id"] == decisions.get(item["id"])), None)
        # Metadata is governed by the form; changing it requires an explicit form edit.
        if selected and item["kind"] == "metadata" and comparable(item["field"], selected["value"]) != comparable(item["field"], profile.get(item["field"], "")):
            selected = None
        item["selected_evidence_id"] = selected["id"] if selected else None
    return {"version": "explicit-1", "signature": signature, "metadata": metadata, "conflicts": conflicts,
            "overflow": overflow,
            "unresolved": overflow or any(not item["selected_evidence_id"] for item in conflicts),
            "limits": "Chỉ nhận diện tiêu đề rõ ràng và một số công thức khác nhau. Không kiểm chứng tính đúng của kiến thức."}


def validated_resolutions(profile, resolutions):
    analysis = analyze_sources({**profile, "source_resolutions": resolutions})
    choices = {item["conflict_id"]: item["evidence_id"] for item in resolutions}
    if len(choices) != len(resolutions):
        raise ValueError("Mỗi mâu thuẫn chỉ được chọn một phương án.")
    valid = {item["id"]: item["selected_evidence_id"] for item in analysis["conflicts"]}
    if any(valid.get(key) != value for key, value in choices.items()):
        raise ValueError("Lựa chọn đã cũ hoặc không khớp nguồn. Muốn đổi thông tin bài học, hãy sửa ở biểu mẫu trước.")
    return analysis


def resolved_claims(profile):
    result = []
    for item in analyze_sources(profile)["conflicts"]:
        selected = next((entry for entry in item["evidence"] if entry["id"] == item["selected_evidence_id"]), None)
        if selected:
            result.append({"field": item["field"], "kind": item["kind"], "selected": selected,
                           "alternatives": [entry for entry in item["evidence"] if entry["id"] != selected["id"]]})
    return result
