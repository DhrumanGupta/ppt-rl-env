from __future__ import annotations

import re
from typing import Any


_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def grade_dummy_presentation(
    *, inspection: Any, task_spec: Any, action_count: int
) -> float:
    required_slide_count = len(task_spec.required_slides or []) or 1
    slide_coverage = min(inspection.slide_count / required_slide_count, 1.0)
    citation_score = (
        1.0
        if not task_spec.citation_required
        else float(inspection.deck_metrics.get("citation_count", 0) > 0)
    )
    quantitative_score = (
        1.0
        if not task_spec.require_quantitative_content
        else float(
            inspection.deck_metrics.get("chart_count", 0) > 0
            or inspection.deck_metrics.get("table_count", 0) > 0
            or any(
                _NUMBER_PATTERN.search(slide.all_text) for slide in inspection.slides
            )
        )
    )
    content_score = min(
        sum(
            1
            for slide in inspection.slides
            if slide.text_metrics.get("word_count", 0) > 0
        )
        / required_slide_count,
        1.0,
    )
    action_score = min(action_count / max(required_slide_count * 2, 1), 1.0)
    score = round(
        max(
            0.0,
            min(
                1.0,
                0.4 * slide_coverage
                + 0.2 * citation_score
                + 0.2 * quantitative_score
                + 0.1 * content_score
                + 0.1 * action_score,
            ),
        ),
        3,
    )
    return score


__all__ = ["grade_dummy_presentation"]
