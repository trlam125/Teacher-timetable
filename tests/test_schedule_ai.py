import json
import os
from unittest.mock import patch

from app.schedule_ai import analyze_schedule_with_gemini


def sample_report():
    return {
        "ok": True,
        "filename": "tkb.xlsx",
        "summary": {"recognized_lessons": 3, "classes": 2, "teachers": 2, "collisions": 0},
        "issues": [],
        "viewer": {
            "days": 5,
            "sessions": 2,
            "periods": 5,
            "classes": [{"id": 1, "name": "10A1"}, {"id": 2, "name": "10A2"}],
            "cells": [
                {
                    "slot": 0,
                    "class_id": 1,
                    "class_name": "10A1",
                    "subject_name": "Toán",
                    "teacher_name": "Cô Hà",
                    "room": "",
                    "raw_text": "Toán Cô Hà",
                    "conflicts": [],
                },
                {
                    "slot": 1,
                    "class_id": 1,
                    "class_name": "10A1",
                    "subject_name": "Toán",
                    "teacher_name": "Cô Hà",
                    "room": "",
                    "raw_text": "Toán Cô Hà",
                    "conflicts": [],
                },
                {
                    "slot": 2,
                    "class_id": 2,
                    "class_name": "10A2",
                    "subject_name": "Lịch sử",
                    "teacher_name": "Nguyễn Văn An",
                    "room": "",
                    "raw_text": "Sử Nguyễn Văn An",
                    "conflicts": [],
                },
            ],
        },
    }


@patch.dict(
    os.environ,
    {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "primary-model",
        "GEMINI_ATTEMPTS_PER_MODEL": "1",
        "GEMINI_RETRY_BASE_SECONDS": "0",
    },
    clear=False,
)
@patch("app.schedule_ai._call_gemini_model")
def test_ai_audit_uses_existing_gemini_key_and_structured_json(call_model):
    call_model.return_value = json.dumps({
        "overview": "Có một điểm nên xem lại.",
        "issues": [{
            "severity": "warning",
            "category": "parser_suspicion",
            "title": "Kiểm tra ô lịch sử",
            "message": "Nên xác nhận cách parser đọc tên giáo viên.",
            "suggestion": "Đối chiếu file gốc.",
            "cell_keys": ["2:2"],
        }],
    }, ensure_ascii=False)

    result, model, failures = analyze_schedule_with_gemini(sample_report())

    assert model == "primary-model"
    assert failures == []
    assert result["summary"]["total"] == 1
    assert result["summary"]["marked_cells"] == 1
    assert result["issues"][0]["cell_keys"] == ["2:2"]

    called_model, called_key, payload = call_model.call_args.args[:3]
    assert called_model == "primary-model"
    assert called_key == "test-key"
    payload_json = json.loads(payload.decode("utf-8"))
    assert payload_json["generationConfig"]["responseMimeType"] == "application/json"
    assert "allowed_cell_keys" in payload_json["contents"][0]["parts"][0]["text"]
    assert "2:2" in payload_json["contents"][0]["parts"][0]["text"]
    assert "không tự tạo" in payload_json["systemInstruction"]["parts"][0]["text"].lower()


@patch.dict(
    os.environ,
    {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "primary-model",
        "GEMINI_ATTEMPTS_PER_MODEL": "1",
        "GEMINI_RETRY_BASE_SECONDS": "0",
    },
    clear=False,
)
@patch("app.schedule_ai._call_gemini_model")
def test_ai_audit_drops_hallucinated_cell_keys(call_model):
    call_model.return_value = json.dumps({
        "overview": "Kiểm tra một số điểm.",
        "issues": [{
            "severity": "warning",
            "category": "distribution",
            "title": "Phân bố",
            "message": "Có thể dồn lịch.",
            "suggestion": "Xem lại.",
            "cell_keys": ["0:1", "999:999"],
        }],
    })

    result, _, _ = analyze_schedule_with_gemini(sample_report())

    assert result["issues"][0]["cell_keys"] == ["0:1"]
    assert result["summary"]["marked_cells"] == 1


@patch.dict(
    os.environ,
    {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "primary-model",
        "GEMINI_ATTEMPTS_PER_MODEL": "1",
        "GEMINI_RETRY_BASE_SECONDS": "0",
    },
    clear=False,
)
@patch("app.schedule_ai._call_gemini_model")
def test_ai_audit_accepts_json_inside_code_fence(call_model):
    call_model.return_value = "```json\n{\"overview\":\"Ổn\",\"issues\":[]}\n```"

    result, model, _ = analyze_schedule_with_gemini(sample_report())

    assert model == "primary-model"
    assert result["issues"] == []
    assert result["overview"] == "Ổn"
