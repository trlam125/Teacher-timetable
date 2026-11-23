from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator
from .resources import ResourceId, RESOURCE_BY_ID


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=200)
    fingerprint: str = Field(max_length=64, default="")
    role: Literal["primary", "reference"] = "primary"
    page: int | None = Field(default=None, ge=1, le=10000)
    text: str = Field(min_length=1, max_length=40000)


class SourceResolution(StrictModel):
    conflict_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    evidence_id: str = Field(pattern=r"^[a-f0-9]{24}$")


class SourceReview(StrictModel):
    resolutions: list[SourceResolution] = Field(max_length=100)
    discard_content: bool = False


class RecognitionHints(StrictModel):
    subject: str = Field(default="", max_length=80)
    grade: str = Field(default="", max_length=40)
    lesson_title: str = Field(default="", max_length=240)
    duration_minutes: int | None = Field(default=None, ge=10, le=240)
    locked_fields: list[str] = Field(default_factory=list, max_length=6)


class RecognitionRequest(StrictModel):
    sources: list[Source] = Field(min_length=1, max_length=100)
    hints: RecognitionHints = Field(default_factory=RecognitionHints)
    consent: bool = False

    @model_validator(mode="after")
    def bounded_sources(self):
        if not self.consent or sum(len(source.text) for source in self.sources) > 40000 or len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Cần đồng ý, mã nguồn duy nhất và tối đa 40.000 ký tự đã chọn.")
        return self


class Profile(StrictModel):
    input_mode: Literal["manual", "document", "hybrid"] = "hybrid"
    generation_mode: Literal["outline", "automatic"] = "outline"
    subject: str = Field(min_length=1, max_length=80)
    grade: str = Field(min_length=1, max_length=40)
    lesson_title: str = Field(min_length=1, max_length=240)
    duration_minutes: int = Field(default=45, ge=10, le=240)
    slide_count: int = Field(default=15, ge=5, le=30)
    objectives: str = Field(default="", max_length=3000)
    must_include: str = Field(default="", max_length=3000)
    avoid: str = Field(default="", max_length=1500)
    level: Literal["foundation", "standard", "advanced"] = "standard"
    grounding: Literal["strict", "balanced"] = "balanced"
    theme: Literal["science", "primary", "geography", "history"] = "science"
    motion: Literal["gentle", "minimal", "none"] = "gentle"
    locked_fields: list[Literal["lesson_title", "subject", "grade", "duration_minutes", "objectives", "slide_count"]] = Field(default_factory=list, max_length=6)
    sources: list[Source] = Field(default_factory=list, max_length=100)
    consent: bool = False
    training_consent: bool = False
    source_resolutions: list[SourceResolution] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_sources(self):
        if self.duration_minutes > self.slide_count * 20:
            raise ValueError("Thời lượng vượt 20 phút mỗi slide. Hãy tăng số slide hoặc giảm thời lượng.")
        if sum(len(source.text) for source in self.sources) > 40000:
            raise ValueError("Tổng văn bản được chọn vượt 40.000 ký tự.")
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Mã đoạn nguồn bị trùng.")
        if (self.input_mode == "document" or self.grounding == "strict") and not self.sources:
            raise ValueError("Hãy chọn tài liệu hoặc dán nội dung cho chế độ này.")
        return self


class OutlineSlide(StrictModel):
    id: str = Field(pattern=r"^s[0-9]{3}$")
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["cover", "objectives", "hook", "section", "concept", "process", "compare", "map", "experiment", "example", "chart", "quiz", "video", "summary", "sources"]
    duration_seconds: int = Field(ge=0, le=1200)
    source_ids: list[str] = Field(default_factory=list, max_length=12)
    source_unit_ids: list[str] = Field(default_factory=list, max_length=5)


class Blueprint(StrictModel):
    lesson_title: str = Field(min_length=1, max_length=240)
    objectives: list[Annotated[str, Field(max_length=300)]] = Field(min_length=1, max_length=6)
    slides: list[OutlineSlide] = Field(min_length=5, max_length=30)
    warnings: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=12)
    grounding_version: Literal["extractive-v1"] | None = None


class GroundedOutline(StrictModel):
    id: str = Field(pattern=r"^s[0-9]{3}$")
    kind: Literal["cover", "objectives", "hook", "section", "concept", "process", "compare", "example", "quiz", "summary", "sources"]
    duration_seconds: int = Field(ge=0, le=1200)
    unit_ids: list[str] = Field(min_length=1, max_length=5)


