"""Opt-in live outline benchmark with public synthetic facts, never real books."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def benchmark(retry_failed=False):
    from app.services.ai_slides import provider
    from app.services.ai_slides.schemas import Blueprint, Profile
    from app.services.ai_slides.state import validate_content
    model = await provider.eligible_model()
    cases = json.loads((ROOT / "tests/fixtures/ai_slides_benchmark.json").read_text(encoding="utf-8"))
    output = ROOT / "tmp/ai-studio-qa/benchmark"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    selected = None
    if retry_failed:
        previous = json.loads((output / "report.json").read_text(encoding="utf-8"))
        selected = {row["case"] for row in previous if row["status"] != "pass"}
    # One request at a time: respect the free account's per-minute allowance.
    for number, case in enumerate(cases, 1):
        if selected is not None and number not in selected:
            continue
        profile = Profile.model_validate({
            "subject": case["subject"], "grade": case["grade"], "lesson_title": case["title"],
            "input_mode": "document", "duration_minutes": 30, "slide_count": 5,
            "objectives": case["facts"], "must_include": case["facts"], "grounding": "strict",
            "consent": True, "training_consent": True,
            "sources": [{"id": "truth-001", "name": "Ghi chú chuẩn của bộ kiểm thử", "text": case["facts"]}],
        }).model_dump()
        started = time.monotonic()
        row = {"case": number, "title": case["title"], "model": model}
        try:
            result, usage = await provider.generate(model, Blueprint, {"task": "plan", "profile": profile})
            (output / f"case-{number:02d}.json").write_text(json.dumps({"profile": profile, "blueprint": result.model_dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
            validate_content(result, profile)
            row.update(status="pass", usage=usage, warnings=result.warnings)
        except provider.StudioError as error:
            row.update(status=error.code, message=error.message)
        row["seconds"] = round(time.monotonic() - started, 2)
        results.append(row)
        (output / ("report-retry.json" if retry_failed else "report.json")).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if row["status"] in {"AI_QUOTA_EXHAUSTED", "AI_AUTH_ERROR", "AI_DATA_POLICY"}:
            break
    print(json.dumps({"completed": len(results), "passed": sum(row["status"] == "pass" for row in results),
                      "scope": "outline schema/source/constraints only; no automatic pedagogical score"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use up to 20 free OpenRouter requests with synthetic facts")
    parser.add_argument("--retry-failed", action="store_true", help="Repeat only failed cases from the first report")
    args = parser.parse_args()
    if not args.live:
        parser.exit(message="No network calls. Add --live to run the synthetic outline benchmark.\n")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("AI_SLIDES_PRIMARY_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    asyncio.run(benchmark(args.retry_failed))
