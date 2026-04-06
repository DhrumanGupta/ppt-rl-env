from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from server.utils.reward_models import (
    CapabilityProfile,
    ChecklistItem,
    EvalSpec,
    ExtractionDraft,
    QuizGenerationContext,
    QuizContextChunk,
    RefinedQuizEvidence,
    RequiredSlideSpec,
    SourcePack,
    TaskConstraints,
    TaskSpec,
    to_serializable,
)

if TYPE_CHECKING:
    from server.utils.reward_quizbank_service import QuizBankGenerationService


SPEC_VERSION = "1.0"

DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    "branch_weights": {"pb": 0.6, "sg": 0.4},
    "pb_dimension_weights": {
        "fundamentals": 0.15,
        "visual_layout": 0.10,
        "completeness": 0.20,
        "correctness": 0.25,
        "fidelity": 0.30,
    },
    "sg_dimension_weights": {"quiz": 0.55, "aesthetics": 0.45},
    "quiz_split": {"concept": 0.5, "data": 0.5},
    "aesthetic_weights": {
        "harmony": 0.20,
        "engagement": 0.20,
        "usability": 0.35,
        "rhythm": 0.25,
    },
    "hard_caps": {
        "blank_title_only_ratio_threshold": 0.4,
        "critical_fidelity_cap": 0.5,
        "blankness_cap": 0.6,
    },
    "soft_penalties": {
        "slide_count_violation": 0.02,
        "overlap": 0.01,
        "missing_citations": 0.01,
        "tiny_text": 0.01,
        "redundancy": 0.03,
        "wrong_slot_behavior": 0.02,
    },
    "render_policy": {
        "allow_render_checks": True,
        "allow_mllm_perceptual_checks": True,
    },
}


_SLIDE_PLAN_PATTERN = re.compile(
    r"^\s*slide\s+(\d+)\s*[:\-.]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_ROLE_KEYWORDS = {
    "title": ["title", "cover", "introduc"],
    "agenda": ["agenda", "overview", "summary"],
    "background": ["background", "context"],
    "definition": ["definition", "define"],
    "comparison": ["compare", "comparison", "versus", "vs"],
    "method": ["method", "approach", "process", "architecture"],
    "result": ["result", "finding", "outcome", "metric"],
    "timeline": ["timeline", "roadmap", "milestone"],
    "summary": ["summary", "recap", "key takeaways"],
    "conclusion": ["conclusion", "recommendation", "next steps"],
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
    "slide",
}


@dataclass(slots=True)
class SourceChunk:
    chunk_id: str
    doc_id: str
    page: int | None
    section: str | None
    chunk_type: str
    text: str


def _source_ref(doc_id: str, page: int | None) -> str:
    return f"{doc_id}:p{page}" if page is not None else doc_id


def _chunk_page_text(
    doc_id: str,
    title: str,
    page: int | None,
    text: str | None,
    *,
    max_chunk_chars: int,
) -> list[QuizContextChunk]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[QuizContextChunk] = []
    current_sentences: list[str] = []
    current_length = 0
    chunk_index = 1

    for sentence in sentences:
        sentence_length = len(sentence)
        would_overflow = (
            current_sentences and current_length + 1 + sentence_length > max_chunk_chars
        )
        if would_overflow:
            chunks.append(
                QuizContextChunk(
                    chunk_id=f"{doc_id}_p{page or 0:02d}_c{chunk_index:02d}",
                    doc_id=doc_id,
                    title=title,
                    page=page,
                    source_ref=_source_ref(doc_id, page),
                    text=" ".join(current_sentences),
                )
            )
            chunk_index += 1
            current_sentences = []
            current_length = 0
        current_sentences.append(sentence)
        current_length += sentence_length if not current_length else sentence_length + 1

    if current_sentences:
        chunks.append(
            QuizContextChunk(
                chunk_id=f"{doc_id}_p{page or 0:02d}_c{chunk_index:02d}",
                doc_id=doc_id,
                title=title,
                page=page,
                source_ref=_source_ref(doc_id, page),
                text=" ".join(current_sentences),
            )
        )
    return chunks


