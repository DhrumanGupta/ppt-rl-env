from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from server.utils.reward_models import (
    ChecklistItem,
    PresentationExtraction,
    SlideExtraction,
    TaskSpec,
)


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


def slide_text_corpus(slide: SlideExtraction) -> str:
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


def deck_text_corpus(extraction: PresentationExtraction) -> str:
    return "\n".join(slide_text_corpus(slide) for slide in extraction.slides)


def compute_overlap_ratio(slide: SlideExtraction) -> float:
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


def is_blank_or_title_only(slide: SlideExtraction) -> bool:
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


def compute_presentation_diagnostics(
    extraction: PresentationExtraction,
    task_spec: TaskSpec,
) -> dict[str, Any]:
    min_font_sizes = [
        slide.text_metrics.get("min_font_size_pt")
        for slide in extraction.slides
        if slide.text_metrics.get("min_font_size_pt") is not None
    ]
    overlap_ratios = [compute_overlap_ratio(slide) for slide in extraction.slides]
    blank_slides = [
        slide.slide_index
        for slide in extraction.slides
        if is_blank_or_title_only(slide)
    ]
    all_fonts = {
        font
        for slide in extraction.slides
        for font in slide.text_metrics.get("unique_font_families", [])
    }
    citation_count = sum(len(slide.citations) for slide in extraction.slides)
    quantitative_slides = [
        slide.slide_index
        for slide in extraction.slides
        if extract_numbers(slide_text_corpus(slide))
    ]
    return {
        "slide_count": extraction.slide_count,
        "slide_count_violation": int(
            (
                task_spec.min_slides is not None
                and extraction.slide_count < task_spec.min_slides
            )
            or (
                task_spec.max_slides is not None
                and extraction.slide_count > task_spec.max_slides
            )
        ),
        "blank_slide_indexes": blank_slides,
        "blank_title_only_ratio": (len(blank_slides) / extraction.slide_count)
        if extraction.slide_count
        else 1.0,
        "citation_count": citation_count,
        "citation_coverage_ratio": (citation_count / extraction.slide_count)
        if extraction.slide_count
        else 0.0,
        "min_font_size_pt": min(min_font_sizes) if min_font_sizes else None,
        "median_overlap_ratio": sorted(overlap_ratios)[len(overlap_ratios) // 2]
        if overlap_ratios
        else 0.0,
        "max_overlap_ratio": max(overlap_ratios) if overlap_ratios else 0.0,
        "unique_font_family_count": len(all_fonts),
        "quantitative_slide_count": len(quantitative_slides),
    }


def compute_aesthetics_scores(extraction: PresentationExtraction) -> dict[str, float]:
    if not extraction.slides:
        return {
            "harmony": 0.0,
            "engagement": 0.0,
            "usability": 0.0,
            "rhythm": 0.0,
            "aesthetic": 0.0,
        }

    font_counts = [
        slide.text_metrics.get("unique_font_family_count", 0)
        for slide in extraction.slides
    ]
    min_fonts = [
        slide.text_metrics.get("min_font_size_pt")
        for slide in extraction.slides
        if slide.text_metrics.get("min_font_size_pt") is not None
    ]
    overlap_scores = [
        1.0 - min(compute_overlap_ratio(slide) / 0.1, 1.0)
        for slide in extraction.slides
    ]
    density = [
        slide.layout_metrics.get("occupied_area_ratio", 0.0)
        for slide in extraction.slides
    ]

    harmony = 1.0 - min(max(font_counts, default=1) - 1, 4) / 4.0
    engagement = min(
        sum(
            1
            for slide in extraction.slides
            if slide.layout_metrics.get("chart_count", 0)
            or slide.layout_metrics.get("table_count", 0)
            or slide.layout_metrics.get("image_count", 0)
        )
        / max(extraction.slide_count, 1),
        1.0,
    )
    usability = 0.5 * (
        1.0 if not min_fonts else min(min(min_fonts) / 18.0, 1.0)
    ) + 0.5 * (sum(overlap_scores) / len(overlap_scores))
    density_mean = sum(density) / len(density)
    rhythm = 1.0 - min(
        sum(abs(item - density_mean) for item in density) / len(density), 1.0
    )
    aesthetic = 0.20 * harmony + 0.20 * engagement + 0.35 * usability + 0.25 * rhythm
    return {
        "harmony": clamp(harmony),
        "engagement": clamp(engagement),
        "usability": clamp(usability),
        "rhythm": clamp(rhythm),
        "aesthetic": clamp(aesthetic),
    }


def _source_supported(text: str, task_spec: TaskSpec) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    source_facts = task_spec.metadata.get("source_facts", [])
    for fact in source_facts:
        if text_match_score(fact.get("text"), normalized) >= 0.6:
            return True
    source_values = set(task_spec.metadata.get("source_values", []))
    numbers = set(extract_numbers(text))
    if numbers and not numbers.issubset(source_values):
        return False
    return not numbers


def score_checklist_item(
    item: ChecklistItem,
    extraction: PresentationExtraction,
    task_spec: TaskSpec,
) -> dict[str, Any]:
    diagnostics = compute_presentation_diagnostics(extraction, task_spec)
    deck_text = deck_text_corpus(extraction)
    verdict = False
    evidence: dict[str, Any] = {}

    if item.item_kind == "slide_count_range":
        verdict = diagnostics["slide_count_violation"] == 0
        evidence = {"slide_count": extraction.slide_count}
    elif item.item_kind == "theme_alignment":
        verdict = any(
            text_match_score(deck_text, point) >= 0.5
            for point in task_spec.required_points[:4]
        )
    elif item.item_kind == "audience_tone":
        verdict = (
            extraction.slide_count > 0 and diagnostics["blank_title_only_ratio"] < 0.75
        )
        evidence = {"audience": task_spec.audience, "tone": task_spec.tone}
    elif item.item_kind == "readable_text":
        min_font = diagnostics.get("min_font_size_pt")
        verdict = min_font is None or min_font >= 10
        evidence = {"min_font_size_pt": min_font}
    elif item.item_kind == "no_major_overlap":
        verdict = diagnostics["max_overlap_ratio"] <= 0.08
        evidence = {"max_overlap_ratio": diagnostics["max_overlap_ratio"]}
    elif item.item_kind == "design_consistency":
        verdict = diagnostics["unique_font_family_count"] <= 3
        evidence = {"unique_font_family_count": diagnostics["unique_font_family_count"]}
    elif item.item_kind == "required_section":
        target = " ".join(item.relevant_sections)
        verdict = any(
            text_match_score(slide.title_text or slide.all_text, target) >= 0.5
            for slide in extraction.slides
        )
        evidence = {"required_sections": item.relevant_sections}
    elif item.item_kind in {"required_point", "correct_required_point"}:
        requirement = item.prompt_text.split(":", 1)[-1].strip()
        verdict = text_match_score(deck_text, requirement) >= 0.6
        if verdict and item.item_kind == "correct_required_point":
            verdict = _source_supported(requirement, task_spec)
        evidence = {"requirement": requirement}
    elif item.item_kind == "citation_coverage":
        verdict = diagnostics["citation_count"] >= max(1, extraction.slide_count // 3)
        evidence = {"citation_count": diagnostics["citation_count"]}
    elif item.item_kind in {"slide_fidelity", "deck_fidelity"}:
        verdict = all(
            _source_supported(slide_text_corpus(slide), task_spec)
            for slide in extraction.slides
        )
    else:
        verdict = False

    return {
        "item_id": item.item_id,
        "dimension": item.dimension,
        "verdict": "yes" if verdict else "no",
        "score": 1.0 if verdict else 0.0,
        "evidence": evidence,
        "source_refs": item.source_refs,
    }


def score_slide_checklist_item(
    item: ChecklistItem,
    slide: SlideExtraction,
    target_role: str,
    title_hint: str | None,
    required_points: list[str],
    required_exact_values: list[str],
    required_shape_kinds: list[str],
    task_spec: TaskSpec,
) -> dict[str, Any]:
    slide_text = slide_text_corpus(slide)
    verdict = False
    evidence: dict[str, Any] = {}

    if item.item_kind == "slide_role_match":
        verdict = (
            text_match_score(slide.title_text or slide_text, target_role) >= 0.3
            or text_match_score(slide_text, target_role) >= 0.3
        )
    elif item.item_kind == "slide_title_alignment":
        verdict = (
            text_match_score(slide.title_text or slide_text, title_hint or target_role)
            >= 0.5
        )
    elif item.item_kind == "slide_required_point":
        requirement = item.prompt_text.split(":", 1)[-1].strip()
        verdict = text_match_score(slide_text, requirement) >= 0.6
        evidence = {"requirement": requirement}
    elif item.item_kind == "slide_exact_value":
        values = set(extract_numbers(slide_text))
        exact_value = item.prompt_text.split("'")[1]
        verdict = exact_value in values
        evidence = {"values": sorted(values)}
    elif item.item_kind == "slide_required_visual":
        present = {shape.shape_kind for shape in slide.shapes}
        verdict = set(required_shape_kinds).issubset(present)
        evidence = {"present_shape_kinds": sorted(present)}
    elif item.item_kind == "slide_fidelity":
        verdict = _source_supported(slide_text, task_spec)
    elif item.item_kind == "slide_readability":
        overlap = compute_overlap_ratio(slide)
        min_font = slide.text_metrics.get("min_font_size_pt")
        verdict = overlap <= 0.08 and (min_font is None or min_font >= 10)
        evidence = {"overlap_ratio": overlap, "min_font_size_pt": min_font}
    else:
        verdict = False

    return {
        "item_id": item.item_id,
        "dimension": item.dimension,
        "verdict": "yes" if verdict else "no",
        "score": 1.0 if verdict else 0.0,
        "evidence": evidence,
        "target_role": target_role,
        "title_hint": title_hint,
        "required_points": required_points,
        "required_exact_values": required_exact_values,
    }


def mean_scores_by_dimension(results: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        grouped[result["dimension"]].append(float(result["score"]))
    return {
        dimension: (sum(scores) / len(scores) if scores else 0.0)
        for dimension, scores in grouped.items()
    }


def redundancy_score(
    slide: SlideExtraction, previous_slides: list[SlideExtraction] | None
) -> float:
    if not previous_slides:
        return 0.0
    slide_tokens = tokenize(slide_text_corpus(slide))
    if not slide_tokens:
        return 0.0
    return max(
        (len(slide_tokens & tokenize(slide_text_corpus(previous))) / len(slide_tokens))
        for previous in previous_slides
    )


__all__ = [
    "clamp",
    "compute_aesthetics_scores",
    "compute_overlap_ratio",
    "compute_presentation_diagnostics",
    "deck_text_corpus",
    "extract_numbers",
    "is_blank_or_title_only",
    "mean_scores_by_dimension",
    "normalize_text",
    "redundancy_score",
    "score_checklist_item",
    "score_slide_checklist_item",
    "slide_text_corpus",
    "text_match_score",
    "tokenize",
]
