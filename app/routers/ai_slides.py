import logging
import time
from copy import deepcopy

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.services.authentication.sessions import current_user, db_session
from app.services.web import templates
from app.services.ai_slides import provider
from app.services.ai_slides.analysis import analyze_sources, resolved_claims, validated_resolutions
from app.services.ai_slides.grounding import STAGES, VERSION as GROUNDING_VERSION, assemble_batch, assemble_plan, assemble_slide, proof_valid, source_units
from app.services.ai_slides.config import settings
from app.services.ai_slides.models import Deck, Revision, Step, Usage
from app.services.ai_slides.schemas import Blueprint, EditRequest, GroundedBatch, GroundedChoice, GroundedPlan, Instruction, Manifest, OutlineUpdate, PresentationSettings, Profile, RecognitionRequest, RestoreRequest, Slide, SlideBatch, SourceReview
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
    analysis = analyze_sources(deck.profile)
    return {
        "id": deck.id, "title": deck.title, "version": deck.version,
        "status": "needs_source_review" if analysis["unresolved"] else deck.status, "profile": deck.profile,
        "blueprint": deck.blueprint, "manifest": deck.manifest,
        "busy": bool(deck.active_token and deck.lease_until > time.time()),
        "error_code": deck.error_code, "updated_at": deck.updated_at,
        "review": content_review(deck.manifest, deck.profile),
        "source_analysis": analysis,
        "grounding_report": [{"slide_id": slide["id"], "verified": proof_valid(slide, deck.profile),
                              "citations": (slide.get("source_proof") or {}).get("citations", []) if proof_valid(slide, deck.profile) else []}
                             for slide in (deck.manifest or {}).get("slides", [])] if deck.profile.get("grounding") == "strict" else [],
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
        "native_motion": config.native_motion,
        "native_motion_message": ("Đã bật Appear/Fade và chuyển cảnh Fade theo bộ kiểm thử PowerPoint Desktop."
                                  if config.native_motion else "Hiệu ứng chưa được bật tại môi trường này sau kiểm thử PowerPoint Desktop."),
        "requests_per_user_day": config.calls_per_user,
        "requests_per_site_day": config.calls_per_site,
        "max_slides": 30, "max_source_chars": 40000, "author_batch_size": 5,
    }


@router.get("/api/ai-slides/decks")
def list_decks(user=Depends(studio_user), db: Session = Depends(db_session)):
    rows = db.scalars(select(Deck).where(Deck.owner_id == user.id).order_by(Deck.updated_at.desc()).limit(100)).all()
    return [{"id": row.id, "title": row.title, "status": "needs_source_review" if analyze_sources(row.profile)["unresolved"] else row.status,
             "version": row.version, "updated_at": row.updated_at} for row in rows]


@router.post("/api/ai-slides/decks", status_code=201)
def create_deck(payload: Profile, user=Depends(studio_user), db: Session = Depends(db_session)):
    if payload.sources and not payload.consent:
        raise HTTPException(422, "Cần đồng ý trước khi lưu đoạn tài liệu lên tài khoản.")
    check_resolutions(payload.model_dump(), payload.model_dump()["source_resolutions"])
    count = db.scalar(select(func.count()).select_from(Deck).where(Deck.owner_id == user.id))
    if count >= 100:
        raise HTTPException(409, "Đã có 100 bài giảng. Hãy xóa bài không cần dùng trước khi tạo thêm.")
    deck = Deck(owner_id=user.id, title=payload.lesson_title, profile=payload.model_dump())
    db.add(deck)
    db.flush()
    db.add(Revision(deck_id=deck.id, version=1, snapshot=snapshot(deck)))
    db.commit()
    return serialize(deck)


def check_resolutions(profile, resolutions):
    try:
        return validated_resolutions(profile, resolutions)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/api/ai-slides/analyze-sources")
def recognize_sources(payload: RecognitionRequest, user=Depends(studio_user)):
    return analyze_sources({**payload.hints.model_dump(), "sources": [source.model_dump() for source in payload.sources]})


