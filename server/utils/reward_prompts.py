from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from server.utils.reward_models import (
    CapabilityProfile,
    RequiredSlideSpec,
    SourcePack,
    TaskConstraints,
    TaskSpec,
    to_serializable,
)


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


__all__ = [
    "SourceChunk",
    "build_source_registry",
    "build_task_spec",
    "normalize_prompt",
    "parse_required_slides",
    "source_pack_digest",
]
