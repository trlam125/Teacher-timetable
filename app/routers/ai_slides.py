import logging
import time
from copy import deepcopy

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.services.authentication.sessions import current_user, db_session
from app.services.web import templates
from app.services.ai_slides import provider
from app.services.ai_slides.config import settings
from app.services.ai_slides.models import Deck, Revision, Step, Usage
from app.services.ai_slides.schemas import Blueprint, EditRequest, Instruction, Manifest, OutlineUpdate, PresentationSettings, Profile, RestoreRequest, Slide, SlideBatch
from app.services.ai_slides.review import content_review
from app.services.ai_slides.state import claim, finish_guard, owned_deck, revise, snapshot, validate_content, version_guard


router = APIRouter()
logger = logging.getLogger("smart_tkb.ai_slides")


def studio_user(user=Depends(current_user)):
    if not settings().enabled:
        raise HTTPException(404, "AI Studio chưa được mở.")
    if user.role not in {"teacher", "admin", "super_admin"}:
        raise HTTPException(403, "Tài khoản chưa có quyền sử dụng AI Studio.")
    return user


def expected_version(value):
    try:
        return int((value or "").strip('"'))
    except ValueError:
        raise HTTPException(428, "Hãy tải phiên bản bài giảng trước khi chỉnh sửa.") from None


def serialize(deck):
    return {
        "id": deck.id, "title": deck.title, "version": deck.version,
        "status": deck.status, "profile": deck.profile,
        "blueprint": deck.blueprint, "manifest": deck.manifest,
        "busy": bool(deck.active_token and deck.lease_until > time.time()),
        "error_code": deck.error_code, "updated_at": deck.updated_at,
        "review": content_review(deck.manifest, deck.profile),
    }


def edit_guard(db, deck_id, user_id, expected):
    deck = db.scalar(select(Deck).where(Deck.id == deck_id, Deck.owner_id == user_id).with_for_update())
    if deck is None:
        raise provider.StudioError("DECK_NOT_FOUND", "Không tìm thấy bài giảng.", 404)
    version_guard(deck, expected)
    deck.active_token = None
    deck.lease_until = 0
    return deck


@router.get("/ai-studio")
def studio_page(request: Request, user=Depends(studio_user)):
    return templates.TemplateResponse("ai_slides/studio.html", {"request": request, "user": user})


@router.get("/ai-studio/simulations/{slug}")
def simulation_page(slug: str, request: Request):
    if slug not in {"ohm", "pendulum", "vietnam-map"} or not settings().enabled:
        raise HTTPException(404)
    return templates.TemplateResponse("ai_slides/simulation.html", {"request": request, "slug": slug})


@router.get("/api/ai-slides/capabilities")
def capabilities(user=Depends(studio_user)):
    config = settings()
    return {
        "ai_configured": bool(config.api_key and config.models),
        "native_motion": False,
        "native_motion_message": "Hiệu ứng đang được kiểm thử trên PowerPoint Desktop.",
        "requests_per_user_day": config.calls_per_user,
        "requests_per_site_day": config.calls_per_site,
        "max_slides": 30, "max_source_chars": 40000, "author_batch_size": 5,
    }


@router.get("/api/ai-slides/decks")
def list_decks(user=Depends(studio_user), db: Session = Depends(db_session)):
    rows = db.scalars(select(Deck).where(Deck.owner_id == user.id).order_by(Deck.updated_at.desc()).limit(100)).all()
    return [{"id": row.id, "title": row.title, "status": row.status, "version": row.version, "updated_at": row.updated_at} for row in rows]


@router.post("/api/ai-slides/decks", status_code=201)
def create_deck(payload: Profile, user=Depends(studio_user), db: Session = Depends(db_session)):
    if payload.sources and not payload.consent:
        raise HTTPException(422, "Cần đồng ý trước khi lưu đoạn tài liệu lên tài khoản.")
    count = db.scalar(select(func.count()).select_from(Deck).where(Deck.owner_id == user.id))
    if count >= 100:
        raise HTTPException(409, "Đã có 100 bài giảng. Hãy xóa bài không cần dùng trước khi tạo thêm.")
    deck = Deck(owner_id=user.id, title=payload.lesson_title, profile=payload.model_dump())
    db.add(deck)
    db.flush()
    db.add(Revision(deck_id=deck.id, version=1, snapshot=snapshot(deck)))
    db.commit()
    return serialize(deck)


