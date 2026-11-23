import asyncio
import os
import time
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


PROFILE = {
    "input_mode": "manual", "subject": "Vật lí", "grade": "Lớp 9",
    "lesson_title": "Định luật Ôm", "duration_minutes": 45, "slide_count": 5,
    "consent": True, "locked_fields": ["lesson_title", "duration_minutes"],
}


def fixture_blueprint():
    return {
        "lesson_title": PROFILE["lesson_title"], "objectives": ["Nêu được I = U/R."],
        "slides": [{
            "id": f"s{number:03d}", "kind": kind, "title": title,
            "duration_seconds": 540, "source_ids": [],
        } for number, (kind, title) in enumerate([
            ("cover", "Định luật Ôm"), ("hook", "Điều gì làm thay đổi dòng điện?"),
            ("concept", "Mối quan hệ U, I, R"), ("quiz", "Kiểm tra hiểu bài"),
            ("summary", "Vận dụng"),
        ], 1)],
        "warnings": [],
    }


def fixture_manifest():
    from app.services.ai_slides.schemas import Manifest
    blueprint = fixture_blueprint()
    slides = deepcopy(blueprint["slides"])
    for slide in slides:
        slide.update(bullets=["Ở nhiệt độ không đổi, I = U/R.", "Đơn vị U là V, I là A và R là Ω."],
                     speaker_notes="Hỏi học sinh về điều kiện áp dụng.")
        if slide["kind"] == "quiz":
            slide.update(question="U = 6 V, R = 3 Ω. I bằng bao nhiêu?", options=["2 A", "18 A"],
                         correct_option=0, explanation="I = 6 / 3 = 2 A.")
    return Manifest.model_validate({"lesson_title": PROFILE["lesson_title"], "slides": slides})


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "SECRET_KEY": "offline-studio-test-placeholder",
            "DATABASE_URL": "postgresql+psycopg://localhost/offline_studio_test",
            "APP_ENV": "development", "APP_BASE_URL": "",
        }):
            from app.routers import ai_slides
            from app.services.authentication.csrf import verify_request_csrf
        cls.routes = ai_slides
        cls.csrf = staticmethod(verify_request_csrf)

    def setUp(self):
        from app.services.ai_slides.models import StudioBase
        self.env = self.enterContext(patch.dict(os.environ, {
            "AI_SLIDES_ENABLED": "true", "AI_SLIDES_MAX_REQUESTS_PER_USER_DAY": "8",
            "AI_SLIDES_MAX_REQUESTS_SERVER_DAY": "40",
        }))
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        StudioBase.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.user = SimpleNamespace(id=1, role="teacher", name="Test Teacher", avatar_url="", email="teacher@example.test")
        self.app = FastAPI(dependencies=[Depends(self.csrf)])
        self.app.include_router(self.routes.router)
        self.app.add_exception_handler(self.routes.provider.StudioError, self.routes.studio_exception_handler)
        self.app.dependency_overrides[self.routes.current_user] = lambda: self.user
        self.app.dependency_overrides[self.routes.db_session] = self.session
        self.client = self.enterContext(TestClient(self.app, base_url="https://testserver"))
        page = self.client.get("/ai-studio")
        self.assertEqual(page.status_code, 200)
        token = page.text.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
        self.client.headers["X-CSRF-Token"] = token

    def session(self):
        with self.session_factory() as db:
            yield db

    def create(self, **overrides):
        response = self.client.post("/api/ai-slides/decks", json={**PROFILE, **overrides})
        self.assertEqual(response.status_code, 201, response.text[:500])
        return response.json()

    def test_generation_mode_is_persisted_and_legacy_clients_keep_outline_behavior(self):
        self.assertEqual(self.create()["profile"]["generation_mode"], "outline")
        automatic = self.create(generation_mode="automatic")
        loaded = self.client.get(f"/api/ai-slides/decks/{automatic['id']}")
        self.assertEqual(loaded.json()["profile"]["generation_mode"], "automatic")

    def call_step(self, deck, kind, key="test-request-key-001"):
        return self.client.post(f"/api/ai-slides/decks/{deck['id']}/{kind}", headers={
            "If-Match": str(deck["version"]), "Idempotency-Key": key,
        })

    def seed_ready(self):
        from app.services.ai_slides.models import Deck, Revision
        from app.services.ai_slides.state import snapshot
        deck = self.create()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = fixture_blueprint()
            row.manifest = fixture_manifest().model_dump()
            row.status = "ready"
            revision = db.scalar(select(Revision).where(Revision.deck_id == row.id, Revision.version == 1))
            revision.snapshot = snapshot(row)
            db.commit()
        return self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()

    def test_source_recognition_requires_consent_and_returns_evidence_without_ai(self):
        body = {"sources": [{"id": "book", "name": "SGK", "page": 35,
                 "text": "Môn: Vật lí\nLớp 9\nBài 12: Định luật Ôm\nThời lượng: 45 phút\nI = U/R."}], "hints": {}}
        with patch.object(self.routes.provider, "generate", new_callable=AsyncMock) as generate:
            self.assertEqual(self.client.post("/api/ai-slides/analyze-sources", json=body).status_code, 422)
            response = self.client.post("/api/ai-slides/analyze-sources", json={**body, "consent": True})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["metadata"]["subject"][0]["value"], "Vật lí")
            self.assertEqual(result["metadata"]["grade"][0]["value"], "Lớp 9")
            self.assertEqual(result["metadata"]["lesson_title"][0]["page"], 35)
            self.assertIn("Bài 12", result["metadata"]["lesson_title"][0]["quote"])
            generate.assert_not_called()

    def test_source_conflict_blocks_ai_until_versioned_evidence_choice_and_undo(self):
        from app.services.ai_slides.models import Quota
        sources = [{"id": "a", "name": "Nguồn A", "text": "I = U/R."},
                   {"id": "b", "name": "Nguồn B", "text": "I = U*R.", "role": "reference"}]
        deck = self.create(sources=sources)
        self.assertTrue(deck["source_analysis"]["unresolved"])
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock) as model:
            blocked = self.call_step(deck, "plan")
            self.assertEqual(blocked.status_code, 422, blocked.text)
            self.assertEqual(blocked.json()["code"], "SOURCE_REVIEW_REQUIRED")
            model.assert_not_called()
        with self.session_factory() as db:
            self.assertEqual(len(db.scalars(select(Quota)).all()), 0)
        conflict = deck["source_analysis"]["conflicts"][0]
        selected = next(item for item in conflict["evidence"] if item["source_id"] == "a")
        body = {"resolutions": [{"conflict_id": conflict["id"], "evidence_id": selected["id"]}]}
        url = f"/api/ai-slides/decks/{deck['id']}/source-review"
        self.user.id = 2
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=body).status_code, 404)
        self.user.id = 1
        self.assertEqual(self.client.patch(url, headers={"If-Match": "99"}, json=body).status_code, 409)
        bad = {"resolutions": [{"conflict_id": conflict["id"], "evidence_id": "made-up"}]}
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=bad).status_code, 422)
        response = self.client.patch(url, headers={"If-Match": "1"}, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["source_analysis"]["unresolved"])
        self.assertEqual(response.json()["profile"]["sources"], deck["profile"]["sources"])
        restored = self.client.post(f"/api/ai-slides/decks/{deck['id']}/restore", headers={"If-Match": "2"}, json={"version": 1})
        self.assertTrue(restored.json()["source_analysis"]["unresolved"])

    def test_source_decisions_cannot_be_reused_after_text_change(self):
        from app.services.ai_slides.analysis import analyze_sources
        from app.services.ai_slides.schemas import Profile
        profile = Profile.model_validate({**PROFILE, "sources": [
            {"id": "a", "name": "A", "text": "I = U/R."}, {"id": "b", "name": "B", "text": "I = U*R."}]}).model_dump()
        conflict = analyze_sources(profile)["conflicts"][0]
        profile["source_resolutions"] = [{"conflict_id": conflict["id"], "evidence_id": conflict["evidence"][0]["id"]}]
        self.assertFalse(analyze_sources(profile)["unresolved"])
        profile["sources"][0]["text"] += " Tài liệu đã chỉnh."
        self.assertTrue(analyze_sources(profile)["unresolved"])

    def test_formula_detection_ignores_examples_and_equivalent_multiplication(self):
        from app.services.ai_slides.analysis import analyze_sources
        result = analyze_sources({"sources": [{"id": "a", "name": "A", "text": "I = 6/3. I = 9/3. U = I*R. U = R×I."}]})
        self.assertEqual(result["conflicts"], [])

    def test_source_metadata_keeps_teacher_fields_and_rejects_overriding_choice(self):
        deck = self.create(sources=[{"id": "a", "name": "Sách", "text": "Bài 13: Điện trở\nLớp 10"}])
        self.assertEqual(deck["profile"]["lesson_title"], PROFILE["lesson_title"])
        conflict = next(item for item in deck["source_analysis"]["conflicts"] if item["field"] == "lesson_title")
        other = next(item for item in conflict["evidence"] if item["source_id"])
        response = self.client.patch(f"/api/ai-slides/decks/{deck['id']}/source-review", headers={"If-Match": "1"},
                                    json={"resolutions": [{"conflict_id": conflict["id"], "evidence_id": other["id"]}]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()["version"], 1)

    def test_resolved_source_choices_are_sent_to_provider(self):
        deck = self.create(sources=[{"id": "a", "name": "A", "text": "I = U/R."}, {"id": "b", "name": "B", "text": "I = U*R."}])
        conflict = deck["source_analysis"]["conflicts"][0]
        body = {"resolutions": [{"conflict_id": conflict["id"], "evidence_id": conflict["evidence"][0]["id"]}]}
        deck = self.client.patch(f"/api/ai-slides/decks/{deck['id']}/source-review", headers={"If-Match": "1"}, json=body).json()
        from app.services.ai_slides.schemas import Blueprint
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"), \
             patch.object(self.routes.provider, "generate", new_callable=AsyncMock, return_value=(Blueprint.model_validate(fixture_blueprint()), {})) as generate:
            response = self.call_step(deck, "plan")
            self.assertEqual(response.status_code, 200, response.text)
            decisions = generate.call_args.args[2]["source_decisions"]
            self.assertEqual(decisions[0]["selected"]["source_id"], "a")
            self.assertEqual(decisions[0]["alternatives"][0]["source_id"], "b")

    def test_changing_source_choice_requires_explicit_reset_when_content_exists(self):
        from app.services.ai_slides.models import Deck
        deck = self.create(sources=[{"id": "a", "name": "A", "text": "I = U/R."}, {"id": "b", "name": "B", "text": "I = U*R."}])
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = fixture_blueprint()
            row.manifest = fixture_manifest().model_dump()
            row.status = "ready"
            db.commit()
        conflict = deck["source_analysis"]["conflicts"][0]
        body = {"resolutions": [{"conflict_id": conflict["id"], "evidence_id": conflict["evidence"][0]["id"]}]}
        url = f"/api/ai-slides/decks/{deck['id']}/source-review"
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=body).status_code, 409)
        response = self.client.patch(url, headers={"If-Match": "1"}, json={**body, "discard_content": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["manifest"])
        self.assertIsNone(response.json()["blueprint"])
        self.assertEqual(response.json()["status"], "draft")

    def strict_profile(self):
        from app.services.ai_slides.schemas import Profile
        return Profile.model_validate({**PROFILE, "grounding": "strict", "sources": [{
            "id": "book", "name": "Nguồn tổng hợp", "page": 35,
            "text": "Ở nhiệt độ không đổi, I = U/R. U đo bằng V, R đo bằng Ω, I đo bằng A.\nU = 6 V và R = 3 Ω thì I = 2 A.\nCường độ dòng điện tỉ lệ thuận với hiệu điện thế khi điện trở không đổi.",
        }]}).model_dump()

    def test_extractive_strict_assembly_has_only_literal_source_content_and_proof(self):
        from app.services.ai_slides.grounding import source_units, assemble_batch, proof_valid, grounded_title
        from app.services.ai_slides.schemas import GroundedBatch
        profile = self.strict_profile()
        units = source_units(profile)
        outline = fixture_blueprint()
        outline["slides"] = [outline["slides"][2]]
        outline["slides"][0]["source_ids"] = ["book"]
        outline["slides"][0]["title"] = grounded_title(profile, outline["slides"][0]["kind"], "s003")
        choice = {"id": "s003", "bullet_unit_ids": [units[0]["id"]], "notes_unit_ids": [units[-1]["id"]],
                  "activity": "discuss", "quiz_gap": None, "quiz_distractors": []}
        batch = assemble_batch(GroundedBatch(lesson_title=profile["lesson_title"], slides=[choice]), profile, outline)
        slide = batch.slides[0].model_dump()
        self.assertEqual(slide["bullets"], [units[0]["quote"]])
        self.assertTrue(proof_valid(slide, profile))
        self.assertNotIn("SGK", slide["speaker_notes"])
        slide["speaker_notes"] += " Diode có đặc tính khác."
        self.assertFalse(proof_valid(slide, profile))

    def test_strict_ai_edit_does_not_certify_arbitrary_manual_title(self):
        from app.services.ai_slides.grounding import assemble_slide, source_units, proof_valid
        from app.services.ai_slides.schemas import GroundedChoice
        profile = self.strict_profile()
        units = source_units(profile)
        outline = {**fixture_blueprint()["slides"][2], "title": "Mặt Trăng làm ra dòng điện", "source_ids": ["book"]}
        choice = GroundedChoice(id=outline["id"], bullet_unit_ids=[units[0]["id"]])
        result = assemble_slide(choice, profile, outline, units).model_dump()
        self.assertEqual(result["title"], outline["title"])
        self.assertFalse(proof_valid(result, profile))
        from app.services.ai_slides.review import content_review
        self.assertIn("UNVERIFIED_GROUNDING", {item["code"] for item in content_review({"slides": [result]}, profile)})

    def test_strict_quiz_options_cannot_use_source_outside_slide_scope(self):
        from app.services.ai_slides.grounding import assemble_slide, source_units
        from app.services.ai_slides.schemas import GroundedChoice
        profile = self.strict_profile()
        profile["sources"].append({"id": "other", "name": "Ngoài phạm vi slide", "text": "Quang hợp.", "page": None})
        units = source_units(profile)
        outline = {**fixture_blueprint()["slides"][3], "source_ids": ["book"]}
        choice = GroundedChoice(id="s004", bullet_unit_ids=[units[0]["id"]], quiz_gap="U/R", quiz_distractors=["Quang hợp"])
        with self.assertRaises(self.routes.provider.StudioError):
            assemble_slide(choice, profile, outline, units)

    def test_rejected_formula_across_lines_or_chunks_is_not_selectable(self):
        from app.services.ai_slides.grounding import source_units
        from app.services.ai_slides.analysis import analyze_sources
        for text in ["I =\nU * R.", "a " * 137 + "I = U * R."]:
            with self.subTest(text=text[:30]):
                profile = self.strict_profile()
                profile["sources"].append({"id": "bad", "name": "B", "page": None, "text": text})
                conflict = next(item for item in analyze_sources(profile)["conflicts"] if item["kind"] == "formula")
                chosen = next(item for item in conflict["evidence"] if item["source_id"] == "book")
                profile["source_resolutions"] = [{"conflict_id": conflict["id"], "evidence_id": chosen["id"]}]
                eligible = [unit["quote"] for unit in source_units(profile) if unit["source_id"] == "bad"]
                self.assertFalse(any("I =" in quote or "U * R" in quote for quote in eligible), eligible)

    def test_strict_rejected_metadata_heading_is_not_selectable(self):
        from app.services.ai_slides.analysis import analyze_sources
        from app.services.ai_slides.grounding import source_units
        profile = self.strict_profile()
        profile["sources"][0]["text"] = "Lớp 10\n" + profile["sources"][0]["text"]
        conflict = next(item for item in analyze_sources(profile)["conflicts"] if item["field"] == "grade")
        teacher = next(item for item in conflict["evidence"] if item["teacher_field"] == "grade")
        profile["source_resolutions"] = [{"conflict_id": conflict["id"], "evidence_id": teacher["id"]}]
        self.assertFalse(any("Lớp 10" in item["quote"] for item in source_units(profile)))
        self.assertTrue(any("I = U/R" in item["quote"] for item in source_units(profile)))

    def test_strict_ai_edit_preserves_manual_resource_without_certifying_it(self):
        from app.services.ai_slides.grounding import assemble_slide, source_units, grounded_title, proof_valid
        from app.services.ai_slides.schemas import GroundedChoice
        profile = self.strict_profile()
        unit = source_units(profile)[0]
        outline = {**fixture_blueprint()["slides"][2], "source_ids": ["book"], "title": grounded_title(profile, "concept", "s003"), "resource_id": "ohm"}
        slide = assemble_slide(GroundedChoice(id="s003", bullet_unit_ids=[unit["id"]]), profile, outline, [unit]).model_dump()
        self.assertEqual(slide["resource_id"], "ohm")
        self.assertFalse(proof_valid(slide, profile))

    def test_strict_outline_cannot_save_unusable_sources_or_change_server_version(self):
        from app.services.ai_slides.models import Deck
        deck = self.create(**self.strict_profile())
        blueprint = fixture_blueprint()
        for slide in blueprint["slides"]:
            slide["source_ids"] = ["book"]
        blueprint["grounding_version"] = "extractive-v1"
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = blueprint
            row.manifest = fixture_manifest().model_dump()
            row.status = "ready"
            db.commit()
        url = f"/api/ai-slides/decks/{deck['id']}/outline"
        invalid = deepcopy(blueprint)
        invalid["slides"][0]["source_ids"] = []
        response = self.client.patch(url, headers={"If-Match": "1"}, json={"blueprint": invalid, "discard_content": True})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNotNone(self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()["manifest"])
        blueprint["grounding_version"] = None
        response = self.client.patch(url, headers={"If-Match": "1"}, json={"blueprint": blueprint, "discard_content": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["blueprint"]["grounding_version"], "extractive-v1")

    def test_extractive_unknown_ref_fails_and_excludes_rejected_formula(self):
        from app.services.ai_slides.grounding import source_units, assemble_batch
        from app.services.ai_slides.analysis import analyze_sources
        from app.services.ai_slides.schemas import GroundedBatch
        profile = self.strict_profile()
        profile["sources"].append({"id": "bad", "name": "B", "page": None, "text": "I = U*R.", "role": "reference"})
        conflict = analyze_sources(profile)["conflicts"][0]
        chosen = next(item for item in conflict["evidence"] if item["source_id"] == "book")
        profile["source_resolutions"] = [{"conflict_id": conflict["id"], "evidence_id": chosen["id"]}]
        self.assertFalse(any(unit["source_id"] == "bad" for unit in source_units(profile)))
        bad = GroundedBatch(lesson_title=profile["lesson_title"], slides=[{
            "id": "s001", "bullet_unit_ids": ["u-fabricated"], "notes_unit_ids": [],
            "activity": "discuss", "quiz_gap": None, "quiz_distractors": [],
        }])
        with self.assertRaises(self.routes.provider.StudioError) as caught:
            assemble_batch(bad, profile, fixture_blueprint())
        self.assertEqual(caught.exception.code, "AI_GROUNDING_ERROR")

    def test_strict_legacy_or_manual_slide_has_grounding_warning(self):
        from app.services.ai_slides.review import content_review
        issues = content_review(fixture_manifest().model_dump(), self.strict_profile())
        self.assertIn("UNVERIFIED_GROUNDING", {item["code"] for item in issues})

    def test_strict_legacy_outline_requires_explicit_replan_before_provider(self):
        from app.services.ai_slides.models import Deck
        deck = self.seed_ready()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.profile = self.strict_profile()
            db.commit()
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock) as model:
            response = self.call_step(deck, "author")
            self.assertEqual(response.json()["code"], "GROUNDING_REPLAN_REQUIRED")
            model.assert_not_called()

    def test_extractive_request_uses_its_own_prompt_without_free_authoring_rules(self):
        import httpx
        import json
        from app.services.ai_slides import provider
        from app.services.ai_slides.grounding import source_units
        from app.services.ai_slides.schemas import GroundedPlan
        profile = self.strict_profile()
        units = source_units(profile)
        original_client = httpx.AsyncClient
        def respond(request):
            body = json.loads(request.content)
            system = body["messages"][0]["content"]
            self.assertTrue(system.startswith(provider.EXTRACTIVE_PROMPT))
            self.assertNotIn("Ghi chú mỗi slide khoảng 200-400", system)
            data = json.loads(next(item["content"] for item in body["messages"] if item["role"] == "user"))
            self.assertNotIn("cite_every_slide", data["output_contract"])
            self.assertNotIn("alternatives", data["source_decisions"][0])
            self.assertEqual(data["available_resources"], [])
            raw = {"lesson_title": profile["lesson_title"], "objective_unit_ids": [units[0]["id"]], "warnings": [],
                   "slides": [{**slot, "kind": kind, "unit_ids": [units[0]["id"]]} for slot, kind in zip(data["output_contract"]["slots"], ["cover", "hook", "concept", "quiz", "summary"])]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(raw)}}]})
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)
        with patch.object(provider.httpx, "AsyncClient", side_effect=client), patch.dict(os.environ, {"AI_SLIDES_OPENROUTER_API_KEY": "mock-only"}):
            result, _ = asyncio.run(provider.generate("fixture/selection:free", GroundedPlan, {
                "task": "plan", "profile": profile, "grounding_contract": {"units": units},
                "source_decisions": [{"field": "I", "selected": {"quote": "I=U/R"}, "alternatives": [{"quote": "I=U*R"}]}],
            }))
        self.assertEqual(len(result.slides), 5)

    def test_strict_full_flow_proof_manual_edit_undo_and_ai_edit(self):
        profile = self.strict_profile()
        deck = self.create(**profile)
        async def generate(model, schema, payload):
            units = payload["grounding_contract"]["units"]
            self.assertNotIn("text", payload["profile"]["sources"][0])
            if payload["task"] == "plan":
                return schema.model_validate({"lesson_title": profile["lesson_title"], "objective_unit_ids": [units[0]["id"]],
                    "slides": [{"id": f"s{i+1:03d}", "kind": kind, "duration_seconds": 540, "unit_ids": [units[0]["id"]]}
                               for i, kind in enumerate(["cover", "hook", "concept", "quiz", "summary"])], "warnings": []}), {}
            outlines = [payload["slide"]] if payload["task"] == "edit" else payload["blueprint"]["slides"]
            choices = [{"id": item["id"], "bullet_unit_ids": [units[0]["id"]], "notes_unit_ids": [units[-1]["id"]],
                        "activity": "read", "quiz_gap": "U/R" if item["kind"] == "quiz" else None,
                        "quiz_distractors": ["V", "Ω"] if item["kind"] == "quiz" else []} for item in outlines]
            return schema.model_validate(choices[0] if payload["task"] == "edit" else {"lesson_title": profile["lesson_title"], "slides": choices}), {}
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"), \
             patch.object(self.routes.provider, "generate", side_effect=generate):
            planned = self.call_step(deck, "plan").json()
            self.assertEqual(planned["blueprint"]["grounding_version"], "extractive-v1")
            if planned["blueprint"]["warnings"]:
                planned = self.client.post(f"/api/ai-slides/decks/{deck['id']}/approve-outline", headers={"If-Match": str(planned["version"])}).json()
            response = self.call_step(planned, "author", "strict-author-001")
            self.assertEqual(response.status_code, 200, response.text)
            ready = response.json()
            self.assertEqual(ready["status"], "ready")
            self.assertTrue(all(row["verified"] for row in ready["grounding_report"]))
            quiz = ready["manifest"]["slides"][3]
            self.assertEqual(quiz["options"][quiz["correct_option"]], "U/R")
            self.assertIn("_____", quiz["question"])
            url = f"/api/ai-slides/decks/{deck['id']}"
            proposal = self.client.post(url + "/slides/s001/propose", headers={"If-Match": str(ready["version"]), "Idempotency-Key": "strict-edit-001"}, json={"instruction": "Đổi hoạt động đọc trích đoạn"})
            self.assertEqual(proposal.status_code, 200, proposal.text)
            self.assertIsNotNone(proposal.json()["proposal"]["source_proof"])
            forged = deepcopy(proposal.json()["proposal"])
            forged["speaker_notes"] += " Nội dung ngoài đề xuất."
            rejected = self.client.patch(url + "/slides/s001", headers={"If-Match": str(ready["version"])},
                                         json={"slide": forged, "proposal_step_id": proposal.json()["step_id"]})
            self.assertEqual(rejected.status_code, 409)
            applied = self.client.patch(url + "/slides/s001", headers={"If-Match": str(ready["version"])},
                                        json={"slide": proposal.json()["proposal"], "proposal_step_id": proposal.json()["step_id"]})
            self.assertEqual(applied.status_code, 200, applied.text)
            ready = applied.json()
            self.assertTrue(all(item["verified"] for item in ready["grounding_report"]))
            edited = deepcopy(ready["manifest"]["slides"][0])
            edited["speaker_notes"] += " Kiến thức giáo viên tự bổ sung."
            manual = self.client.patch(url + "/slides/s001", headers={"If-Match": str(ready["version"])}, json={"slide": edited})
            self.assertEqual(manual.status_code, 200, manual.text)
            self.assertIsNone(manual.json()["manifest"]["slides"][0]["source_proof"])
            self.assertIn("UNVERIFIED_GROUNDING", {item["code"] for item in manual.json()["review"]})
            restored = self.client.post(url + "/restore", headers={"If-Match": str(manual.json()["version"])}, json={"version": ready["version"]}).json()
            self.assertTrue(all(row["verified"] for row in restored["grounding_report"]))

    def test_strict_invalid_ai_selection_preserves_outline_and_safe_log(self):
        profile = self.strict_profile()
        deck = self.create(**profile)
        from app.services.ai_slides.models import Deck
        from app.services.ai_slides.schemas import GroundedBatch
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = {**fixture_blueprint(), "grounding_version": "extractive-v1"}
            for slide in row.blueprint["slides"]:
                slide["source_ids"] = ["book"]
            row.status = "planned"
            db.commit()
        bad = GroundedBatch(lesson_title=profile["lesson_title"], slides=[{"id": "s001", "bullet_unit_ids": ["u-fake"]}])
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"), \
             patch.object(self.routes.provider, "generate", new_callable=AsyncMock, return_value=(bad, {})):
            response = self.call_step(deck, "author")
            self.assertEqual(response.json()["code"], "AI_GROUNDING_ERROR")
        stored = self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()
        self.assertIsNone(stored["manifest"])
        self.assertIsNotNone(stored["blueprint"])
        self.assertFalse(stored["busy"])
        logs = self.client.get(f"/api/ai-slides/decks/{deck['id']}/steps").json()
        self.assertEqual(logs[0]["error_code"], "AI_GROUNDING_ERROR")
        self.assertNotIn(profile["sources"][0]["text"], logs[0]["error_message"])

    def test_strict_proposal_preserves_attachment_and_keeps_manual_title_unverified(self):
        from app.services.ai_slides.models import Deck
        from app.services.ai_slides.schemas import Manifest
        from app.services.ai_slides.grounding import source_units
        profile = self.strict_profile()
        deck = self.create(**profile)
        manifest = fixture_manifest().model_dump()
        for slide in manifest["slides"]:
            slide["source_ids"] = ["book"]
        manifest["slides"][0].update(title="I = U * R", resource_id="ohm")
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.manifest = Manifest.model_validate(manifest).model_dump()
            row.status = "ready"
            db.commit()
        unit = source_units(profile)[0]
        async def select(model, schema, payload):
            return schema.model_validate({"id": "s001", "bullet_unit_ids": [unit["id"]], "activity": "compare"}), {}
        url = f"/api/ai-slides/decks/{deck['id']}"
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"), patch.object(self.routes.provider, "generate", side_effect=select):
            response = self.client.post(url + "/slides/s001/propose", headers={"If-Match": "1", "Idempotency-Key": "attached-proposal-001"}, json={"instruction": "Đổi hoạt động so sánh"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["proposal"]["resource_id"], "ohm")
        applied = self.client.patch(url + "/slides/s001", headers={"If-Match": "1"}, json={"slide": response.json()["proposal"], "proposal_step_id": response.json()["step_id"]})
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertFalse(applied.json()["grounding_report"][0]["verified"])

    def test_outline_edit_requires_explicit_reset_and_restores_previous_content(self):
        deck = self.seed_ready()
        url = f"/api/ai-slides/decks/{deck['id']}"
        outline = fixture_blueprint()
        outline["slides"][1]["title"] = "Khởi động đã chỉnh"
        body = {"blueprint": outline}
        self.assertEqual(self.client.patch(url + "/outline", headers={"If-Match": "1"}, json=body).status_code, 409)
        updated = self.client.patch(url + "/outline", headers={"If-Match": "1"}, json={**body, "discard_content": True})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)
        self.assertIsNone(updated.json()["manifest"])
        self.assertEqual(updated.json()["blueprint"]["slides"][1]["title"], "Khởi động đã chỉnh")
        restored = self.client.post(url + "/restore", headers={"If-Match": "2"}, json={"version": 1})
        self.assertEqual(restored.status_code, 200, restored.text)
        # Initial fixture is deliberately persisted in revision for this scenario.
        self.assertIsNotNone(restored.json()["manifest"])

    def test_outline_edit_enforces_owner_version_duration_and_source_constraints(self):
        from app.services.ai_slides.models import Deck
        deck = self.create()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = fixture_blueprint()
            row.status = "planned"
            db.commit()
        url = f"/api/ai-slides/decks/{deck['id']}/outline"
        payload = {"blueprint": fixture_blueprint()}
        self.user.id = 2
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=payload).status_code, 404)
        self.user.id = 1
        self.assertEqual(self.client.patch(url, headers={"If-Match": "99"}, json=payload).status_code, 409)
        bad = deepcopy(payload)
        bad["blueprint"]["slides"][0]["duration_seconds"] = 0
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=bad).status_code, 422)
        bad = deepcopy(payload)
        bad["blueprint"]["slides"][0]["source_ids"] = ["made-up"]
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json=bad).status_code, 422)
        good = self.client.patch(url, headers={"If-Match": "1"}, json=payload)
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(good.json()["version"], 2)

    def test_presentation_settings_preserve_content_and_never_call_provider(self):
        deck = self.seed_ready()
        url = f"/api/ai-slides/decks/{deck['id']}/presentation"
        with patch.object(self.routes.provider, "generate", new_callable=AsyncMock) as generate:
            response = self.client.patch(url, headers={"If-Match": "1"}, json={"theme": "history", "motion": "none"})
            self.assertEqual(response.status_code, 200, response.text)
            changed = response.json()
            self.assertEqual(changed["manifest"], deck["manifest"])
            self.assertEqual(changed["blueprint"], deck["blueprint"])
            self.assertEqual(changed["status"], "ready")
            self.assertEqual(changed["profile"]["theme"], "history")
            self.assertEqual(changed["profile"]["motion"], "none")
            self.assertEqual(changed["version"], 2)
            generate.assert_not_called()
        self.assertEqual(self.client.patch(url, headers={"If-Match": "1"}, json={"theme": "science", "motion": "gentle"}).status_code, 409)
        self.assertEqual(self.client.patch(url, headers={"If-Match": "2"}, json={"theme": "history", "motion": "none", "subject": "Đổi ngoài phạm vi"}).status_code, 422)

    def test_native_motion_is_off_by_default_and_can_be_enabled_after_manual_qa(self):
        with patch.dict(os.environ, {"AI_SLIDES_NATIVE_MOTION_ENABLED": "false"}):
            self.assertFalse(self.client.get('/api/ai-slides/capabilities').json()['native_motion'])
        with patch.dict(os.environ, {"AI_SLIDES_NATIVE_MOTION_ENABLED": "true"}):
            capabilities = self.client.get('/api/ai-slides/capabilities').json()
            self.assertTrue(capabilities['native_motion'])
            self.assertIn('Appear', capabilities['native_motion_message'])

    def test_content_review_reports_unverified_page_without_claiming_fact_check(self):
        from app.services.ai_slides.review import content_review
        manifest = fixture_manifest().model_dump()
        manifest["slides"][1]["bullets"] = ["Làm bài tập SGK trang 999."]
        issues = content_review(manifest, {**PROFILE, "sources": []})
        self.assertTrue(any(row["code"] == "UNVERIFIED_REFERENCE" and row["slide_id"] == "s002" for row in issues))
        manifest["slides"][1]["bullets"] = ["Kiểm tra đơn vị trước khi tính."]
        self.assertFalse(any(row["code"] == "UNVERIFIED_REFERENCE" for row in content_review(manifest, {**PROFILE, "sources": []})))
        for field, value in [("question", "Làm bài tập SGK trang 999."),
                             ("options", ["Theo SGK trang 999.", "Phương án khác"]),
                             ("teacher_action", "Mở sách trang 999."),
                             ("student_action", "Đọc tài liệu trang 999.")]:
            with self.subTest(field=field):
                candidate = fixture_manifest().model_dump()
                candidate["slides"][3][field] = value
                self.assertTrue(any(row["code"] == "UNVERIFIED_REFERENCE" and row["slide_id"] == "s004"
                                    for row in content_review(candidate, {**PROFILE, "sources": []})))

    def test_auth_roles_flag_and_csrf_are_enforced(self):
        self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/ai-slides/decks", json=PROFILE).status_code, 403)
        self.user.role = "guest"
        self.assertEqual(self.client.get("/ai-studio").status_code, 403)
        self.user.role = "admin"
        self.assertEqual(self.client.get("/ai-studio").status_code, 200)
        self.user.role = "super_admin"
        self.assertEqual(self.client.get("/ai-studio").status_code, 200)
        with patch.dict(os.environ, {"AI_SLIDES_ENABLED": "false"}):
            self.assertEqual(self.client.get("/ai-studio").status_code, 404)

    def test_ownership_applies_to_read_edit_history_delete(self):
        deck = self.create()
        self.user.id = 2
        base = f"/api/ai-slides/decks/{deck['id']}"
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.get(base + "/revisions").status_code, 404)
        self.assertEqual(self.client.get(base + "/steps").status_code, 404)
        self.assertEqual(self.client.patch(base + "/input-profile", headers={"If-Match": "1"}, json=PROFILE).status_code, 404)
        self.assertEqual(self.client.delete(base, headers={"If-Match": "1"}).status_code, 404)

    def test_no_cloud_or_saved_sources_without_consent(self):
        deck = self.create(consent=False)
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock) as model:
            self.assertEqual(self.call_step(deck, "plan").status_code, 422)
            model.assert_not_called()
        source = {"id": "src-01", "name": "Test", "text": "Test source"}
        self.assertEqual(self.client.post("/api/ai-slides/decks", json={
            **PROFILE, "sources": [source], "consent": False,
        }).status_code, 422)

    def test_two_steps_persist_and_idempotency_does_not_repeat_provider(self):
        from app.services.ai_slides.schemas import Blueprint
        deck = self.create()
        with (
            patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"),
            patch.object(self.routes.provider, "generate", new_callable=AsyncMock, side_effect=[
                (Blueprint.model_validate(fixture_blueprint()), {}),
                (fixture_manifest(), {}),
            ]) as generate,
        ):
            planned = self.call_step(deck, "plan")
            self.assertEqual(planned.status_code, 200, planned.text[:500])
            replay = self.call_step(deck, "plan")
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(generate.call_count, 1)
            authored = self.call_step(planned.json(), "author", key="test-author-key-001")
            self.assertEqual(authored.status_code, 200, authored.text[:500])
            saved = self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()
            self.assertEqual(saved["status"], "ready")
            self.assertEqual(len(saved["manifest"]["slides"]), 5)
            self.assertEqual(saved["version"], 3)

    def test_failure_preserves_blueprint_and_consumes_quota(self):
        from app.services.ai_slides.models import Deck, Quota, Step
        deck = self.create()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = fixture_blueprint()
            row.status = "planned"
            db.commit()
        with (
            patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"),
            patch.object(self.routes.provider, "generate", new_callable=AsyncMock,
                         side_effect=self.routes.provider.StudioError("AI_TIMEOUT", "Timeout")),
        ):
            response = self.call_step(deck, "author")
            self.assertEqual(response.status_code, 503)
            self.assertIsNotNone(response.json()["step_id"])
        history = self.client.get(f"/api/ai-slides/decks/{deck['id']}/steps").json()
        self.assertEqual(history[0]["error_code"], "AI_TIMEOUT")
        self.assertEqual(history[0]["error_message"], "Timeout")
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            self.assertIsNotNone(row.blueprint)
            self.assertIsNone(row.active_token)
            self.assertEqual(db.scalars(select(Step)).one().error_code, "AI_TIMEOUT")
            self.assertTrue(all(quota.requests == 1 for quota in db.scalars(select(Quota))))

    def test_author_batches_resume_after_failure_and_replay_without_duplicate_slides(self):
        from app.services.ai_slides.models import Deck
        from app.services.ai_slides.schemas import SlideBatch
        deck = self.create(slide_count=15)
        outline = fixture_blueprint()
        slides = []
        for index in range(15):
            slide = deepcopy(fixture_manifest().model_dump()["slides"][index % 5])
            slide.update(id=f"s{index+1:03d}", title=f"Hoạt động {index+1}", duration_seconds=180)
            slides.append(slide)
        outline["slides"] = [{key: slide[key] for key in ("id", "title", "kind", "duration_seconds", "source_ids")} for slide in slides]
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.blueprint = outline
            row.status = "planned"
            db.commit()
        batches = [SlideBatch.model_validate({"lesson_title": PROFILE["lesson_title"], "slides": slides[index:index+5]}) for index in (0, 5, 10)]
        with (
            patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock, return_value="test/free:free"),
            patch.object(self.routes.provider, "generate", new_callable=AsyncMock, side_effect=[
                (batches[0], {}), self.routes.provider.StudioError("AI_TIMEOUT", "Timeout"),
                (batches[1], {}), (batches[2], {}),
            ]) as generate,
        ):
            first = self.call_step(deck, "author", "author-batch-0001")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["status"], "authoring")
            self.assertEqual(self.call_step(deck, "author", "author-batch-0001").status_code, 200)
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(self.call_step(first.json(), "author", "author-batch-0002").status_code, 503)
            resumed = self.client.get(f"/api/ai-slides/decks/{deck['id']}").json()
            self.assertEqual(len(resumed["manifest"]["slides"]), 5)
            second = self.call_step(resumed, "author", "author-batch-0003")
            self.assertEqual(second.status_code, 200, second.text)
            final = self.call_step(second.json(), "author", "author-batch-0004")
            self.assertEqual(final.status_code, 200, final.text)
            self.assertEqual(final.json()["status"], "ready")
            self.assertEqual(len({slide["id"] for slide in final.json()["manifest"]["slides"]}), 15)
            self.assertEqual(generate.call_args_list[2].args[2]["blueprint"]["slides"][0]["id"], "s006")

    def test_provider_total_deadline_and_training_choice(self):
        import httpx
        import json
        from app.services.ai_slides import provider
        from app.services.ai_slides.schemas import Blueprint
        client_type = httpx.AsyncClient

        async def respond(request):
            body = json.loads(request.content)
            self.assertEqual(body["provider"]["data_collection"], "allow")
            self.assertEqual(body["provider"]["max_price"], {"prompt": 0, "completion": 0})
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={})

        def client(**kwargs):
            return client_type(transport=httpx.MockTransport(respond), **kwargs)

        with (
            patch.object(provider, "settings", return_value=SimpleNamespace(timeout=0.01, api_key="test")),
            patch.object(provider.httpx, "AsyncClient", side_effect=client),
        ):
            with self.assertRaises(provider.StudioError) as error:
                asyncio.run(provider.generate("fixture/free:free", Blueprint, {"profile": {"training_consent": True}}))
        self.assertEqual(error.exception.code, "AI_TIMEOUT")

    def test_active_lease_blocks_other_keys_and_quota_overflow_rolls_back(self):
        from app.services.ai_slides.models import Deck, Quota
        deck = self.create()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.active_token = "other-request"
            row.lease_until = time.time() + 120
            db.commit()
        with patch.object(self.routes.provider, "eligible_model", new_callable=AsyncMock) as model:
            self.assertEqual(self.call_step(deck, "plan").status_code, 409)
            model.assert_not_called()
        with self.session_factory() as db:
            row = db.get(Deck, deck["id"])
            row.lease_until = time.time() - 1
            db.commit()
        from app.services.ai_slides.state import reserve_quota
        with patch.dict(os.environ, {"AI_SLIDES_MAX_REQUESTS_PER_USER_DAY": "1"}):
            with self.session_factory() as db:
                reserve_quota(db, 1)
                db.commit()
            with self.session_factory() as db:
                with self.assertRaises(self.routes.provider.StudioError):
                    reserve_quota(db, 1)
                db.rollback()
                self.assertTrue(all(row.requests == 1 for row in db.scalars(select(Quota))))

    def test_stale_version_rejected_and_restore_creates_new_revision(self):
        deck = self.create()
        base = f"/api/ai-slides/decks/{deck['id']}"
        changed = self.client.patch(base + "/input-profile", headers={"If-Match": "1"},
                                    json={**PROFILE, "theme": "history"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.patch(base + "/input-profile", headers={"If-Match": "1"}, json=PROFILE).status_code, 409)
        restored = self.client.post(base + "/restore", headers={"If-Match": "2"}, json={"version": 1})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["version"], 3)
        self.assertEqual(restored.json()["profile"]["theme"], "science")

    def test_provider_price_gate_fails_closed(self):
        from app.services.ai_slides.provider import is_free
        self.assertTrue(is_free({"id": "test:free", "pricing": {"prompt": "0", "completion": "0"}}))
        for model in [
            {"id": "test", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "test:free", "pricing": {"prompt": "0.01", "completion": "0"}},
            {"id": "test:free", "pricing": {"prompt": "0", "completion": "0", "request": "1"}},
            {"id": "test:free", "pricing": {"prompt": "0"}},
        ]:
            self.assertFalse(is_free(model))

    def test_provider_catalog_and_request_use_the_studio_key_and_strict_schema(self):
        import httpx
        from app.services.ai_slides import provider
        from app.services.ai_slides.schemas import Blueprint
        client_type = httpx.AsyncClient
        calls = []

        def respond(request):
            calls.append(request)
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{
                    "id": "fixture/free:free", "pricing": {"prompt": "0", "completion": "0"},
                    "supported_parameters": ["structured_outputs"],
                }]})
            self.assertEqual(request.headers["Authorization"], "Bearer studio-test-key")
            import json
            body = json.loads(request.content)
            self.assertEqual(body["model"], "fixture/free:free")
            self.assertTrue(body["provider"]["require_parameters"])
            schema = body["response_format"]["json_schema"]["schema"]
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            self.assertEqual(schema["properties"]["slides"]["minItems"], 5)
            self.assertEqual(schema["properties"]["slides"]["maxItems"], 5)
            self.assertEqual(schema["properties"]["lesson_title"]["enum"], [PROFILE["lesson_title"]])
            return httpx.Response(200, json={"choices": [{"message": {
                "content": json.dumps(fixture_blueprint()),
            }}], "usage": {"prompt_tokens": 5, "completion_tokens": 10}})

        def client(**kwargs):
            return client_type(transport=httpx.MockTransport(respond), **kwargs)

        async def exercise():
            model = await provider.eligible_model()
            return await provider.generate(model, Blueprint, {"task": "plan", "profile": PROFILE})

        with (
            patch.dict(os.environ, {
                "AI_SLIDES_OPENROUTER_API_KEY": "studio-test-key",
                "AI_SLIDES_PRIMARY_MODEL": "fixture/free:free", "AI_SLIDES_FALLBACK_MODELS": "",
            }),
            patch.object(provider.httpx, "AsyncClient", side_effect=client),
        ):
            result, usage = asyncio.run(exercise())
        self.assertEqual(result.lesson_title, PROFILE["lesson_title"])
        self.assertEqual(usage, {"input_tokens": 5, "output_tokens": 10})
        self.assertEqual(len(calls), 2)

    def test_source_scope_and_locked_title_validation(self):
        from app.services.ai_slides.schemas import Blueprint, Profile
        from app.services.ai_slides.state import validate_content
        profile = Profile.model_validate(PROFILE).model_dump()
        blueprint = fixture_blueprint()
        blueprint["slides"][1]["source_ids"] = ["invented-source"]
        with self.assertRaises(self.routes.provider.StudioError):
            validate_content(Blueprint.model_validate(blueprint), profile)
        blueprint = fixture_blueprint()
        blueprint["lesson_title"] = "A different lesson"
        with self.assertRaises(self.routes.provider.StudioError):
            validate_content(Blueprint.model_validate(blueprint), profile)

    def test_chart_video_and_repetitive_content_are_validated(self):
        from pydantic import ValidationError
        from app.services.ai_slides.schemas import Blueprint, Profile, Slide
        from app.services.ai_slides.state import validate_content
        slide = fixture_manifest().model_dump()["slides"][0]
        with self.assertRaises(ValidationError):
            Slide.model_validate({**slide, "kind": "chart"})
        with self.assertRaises(ValidationError):
            Slide.model_validate({**slide, "kind": "video", "resource_id": "ohm"})
        with self.assertRaises(ValidationError):
            Slide.model_validate({**slide, "kind": "chart", "chart_data": {
                "labels": ["A", "B"], "values": [1, 2, 3], "series_name": "Sai số lượng", "data_origin": "example",
            }})
        self.assertEqual(Slide.model_validate({**slide, "question": None}).question, "")
        blueprint = fixture_blueprint()
        for item in blueprint["slides"]:
            item["title"] = "Nội dung lặp"
        with self.assertRaises(self.routes.provider.StudioError) as error:
            validate_content(Blueprint.model_validate(blueprint), Profile.model_validate(PROFILE).model_dump())
        self.assertEqual(error.exception.code, "AI_QUALITY_ERROR")

    def test_strict_provider_schema_requires_nullable_and_default_fields(self):
        from app.services.ai_slides.provider import strict_schema
        from app.services.ai_slides.schemas import Manifest
        schema = strict_schema(Manifest)

        def check(node):
            if isinstance(node, dict):
                self.assertNotIn("default", node)
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)
        check(schema)

    def test_locked_objectives_are_validated_and_studio_metadata_is_isolated(self):
        from app.models import Base
        from app.services.ai_slides.schemas import Blueprint, Profile
        from app.services.ai_slides.state import validate_content
        profile = Profile.model_validate({
            **PROFILE, "objectives": "Mục tiêu đã khóa", "locked_fields": ["objectives"],
        }).model_dump()
        with self.assertRaises(self.routes.provider.StudioError):
            validate_content(Blueprint.model_validate(fixture_blueprint()), profile)
        self.assertFalse(any(name.startswith("ai_slide_") for name in Base.metadata.tables))
