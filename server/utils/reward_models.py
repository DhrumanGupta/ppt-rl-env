from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

SUPPORTED_SHAPE_KINDS = {
    "accent_bar",
    "text",
    "citation",
    "chart",
    "table",
    "image",
}


@dataclass(slots=True)
class SourceDocument:
    doc_id: str
    title: str
    path: str | None
    mime_type: str
    text: str | None
    pages: list[str] | None
    images: list[str] | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourcePack:
    task_id: str
    documents: list[SourceDocument]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskConstraints:
    min_slides: int | None = None
    max_slides: int | None = None
    target_audience: str | None = None
    tone: str | None = None
    extra_constraints: dict[str, Any] = field(default_factory=dict)


# TODO: Remove
@dataclass(slots=True)
class CapabilityProfile:
    supported_shape_kinds: set[str] = field(
        default_factory=lambda: set(SUPPORTED_SHAPE_KINDS)
    )
    supports_native_text: bool = True
    supports_native_chart: bool = True
    supports_native_table: bool = True
    supports_native_image: bool = True
    supports_runtime_theme_binding: bool = True
    supports_grouping: bool = False
    supports_master_editing: bool = False
    supports_animation: bool = False
    supports_embedded_media: bool = False


@dataclass(slots=True)
class ExtractedTextBlock:
    paragraph_texts: list[str] = field(default_factory=list)
    bullet_levels: list[int | None] = field(default_factory=list)
    font_names: list[str | None] = field(default_factory=list)
    font_sizes_pt: list[float | None] = field(default_factory=list)
    bold_flags: list[bool | None] = field(default_factory=list)
    italic_flags: list[bool | None] = field(default_factory=list)
    color_hexes: list[str | None] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedChart:
    chart_type: str
    title: str | None = None
    categories: list[str] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    has_legend: bool = False
    axis_labels: dict[str, Any] = field(default_factory=dict)
    style_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedTable:
    rows: int
    cols: int
    cells: list[list[str]] = field(default_factory=list)
    header_present: bool = False
    style_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedImage:
    width_px: int | None = None
    height_px: int | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedShape:
    shape_id: int
    shape_kind: str
    semantic_role: str | None
    name: str | None
    x: float
    y: float
    w: float
    h: float
    z_index: int
    fill_color_hex: str | None = None
    line_color_hex: str | None = None
    raw_text: str | None = None
    text_blocks: list[ExtractedTextBlock] = field(default_factory=list)
    chart: ExtractedChart | None = None
    table: ExtractedTable | None = None
    image: ExtractedImage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedSlide:
    slide_index: int
    slide_id: int
    layout_name: str | None = None
    background_color_hex: str | None = None
    title_text: str | None = None
    all_text: str = ""
    citations: list[str] = field(default_factory=list)
    shapes: list[ExtractedShape] = field(default_factory=list)
    text_metrics: dict[str, Any] = field(default_factory=dict)
    layout_metrics: dict[str, Any] = field(default_factory=dict)
    color_metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedPresentation:
    slide_count: int
    slide_ids: list[int] = field(default_factory=list)
    slides: list[ExtractedSlide] = field(default_factory=list)
    # TODO: Remove
    deck_metrics: dict[str, Any] = field(default_factory=dict)
    # TODO: Remove
    theme_summary: dict[str, Any] = field(default_factory=dict)
    # TODO: Remove
    metadata: dict[str, Any] = field(default_factory=dict)


# TODO: Remove
@dataclass(slots=True)
class PresentationSemanticIndex:
    slide_semantics: dict[int, dict[str, Any]] = field(default_factory=dict)
    shape_semantics: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RequiredSlideSpec:
    slide_index: int
    slide_role: str
    title_hint: str | None
    instructions: str
    required_points: list[str] = field(default_factory=list)
    required_exact_values: list[str] = field(default_factory=list)
    required_shape_kinds: list[str] = field(default_factory=list)
    citation_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    prompt: str
    audience: str | None = None
    tone: str | None = None
    min_slides: int | None = None
    max_slides: int | None = None
    required_sections: list[str] = field(default_factory=list)
    required_points: list[str] = field(default_factory=list)
    required_slides: list[RequiredSlideSpec] | None = None
    citation_required: bool = False
    require_quantitative_content: bool = False
    capability_profile: CapabilityProfile = field(default_factory=CapabilityProfile)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChecklistItem:
    item_id: str
    dimension: str
    prompt_text: str
    item_kind: str
    required_slide_scope: list[int] | None = None
    relevant_sections: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    binary: bool = True
    fail_if_partial: bool = True
    weight: float = 1.0
    evidence_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QuizQuestion:
    question_id: str
    question_type: str
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    source_refs: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QuizAnchor:
    anchor_id: str
    anchor_type: str
    statement: str
    source_quote: str
    source_ref: str
    doc_id: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QuizContextChunk:
    chunk_id: str
    doc_id: str
    title: str
    page: int | None
    source_ref: str
    text: str


