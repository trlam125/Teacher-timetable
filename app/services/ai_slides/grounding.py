"""Strict mode: model selects references, server assembles literal excerpts.

This proves text provenance, never the truth or relevance of the source itself.
There is no silent fallback from unrestricted AI content to this contract.
"""
import hashlib
import json
import re
from copy import deepcopy

from .analysis import FORMULA, comparable, resolved_claims, source_signature, symbolic
from .provider import StudioError
from .schemas import Blueprint, Slide, SlideBatch


VERSION = "extractive-v1"
STAGES = {"cover": "Bài học", "objectives": "Mục tiêu", "hook": "Khởi động", "section": "Chuyển phần",
          "concept": "Khám phá", "process": "Theo dõi quá trình", "compare": "Đối chiếu", "example": "Ví dụ trong nguồn",
          "quiz": "Luyện tập từ ngữ", "summary": "Tổng kết", "sources": "Nguồn bài học"}
ACTIVITIES = {
    "discuss": ("Mời học sinh giải thích trích đoạn và chỉ ra căn cứ trong nguồn.", "Trao đổi theo trích đoạn, nêu điều chưa rõ để đối chiếu nguồn."),
    "restate": ("Mời học sinh diễn đạt lại trích đoạn bằng lời của mình.", "Diễn đạt lại, sau đó đối chiếu với văn bản nguồn."),
    "compare": ("Hướng dẫn học sinh đối chiếu các trích đoạn đang hiển thị.", "Nêu điểm giống và khác nhau giữa các trích đoạn."),
    "read": ("Hướng dẫn học sinh đọc và đánh dấu thông tin chính trong nguồn.", "Đọc trích đoạn và đánh dấu thông tin cần ghi nhớ."),
}


def failure(message="AI chọn trích đoạn không hợp lệ. Bản nháp được giữ; hãy thử lại."):
    return StudioError("AI_GROUNDING_ERROR", message, 422)


