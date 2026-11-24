import time
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import settings
from .models import Deck, Quota, Revision, Step, now
from .provider import StudioError


def owned_deck(db, deck_id, user_id):
    deck = db.scalar(select(Deck).where(Deck.id == deck_id, Deck.owner_id == user_id))
    if deck is None:
        raise StudioError("DECK_NOT_FOUND", "Không tìm thấy bài giảng.", 404)
    return deck


def version_guard(deck, expected):
    if deck.version != expected:
        raise StudioError("STEP_CONFLICT", "Bài giảng đã thay đổi ở tab khác. Hãy tải lại bản mới nhất.", 409)
    if deck.active_token and deck.lease_until > time.time():
        raise StudioError("STEP_RUNNING", "AI đang xử lý bài giảng này. Hãy chờ kết quả.", 409)


def snapshot(deck):
    return {
        "title": deck.title, "profile": deck.profile, "blueprint": deck.blueprint,
        "manifest": deck.manifest, "status": deck.status,
    }


def revise(db, deck):
    deck.version += 1
    deck.updated_at = now()
    db.add(Revision(deck_id=deck.id, version=deck.version, snapshot=snapshot(deck)))


def reserve_quota(db, user_id):
    config = settings()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    for key, limit in (
        (f"{day}:site", config.calls_per_site),
        (f"{day}:user:{user_id}", config.calls_per_user),
    ):
        db.execute(insert(Quota).values(key=key, requests=0).on_conflict_do_nothing())
        result = db.execute(update(Quota).where(
            Quota.key == key, Quota.requests < limit,
        ).values(requests=Quota.requests + 1))
        if result.rowcount != 1:
            raise StudioError("AI_QUOTA_EXHAUSTED", "Đã hết lượt AI trong ngày. Bạn vẫn có thể sửa và tải bài đã tạo.", 429)


def claim(db, deck, kind, key, expected):
    prior = db.scalar(select(Step).where(Step.deck_id == deck.id, Step.idempotency_key == key))
    if prior is not None:
        if prior.kind != kind or prior.input_version != expected:
            raise StudioError("STEP_CONFLICT", "Mã yêu cầu đã được dùng cho nội dung khác.", 409)
        if prior.state == "completed":
            return None
        raise StudioError("STEP_CONFLICT", "Lượt này đã được xử lý. Tải lại bài giảng trước khi thử lượt mới.", 409)
    version_guard(deck, expected)
    token = str(uuid4())
    timestamp = time.time()
    result = db.execute(update(Deck).where(
        Deck.id == deck.id, Deck.version == expected,
        (Deck.active_token.is_(None)) | (Deck.lease_until <= timestamp),
    ).values(active_token=token, lease_until=timestamp + settings().timeout + 45))
    if result.rowcount != 1:
        raise StudioError("STEP_CONFLICT", "Một lượt khác đã bắt đầu xử lý bài giảng.", 409)
    db.execute(update(Step).where(Step.deck_id == deck.id, Step.state == "running").values(
        state="failed", error_code="LEASE_EXPIRED",
    ))
    reserve_quota(db, deck.owner_id)
    step = Step(id=token, deck_id=deck.id, idempotency_key=key, kind=kind, input_version=expected)
    db.add(step)
    db.commit()
    db.refresh(deck)
    return step


def finish_guard(db, deck_id, token, expected):
    result = db.execute(update(Deck).where(
        Deck.id == deck_id, Deck.active_token == token, Deck.version == expected,
    ).values(active_token=None, lease_until=0))
    if result.rowcount != 1:
        raise StudioError("STEP_CONFLICT", "Kết quả cũ đã được bỏ qua vì bài giảng có lượt xử lý mới.", 409)
    db.expire_all()
    return db.get(Deck, deck_id)