@router.patch("/api/ai-slides/decks/{deck_id}/source-review")
def review_sources(deck_id: str, payload: SourceReview, if_match: str | None = Header(None),
                   user=Depends(studio_user), db: Session = Depends(db_session)):
    deck = edit_guard(db, deck_id, user.id, expected_version(if_match))
    resolutions = [item.model_dump() for item in payload.resolutions]
    check_resolutions(deck.profile, resolutions)
    prior = {item["conflict_id"]: item["evidence_id"] for item in deck.profile.get("source_resolutions", [])}
    changed = prior != {item["conflict_id"]: item["evidence_id"] for item in resolutions}
    if changed and (deck.blueprint or deck.manifest):
        if not payload.discard_content:
            raise HTTPException(409, "Đổi thông tin ưu tiên cần xác nhận soạn lại. Bài cũ được giữ để hoàn tác.")
        deck.blueprint = None
        deck.manifest = None
        deck.status = "draft"
        deck.error_code = None
    deck.profile = {**deck.profile, "source_resolutions": resolutions}
    revise(db, deck)
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
    check_resolutions(payload.model_dump(), payload.model_dump()["source_resolutions"])
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
    if deck.profile.get("grounding") == "strict" and any(slide.kind not in STAGES for slide in payload.blueprint.slides):
        raise HTTPException(422, "Chế độ trích đoạn chưa tự tạo biểu đồ, bản đồ, video hoặc thí nghiệm. Hãy dùng loại nội dung khác hoặc chuyển sang Cân bằng.")
    if deck.profile.get("grounding") == "strict":
        units = source_units(deck.profile)
        for slide in payload.blueprint.slides:
            eligible = [unit["id"] for unit in units if unit["source_id"] in slide.source_ids]
            if not eligible:
                raise HTTPException(422, f"Slide {slide.id} cần nguồn còn trích đoạn hợp lệ. Hãy chọn lại nguồn trước khi lưu dàn ý.")
            slide.source_unit_ids = [unit_id for unit_id in slide.source_unit_ids if unit_id in eligible] or eligible[:5]
    payload.blueprint.grounding_version = deck.blueprint.get("grounding_version")
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
    previous = manifest["slides"][indices[0]]
    changed = payload.slide.model_dump()
    # A caller cannot mint proof by sending it in a manual PATCH. Preserve only
    # a pre-existing server proof when every content field is still identical.
    changed["source_proof"] = previous.get("source_proof")
    if not proof_valid(changed, deck.profile):
        changed["source_proof"] = None
    if payload.proposal_step_id:
        proposal_step = db.get(Step, payload.proposal_step_id)
        proposed = payload.slide.model_dump()
        if (not proposal_step or proposal_step.deck_id != deck.id or proposal_step.state != "completed"
                or proposal_step.input_version != deck.version or proposal_step.proposal != proposed):
            raise HTTPException(409, "Đề xuất không còn khớp phiên bản bài giảng. Hãy yêu cầu AI đề xuất lại.")
        changed = proposed
    manifest["slides"][indices[0]] = changed
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
        return {"proposal": prior.proposal, "version": version, "step_id": prior.id} if prior.proposal else serialize(deck)
    if not deck.profile.get("consent"):
        raise provider.StudioError("CONSENT_REQUIRED", "Hãy đồng ý gửi thông tin bài học đã chọn tới AI.", 422)
    if analyze_sources(deck.profile)["unresolved"]:
        raise provider.StudioError("SOURCE_REVIEW_REQUIRED", "Các nguồn có thông tin khác nhau. Hãy chọn thông tin ưu tiên trong phần Rà soát nguồn trước khi gọi AI.", 422)
    if kind == "author" and (not deck.blueprint or deck.blueprint.get("warnings")):
        raise provider.StudioError("NEEDS_TEACHER_REVIEW", "Hãy xác nhận các lưu ý trong dàn ý trước khi soạn slide.", 422)
    if kind == "edit" and (deck.status != "ready" or not deck.manifest):
        raise provider.StudioError("STEP_CONFLICT", "Bài giảng chưa có nội dung để sửa.", 409)
    version_guard(deck, version)
    strict = deck.profile.get("grounding") == "strict"
    catalog = source_units(deck.profile) if strict else None
    if strict and "objectives" in deck.profile.get("locked_fields", []) and deck.profile.get("objectives"):
        locked = [line.strip() for line in deck.profile["objectives"].splitlines() if line.strip()]
        if len(locked) > 6 or any(len(line) > 300 for line in locked):
            raise provider.StudioError("TEACHER_CONSTRAINTS_INVALID", "Mục tiêu đã khóa cần tối đa 6 dòng, mỗi dòng tối đa 300 ký tự.", 422)
    if strict and kind == "author" and deck.blueprint.get("grounding_version") != GROUNDING_VERSION:
        raise provider.StudioError("GROUNDING_REPLAN_REQUIRED", "Dàn ý này có trước chế độ trích đoạn. Hãy lập lại dàn ý bám nguồn; bản cũ vẫn nằm trong lịch sử.", 422)
    if strict and kind == "author" and any(not any(unit["source_id"] in slide["source_ids"] for unit in catalog) for slide in deck.blueprint["slides"]):
        raise provider.StudioError("GROUNDING_OUTLINE_INVALID", "Một số slide chưa có trích đoạn hợp lệ. Hãy chỉnh nguồn trong dàn ý trước khi soạn.", 422)
    selected_slide = next((slide for slide in (deck.manifest or {}).get("slides", []) if slide["id"] == slide_id), None) if kind == "edit" else None
    if kind == "edit" and selected_slide is None:
        raise provider.StudioError("SLIDE_NOT_FOUND", "Không tìm thấy slide.", 404)
    if strict and kind == "edit" and (selected_slide["kind"] not in STAGES or not any(unit["source_id"] in selected_slide["source_ids"] for unit in catalog)):
        raise provider.StudioError("GROUNDING_EDIT_UNSUPPORTED", "Slide này chưa hỗ trợ chọn lại trích đoạn bằng AI. Hãy chỉnh tay hoặc đổi loại/nguồn trước.", 422)
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
    if strict:
        schema = {"plan": GroundedPlan, "author": GroundedBatch, "edit": GroundedChoice}[kind]
    profile = deepcopy(deck.profile)
    payload = {"task": kind, "profile": profile, "prompt_version": provider.PROMPT_VERSION}
    payload["source_decisions"] = resolved_claims(profile)
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
        if strict:
            catalog = [unit for unit in catalog if unit["source_id"] in matching[0]["source_ids"]]
    if strict:
        payload["grounding_contract"] = {"version": GROUNDING_VERSION, "units": catalog}
        payload["profile"] = {**profile, "sources": [{key: source.get(key) for key in ("id", "name", "page", "role")} for source in profile["sources"]]}
    db.close()
    usage = {}
    try:
        result, usage = await provider.generate(model_id, schema, payload)
        deck = finish_guard(db, deck_id, token, version)
        step = db.get(Step, token)
        if strict:
            if kind == "plan":
                result = assemble_plan(result, deck.profile, catalog)
            elif kind == "author":
                result = assemble_batch(result, deck.profile, payload["blueprint"], catalog)
            else:
                result = assemble_slide(result, deck.profile, payload["slide"], catalog)
        elif kind == "plan":
            result.grounding_version = None
        elif kind == "author":
            for slide in result.slides:
                slide.source_proof = None
        else:
            result.source_proof = None
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
            return {"proposal": proposed, "version": deck.version, "step_id": token}
        deck.error_code = None
        revise(db, deck)
        step.state = "completed"
        step.model = model_id
        db.add(Usage(owner_id=user.id, deck_id=deck_id, step_id=token, model=model_id, status="completed", **usage))
        db.commit()
        return serialize(deck)
    except Exception as error:
        db.rollback()
        if isinstance(error, ValidationError):
            paths = [".".join(map(str, item["loc"])) for item in error.errors(include_input=False)][:5]
            error = provider.StudioError("AI_GROUNDING_ERROR" if strict else "AI_INVALID_JSON",
                                         "Nội dung không khớp ràng buộc: " + ", ".join(paths) + ". Bản nháp được giữ.", 422)
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
