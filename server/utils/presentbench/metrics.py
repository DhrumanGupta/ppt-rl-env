from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from ..reward_metrics import (
    clamp,
    compute_overlap_ratio,
    deck_text_corpus,
    extract_numbers,
    is_blank_or_title_only,
    normalize_text,
    slide_text_corpus,
    text_match_score,
)
from ..reward_models import (
    ChecklistItem,
    ExtractedPresentation,
    ExtractedShape,
    ExtractedSlide,
    TaskSpec,
)

_TEXTUAL_SHAPE_KINDS = {"text", "citation"}
_MINIMAL_STALENESS_ROLES = {"title", "agenda"}
_MODERATE_STALENESS_ROLES = {"summary", "conclusion"}
_STALENESS_ROLE_PROFILES = {
    "minimal": {
        "target_occupied_area_ratio": 0.06,
        "target_body_word_count": 4,
        "target_shape_count": 2,
        "target_visual_anchor_count": 0,
        "minimum_title_font_pt": 24.0,
        "role_weights": {
            "structural_thinness": 0.35,
            "hierarchy_weakness": 0.40,
            "visual_flatness": 0.25,
        },
    },
    "moderate": {
        "target_occupied_area_ratio": 0.10,
        "target_body_word_count": 10,
        "target_shape_count": 3,
        "target_visual_anchor_count": 1,
        "minimum_title_font_pt": 24.0,
        "role_weights": {
            "structural_thinness": 0.40,
            "hierarchy_weakness": 0.30,
            "visual_flatness": 0.30,
        },
    },
    "standard": {
        "target_occupied_area_ratio": 0.14,
        "target_body_word_count": 18,
        "target_shape_count": 4,
        "target_visual_anchor_count": 1,
        "minimum_title_font_pt": 24.0,
        "role_weights": {
            "structural_thinness": 0.40,
            "hierarchy_weakness": 0.25,
            "visual_flatness": 0.35,
        },
    },
}


def _staleness_profile(role: str | None) -> tuple[str, dict[str, Any]]:
    normalized_role = normalize_text(role)
    if normalized_role in _MINIMAL_STALENESS_ROLES:
        return "minimal", _STALENESS_ROLE_PROFILES["minimal"]
    if normalized_role in _MODERATE_STALENESS_ROLES:
        return "moderate", _STALENESS_ROLE_PROFILES["moderate"]
    return "standard", _STALENESS_ROLE_PROFILES["standard"]


def _text_shapes(slide: ExtractedSlide) -> list[ExtractedShape]:
    return [
        shape
        for shape in slide.shapes
        if shape.shape_kind in _TEXTUAL_SHAPE_KINDS and (shape.raw_text or "").strip()
    ]


def _shape_word_count(shape: ExtractedShape | None) -> int:
    if shape is None or not shape.raw_text:
        return 0
    return len([token for token in shape.raw_text.split() if token.strip()])


def _shape_font_sizes(shape: ExtractedShape) -> list[float]:
    return [
        float(size)
        for block in shape.text_blocks
        for size in block.font_sizes_pt
        if size is not None and size > 0
    ]


def _shape_max_font_size(shape: ExtractedShape | None) -> float | None:
    if shape is None:
        return None
    font_sizes = _shape_font_sizes(shape)
    return max(font_sizes) if font_sizes else None


def _shape_text_colors(shape: ExtractedShape) -> set[str]:
    return {
        color.strip().upper()
        for block in shape.text_blocks
        for color in block.color_hexes
        if color
    }


def _shape_has_emphasis(shape: ExtractedShape) -> bool:
    for block in shape.text_blocks:
        if any(flag for flag in block.bold_flags if flag is not None):
            return True
        if any(flag for flag in block.italic_flags if flag is not None):
            return True
    return False


def _title_shape(
    slide: ExtractedSlide, text_shapes: list[ExtractedShape]
) -> ExtractedShape | None:
    if not text_shapes:
        return None
    title_text = normalize_text(slide.title_text)
    if title_text:
        title_matches = [
            shape
            for shape in text_shapes
            if normalize_text(shape.raw_text) == title_text
        ]
        if title_matches:
            return min(title_matches, key=lambda shape: (shape.y, shape.x))
    return min(text_shapes, key=lambda shape: (shape.y, shape.x))


def _slide_role_map(task_spec: TaskSpec) -> dict[int, str]:
    return {
        slide.slide_index: slide.slide_role for slide in task_spec.required_slides or []
    }