def build_quiz_generation_context(
    source_pack: SourcePack,
    *,
    max_chunk_chars: int = 1200,
) -> QuizGenerationContext:
    chunks: list[QuizContextChunk] = []
    for document in sorted(source_pack.documents, key=lambda doc: doc.doc_id):
        if document.pages:
            for page_index, page_text in enumerate(document.pages, start=1):
                chunks.extend(
                    _chunk_page_text(
                        document.doc_id,
                        document.title,
                        page_index,
                        page_text,
                        max_chunk_chars=max_chunk_chars,
                    )
                )
        else:
            chunks.extend(
                _chunk_page_text(
                    document.doc_id,
                    document.title,
                    None,
                    document.text,
                    max_chunk_chars=max_chunk_chars,
                )
            )

    return QuizGenerationContext(
        task_id=source_pack.task_id,
        document_count=len(source_pack.documents),
        chunks=chunks,
        metadata={"max_chunk_chars": max_chunk_chars},
    )


def render_quiz_generation_context(context: QuizGenerationContext) -> str:
    rendered_chunks = []
    for chunk in context.chunks:
        rendered_chunks.append(
            "\n".join(
                [
                    f"[CHUNK {chunk.chunk_id}]",
                    f"doc_id: {chunk.doc_id}",
                    f"title: {chunk.title}",
                    f"source_ref: {chunk.source_ref}",
                    f"page: {chunk.page if chunk.page is not None else 'null'}",
                    chunk.text,
                ]
            )
        )
    return "\n\n".join(rendered_chunks)


def build_quiz_extraction_prompts(
    task_spec: TaskSpec,
    source_context: QuizGenerationContext,
) -> tuple[str, str]:
    system_prompt = (
        "You are a Forensic Analyst building a source-grounded quiz bank for PPT reward "
        "evaluation. Return strict JSON only. Extract anchors only when directly supported "
        "by the provided source text. Every anchor must include anchor_id, statement, "
        "source_quote, source_ref, doc_id, page, and metadata. Put numeric facts in "
        "quantitative_anchors and conceptual facts in qualitative_key_points."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_anchors": [...], "qualitative_key_points": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Extract 4 to 6 quantitative anchors when available.\n"
        "- Extract 6 to 8 qualitative anchors when available.\n"
        "- source_quote must be verbatim from the source text.\n"
        "- source_ref must match the provided source_ref field.\n"
        "- page must be null when unavailable.\n"
        "- metadata may include numbers or rationale.\n\n"
        "Source context:\n"
        f"{render_quiz_generation_context(source_context)}"
    )
    return system_prompt, user_prompt


def build_quiz_refinement_prompts(
    task_spec: TaskSpec,
    source_context: QuizGenerationContext,
    extraction_draft: ExtractionDraft,
) -> tuple[str, str]:
    system_prompt = (
        "You are a Strict Editor refining extracted quiz evidence. Return strict JSON only. "
        "Keep only verified, high-value anchors. Remove duplicates, vague statements, and "
        "unsupported claims. Preserve exact source quotes and source locations."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_anchors": [...], "qualitative_anchors": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Keep only anchors directly supported by the source text.\n"
        "- Keep source_quote verbatim.\n"
        "- Keep source_ref, doc_id, and page aligned with the source text.\n"
        "- metadata may include edit notes or coverage notes.\n\n"
        "Draft extraction JSON:\n"
        f"{json.dumps(to_serializable(extraction_draft), indent=2, sort_keys=True)}\n\n"
        "Source context:\n"
        f"{render_quiz_generation_context(source_context)}"
    )
    return system_prompt, user_prompt


