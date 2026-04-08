from __future__ import annotations

from collections import defaultdict
from typing import Any

from server.utils.reward_metrics import (
    clamp,
    compute_overlap_ratio,
    deck_text_corpus,
    extract_numbers,
    is_blank_or_title_only,
    normalize_text,
    slide_text_corpus,
    text_match_score,
)
from server.utils.reward_models import (
    ChecklistItem,
    ExtractedPresentation,
    ExtractedSlide,
    TaskSpec,
)


def compute_presentation_diagnostics(
    extraction: ExtractedPresentation,
    task_spec: TaskSpec,
) -> dict[str, Any]:
    min_font_sizes = [
        slide.text_metrics.get("min_font_size_pt")
        for slide in extraction.slides
        if slide.text_metrics.get("min_font_size_pt") is not None
    ]
    overlap_ratios = [compute_overlap_ratio(slide) for slide in extraction.slides]
    blank_count = sum(1 for slide in extraction.slides if is_blank_or_title_only(slide))
    visual_sparsity = [
        compute_visual_sparsity_penalty(slide)["penalty"] for slide in extraction.slides
    ]
    all_fonts = {
        font
        for slide in extraction.slides
        for font in slide.text_metrics.get("unique_font_families", [])
    }
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
        "blank_title_only_ratio": (blank_count / extraction.slide_count)
        if extraction.slide_count
        else 1.0,
        "min_font_size_pt": min(min_font_sizes) if min_font_sizes else None,
        "max_overlap_ratio": max(overlap_ratios) if overlap_ratios else 0.0,
        "mean_visual_sparsity_penalty": (
            sum(visual_sparsity) / len(visual_sparsity) if visual_sparsity else 0.0
        ),
        "max_visual_sparsity_penalty": max(visual_sparsity) if visual_sparsity else 0.0,
        "unique_font_family_count": len(all_fonts),
    }


def compute_aesthetics_scores(extraction: ExtractedPresentation) -> dict[str, float]:
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
        "harmony": max(0.0, min(1.0, harmony)),
        "engagement": max(0.0, min(1.0, engagement)),
        "usability": max(0.0, min(1.0, usability)),
        "rhythm": max(0.0, min(1.0, rhythm)),
        "aesthetic": max(0.0, min(1.0, aesthetic)),
    }


def _source_supported(text: str, task_spec: TaskSpec) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    source_facts = task_spec.metadata.get("source_facts", [])
    for fact in source_facts:
        if text_match_score(fact.get("text"), text) >= 0.6:
            return True
    source_values = set(task_spec.metadata.get("source_values", []))
    numbers = set(extract_numbers(text))
    if numbers:
        return numbers.issubset(source_values)
    return True


