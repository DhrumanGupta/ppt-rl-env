from __future__ import annotations

import re
from typing import Any

from server.utils.reward_models import ExtractedPresentation, ExtractedSlide


_WORD_PATTERN = re.compile(r"[a-z0-9%]+")
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text: str | None) -> set[str]:
    return {
        token
        for token in _WORD_PATTERN.findall(normalize_text(text))
        if token not in _STOPWORDS
    }


def extract_numbers(text: str | None) -> list[str]:
    if not text:
        return []
    return _NUMBER_PATTERN.findall(text)


def text_match_score(candidate: str | None, requirement: str | None) -> float:
    if not candidate or not requirement:
        return 0.0
    candidate_norm = normalize_text(candidate)
    requirement_norm = normalize_text(requirement)
    if requirement_norm in candidate_norm:
        return 1.0
    candidate_tokens = tokenize(candidate_norm)
    requirement_tokens = tokenize(requirement_norm)
    if not requirement_tokens:
        return 0.0
    overlap = candidate_tokens & requirement_tokens
    return len(overlap) / len(requirement_tokens)


def slide_text_corpus(slide: ExtractedSlide) -> str:
    parts = [slide.title_text or "", slide.all_text]
    for shape in slide.shapes:
        if shape.chart is not None:
            if shape.chart.title:
                parts.append(shape.chart.title)
            parts.extend(shape.chart.categories)
            for series in shape.chart.series:
                if series.get("name"):
                    parts.append(str(series["name"]))
                parts.extend(str(value) for value in series.get("values", []))
        if shape.table is not None:
            parts.extend(cell for row in shape.table.cells for cell in row)
    return "\n".join(part for part in parts if part)


def deck_text_corpus(extraction: ExtractedPresentation) -> str:
    return "\n".join(slide_text_corpus(slide) for slide in extraction.slides)


def compute_overlap_ratio(slide: ExtractedSlide) -> float:
    def intersection_area(a: Any, b: Any) -> float:
        x_overlap = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
        y_overlap = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
        return x_overlap * y_overlap

    total_overlap = 0.0
    total_area = sum(shape.w * shape.h for shape in slide.shapes)
    if total_area <= 0:
        return 0.0
    for index, first in enumerate(slide.shapes):
        for second in slide.shapes[index + 1 :]:
            total_overlap += intersection_area(first, second)
    return total_overlap / total_area


def is_blank_or_title_only(slide: ExtractedSlide) -> bool:
    non_citation_texts = [
        shape.raw_text.strip()
        for shape in slide.shapes
        if shape.raw_text and shape.shape_kind == "text"
    ]
    if not slide.shapes:
        return True
    if len(non_citation_texts) == 0 and not any(
        shape.shape_kind in {"chart", "table", "image"} for shape in slide.shapes
    ):
        return True
    if (
        len(non_citation_texts) == 1
        and slide.title_text
        and non_citation_texts[0] == slide.title_text
    ):
        return True
    return False


__all__ = [
    "clamp",
    "compute_overlap_ratio",
    "deck_text_corpus",
    "extract_numbers",
    "is_blank_or_title_only",
    "normalize_text",
    "slide_text_corpus",
    "text_match_score",
    "tokenize",
]
