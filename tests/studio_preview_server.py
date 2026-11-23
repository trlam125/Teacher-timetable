"""Loopback-only disposable harness for headless E2E. Never imported by app."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    DATABASE_URL="postgresql+psycopg://localhost/offline_studio_preview",
    SECRET_KEY="local-headless-test-placeholder",
    APP_ENV="development", APP_BASE_URL="", AI_SLIDES_ENABLED="true",
    AI_SLIDES_OPENROUTER_API_KEY="fixture-provider-never-sent",
    AI_SLIDES_PRIMARY_MODEL="fixture/test:free",
    AI_SLIDES_NATIVE_MOTION_ENABLED="true",
    AI_SLIDES_MAX_REQUESTS_PER_USER_DAY="100",
    AI_SLIDES_MAX_REQUESTS_SERVER_DAY="200",
)

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.routers import ai_slides
from app.services.ai_slides.models import StudioBase
from app.services.authentication.csrf import verify_request_csrf

root = Path(__file__).resolve().parents[1]
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
StudioBase.metadata.create_all(engine)
factory = sessionmaker(engine, expire_on_commit=False)
app = FastAPI(dependencies=[Depends(verify_request_csrf)])
app.include_router(ai_slides.router)
app.add_exception_handler(ai_slides.provider.StudioError, ai_slides.studio_exception_handler)
app.mount("/static", StaticFiles(directory=root / "app/static"))
app.dependency_overrides[ai_slides.current_user] = lambda: SimpleNamespace(
    id=1, role="super_admin", name="Tài khoản kiểm thử", avatar_url="", email="test@example.test",
)


def session():
    with factory() as db:
        yield db


async def model():
    return "fixture/test:free"


async def generate(model_id, schema, payload):
    profile = payload["profile"]
    if payload.get("grounding_contract"):
        import re
        units = payload["grounding_contract"]["units"]
        count = profile["slide_count"]
        if payload["task"] == "plan":
            duration, extra = divmod(profile["duration_minutes"] * 60, count)
            kinds = ["cover", "hook", "concept", "quiz", "summary"]
            return schema.model_validate({"lesson_title": profile["lesson_title"], "objective_unit_ids": [units[0]["id"]], "warnings": [],
                "slides": [{"id": f"s{i+1:03d}", "kind": kinds[i % 5], "duration_seconds": duration + (i < extra), "unit_ids": [units[i % len(units)]["id"]]} for i in range(count)]}), {}
        outlines = [payload["slide"]] if payload["task"] == "edit" else payload["blueprint"]["slides"]
        choices = []
        for outline in outlines:
            allowed = [unit for unit in units if unit["source_id"] in outline["source_ids"]]
            unit = max(allowed, key=lambda item: len(item["quote"]))
            gap, distractors = None, []
            if outline["kind"] == "quiz":
                words = list(dict.fromkeys(re.findall(r"\b\w+\b", unit["quote"])))
                gap = next(word for word in words if unit["quote"].count(word) == 1)
                distractors = [word for word in words if word.casefold() != gap.casefold()][:2]
            choices.append({"id": outline["id"], "bullet_unit_ids": [unit["id"]], "notes_unit_ids": [unit["id"]],
                            "activity": "compare" if payload["task"] == "edit" else "read", "quiz_gap": gap, "quiz_distractors": distractors})
        return schema.model_validate(choices[0] if payload["task"] == "edit" else {"lesson_title": profile["lesson_title"], "slides": choices}), {}
    if payload["task"] == "edit":
        slide = {**payload["slide"]}
        slide["bullets"] = ["Ví dụ đã được sửa trong kiểm thử."]
        return schema.model_validate(slide), {}
    count = profile["slide_count"]
    duration, extra = divmod(profile["duration_minutes"] * 60, count)
    source_ids = [source["id"] for source in profile["sources"]][:12]
    kinds = ["cover", "hook", "concept", "quiz", "summary"]
    slides = []
    for index in range(count):
        kind = kinds[index % len(kinds)]
        slide = {
            "id": f"s{index+1:03d}", "title": profile["lesson_title"] + f" — phần {index+1}",
            "kind": kind, "duration_seconds": duration + (index < extra), "source_ids": source_ids,
        }
        if payload["task"] == "author":
            slide.update(
                bullets=["Ở nhiệt độ không đổi, I = U/R.", "Kiểm tra đơn vị trước khi tính."],
                speaker_notes="Ghi chú giáo viên phục vụ kiểm thử.", teacher_action="Đặt câu hỏi.",
                student_action="Nêu dự đoán.",
            )
            if kind == "quiz":
                slide.update(question="6 / 3 bằng bao nhiêu?", options=["2 A", "18 A"],
                             correct_option=0, explanation="I = 6 / 3 = 2 A.")
        slides.append(slide)
    if payload["task"] == "author":
        slides = []
        for outline in payload["blueprint"]["slides"]:
            slide = {**outline, "bullets": ["Ở nhiệt độ không đổi, I = U/R.", "Kiểm tra đơn vị trước khi tính."],
                     "speaker_notes": "Ghi chú giáo viên phục vụ kiểm thử.", "teacher_action": "Đặt câu hỏi.",
                     "student_action": "Nêu dự đoán."}
            if slide["kind"] == "quiz":
                slide.update(question="6 / 3 bằng bao nhiêu?", options=["2 A", "18 A"],
                             correct_option=0, explanation="I = 6 / 3 = 2 A.")
            if slide["kind"] == "chart":
                slide["chart_data"] = {"chart_type": "bar", "labels": ["2 V", "4 V"], "values": [1, 2],
                                       "series_name": "I (A)", "data_origin": "example"}
            slides.append(slide)
    value = {"lesson_title": profile["lesson_title"], "slides": slides}
    if payload["task"] == "plan":
        value.update(objectives=["Hiểu bài học."], warnings=[])
    return schema.model_validate(value), {}


app.dependency_overrides[ai_slides.db_session] = session
ai_slides.provider.eligible_model = model
ai_slides.provider.generate = generate

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
