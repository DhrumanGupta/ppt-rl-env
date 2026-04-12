from __future__ import annotations

from typing import Any

import numpy as np

from .reward_metrics import clamp
from .reward_models import (
    ExtractedPresentation,
    ExtractedShape,
    ExtractedSlide,
)

_TEXT_SHAPE_KINDS = {"text", "citation"}


def _text_shapes(slide: ExtractedSlide) -> list[ExtractedShape]:
    return [
        shape
        for shape in slide.shapes
        if shape.shape_kind in _TEXT_SHAPE_KINDS and (shape.raw_text or "").strip()
    ]


def _shape_area(shape: ExtractedShape) -> float:
    return max(shape.w, 0.0) * max(shape.h, 0.0)


def _intersection_area(first: ExtractedShape, second: ExtractedShape) -> float:
    x_overlap = max(
        0.0,
        min(first.x + first.w, second.x + second.w) - max(first.x, second.x),
    )
    y_overlap = max(
        0.0,
        min(first.y + first.h, second.y + second.h) - max(first.y, second.y),
    )
    return x_overlap * y_overlap


def _visible_area_ratio(
    shape: ExtractedShape,
    *,
    slide_width_in: float,
    slide_height_in: float,
) -> float:
    area = _shape_area(shape)
    if area <= 0 or slide_width_in <= 0 or slide_height_in <= 0:
        return 0.0
    visible_width = max(
        0.0,
        min(shape.x + shape.w, slide_width_in) - max(shape.x, 0.0),
    )
    visible_height = max(
        0.0,
        min(shape.y + shape.h, slide_height_in) - max(shape.y, 0.0),
    )
    return clamp((visible_width * visible_height) / area)


def _word_count(text: str) -> int:
    return len([token for token in text.split() if token.strip()])


def _shape_font_size_pt(shape: ExtractedShape) -> float | None:
    font_sizes = [
        size
        for block in shape.text_blocks
        for size in block.font_sizes_pt
        if size is not None and size > 0
    ]
    return max(font_sizes) if font_sizes else None


def _estimate_line_count(text: str, *, chars_per_line: int) -> int:
    if chars_per_line <= 0:
        return max(len(text.splitlines()), 1)
    total_lines = 0
    for paragraph in text.splitlines() or [text]:
        stripped = paragraph.strip()
        if not stripped:
            total_lines += 1
            continue
        words = stripped.split()
        line_length = 0
        paragraph_lines = 1
        for word in words:
            word_length = len(word)
            if line_length == 0:
                line_length = word_length
                continue
            if line_length + 1 + word_length <= chars_per_line:
                line_length += 1 + word_length
                continue
            paragraph_lines += 1
            line_length = word_length
        total_lines += paragraph_lines
    return max(total_lines, 1)


def _fit_score(shape: ExtractedShape) -> float:
    text = (shape.raw_text or "").strip()
    if not text:
        return 1.0
    font_size_pt = _shape_font_size_pt(shape)
    if font_size_pt is None:
        return 1.0
    width_pt = max(shape.w * 72.0, 1.0)
    height_pt = max(shape.h * 72.0, 1.0)
    avg_char_width_pt = max(font_size_pt * 0.52, 1.0)
    line_height_pt = max(font_size_pt * 1.2, 1.0)
    chars_per_line = max(int(width_pt / avg_char_width_pt), 1)
    available_lines = max(height_pt / line_height_pt, 0.25)
    required_lines = float(_estimate_line_count(text, chars_per_line=chars_per_line))
    if required_lines <= available_lines:
        return 1.0
    return clamp(available_lines / required_lines)