def _background_richness_score(background_rgb: tuple[int, int, int] | None) -> float:
    if background_rgb is None:
        return 0.5
    channel_spread = max(background_rgb) - min(background_rgb)
    mean_channel = sum(background_rgb) / 3.0
    if mean_channel >= 250.0 and channel_spread <= 4:
        return 0.0
    if mean_channel >= 242.0 and channel_spread <= 10:
        return 0.25
    if mean_channel >= 230.0 and channel_spread <= 18:
        return 0.5
    return 1.0


def compute_presentation_diagnostics(
    extraction: ExtractedPresentation,
    task_spec: TaskSpec,
) -> dict[str, Any]:
    role_map = _slide_role_map(task_spec)
    min_font_sizes = [
        slide.text_metrics.get("min_font_size_pt")
        for slide in extraction.slides
        if slide.text_metrics.get("min_font_size_pt") is not None
    ]
    overlap_ratios = [compute_overlap_ratio(slide) for slide in extraction.slides]
    blank_count = sum(1 for slide in extraction.slides if is_blank_or_title_only(slide))
    staleness = [
        compute_slide_staleness_penalty(
            slide,
            role=role_map.get(slide.slide_index),
        )["penalty"]
        for slide in extraction.slides
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
        "mean_staleness_penalty": (
            sum(staleness) / len(staleness) if staleness else 0.0
        ),
        "max_staleness_penalty": max(staleness) if staleness else 0.0,
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


def compute_slide_staleness_penalty(
    slide: ExtractedSlide,
    *,
    role: str | None = None,
) -> dict[str, Any]:
    profile_name, profile = _staleness_profile(role)
    text_shapes = _text_shapes(slide)
    title_shape = _title_shape(slide, text_shapes)
    body_shapes = [
        shape
        for shape in text_shapes
        if title_shape is None or shape.shape_id != title_shape.shape_id
    ]
    title_font_size = _shape_max_font_size(title_shape)
    body_font_sizes = [
        font_size
        for shape in body_shapes
        if (font_size := _shape_max_font_size(shape)) is not None
    ]
    body_font_size = float(median(body_font_sizes)) if body_font_sizes else None

    occupied_area_ratio = float(slide.layout_metrics.get("occupied_area_ratio", 0.0))
    shape_count = len(slide.shapes)
    total_word_count = len((slide_text_corpus(slide) or "").split())
    title_word_count = _shape_word_count(title_shape)
    body_word_count = max(total_word_count - title_word_count, 0)
    non_text_shape_count = sum(
        1 for shape in slide.shapes if shape.shape_kind not in _TEXTUAL_SHAPE_KINDS
    )
    rich_visual_count = (
        int(slide.layout_metrics.get("chart_count", 0))
        + int(slide.layout_metrics.get("table_count", 0))
        + int(slide.layout_metrics.get("image_count", 0))
    )
    background_rgb = _hex_to_rgb(slide.background_color_hex)
    background_richness = _background_richness_score(background_rgb)
    palette = slide.color_metrics.get("palette", [])
    palette_size = len(palette)
    background_hex = (slide.background_color_hex or "").strip().upper().lstrip("#")
    filled_shape_count = sum(
        1
        for shape in slide.shapes
        if shape.fill_color_hex
        and shape.fill_color_hex.strip().upper().lstrip("#") != background_hex
    )
    visual_anchor_count = rich_visual_count + filled_shape_count
    text_color_count = len(
        {color for shape in text_shapes for color in _shape_text_colors(shape)}
    )
    distinct_font_sizes = {
        round(font_size, 1)
        for shape in text_shapes
        for font_size in _shape_font_sizes(shape)
    }
    emphasized_shape_count = sum(
        1 for shape in text_shapes if _shape_has_emphasis(shape)
    )
    slide_height_in = float(slide.metadata.get("slide_height_in") or 0.0)
    title_top_score = 0.4
    if title_shape is not None and slide_height_in > 0:
        title_top_score = clamp(
            1.0 - (title_shape.y / max(slide_height_in * 0.35, 1e-6))
        )

    occupancy_score = clamp(occupied_area_ratio / profile["target_occupied_area_ratio"])
    body_content_score = clamp(
        body_word_count / max(float(profile["target_body_word_count"]), 1.0)
    )
    shape_score = clamp(shape_count / max(float(profile["target_shape_count"]), 1.0))
    target_anchor_count = float(profile["target_visual_anchor_count"])
    if target_anchor_count <= 0.0:
        anchor_score = 1.0 if visual_anchor_count > 0 else 0.7
    else:
        anchor_score = clamp(visual_anchor_count / target_anchor_count)
    structural_strength = clamp(
        0.35 * occupancy_score
        + 0.30 * body_content_score
        + 0.20 * shape_score
        + 0.15 * anchor_score
    )
    if profile_name == "minimal" and title_shape is not None and body_font_size is None:
        structural_strength = max(
            structural_strength, 0.75 if shape_count >= 1 else 0.6
        )
    structural_thinness = 1.0 - structural_strength

    if title_shape is None:
        size_contrast_score = 0.3
    elif body_font_size is None:
        size_contrast_score = clamp(
            ((title_font_size or 0.0) - float(profile["minimum_title_font_pt"])) / 8.0
        )
        if profile_name == "minimal":
            size_contrast_score = max(
                size_contrast_score, 0.85 if title_font_size else 0.5
            )
    else:
        size_gap = (title_font_size or 0.0) - body_font_size
        size_contrast_score = clamp((size_gap - 2.0) / 12.0)
    font_size_variety = clamp((len(distinct_font_sizes) - 1) / 2.0)
    text_color_variety = clamp((text_color_count - 1) / 2.0)
    style_variety_score = clamp(0.65 * font_size_variety + 0.35 * text_color_variety)
    if profile_name == "minimal" and body_font_size is None and title_font_size:
        style_variety_score = max(
            style_variety_score,
            clamp((title_font_size - float(profile["minimum_title_font_pt"])) / 6.0),
        )
    emphasis_score = clamp(
        0.60 * min(emphasized_shape_count, 1) + 0.40 * min(filled_shape_count, 1)
    )
    hierarchy_strength = clamp(
        0.45 * size_contrast_score
        + 0.25 * title_top_score
        + 0.15 * style_variety_score
        + 0.15 * emphasis_score
    )
    if profile_name == "minimal" and title_shape is not None and body_font_size is None:
        hierarchy_strength = max(hierarchy_strength, 0.75)
    hierarchy_weakness = 1.0 - hierarchy_strength

    palette_richness = clamp((palette_size - 2) / 3.0)
    text_color_richness = clamp((text_color_count - 1) / 2.0)
    anchor_richness = clamp(visual_anchor_count / 1.0)
    visual_energy = clamp(
        0.40 * anchor_richness
        + 0.25 * palette_richness
        + 0.20 * text_color_richness
        + 0.15 * background_richness
    )
    if profile_name == "minimal" and title_shape is not None and body_font_size is None:
        visual_energy = max(visual_energy, 0.45 + 0.20 * background_richness)
    visual_flatness = 1.0 - visual_energy

    role_weights = profile["role_weights"]
    penalty = clamp(
        role_weights["structural_thinness"] * structural_thinness
        + role_weights["hierarchy_weakness"] * hierarchy_weakness
        + role_weights["visual_flatness"] * visual_flatness
    )

    return {
        "penalty": penalty,
        "role": role,
        "role_profile": profile_name,
        "structural_thinness": structural_thinness,
        "hierarchy_weakness": hierarchy_weakness,
        "visual_flatness": visual_flatness,
        "occupied_area_ratio": occupied_area_ratio,
        "shape_count": shape_count,
        "body_word_count": body_word_count,
        "non_text_shape_count": non_text_shape_count,
        "rich_visual_count": rich_visual_count,
        "filled_shape_count": filled_shape_count,
        "visual_anchor_count": visual_anchor_count,
        "palette_size": palette_size,
        "text_color_count": text_color_count,
        "background_richness": background_richness,
        "plain_light_background": background_richness == 0.0,
        "title_font_size_pt": title_font_size,
        "body_font_size_pt": body_font_size,
        "title_top_score": title_top_score,
        "size_contrast_score": size_contrast_score,
        "style_variety_score": style_variety_score,
        "emphasis_score": emphasis_score,
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
    "compute_aesthetics_scores",
    "compute_presentation_diagnostics",
    "compute_slide_staleness_penalty",
    "mean_scores_by_dimension",
    "redundancy_score",
    "score_checklist_item",
    "score_generic_slide_checklist_items",
    "score_slide_checklist_item",
]