class GroundedPlan(StrictModel):
    lesson_title: str = Field(min_length=1, max_length=240)
    objective_unit_ids: list[str] = Field(min_length=1, max_length=6)
    slides: list[GroundedOutline] = Field(min_length=5, max_length=30)
    warnings: list[Literal["SHORT_SOURCE", "UNCLEAR_SCOPE"]] = Field(default_factory=list, max_length=2)


class GroundedChoice(StrictModel):
    id: str = Field(pattern=r"^s[0-9]{3}$")
    bullet_unit_ids: list[str] = Field(min_length=1, max_length=5)
    notes_unit_ids: list[str] = Field(default_factory=list, max_length=5)
    activity: Literal["discuss", "restate", "compare", "read"] = "discuss"
    quiz_gap: str | None = Field(default=None, min_length=1, max_length=60)
    quiz_distractors: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=3)


class GroundedBatch(StrictModel):
    lesson_title: str = Field(min_length=1, max_length=240)
    slides: list[GroundedChoice] = Field(min_length=1, max_length=5)


class QuoteEvidence(StrictModel):
    field: Literal["bullets", "speaker_notes", "question", "correct_option", "options"]
    index: int = Field(ge=0, le=5)
    unit_id: str = Field(max_length=40)
    source_id: str = Field(max_length=64)
    quote: str = Field(min_length=1, max_length=300)
    page: int | None = None


class SourceProof(StrictModel):
    version: Literal["extractive-v1"] = "extractive-v1"
    source_signature: str = Field(pattern=r"^[a-f0-9]{24}$")
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    citations: list[QuoteEvidence] = Field(min_length=1, max_length=16)


class ChartData(StrictModel):
    chart_type: Literal["bar", "line"] = "bar"
    labels: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(min_length=2, max_length=8)
    values: list[FiniteFloat] = Field(min_length=2, max_length=8)
    series_name: str = Field(min_length=1, max_length=80)
    data_origin: Literal["source", "example"]

    @model_validator(mode="after")
    def matching_values(self):
        if len(self.labels) != len(self.values):
            raise ValueError("Số nhãn và số giá trị biểu đồ phải bằng nhau.")
        return self


class Slide(OutlineSlide):
    source_unit_ids: list[str] = Field(default_factory=list, max_length=10)
    bullets: list[Annotated[str, Field(max_length=350)]] = Field(default_factory=list, max_length=5)
    speaker_notes: str = Field(default="", max_length=2200)
    teacher_action: str = Field(default="", max_length=400)
    student_action: str = Field(default="", max_length=400)
    question: str = Field(default="", max_length=400)
    options: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=4)
    correct_option: int | None = Field(default=None, ge=0, le=3)
    explanation: str = Field(default="", max_length=600)
    resource_id: ResourceId | None = None
    chart_data: ChartData | None = None
    source_proof: SourceProof | None = None

    @field_validator("speaker_notes", "teacher_action", "student_action", "question", "explanation", mode="before")
    @classmethod
    def empty_optional_text(cls, value):
        return "" if value is None else value

    @model_validator(mode="after")
    def validate_quiz(self):
        if self.kind == "quiz" and (len(self.options) < 2 or self.correct_option is None or self.correct_option >= len(self.options)):
            raise ValueError("Câu hỏi cần phương án và đáp án hợp lệ.")
        if self.kind == "chart" and self.chart_data is None:
            raise ValueError("Slide biểu đồ cần dữ liệu số và nhãn.")
        if self.kind == "video" and RESOURCE_BY_ID.get(self.resource_id, {}).get('kind') != 'video':
            raise ValueError("Slide video cần video đã xác minh trong kho; mô phỏng không phải video.")
        if self.chart_data and self.chart_data.data_origin == "source" and not self.source_ids:
            raise ValueError("Biểu đồ dùng số liệu nguồn cần tham chiếu đoạn nguồn.")
        return self


class Manifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    lesson_title: str = Field(min_length=1, max_length=240)
    slides: list[Slide] = Field(min_length=5, max_length=30)


class SlideBatch(Manifest):
    slides: list[Slide] = Field(min_length=1, max_length=5)


class OutlineUpdate(StrictModel):
    blueprint: Blueprint
    discard_content: bool = False


class PresentationSettings(StrictModel):
    theme: Literal["science", "primary", "geography", "history"]
    motion: Literal["gentle", "minimal", "none"]


class EditRequest(StrictModel):
    slide: Slide
    proposal_step_id: str | None = Field(default=None, max_length=36)


class Instruction(StrictModel):
    instruction: str = Field(min_length=3, max_length=2000)


class RestoreRequest(StrictModel):
    version: int = Field(ge=1)
