from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

import numpy as np

from server.utils.reward_models import ExtractedPresentation, ExtractedSlide


_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_NUMERIC_BOUNDARY_PATTERN = re.compile(
    r"(?<![0-9])"
    r"[\$\u00a3\u20ac]?"
    r"\d{1,3}(?:,\d{3})*(?:\.\d+)?"
    r"[%]?"
    r"(?:\s*(?:million|billion|trillion|thousand|mn|bn|tn|m|b|k))?"
    r"(?![0-9])",
    re.IGNORECASE,
)
_MAGNITUDE_MAP: dict[str, int] = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
    "tn": 1_000_000_000_000,
    "trillion": 1_000_000_000_000,
}
_TEXT_UNIT_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_DEFAULT_SENTENCE_MODEL = os.environ.get(
    "SENTENCE_TRANSFORMER_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _similarity_units(text: str | None) -> list[str]:
    if not text:
        return []
    units = [
        segment.strip()
        for segment in _TEXT_UNIT_SPLIT_PATTERN.split(text)
        if segment.strip()
    ]
    return units or [text.strip()]


@lru_cache(maxsize=1)
def _similarity_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_DEFAULT_SENTENCE_MODEL)


def _parse_numeric_value(raw: str) -> float | None:
    """Parse a numeric string into a canonical float.

    Handles commas, currency symbols, percentage signs, and magnitude
    suffixes (e.g. "1.2M", "$3,400", "25%", "2 billion").
    """
    cleaned = raw.strip().lstrip("$\u00a3\u20ac")
    cleaned = cleaned.replace(",", "")
    magnitude = 1
    for suffix, factor in _MAGNITUDE_MAP.items():
        if cleaned.lower().endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
            magnitude = factor
            break
    is_percent = cleaned.endswith("%")
    if is_percent:
        cleaned = cleaned[:-1]
    try:
        value = float(cleaned) * magnitude
    except ValueError:
        return None
    if is_percent:
        value = round(value, 6)
    return value


def normalized_number_match(candidate_text: str, target: str) -> bool:
    """Check if *target* numeric value appears in *candidate_text*.

    Uses word-boundary-aware extraction and canonical float comparison
    to avoid false positives (e.g. "25%" inside "125%") and false
    negatives (e.g. "1,234" vs "1234", "$5.2M" vs "5.2 million").
    """
    target_val = _parse_numeric_value(target)
    if target_val is None:
        return target in candidate_text
    for match in _NUMERIC_BOUNDARY_PATTERN.finditer(candidate_text):
        candidate_val = _parse_numeric_value(match.group())
        if candidate_val is not None and abs(candidate_val - target_val) < 1e-6:
            return True
    return False


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
    candidate_units = _similarity_units(candidate)
    if not candidate_units or not requirement_norm:
        return 0.0
    model = _similarity_model()
    embeddings = model.encode(
        [*candidate_units, requirement],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    requirement_embedding = embeddings[-1]
    candidate_embeddings = embeddings[:-1]
    return max(0.0, float(np.max(candidate_embeddings @ requirement_embedding)))


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
    "normalized_number_match",
    "slide_text_corpus",
    "text_match_score",
]