def build_quiz_generation_prompts(
    task_spec: TaskSpec,
    refined_evidence: RefinedQuizEvidence,
    *,
    target_question_count: int,
    concept_target: int,
    data_target: int,
    question_slots: list[dict[str, str]],
) -> tuple[str, str]:
    slot_json = json.dumps(question_slots, indent=2, sort_keys=True)
    system_prompt = (
        "You are a Professional Exam Setter. Return strict JSON only. Build a source-grounded "
        "multiple-choice quiz for slides-only open-book evaluation. Every question must have "
        "exactly 4 distinct options, one correct answer using the option text itself, an "
        "explanation, source_refs, and source_quotes. Do not emit commentary, markdown, "
        "or keys outside the requested schema."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"questions": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        f"- Generate exactly {target_question_count} questions.\n"
        f"- Generate exactly {concept_target} concept questions.\n"
        f"- Generate exactly {data_target} data questions.\n"
        "- Follow the requested slot plan exactly; emit one question for each slot and reuse the provided question_id exactly.\n"
        "- Each question object must contain question_id, question_type, question, options, "
        "correct_answer, explanation, source_refs, and source_quotes.\n"
        "- question_type must be either concept or data.\n"
        "- options must contain exactly 4 distinct strings.\n"
        "- correct_answer must equal one of the option texts.\n"
        "- explanation must mention at least one cited source_ref verbatim.\n"
        "- source_refs and source_quotes must come directly from the verified evidence.\n"
        "- Do not duplicate the same question stem or correct answer across slots unless the slot plan requires it.\n"
        "- Use only the verified evidence below.\n\n"
        "Question slot plan:\n"
        f"{slot_json}\n\n"
        "Verified evidence JSON:\n"
        f"{json.dumps(to_serializable(refined_evidence), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


def build_quiz_regeneration_prompts(
    task_spec: TaskSpec,
    refined_evidence: RefinedQuizEvidence,
    *,
    failed_slots: list[dict[str, Any]],
    preserved_questions: list[dict[str, Any]],
) -> tuple[str, str]:
    system_prompt = (
        "You are a Professional Exam Setter repairing only invalid quiz questions. Return strict "
        "JSON only. Regenerate only the requested failed slots and preserve the exact question_id "
        "and question_type for each repaired question."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"questions": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Generate questions only for the failed slots below.\n"
        "- Do not include preserved questions in the output.\n"
        "- Reuse each failed slot's question_id and question_type exactly.\n"
        "- Each repaired question must contain question_id, question_type, question, options, correct_answer, explanation, source_refs, and source_quotes.\n"
        "- options must contain exactly 4 distinct strings.\n"
        "- correct_answer must equal one of the option texts.\n"
        "- explanation must mention at least one cited source_ref verbatim.\n"
        "- source_refs and source_quotes must come directly from the verified evidence.\n"
        "- Avoid overlapping stems or correct answers with preserved questions unless unavoidable.\n\n"
        "Failed slots to repair:\n"
        f"{json.dumps(failed_slots, indent=2, sort_keys=True)}\n\n"
        "Already valid preserved questions:\n"
        f"{json.dumps(preserved_questions, indent=2, sort_keys=True)}\n\n"
        "Verified evidence JSON:\n"
        f"{json.dumps(to_serializable(refined_evidence), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt).strip()


def source_pack_digest(source_pack: SourcePack) -> str:
    payload = to_serializable(source_pack)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _split_sentences(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        segment.strip()
        for segment in _SENTENCE_SPLIT_PATTERN.split(text)
        if segment.strip()
    ]


def build_source_registry(source_pack: SourcePack) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    for document in sorted(source_pack.documents, key=lambda doc: doc.doc_id):
        if document.pages:
            for page_index, page_text in enumerate(document.pages, start=1):
                for sentence_index, sentence in enumerate(
                    _split_sentences(page_text), start=1
                ):
                    chunks.append(
                        SourceChunk(
                            chunk_id=f"{document.doc_id}_p{page_index:02d}_c{sentence_index:02d}",
                            doc_id=document.doc_id,
                            page=page_index,
                            section=None,
                            chunk_type="sentence",
                            text=sentence,
                        )
                    )
        else:
            for sentence_index, sentence in enumerate(
                _split_sentences(document.text), start=1
            ):
                chunks.append(
                    SourceChunk(
                        chunk_id=f"{document.doc_id}_p00_c{sentence_index:02d}",
                        doc_id=document.doc_id,
                        page=None,
                        section=None,
                        chunk_type="sentence",
                        text=sentence,
                    )
                )
    return chunks


def _infer_role(instruction: str) -> str:
    lowered = instruction.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return role
    return "summary"


def _extract_required_shape_kinds(instruction: str) -> list[str]:
    lowered = instruction.lower()
    required: list[str] = []
    if any(keyword in lowered for keyword in ("chart", "graph", "plot")):
        required.append("chart")
    if "table" in lowered:
        required.append("table")
    if any(keyword in lowered for keyword in ("image", "photo", "diagram", "visual")):
        required.append("image")
    if any(
        keyword in lowered for keyword in ("citation", "cite", "source", "reference")
    ):
        required.append("citation")
    if any(keyword in lowered for keyword in ("title", "headline", "bullet", "text")):
        required.append("text")
    return sorted(set(required))


def _extract_required_points(instruction: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", instruction).strip()
    stripped = re.sub(
        r"^(show|include|cover|present|provide)\s+", "", cleaned, flags=re.IGNORECASE
    )
    parts = re.split(r"\s+with\s+|\s+including\s+|;|,|\band\b", stripped)
    points = []
    for part in parts:
        part = part.strip(" .")
        if len(part.split()) >= 2:
            points.append(part)
    return list(dict.fromkeys(points[:4])) or [cleaned]


def _extract_exact_values(text: str) -> list[str]:
    return list(dict.fromkeys(_NUMBER_PATTERN.findall(text)))


def parse_required_slides(prompt: str) -> list[RequiredSlideSpec]:
    required_slides: list[RequiredSlideSpec] = []
    for match in _SLIDE_PLAN_PATTERN.finditer(prompt):
        slide_index = int(match.group(1))
        instruction = match.group(2).strip()
        title_hint = (
            instruction.split(" with ", 1)[0].strip(" .") if instruction else None
        )
        required_slides.append(
            RequiredSlideSpec(
                slide_index=slide_index,
                slide_role=_infer_role(instruction),
                title_hint=title_hint,
                instructions=instruction,
                required_points=_extract_required_points(instruction),
                required_exact_values=_extract_exact_values(instruction),
                required_shape_kinds=_extract_required_shape_kinds(instruction),
                citation_required=bool(
                    re.search(
                        r"cite|citation|source|reference", instruction, re.IGNORECASE
                    )
                ),
                metadata={"raw_instruction": instruction},
            )
        )
    return sorted(required_slides, key=lambda item: item.slide_index)


def _infer_audience(prompt: str, task_constraints: TaskConstraints | None) -> str:
    if task_constraints and task_constraints.target_audience:
        return task_constraints.target_audience
    lowered = prompt.lower()
    if "executive" in lowered:
        return "executive"
    if "student" in lowered or "classroom" in lowered:
        return "education"
    if "research" in lowered or "academic" in lowered:
        return "academic"
    return "general_professional"


def _infer_tone(prompt: str, task_constraints: TaskConstraints | None) -> str:
    if task_constraints and task_constraints.tone:
        return task_constraints.tone
    lowered = prompt.lower()
    if "persuasive" in lowered:
        return "persuasive"
    if "formal" in lowered:
        return "formal"
    return "professional"


def _infer_slide_constraints(
    prompt: str,
    task_constraints: TaskConstraints | None,
    required_slides: list[RequiredSlideSpec],
) -> tuple[int | None, int | None]:
    if task_constraints and task_constraints.min_slides is not None:
        min_slides = task_constraints.min_slides
    else:
        min_slides = len(required_slides) or None
    if task_constraints and task_constraints.max_slides is not None:
        max_slides = task_constraints.max_slides
    else:
        max_slides = len(required_slides) or None

    match = re.search(r"(\d+)\s*[-to]{1,3}\s*(\d+)\s+slides", prompt, re.IGNORECASE)
    if match:
        min_slides = int(match.group(1))
        max_slides = int(match.group(2))
    else:
        match = re.search(r"(\d+)\s+slides", prompt, re.IGNORECASE)
        if match:
            min_slides = int(match.group(1))
            max_slides = int(match.group(1))
    return min_slides, max_slides


def _source_fact_candidates(chunks: list[SourceChunk]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for chunk in chunks:
        text = chunk.text.strip()
        if len(text.split()) < 3:
            continue
        ref = (
            f"{chunk.doc_id}:p{chunk.page}" if chunk.page is not None else chunk.doc_id
        )
        candidates.append({"text": text, "ref": ref, "quote": text})
    return candidates


def build_task_spec(
    prompt: str,
    source_pack: SourcePack,
    task_constraints: TaskConstraints | None = None,
    capability_profile: CapabilityProfile | None = None,
) -> TaskSpec:
    normalized_prompt = normalize_prompt(prompt)
    required_slides = parse_required_slides(prompt)
    chunks = build_source_registry(source_pack)
    facts = _source_fact_candidates(chunks)
    audience = _infer_audience(prompt, task_constraints)
    tone = _infer_tone(prompt, task_constraints)
    min_slides, max_slides = _infer_slide_constraints(
        prompt, task_constraints, required_slides
    )
    citation_required = True
    require_quantitative_content = bool(
        re.search(
            r"chart|table|metric|data|quant|compare|percentage|percent|trend",
            prompt,
            re.IGNORECASE,
        )
    )

    required_sections = []
    if required_slides:
        required_sections = list(
            dict.fromkeys(slide.slide_role for slide in required_slides)
        )
    else:
        required_sections = ["summary"]

    required_points = []
    for slide in required_slides:
        required_points.extend(slide.required_points)
    numeric_facts = [
        fact["text"] for fact in facts if _NUMBER_PATTERN.search(fact["text"])
    ]
    if not required_points:
        required_points.extend(fact["text"] for fact in facts[:4])
    required_points.extend(numeric_facts[:4])
    required_points = list(dict.fromkeys(point for point in required_points if point))[
        :12
    ]

    return TaskSpec(
        task_id=source_pack.task_id,
        prompt=normalized_prompt,
        audience=audience,
        tone=tone,
        min_slides=min_slides,
        max_slides=max_slides,
        required_sections=required_sections,
        required_points=required_points,
        required_slides=required_slides or None,
        citation_required=citation_required,
        require_quantitative_content=require_quantitative_content,
        capability_profile=capability_profile or CapabilityProfile(),
        metadata={
            "source_digest": source_pack_digest(source_pack),
            "source_facts": facts,
            "source_values": sorted(
                {
                    value
                    for fact in facts
                    for value in _extract_exact_values(fact["text"])
                }
            ),
            "prompt_has_slide_plan": bool(required_slides),
        },
    )


def generate_checklist(task_spec: TaskSpec) -> list[ChecklistItem]:
    checklist: list[ChecklistItem] = [
        ChecklistItem(
            item_id="fundamentals_slide_count",
            dimension="fundamentals",
            prompt_text="Is the slide count within the requested range?",
            item_kind="slide_count_range",
            source_refs=[],
        ),
        ChecklistItem(
            item_id="fundamentals_theme",
            dimension="fundamentals",
            prompt_text="Does the deck maintain a central theme aligned with the prompt?",
            item_kind="theme_alignment",
            relevant_sections=task_spec.required_sections,
            source_refs=[],
        ),
        ChecklistItem(
            item_id="fundamentals_audience",
            dimension="fundamentals",
            prompt_text="Is the deck appropriate for the intended audience and tone?",
            item_kind="audience_tone",
            source_refs=[],
        ),
        ChecklistItem(
            item_id="visual_readability",
            dimension="visual_layout",
            prompt_text="Is the text readable without tiny fonts?",
            item_kind="readable_text",
            source_refs=[],
        ),
        ChecklistItem(
            item_id="visual_overlap",
            dimension="visual_layout",
            prompt_text="Are there no major overlaps or clipping risks?",
            item_kind="no_major_overlap",
            source_refs=[],
        ),
        ChecklistItem(
            item_id="visual_consistency",
            dimension="visual_layout",
            prompt_text="Is the visual design reasonably consistent across slides?",
            item_kind="design_consistency",
            source_refs=[],
        ),
    ]

    for index, section in enumerate(task_spec.required_sections, start=1):
        checklist.append(
            ChecklistItem(
                item_id=f"completeness_section_{index:02d}",
                dimension="completeness",
                prompt_text=f"Does the deck include a clear '{section}' section?",
                item_kind="required_section",
                relevant_sections=[section],
                source_refs=[],
            )
        )

    for index, point in enumerate(task_spec.required_points, start=1):
        source_refs = [
            fact["ref"]
            for fact in task_spec.metadata.get("source_facts", [])
            if point in fact["text"]
        ][:2]
        checklist.append(
            ChecklistItem(
                item_id=f"completeness_point_{index:02d}",
                dimension="completeness",
                prompt_text=f"Does the deck cover this required point: {point}?",
                item_kind="required_point",
                source_refs=source_refs,
            )
        )
        checklist.append(
            ChecklistItem(
                item_id=f"correctness_point_{index:02d}",
                dimension="correctness",
                prompt_text=f"Is this required point stated correctly: {point}?",
                item_kind="correct_required_point",
                source_refs=source_refs,
            )
        )

    if task_spec.citation_required:
        checklist.append(
            ChecklistItem(
                item_id="correctness_citations",
                dimension="correctness",
                prompt_text="Are factual claims supported with citation-like content where needed?",
                item_kind="citation_coverage",
                source_refs=[],
            )
        )

    if task_spec.required_slides:
        for slide in task_spec.required_slides:
            checklist.append(
                ChecklistItem(
                    item_id=f"fidelity_slide_{slide.slide_index:02d}",
                    dimension="fidelity",
                    prompt_text=f"Is all content on Slide {slide.slide_index} supported by the source pack?",
                    item_kind="slide_fidelity",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                    source_refs=[],
                )
            )
    else:
        checklist.append(
            ChecklistItem(
                item_id="fidelity_deck",
                dimension="fidelity",
                prompt_text="Is all deck content supported by the source pack?",
                item_kind="deck_fidelity",
                source_refs=[],
            )
        )

    return checklist


def generate_slide_checklists(task_spec: TaskSpec) -> dict[int, list[ChecklistItem]]:
    slide_checklists: dict[int, list[ChecklistItem]] = {}
    for slide in task_spec.required_slides or []:
        items = [
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_prompt_alignment",
                dimension="prompt_alignment",
                prompt_text=f"Does Slide {slide.slide_index} match the intended role '{slide.slide_role}'?",
                item_kind="slide_role_match",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
                source_refs=[],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_title_alignment",
                dimension="prompt_alignment",
                prompt_text=f"Is Slide {slide.slide_index} title aligned with '{slide.title_hint or slide.instructions}'?",
                item_kind="slide_title_alignment",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
                source_refs=[],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_fidelity",
                dimension="local_fidelity",
                prompt_text=f"Is all content on Slide {slide.slide_index} supported by the source pack?",
                item_kind="slide_fidelity",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
                source_refs=[],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_usability",
                dimension="local_usability",
                prompt_text=f"Is Slide {slide.slide_index} readable and free of major clutter?",
                item_kind="slide_readability",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
                source_refs=[],
            ),
        ]
        for point_index, point in enumerate(slide.required_points, start=1):
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_point_{point_index:02d}",
                    dimension="local_completeness",
                    prompt_text=f"Does Slide {slide.slide_index} cover this point: {point}?",
                    item_kind="slide_required_point",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                    source_refs=[],
                )
            )
        for exact_index, exact_value in enumerate(slide.required_exact_values, start=1):
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_exact_{exact_index:02d}",
                    dimension="local_correctness",
                    prompt_text=f"Does Slide {slide.slide_index} include the exact value '{exact_value}' correctly?",
                    item_kind="slide_exact_value",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                    source_refs=[],
                )
            )
        if slide.required_shape_kinds:
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_visual_kind",
                    dimension="local_completeness",
                    prompt_text=f"Does Slide {slide.slide_index} include the expected supported visual forms?",
                    item_kind="slide_required_visual",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                    source_refs=[],
                    evidence_policy={
                        "required_shape_kinds": slide.required_shape_kinds
                    },
                )
            )
        slide_checklists[slide.slide_index] = items
    return slide_checklists