@dataclass(slots=True)
class QuizGenerationContext:
    task_id: str
    document_count: int
    chunks: list[QuizContextChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionDraft:
    quantitative_anchors: list[QuizAnchor] = field(default_factory=list)
    qualitative_anchors: list[QuizAnchor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RefinedQuizEvidence:
    quantitative_anchors: list[QuizAnchor] = field(default_factory=list)
    qualitative_anchors: list[QuizAnchor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedQuizBankPayload:
    questions: list[QuizQuestion] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PresentBenchEvalSpec:
    task_spec: TaskSpec
    checklist: list[ChecklistItem] = field(default_factory=list)
    slide_checklists: dict[int, list[ChecklistItem]] = field(default_factory=dict)
    scoring_config: dict[str, Any] = field(default_factory=dict)
    spec_version: str = "1.0"
    spec_hash: str = ""


@dataclass(slots=True)
class SlidesGenBenchEvalSpec:
    task_spec: TaskSpec
    quiz_bank: list[QuizQuestion] = field(default_factory=list)
    scoring_config: dict[str, Any] = field(default_factory=dict)
    spec_version: str = "1.0"
    spec_hash: str = ""


@dataclass(slots=True)
class EvalSpec:
    task_spec: TaskSpec
    presentbench: PresentBenchEvalSpec
    slidesgenbench: SlidesGenBenchEvalSpec
    scoring_config: dict[str, Any] = field(default_factory=dict)
    spec_version: str = "1.0"
    spec_hash: str = ""


@dataclass(slots=True)
class PresentBenchScoreResult:
    reward_total: float
    reward_breakdown: dict[str, float] = field(default_factory=dict)
    hard_caps: dict[str, float] = field(default_factory=dict)
    soft_penalties: dict[str, float] = field(default_factory=dict)
    checklist_results: list[dict[str, Any]] = field(default_factory=list)
    aesthetics_results: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SlidesGenBenchScoreResult:
    reward_total: float
    reward_breakdown: dict[str, float] = field(default_factory=dict)
    quiz_results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RewardResult:
    reward_total: float
    reward_breakdown: dict[str, float] = field(default_factory=dict)
    hard_caps: dict[str, float] = field(default_factory=dict)
    soft_penalties: dict[str, float] = field(default_factory=dict)
    checklist_results: list[dict[str, Any]] = field(default_factory=list)
    quiz_results: list[dict[str, Any]] = field(default_factory=list)
    aesthetics_results: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IntermediateSlideRewardResult:
    slide_index: int
    reward_total: float
    reward_breakdown: dict[str, float] = field(default_factory=dict)
    hard_caps: dict[str, float] = field(default_factory=dict)
    soft_penalties: dict[str, float] = field(default_factory=dict)
    checklist_results: list[dict[str, Any]] = field(default_factory=list)
    aesthetics_results: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def to_serializable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_serializable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(item) for item in value]
    if isinstance(value, set):
        return [to_serializable(item) for item in sorted(value, key=str)]
    return value


__all__ = [
    "SUPPORTED_SHAPE_KINDS",
    "SourceDocument",
    "SourcePack",
    "TaskConstraints",
    "CapabilityProfile",
    "ExtractedTextBlock",
    "ExtractedChart",
    "ExtractedTable",
    "ExtractedImage",
    "ExtractedShape",
    "ExtractedSlide",
    "ExtractedPresentation",
    "PresentationSemanticIndex",
    "RequiredSlideSpec",
    "TaskSpec",
    "ChecklistItem",
    "QuizQuestion",
    "QuizAnchor",
    "QuizContextChunk",
    "QuizGenerationContext",
    "ExtractionDraft",
    "RefinedQuizEvidence",
    "GeneratedQuizBankPayload",
    "PresentBenchEvalSpec",
    "SlidesGenBenchEvalSpec",
    "EvalSpec",
    "PresentBenchScoreResult",
    "SlidesGenBenchScoreResult",
    "RewardResult",
    "IntermediateSlideRewardResult",
    "to_serializable",
]