def compute_slide_text_layout_scores(
    slide: ExtractedSlide,
    *,
    config: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    config = config or {
        "target_words": 80,
        "hard_max_words": 140,
        "max_overlap_tolerance_ratio": 0.0,
        "hard_max_overlap_ratio": 0.15,
        "clip_hard_cap": 0.05,
        "overlap_hard_cap": 0.05,
    }
    weights = weights or {
        "bounds": 0.4,
        "density": 0.3,
        "overlap": 0.3,
    }

    slide_width_in = float(slide.metadata.get("slide_width_in") or 0.0)
    slide_height_in = float(slide.metadata.get("slide_height_in") or 0.0)
    text_shapes = _text_shapes(slide)
    word_count = sum(_word_count(shape.raw_text or "") for shape in text_shapes)

    if not text_shapes:
        return {
            "text_layout": 1.0,
            "text_bounds": 1.0,
            "text_density": 1.0,
            "text_overlap": 1.0,
            "available": True,
            "word_count_text_shapes": 0,
            "text_shape_count": 0,
            "cropped_text_shape_count": 0,
            "max_text_overlap_ratio": 0.0,
            "overlapping_text_pair_count": 0,
            "cropped_shape_ids": [],
            "overlapping_shape_pairs": [],
        }

    visible_ratios = [
        _visible_area_ratio(
            shape,
            slide_width_in=slide_width_in,
            slide_height_in=slide_height_in,
        )
        for shape in text_shapes
    ]
    fit_scores = [_fit_score(shape) for shape in text_shapes]
    bounds_shape_scores = [
        min(visible_ratio, fit_score)
        for visible_ratio, fit_score in zip(visible_ratios, fit_scores, strict=True)
    ]
    bounds_score = (
        clamp(float(np.mean(bounds_shape_scores))) if bounds_shape_scores else 1.0
    )
    out_of_bounds_shape_ids = [
        shape.shape_id
        for shape, visible_ratio in zip(text_shapes, visible_ratios, strict=True)
        if visible_ratio < 0.999
    ]
    overflowing_shape_ids = [
        shape.shape_id
        for shape, fit_score in zip(text_shapes, fit_scores, strict=True)
        if fit_score < 0.999
    ]
    cropped_shape_ids = sorted(set(out_of_bounds_shape_ids + overflowing_shape_ids))

    target_words = max(int(config.get("target_words", 80)), 0)
    hard_max_words = max(int(config.get("hard_max_words", 140)), target_words + 1)
    if word_count <= target_words:
        density_score = 1.0
    elif word_count >= hard_max_words:
        density_score = 0.0
    else:
        density_score = 1.0 - (
            (word_count - target_words) / (hard_max_words - target_words)
        )

    overlap_tolerance_ratio = max(
        float(config.get("max_overlap_tolerance_ratio", 0.0)),
        0.0,
    )
    hard_max_overlap_ratio = max(
        float(config.get("hard_max_overlap_ratio", 0.15)),
        overlap_tolerance_ratio + 1e-6,
    )
    overlap_ratios: list[float] = []
    overlapping_shape_pairs: list[dict[str, Any]] = []
    for index, first in enumerate(text_shapes):
        first_area = _shape_area(first)
        if first_area <= 0:
            continue
        for second in text_shapes[index + 1 :]:
            second_area = _shape_area(second)
            if second_area <= 0:
                continue
            overlap_area = _intersection_area(first, second)
            ratio = overlap_area / min(first_area, second_area)
            overlap_ratios.append(ratio)
            if ratio > overlap_tolerance_ratio:
                overlapping_shape_pairs.append(
                    {
                        "shape_ids": [first.shape_id, second.shape_id],
                        "overlap_ratio": ratio,
                    }
                )

    max_overlap_ratio = max(overlap_ratios, default=0.0)
    if max_overlap_ratio <= overlap_tolerance_ratio:
        overlap_score = 1.0
    elif max_overlap_ratio >= hard_max_overlap_ratio:
        overlap_score = 0.0
    else:
        overlap_score = 1.0 - (
            (max_overlap_ratio - overlap_tolerance_ratio)
            / (hard_max_overlap_ratio - overlap_tolerance_ratio)
        )

    text_layout = clamp(
        weights.get("bounds", 0.4) * bounds_score
        + weights.get("density", 0.3) * density_score
        + weights.get("overlap", 0.3) * overlap_score
    )
    hard_cap = 1.0
    if cropped_shape_ids:
        hard_cap = min(hard_cap, float(config.get("clip_hard_cap", 0.05)))
    if overlapping_shape_pairs:
        hard_cap = min(hard_cap, float(config.get("overlap_hard_cap", 0.05)))
    return {
        "text_layout": text_layout,
        "text_bounds": bounds_score,
        "text_density": clamp(density_score),
        "text_overlap": clamp(overlap_score),
        "hard_cap": clamp(hard_cap),
        "available": slide_width_in > 0 and slide_height_in > 0,
        "word_count_text_shapes": word_count,
        "text_shape_count": len(text_shapes),
        "cropped_text_shape_count": len(cropped_shape_ids),
        "out_of_bounds_text_shape_count": len(out_of_bounds_shape_ids),
        "overflowing_text_shape_count": len(overflowing_shape_ids),
        "max_text_overlap_ratio": max_overlap_ratio,
        "overlapping_text_pair_count": len(overlapping_shape_pairs),
        "cropped_shape_ids": cropped_shape_ids,
        "out_of_bounds_shape_ids": out_of_bounds_shape_ids,
        "overflowing_shape_ids": overflowing_shape_ids,
        "overlapping_shape_pairs": overlapping_shape_pairs,
    }


def compute_presentation_text_layout_scores(
    extraction: ExtractedPresentation,
    *,
    config: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_slide = [
        {
            "slide_index": slide.slide_index,
            **compute_slide_text_layout_scores(slide, config=config, weights=weights),
        }
        for slide in extraction.slides
    ]
    if not per_slide:
        return {
            "text_layout": 0.0,
            "text_bounds": 0.0,
            "text_density": 0.0,
            "text_overlap": 0.0,
            "hard_cap": 0.0,
            "available": False,
            "slide_count": 0,
            "per_slide": [],
        }

    return {
        "text_layout": float(np.mean([item["text_layout"] for item in per_slide])),
        "text_bounds": float(np.mean([item["text_bounds"] for item in per_slide])),
        "text_density": float(np.mean([item["text_density"] for item in per_slide])),
        "text_overlap": float(np.mean([item["text_overlap"] for item in per_slide])),
        "hard_cap": float(min(item["hard_cap"] for item in per_slide)),
        "available": True,
        "slide_count": len(per_slide),
        "per_slide": per_slide,
        "deck_metrics": {
            "mean_word_count_text_shapes": float(
                np.mean([item["word_count_text_shapes"] for item in per_slide])
            ),
            "cropped_slide_count": sum(
                1 for item in per_slide if item["cropped_text_shape_count"] > 0
            ),
            "overlap_slide_count": sum(
                1 for item in per_slide if item["overlapping_text_pair_count"] > 0
            ),
        },
    }


__all__ = [
    "compute_presentation_text_layout_scores",
    "compute_slide_text_layout_scores",
]
