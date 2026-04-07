"""PEI (Presentation Editability Intelligence) knockout scoring.

L0-L5 levels per SlidesGen-Bench (Yang et al., 2026).
Failing a lower level precludes credit at higher ones.
"""

from __future__ import annotations

from typing import Any

from pptx.presentation import Presentation as PptxPresentation

from server.utils.pptx_functions import PptxEditor
from server.utils.pptx_extraction import open_presentation

PEI_LEVEL_REWARD: dict[int, float] = {
    0: 0.00,
    1: 0.20,
    2: 0.45,
    3: 0.70,
    4: 0.90,
    5: 1.00,
}


def _has_selectable_text(prs: PptxPresentation) -> bool:
    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                if (shape.text_frame.text or "").strip():
                    return True
    return False


def _text_is_not_fragmented(prs: PptxPresentation) -> bool:
    """At least 30% of non-empty text frames have multiple paragraphs."""
    multi = 0
    single = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            non_empty = [p for p in shape.text_frame.paragraphs if (p.text or "").strip()]
            if len(non_empty) > 1:
                multi += 1
            elif len(non_empty) == 1:
                single += 1
    total = multi + single
    return total > 0 and (multi / total) >= 0.3


def _has_vector_shapes(prs: PptxPresentation) -> bool:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "shape_type", None) in (
                MSO_SHAPE_TYPE.AUTO_SHAPE,
                MSO_SHAPE_TYPE.FREEFORM,
            ):
                return True
            if getattr(shape, "has_chart", False) or getattr(shape, "has_table", False):
                return True
    return False


def _has_slide_master_inheritance(prs: PptxPresentation) -> bool:
    """Slides use more than one layout (not just the default)."""
    if not prs.slide_masters or not prs.slide_layouts:
        return False
    layouts_used: set[str] = set()
    for slide in prs.slides:
        layout = getattr(slide, "slide_layout", None)
        if layout is not None:
            layouts_used.add(getattr(layout, "name", "") or "")
    return len(layouts_used) > 1


def _has_logical_grouping(prs: PptxPresentation) -> bool:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
                return True
    return False


def _has_native_chart_data(prs: PptxPresentation) -> bool:
    for slide in prs.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_chart", False):
                continue
            try:
                series = list(shape.chart.series)
                if series and list(series[0].values):
                    return True
            except Exception:
                continue
    return False


def _has_animation_or_media(prs: PptxPresentation) -> bool:
    ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    for slide in prs.slides:
        xml = slide._element
        for t in xml.findall(f"{{{ns}}}timing"):
            if t.findall(f".//{{{ns}}}seq"):
                return True
        if xml.findall(f"{{{ns}}}transition"):
            return True
        for shape in slide.shapes:
            if getattr(shape, "media_type", None) is not None:
                return True
    return False


def evaluate_pei_level(
    presentation: PptxEditor | PptxPresentation | str,
) -> dict[str, Any]:
    prs = open_presentation(presentation).presentation

    if not prs.slides or len(prs.slides) == 0:
        return {"pei_level": 0, "pei_reward": 0.0, "gate_results": {}}

    gates: dict[str, bool] = {}

    # L1: selectable, non-fragmented text
    has_text = _has_selectable_text(prs)
    not_fragmented = _text_is_not_fragmented(prs) if has_text else False
    gates["L1_selectable_text"] = has_text
    gates["L1_not_fragmented"] = not_fragmented
    if not has_text or not not_fragmented:
        level = 1 if has_text else 0
        return {"pei_level": level, "pei_reward": PEI_LEVEL_REWARD[level], "gate_results": gates}

    # L2: vector shapes
    gates["L2_vector_shapes"] = _has_vector_shapes(prs)
    if not gates["L2_vector_shapes"]:
        return {"pei_level": 1, "pei_reward": PEI_LEVEL_REWARD[1], "gate_results": gates}

    # L3: master inheritance AND grouping
    gates["L3_master_inheritance"] = _has_slide_master_inheritance(prs)
    gates["L3_logical_grouping"] = _has_logical_grouping(prs)
    if not (gates["L3_master_inheritance"] and gates["L3_logical_grouping"]):
        return {"pei_level": 2, "pei_reward": PEI_LEVEL_REWARD[2], "gate_results": gates}

    # L4: native chart data
    gates["L4_native_chart_data"] = _has_native_chart_data(prs)
    if not gates["L4_native_chart_data"]:
        return {"pei_level": 3, "pei_reward": PEI_LEVEL_REWARD[3], "gate_results": gates}

    # L5: animation or media
    try:
        gates["L5_animation_or_media"] = _has_animation_or_media(prs)
    except Exception:
        gates["L5_animation_or_media"] = False
    if not gates["L5_animation_or_media"]:
        return {"pei_level": 4, "pei_reward": PEI_LEVEL_REWARD[4], "gate_results": gates}

    return {"pei_level": 5, "pei_reward": PEI_LEVEL_REWARD[5], "gate_results": gates}


__all__ = ["PEI_LEVEL_REWARD", "evaluate_pei_level"]