@router.get("/api/ai-slides/decks/{deck_id}")
def get_deck(deck_id: str, user=Depends(studio_user), db: Session = Depends(db_session)):
    return serialize(owned_deck(db, deck_id, user.id))


@router.patch("/api/ai-slides/decks/{deck_id}/input-profile")
def update_profile(deck_id: str, payload: Profile, if_match: str | None = Header(None),
                   user=Depends(studio_user), db: Session = Depends(db_session)):
    if payload.sources and not payload.consent:
        raise HTTPException(422, "Cần đồng ý trước khi lưu đoạn tài liệu lên tài khoản.")
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    deck.profile = payload.model_dump()
    deck.title = payload.lesson_title
    deck.blueprint = None
    deck.manifest = None
    deck.status = "draft"
    deck.error_code = None
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.get("/api/ai-slides/decks/{deck_id}/revisions")
def revisions(deck_id: str, user=Depends(studio_user), db: Session = Depends(db_session)):
    owned_deck(db, deck_id, user.id)
    return [{"version": row.version, "created_at": row.created_at} for row in db.scalars(
        select(Revision).where(Revision.deck_id == deck_id).order_by(Revision.version.desc()).limit(100),
    )]


@router.patch("/api/ai-slides/decks/{deck_id}/outline")
def update_outline(deck_id: str, payload: OutlineUpdate, if_match: str | None = Header(None),
                   user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    if not deck.blueprint:
        raise HTTPException(409, "Hãy tạo dàn ý trước khi chỉnh sửa.")
    if deck.manifest and not payload.discard_content:
        raise HTTPException(409, "Bài đã có nội dung. Cần xác nhận soạn lại từ dàn ý đã chỉnh; có thể hoàn tác về bài cũ.")
    try:
        validate_content(payload.blueprint, deck.profile)
    except provider.StudioError as error:
        raise provider.StudioError(error.code, error.message, 422) from None
    deck.blueprint = payload.blueprint.model_dump()
    deck.manifest = None
    deck.status = "needs_review" if payload.blueprint.warnings else "planned"
    deck.error_code = None
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.patch("/api/ai-slides/decks/{deck_id}/presentation")
def update_presentation(deck_id: str, payload: PresentationSettings, if_match: str | None = Header(None),
                        user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    deck.profile = {**deck.profile, **payload.model_dump()}
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.get("/api/ai-slides/decks/{deck_id}/steps")
def step_history(deck_id: str, user=Depends(studio_user), db: Session = Depends(db_session)):
    owned_deck(db, deck_id, user.id)
    return [{
        "id": row.id, "kind": row.kind, "state": row.state, "model": row.model,
        "input_version": row.input_version, "error_code": row.error_code,
        "error_message": row.error_message, "created_at": row.created_at,
    } for row in db.scalars(select(Step).where(Step.deck_id == deck_id).order_by(Step.created_at.desc(), Step.id.desc()).limit(100))]


@router.post("/api/ai-slides/decks/{deck_id}/restore")
def restore(deck_id: str, payload: RestoreRequest, if_match: str | None = Header(None),
            user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    revision = db.scalar(select(Revision).where(Revision.deck_id == deck_id, Revision.version == payload.version))
    if revision is None:
        raise HTTPException(404, "Không tìm thấy phiên bản.")
    for field in ("profile", "blueprint", "manifest", "title", "status"):
        setattr(deck, field, revision.snapshot[field])
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.patch("/api/ai-slides/decks/{deck_id}/slides/{slide_id}")
def edit_slide(deck_id: str, slide_id: str, payload: EditRequest, if_match: str | None = Header(None),
               user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    if deck.status != "ready" or not deck.manifest or payload.slide.id != slide_id:
        raise HTTPException(409, "Slide chưa sẵn sàng.")
    manifest = deepcopy(deck.manifest)
    indices = [index for index, slide in enumerate(manifest["slides"]) if slide["id"] == slide_id]
    if not indices:
        raise HTTPException(404, "Không tìm thấy slide.")
    manifest["slides"][indices[0]] = payload.slide.model_dump()
    validate_content(Manifest.model_validate(manifest), deck.profile)
    deck.manifest = manifest
    deck.error_code = None
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.delete("/api/ai-slides/decks/{deck_id}")
def delete_deck(deck_id: str, if_match: str | None = Header(None),
                user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    for model in (Step, Revision):
        db.execute(delete(model).where(model.deck_id == deck.id))
    db.delete(deck)
    db.commit()
    return {"ok": True}


async def ai_step(deck_id, kind, key, version, user, db, *, slide_id=None, instruction=None):
    deck = owned_deck(db, deck_id, user.id)
    step_kind = kind if not slide_id else f"edit:{slide_id}"
    prior = db.scalar(select(Step).where(Step.deck_id == deck.id, Step.idempotency_key == key))
    if prior is not None and prior.state == "completed":
        same_kind = prior.kind == step_kind or (kind == "author" and prior.kind.startswith("author:"))
        if not same_kind or prior.input_version != version:
            raise provider.StudioError("STEP_CONFLICT", "Mã yêu cầu đã được dùng cho nội dung khác.", 409)
        return {"proposal": prior.proposal, "version": version} if prior.proposal else serialize(deck)
    if not deck.profile.get("consent"):
        raise provider.StudioError("CONSENT_REQUIRED", "Hãy đồng ý gửi thông tin bài học đã chọn tới AI.", 422)
    if kind == "author" and (not deck.blueprint or deck.blueprint.get("warnings")):
        raise provider.StudioError("NEEDS_TEACHER_REVIEW", "Hãy xác nhận các lưu ý trong dàn ý trước khi soạn slide.", 422)
    if kind == "edit" and (deck.status != "ready" or not deck.manifest):
        raise provider.StudioError("STEP_CONFLICT", "Bài giảng chưa có nội dung để sửa.", 409)
    version_guard(deck, version)
    cursor = len((deck.manifest or {}).get("slides", [])) if kind == "author" else 0
    if kind == "author":
        if cursor >= len(deck.blueprint["slides"]):
            return serialize(deck)
        step_kind = f"author:{cursor}"
    model_id = await provider.eligible_model()
    step = claim(db, deck, step_kind, key, version)
    if step is None:
        return serialize(deck)
    token = step.id
    step.model = model_id
    db.commit()
    schema = {"plan": Blueprint, "author": SlideBatch, "edit": Slide}[kind]
    profile = deepcopy(deck.profile)
    payload = {"task": kind, "profile": profile, "prompt_version": provider.PROMPT_VERSION}
    if kind == "author":
        payload["blueprint"] = deepcopy(deck.blueprint)
        payload["blueprint"]["slides"] = deck.blueprint["slides"][cursor:cursor + 5]
        payload["author_scope"] = {
            "slides_in_response": len(payload["blueprint"]["slides"]),
            "response_total_seconds": sum(slide["duration_seconds"] for slide in payload["blueprint"]["slides"]),
        }
    if kind == "edit":
        matching = [slide for slide in deck.manifest["slides"] if slide["id"] == slide_id]
        if not matching:
            finish_guard(db, deck.id, token, version)
            step.state = "failed"
            db.commit()
            raise provider.StudioError("SLIDE_NOT_FOUND", "Không tìm thấy slide.", 404)
        payload.update(slide=matching[0], instruction=instruction, editable_fields=[
            "title", "bullets", "speaker_notes", "teacher_action", "student_action",
            "question", "options", "correct_option", "explanation",
        ])
    db.close()
    usage = {}
    try:
        result, usage = await provider.generate(model_id, schema, payload)
        deck = finish_guard(db, deck_id, token, version)
        step = db.get(Step, token)
        if kind == "plan":
            validate_content(result, profile)
            deck.blueprint = result.model_dump()
            deck.manifest = None
            deck.status = "needs_review" if result.warnings else "planned"
        elif kind == "author":
            batch_profile = {**profile, "slide_count": payload["author_scope"]["slides_in_response"],
                             "duration_minutes": payload["author_scope"]["response_total_seconds"] / 60}
            validate_content(result, batch_profile, payload["blueprint"], partial=True)
            if [slide.duration_seconds for slide in result.slides] != [slide["duration_seconds"] for slide in payload["blueprint"]["slides"]]:
                raise provider.StudioError("AI_CONSTRAINT_ERROR", "Thời lượng slide khác dàn ý đã duyệt. Hãy thử lại.")
            merged = result.model_dump()
            merged["slides"] = (deck.manifest or {}).get("slides", []) + merged["slides"]
            complete = len(merged["slides"]) == profile["slide_count"]
            if complete:
                validate_content(Manifest.model_validate(merged), profile, deck.blueprint)
            deck.manifest = merged
            deck.status = "ready" if complete else "authoring"
        else:
            original = payload["slide"]
            proposed = result.model_dump()
            for field in ("id", "kind", "duration_seconds", "source_ids", "resource_id"):
                if proposed[field] != original[field]:
                    raise provider.StudioError("AI_SCOPE_ERROR", "AI đề nghị sửa ngoài phạm vi slide cho phép.", 422)
            step.state = "completed"
            step.model = model_id
            step.proposal = proposed
            db.add(Usage(owner_id=user.id, deck_id=deck_id, step_id=token, model=model_id, status="proposal", **usage))
            db.commit()
            return {"proposal": proposed, "version": deck.version}
        deck.error_code = None
        revise(db, deck)
        step.state = "completed"
        step.model = model_id
        db.add(Usage(owner_id=user.id, deck_id=deck_id, step_id=token, model=model_id, status="completed", **usage))
        db.commit()
        return serialize(deck)
    except Exception as error:
        db.rollback()
        if not isinstance(error, provider.StudioError):
            logger.exception("Unexpected Studio failure step=%s deck=%s", token, deck_id)
        failure = error if isinstance(error, provider.StudioError) else provider.StudioError(
            "AI_INTERNAL_ERROR", "Xử lý bài giảng gặp lỗi. Bản nháp vẫn được giữ.",
        )
        db.execute(update(Deck).where(Deck.id == deck_id, Deck.active_token == token).values(
            active_token=None, lease_until=0, error_code=failure.code,
        ))
        stored_step = db.get(Step, token)
        if stored_step:
            stored_step.state = "failed"
            stored_step.model = model_id
            stored_step.error_code = failure.code
            stored_step.error_message = failure.message
        db.add(Usage(owner_id=user.id, deck_id=deck_id, step_id=token, model=model_id, status=failure.code, **usage))
        db.commit()
        logger.warning("Studio step=%s deck=%s model=%s error=%s", token, deck_id, model_id, failure.code)
        failure.step_id = token
        raise failure


@router.post("/api/ai-slides/decks/{deck_id}/plan")
@router.post("/api/ai-slides/decks/{deck_id}/author")
async def generate_step(deck_id: str, request: Request, if_match: str | None = Header(None),
                        idempotency_key: str = Header(..., min_length=8, max_length=128),
                        user=Depends(studio_user), db: Session = Depends(db_session)):
    kind = request.url.path.rsplit("/", 1)[-1]
    return await ai_step(deck_id, kind, idempotency_key, expected_version(if_match), user, db)


@router.post("/api/ai-slides/decks/{deck_id}/approve-outline")
def approve_outline(deck_id: str, if_match: str | None = Header(None),
                    user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    if not deck.blueprint:
        raise HTTPException(409, "Chưa có dàn ý.")
    blueprint = deepcopy(deck.blueprint)
    blueprint["warnings"] = []
    deck.blueprint = blueprint
    deck.status = "planned"
    revise(db, deck)
    db.commit()
    return serialize(deck)


@router.post("/api/ai-slides/decks/{deck_id}/slides/{slide_id}/propose")
async def propose_edit(deck_id: str, slide_id: str, payload: Instruction,
                       if_match: str | None = Header(None),
                       idempotency_key: str = Header(..., min_length=8, max_length=128),
                       user=Depends(studio_user), db: Session = Depends(db_session)):
    return await ai_step(deck_id, "edit", idempotency_key, expected_version(if_match), user, db,
                         slide_id=slide_id, instruction=payload.instruction)


@router.get("/api/ai-slides/admin/usage")
def admin_usage(user=Depends(studio_user), db: Session = Depends(db_session)):
    if user.role not in {"admin", "super_admin"}:
        raise HTTPException(403)
    return [{
        "step_id": row.step_id, "model": row.model, "status": row.status,
        "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
        "created_at": row.created_at,
    } for row in db.scalars(select(Usage).order_by(Usage.id.desc()).limit(100))]


async def studio_exception_handler(request, error):
    return JSONResponse({"code": error.code, "message": error.message,
                         "step_id": getattr(error, "step_id", None), "provider_status": error.provider_status}, status_code=error.status)