def source_units(profile):
    rejected = {}
    claims = resolved_claims(profile)
    for claim in claims:
        if claim["kind"] == "formula":
            selected = FORMULA.search(claim["selected"]["quote"])
            chosen = symbolic(selected[2]) if selected else None
            for alternative in claim["alternatives"]:
                match = FORMULA.search(alternative["quote"])
                if match and symbolic(match[2]) != chosen:
                    rejected.setdefault(match[1], set()).add(symbolic(match[2]))
    units = []
    for source in profile.get("sources", []):
        excluded_spans = [match.span() for match in FORMULA.finditer(source["text"])
                          if symbolic(match[2]) in rejected.get(match[1], set())]
        for claim in claims:
            if claim["kind"] != "metadata":
                continue
            for alternative in claim["alternatives"]:
                if (alternative["source_id"] == source["id"] and comparable(claim["field"], alternative["value"])
                        != comparable(claim["field"], claim["selected"]["value"])):
                    excluded_spans.extend(match.span() for match in re.finditer(re.escape(alternative["quote"]), source["text"]))
        # Word-boundary chunks retain the exact whitespace and punctuation of the source.
        for line_match in re.finditer(r"[^\r\n]+", source["text"]):
            line = line_match[0]
            boundaries = [0, *[match.end() for match in re.finditer(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])", line)], len(line)]
            for left, right in zip(boundaries, boundaries[1:]):
                sentence = line[left:right]
                cursor = line_match.start() + left + len(sentence) - len(sentence.lstrip())
                rest = sentence.strip()
                while rest:
                    end = min(280, len(rest))
                    if end < len(rest):
                        boundary = rest.rfind(" ", 0, end)
                        if boundary > 0:
                            end = boundary
                    raw_quote, tail = rest[:end], rest[end:]
                    quote = raw_quote.strip()
                    start, stop = cursor, cursor + len(quote)
                    cursor += end + len(tail) - len(tail.lstrip())
                    rest = tail.strip()
                    if not quote or any(start < last and stop > first for first, last in excluded_spans):
                        continue
                    unit_id = "u-" + hashlib.sha256((source["id"] + "\0" + quote).encode()).hexdigest()[:20]
                    if any(unit["id"] == unit_id for unit in units):
                        continue
                    units.append({"id": unit_id, "source_id": source["id"], "page": source.get("page"), "quote": quote})
                    if len(units) > 600:
                        raise failure("Có quá nhiều trích đoạn ngắn. Hãy thu hẹp nguồn bài học rồi thử lại.")
    if not units:
        raise failure("Chưa còn trích đoạn phù hợp sau khi áp dụng lựa chọn nguồn. Hãy kiểm tra lại phạm vi tài liệu.")
    return units


def select_units(ids, catalog, allowed=None):
    by_id = {unit["id"]: unit for unit in catalog}
    if len(set(ids)) != len(ids) or any(unit_id not in by_id for unit_id in ids):
        raise failure()
    selected = [by_id[unit_id] for unit_id in ids]
    if allowed is not None and any(unit["source_id"] not in allowed for unit in selected):
        raise failure("AI chọn trích đoạn ngoài nguồn của slide. Hãy chỉnh dàn ý nếu muốn đổi nguồn.")
    return selected


def assemble_plan(result, profile, catalog=None):
    catalog = catalog if catalog is not None else source_units(profile)
    objectives = select_units(result.objective_unit_ids, catalog)
    warnings = {"SHORT_SOURCE": "Nguồn ngắn; cần kiểm tra độ lặp và thời lượng hoạt động.",
                "UNCLEAR_SCOPE": "Phạm vi bài học chưa rõ; hãy kiểm tra các trích đoạn được chọn."}
    slides = []
    for number, choice in enumerate(result.slides, 1):
        selected = select_units(choice.unit_ids, catalog)
        title = grounded_title(profile, choice.kind, choice.id)
        slides.append({"id": choice.id, "title": title, "kind": choice.kind, "duration_seconds": choice.duration_seconds,
                       "source_ids": list(dict.fromkeys(unit["source_id"] for unit in selected)), "source_unit_ids": choice.unit_ids})
    objective_text = ["Trình bày nội dung: " + unit["quote"] for unit in objectives]
    if "objectives" in profile.get("locked_fields", []) and profile.get("objectives"):
        objective_text = [line.strip() for line in profile["objectives"].splitlines() if line.strip()]
    flags = [warnings[code] for code in dict.fromkeys(result.warnings)]
    if len(catalog) < profile["slide_count"] and "SHORT_SOURCE" not in result.warnings:
        flags.append(warnings["SHORT_SOURCE"])
    return Blueprint.model_validate({"lesson_title": result.lesson_title, "objectives": objective_text,
                                     "slides": slides, "warnings": flags, "grounding_version": VERSION})


def content_digest(slide):
    data = {key: value for key, value in slide.items() if key != "source_proof"}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def grounded_title(profile, kind, slide_id):
    return f"{STAGES[kind]} {int(slide_id[1:])} · {profile['lesson_title']}"[:160]


def assemble_slide(choice, profile, outline, catalog):
    if choice.id != outline["id"] or outline["kind"] not in STAGES:
        raise failure("Loại slide này chưa có trong chế độ trích đoạn. Hãy dùng loại nội dung hoặc chuyển sang chế độ cân bằng.")
    bullets = select_units(choice.bullet_unit_ids, catalog, outline["source_ids"])
    notes = select_units(choice.notes_unit_ids, catalog, outline["source_ids"])
    teacher, student = ACTIVITIES[choice.activity]
    data = {key: deepcopy(outline[key]) for key in ("id", "title", "kind", "duration_seconds", "source_ids")}
    for key in ("resource_id", "chart_data"):
        if key in outline:
            data[key] = deepcopy(outline[key])
    data.update(source_unit_ids=list(dict.fromkeys(choice.bullet_unit_ids + choice.notes_unit_ids)),
                bullets=[unit["quote"] for unit in bullets], speaker_notes="\n\n".join(unit["quote"] for unit in notes),
                teacher_action=teacher, student_action=student)
    citations = [{"field": field, "index": index, "unit_id": unit["id"], "source_id": unit["source_id"],
                  "quote": unit["quote"], "page": unit["page"]}
                 for field, items in (("bullets", bullets), ("speaker_notes", notes)) for index, unit in enumerate(items)]
    if outline["kind"] == "quiz":
        quote, gap = bullets[0]["quote"], choice.quiz_gap
        if not gap or quote.count(gap) != 1 or len(choice.quiz_distractors) < 1:
            raise failure("Câu điền trích đoạn cần một từ/cụm từ duy nhất trong nguồn và phương án khác nhau.")
        options = [gap, *choice.quiz_distractors]
        allowed_units = [unit for unit in catalog if unit["source_id"] in outline["source_ids"]]
        if len({item.casefold() for item in options}) != len(options) or any(not any(item in unit["quote"] for unit in allowed_units) for item in options):
            raise failure("Các phương án cần khác nhau và lấy từ văn bản nguồn.")
        correct = int(hashlib.sha256(choice.id.encode()).hexdigest()[:4], 16) % len(options)
        options.insert(correct, options.pop(0))
        data.update(question="Điền đúng nguyên văn trích đoạn:\n“" + quote.replace(gap, "_____", 1) + "”",
                    options=options, correct_option=correct, explanation="Nguyên văn nguồn: “" + quote + "”")
        for field in ("question", "correct_option"):
            citations.append({"field": field, "index": 0, "unit_id": bullets[0]["id"], "source_id": bullets[0]["source_id"],
                              "quote": quote, "page": bullets[0]["page"]})
        for index, option in enumerate(options):
            unit = next(unit for unit in allowed_units if option in unit["quote"])
            citations.append({"field": "options", "index": index, "unit_id": unit["id"], "source_id": unit["source_id"],
                              "quote": unit["quote"], "page": unit["page"]})
    elif choice.quiz_gap or choice.quiz_distractors:
        raise failure("AI thêm phương án câu hỏi vào slide không phải quiz.")
    slide = Slide.model_validate(data)
    proof = {"version": VERSION, "source_signature": source_signature(profile),
             "content_digest": content_digest(slide.model_dump()), "citations": citations}
    return Slide.model_validate({**slide.model_dump(), "source_proof": proof})


def assemble_batch(result, profile, blueprint, catalog=None):
    catalog = catalog if catalog is not None else source_units(profile)
    outlines = {slide["id"]: slide for slide in blueprint["slides"]}
    slides = []
    for choice in result.slides:
        if choice.id not in outlines:
            raise failure()
        slides.append(assemble_slide(choice, profile, outlines[choice.id], catalog))
    return SlideBatch(lesson_title=result.lesson_title, slides=slides)


def proof_valid(slide, profile):
    proof = slide.get("source_proof")
    if not proof or proof.get("version") != VERSION or proof.get("content_digest") != content_digest(slide):
        return False
    if proof.get("source_signature") != source_signature(profile):
        return False
    if (slide.get("kind") not in STAGES or slide.get("title") != grounded_title(profile, slide["kind"], slide["id"])
            or slide.get("resource_id") or slide.get("chart_data")):
        return False
    source_map = {source["id"]: source for source in profile.get("sources", [])}
    return bool(proof.get("citations")) and all(item["source_id"] in source_map and item["quote"] in source_map[item["source_id"]]["text"] for item in proof["citations"])