def score_checklist_item(
    item: ChecklistItem,
    extraction: ExtractedPresentation,
    task_spec: TaskSpec,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
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
    elif item.item_kind == "slide_fidelity":
        target_slides = [
            slide
            for slide in extraction.slides
            if slide.slide_index in (item.required_slide_scope or [])
        ]
        verdict = (
            all(
                _source_supported(slide_text_corpus(slide), task_spec)
                for slide in target_slides
            )
            if target_slides
            else True
        )
    elif item.item_kind == "deck_fidelity":
        verdict = all(
            _source_supported(slide_text_corpus(slide), task_spec)
            for slide in extraction.slides
        )

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
    slide: ExtractedSlide,
    target_role: str,
    title_hint: str | None,
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

    return {
        "item_id": item.item_id,
        "dimension": item.dimension,
        "verdict": "yes" if verdict else "no",
        "score": 1.0 if verdict else 0.0,
        "evidence": evidence,
        "target_role": target_role,
        "title_hint": title_hint,
    }


def _hex_to_rgb(color_hex: str | None) -> tuple[int, int, int] | None:
    if not color_hex:
        return None
    normalized = color_hex.strip().lstrip("#")
    if len(normalized) != 6:
        return None
    try:
        return (
            int(normalized[0:2], 16),
            int(normalized[2:4], 16),
            int(normalized[4:6], 16),
        )
    except ValueError:
        return None


def compute_visual_sparsity_penalty(slide: ExtractedSlide) -> dict[str, Any]:
    occupied_area_ratio = float(slide.layout_metrics.get("occupied_area_ratio", 0.0))
    text_word_count = len((slide_text_corpus(slide) or "").split())
    non_text_shape_count = sum(
        1 for shape in slide.shapes if shape.shape_kind not in {"text", "citation"}
    )
    rich_visual_count = (
        int(slide.layout_metrics.get("chart_count", 0))
        + int(slide.layout_metrics.get("table_count", 0))
        + int(slide.layout_metrics.get("image_count", 0))
    )
    palette = slide.color_metrics.get("palette", [])
    palette_size = len(palette)
    background_rgb = _hex_to_rgb(slide.background_color_hex)
    plain_light_background = False
    if background_rgb is not None:
        plain_light_background = (
            min(background_rgb) >= 250
            and (max(background_rgb) - min(background_rgb)) <= 4
        )

    occupancy_penalty = 1.0 - clamp((occupied_area_ratio - 0.03) / 0.12)
    text_penalty = 1.0 - clamp((text_word_count - 4.0) / 20.0)
    non_text_penalty = (
        0.0 if non_text_shape_count >= 2 else 1.0 - 0.5 * non_text_shape_count
    )
    palette_penalty = 1.0 if palette_size <= 2 else 0.5 if palette_size == 3 else 0.0
    plain_background_penalty = 1.0 if plain_light_background else 0.0

    penalty = clamp(
        0.25 * occupancy_penalty
        + 0.15 * text_penalty
        + 0.10 * non_text_penalty
        + 0.10 * palette_penalty
        + 0.40 * plain_background_penalty
    )
    if rich_visual_count > 0:
        penalty = clamp(penalty - 0.20)
    elif non_text_shape_count > 0 and not plain_light_background:
        penalty = clamp(penalty - 0.15)

    return {
        "penalty": penalty,
        "occupied_area_ratio": occupied_area_ratio,
        "text_word_count": text_word_count,
        "non_text_shape_count": non_text_shape_count,
        "rich_visual_count": rich_visual_count,
        "palette_size": palette_size,
        "plain_light_background": plain_light_background,
    }


def score_generic_slide_checklist_items(
    slide: ExtractedSlide,
    task_spec: TaskSpec,
) -> list[dict[str, Any]]:
    slide_text = slide_text_corpus(slide)
    slide_title = slide.title_text or ""
    normalized_slide_text = normalize_text(slide_text)
    required_points = task_spec.required_points[:6]
    matched_points = [
        point for point in required_points if text_match_score(slide_text, point) >= 0.6
    ]
    matched_sections = [
        section
        for section in task_spec.required_sections
        if text_match_score(slide_title or slide_text, section) >= 0.3
        or text_match_score(slide_text, section) >= 0.3
    ]
    source_supported = _source_supported(slide_text, task_spec)
    slide_numbers = extract_numbers(slide_text)
    source_values = set(task_spec.metadata.get("source_values", []))
    numeric_supported = not slide_numbers or set(slide_numbers).issubset(source_values)
    overlap = compute_overlap_ratio(slide)
    min_font = slide.text_metrics.get("min_font_size_pt")
    readable = overlap <= 0.08 and (min_font is None or min_font >= 10)
    visual_kinds = {shape.shape_kind for shape in slide.shapes}
    quantitative_visual_present = bool(visual_kinds & {"chart", "table"})
    prompt_alignment_score = max(
        text_match_score(slide_title or slide_text, task_spec.prompt),
        max(
            [text_match_score(slide_text, point) for point in matched_points],
            default=0.0,
        ),
        max(
            [
                text_match_score(slide_title or slide_text, section)
                for section in matched_sections
            ],
            default=0.0,
        ),
    )
    contribution_score = (
        len(matched_points) / len(required_points)
        if required_points
        else prompt_alignment_score
    )
    if task_spec.require_quantitative_content:
        contribution_score = min(
            1.0,
            0.8 * contribution_score + 0.2 * float(quantitative_visual_present),
        )

    return [
        {
            "item_id": f"slide_{slide.slide_index:02d}_generic_prompt_alignment",
            "dimension": "prompt_alignment",
            "verdict": "yes" if prompt_alignment_score >= 0.35 else "no",
            "score": prompt_alignment_score,
            "evidence": {
                "matched_sections": matched_sections,
                "matched_required_points": matched_points,
            },
            "target_role": None,
            "title_hint": None,
        },
        {
            "item_id": f"slide_{slide.slide_index:02d}_generic_completeness",
            "dimension": "local_completeness",
            "verdict": "yes" if contribution_score >= 0.3 else "no",
            "score": contribution_score,
            "evidence": {
                "matched_required_points": matched_points,
                "required_point_count": len(required_points),
                "quantitative_visual_present": quantitative_visual_present,
            },
            "target_role": None,
            "title_hint": None,
        },
        {
            "item_id": f"slide_{slide.slide_index:02d}_generic_correctness",
            "dimension": "local_correctness",
            "verdict": "yes" if source_supported and numeric_supported else "no",
            "score": 1.0 if source_supported and numeric_supported else 0.0,
            "evidence": {
                "numeric_supported": numeric_supported,
                "slide_numbers": slide_numbers,
            },
            "target_role": None,
            "title_hint": None,
        },
        {
            "item_id": f"slide_{slide.slide_index:02d}_generic_fidelity",
            "dimension": "local_fidelity",
            "verdict": "yes" if source_supported else "no",
            "score": 1.0 if source_supported else 0.0,
            "evidence": {"source_supported": source_supported},
            "target_role": None,
            "title_hint": None,
        },
        {
            "item_id": f"slide_{slide.slide_index:02d}_generic_usability",
            "dimension": "local_usability",
            "verdict": "yes" if readable else "no",
            "score": 1.0 if readable else 0.0,
            "evidence": {
                "overlap_ratio": overlap,
                "min_font_size_pt": min_font,
                "has_text": bool(normalized_slide_text),
            },
            "target_role": None,
            "title_hint": None,
        },
    ]


def mean_scores_by_dimension(results: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        grouped[result["dimension"]].append(float(result["score"]))
    return {
        dimension: (sum(scores) / len(scores) if scores else 0.0)
        for dimension, scores in grouped.items()
    }


def redundancy_score(
    slide: ExtractedSlide,
    previous_slides: list[ExtractedSlide] | None,
) -> float:
    if not previous_slides:
        return 0.0
    slide_text = slide_text_corpus(slide)
    if not normalize_text(slide_text):
        return 0.0
    return max(
        text_match_score(slide_text_corpus(previous), slide_text)
        for previous in previous_slides
    )


__all__ = [
    "compute_visual_sparsity_penalty",
    "compute_aesthetics_scores",
    "compute_presentation_diagnostics",
    "mean_scores_by_dimension",
    "redundancy_score",
    "score_checklist_item",
    "score_generic_slide_checklist_items",
    "score_slide_checklist_item",
]