def validate_generated_references(texts, profile):
    supplied = '\n'.join(source['text'] for source in profile.get('sources', []))
    for text in texts:
        if any(fragment not in supplied for fragment in re.findall(r'[\u3400-\u9fff\uac00-\ud7af]+', text)):
            raise StudioError('AI_LANGUAGE_ERROR', 'AI chèn chữ Hán/Hàn không có trong nguồn tiếng Việt. Kết quả bị chặn; bản nháp được giữ để thử lại hoặc sửa phạm vi.', 422)
        for match in re.finditer(r'(?:SGK|sách(?: giáo khoa)?).{0,60}?(?:trang|tr\.)\s*\d+', text, re.I):
            if match[0] not in supplied:
                raise StudioError('AI_UNVERIFIED_REFERENCE', 'AI nêu trang sách chưa có trong đoạn nguồn; kết quả bị chặn. Bổ sung nguồn hoặc thu hẹp yêu cầu rồi thử lại.', 422)
        if 'phet-ohms-law' in text and re.search(r'(?:đặt|điều chỉnh).{0,100}R[1₁].{0,60}R[2₂]', text, re.I):
            raise StudioError('AI_RESOURCE_MISMATCH', 'AI mô tả điều khiển R1/R2 không có trong học liệu PhET định luật Ôm. Kết quả bị chặn để tránh hướng dẫn sai.', 422)


def validate_content(result, profile, blueprint=None, *, partial=False, generated=False):
    sources = {source["id"] for source in profile["sources"]}
    slides = result.slides
    if generated:
        texts = [*getattr(result, 'warnings', [])]
        for slide in slides:
            texts.extend([slide.title, *getattr(slide, 'bullets', []), getattr(slide, 'speaker_notes', ''),
                          getattr(slide, 'teacher_action', ''), getattr(slide, 'student_action', ''),
                          getattr(slide, 'question', ''), *getattr(slide, 'options', []), getattr(slide, 'explanation', '')])
        validate_generated_references(texts, profile)
    if len(slides) != profile["slide_count"] or len({slide.id for slide in slides}) != len(slides):
        raise StudioError("AI_CONSTRAINT_ERROR", "AI trả sai số slide hoặc mã slide trùng. Hãy thử lại.")
    distinct_titles = {slide.title.casefold().strip() for slide in slides}
    if len(distinct_titles) < len(slides) * 0.8 or (not partial and len({slide.kind for slide in slides}) < 3):
        raise StudioError("AI_QUALITY_ERROR", "Dàn bài bị lặp tiêu đề hoặc thiếu loại hoạt động. Hãy thử mô hình khác.")
    if result.lesson_title != profile["lesson_title"]:
        raise StudioError("NEEDS_TEACHER_REVIEW", "AI đề nghị đổi tên bài. Tên đã nhập được giữ, hãy kiểm tra nguồn và thử lại.", 422)
    if hasattr(result, "objectives") and "objectives" in profile["locked_fields"] and profile["objectives"]:
        expected_objectives = [line.strip() for line in profile["objectives"].splitlines() if line.strip()]
        if result.objectives != expected_objectives:
            raise StudioError("NEEDS_TEACHER_REVIEW", "AI đề nghị sửa mục tiêu đã khóa. Hãy kiểm tra dàn ý và thử lại.", 422)
    if any(set(slide.source_ids) - sources for slide in slides):
        raise StudioError("AI_SOURCE_ERROR", "AI tham chiếu đoạn nguồn chưa được cung cấp. Hãy thử lại.")
    if profile["grounding"] != 'balanced' and any(
        not slide.source_ids for slide in slides if slide.kind not in {"cover", "section", "sources"}
    ):
        raise StudioError("AI_SOURCE_ERROR", "Một số slide chưa dẫn nguồn trong chế độ bám sát tài liệu.")
    if blueprint and [(slide.id, slide.kind) for slide in slides] != [
        (slide["id"], slide["kind"]) for slide in blueprint["slides"]
    ]:
        raise StudioError("AI_CONSTRAINT_ERROR", "AI đã thay đổi cấu trúc dàn ý. Hãy thử lại.")
    expected_seconds = profile["duration_minutes"] * 60
    if abs(sum(slide.duration_seconds for slide in slides) - expected_seconds) > 60:
        raise StudioError("AI_CONSTRAINT_ERROR", "Thời lượng các slide lệch quá một phút so với bài học.")