def build_eval_spec_payload(
    prompt: str,
    source_pack: SourcePack,
    task_constraints: TaskConstraints | None = None,
    *,
    quiz_bank_service: QuizBankGenerationService,
    mode: str = "eval",
) -> EvalSpec:
    task_spec = build_task_spec(prompt, source_pack, task_constraints)
    checklist = generate_checklist(task_spec)
    slide_checklists = generate_slide_checklists(task_spec)
    quiz_bank, quiz_bank_metadata = quiz_bank_service.generate_quiz_bank(
        task_spec=task_spec,
        source_pack=source_pack,
        mode=mode,
    )
    task_spec.metadata["quiz_bank_generation"] = quiz_bank_metadata
    payload = {
        "task_spec": to_serializable(task_spec),
        "checklist": to_serializable(checklist),
        "slide_checklists": to_serializable(slide_checklists),
        "quiz_bank": to_serializable(quiz_bank),
        "scoring_config": DEFAULT_SCORING_CONFIG,
        "spec_version": SPEC_VERSION,
    }
    spec_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EvalSpec(
        task_spec=task_spec,
        checklist=checklist,
        slide_checklists=slide_checklists,
        quiz_bank=quiz_bank,
        scoring_config=DEFAULT_SCORING_CONFIG,
        spec_version=SPEC_VERSION,
        spec_hash=spec_hash,
    )


__all__ = [
    "DEFAULT_SCORING_CONFIG",
    "SPEC_VERSION",
    "SourceChunk",
    "build_quiz_extraction_prompts",
    "build_quiz_generation_context",
    "build_quiz_generation_prompts",
    "build_quiz_regeneration_prompts",
    "build_quiz_refinement_prompts",
    "build_eval_spec_payload",
    "build_source_registry",
    "build_task_spec",
    "generate_checklist",
    "generate_slide_checklists",
    "normalize_prompt",
    "parse_required_slides",
    "render_quiz_generation_context",
    "source_pack_digest",
]
