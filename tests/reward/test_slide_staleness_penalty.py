from __future__ import annotations

from unittest.mock import patch

from ppt_agent.server.utils.pptx_extraction import PptxExtractionService
from ppt_agent.server.utils.pptx_functions import PptxEditor
from ppt_agent.server.utils.presentbench.metrics import compute_slide_staleness_penalty
from ppt_agent.server.utils.reward_kernel import (
    build_eval_spec,
    evaluate_presentation,
    evaluate_slide,
)
from ppt_agent.server.utils.reward_models import SourceDocument, SourcePack


class EmptyQuizBankService:
    def generate_quiz_bank(self, *, task_spec, source_pack, mode="eval"):
        del task_spec, source_pack, mode
        return [], {"stage": "empty"}


class NoopQuantJudge:
    def judge_quantitative_questions(
        self, *, task_spec, presentation_extraction, questions
    ):
        del task_spec, presentation_extraction, questions
        return {}, {"stage": "empty"}


def _local_match(candidate: str | None, requirement: str | None) -> float:
    candidate_words = set((candidate or "").lower().replace(".", "").split())
    requirement_words = set((requirement or "").lower().replace(".", "").split())
    if not candidate_words or not requirement_words:
        return 0.0
    if requirement_words.issubset(candidate_words):
        return 1.0
    return len(candidate_words & requirement_words) / len(requirement_words)


def _make_source_pack() -> SourcePack:
    return SourcePack(
        task_id="slide-staleness",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Memo",
                path=None,
                mime_type="text/plain",
                text=(
                    "Retention improved from 88% to 93%. "
                    "Northstar results summary with source-backed operating context."
                ),
                pages=None,
                images=None,
                metadata={},
            )
        ],
        metadata={},
    )


def _make_eval_spec():
    return build_eval_spec(
        (
            "Create a one-slide presentation.\n"
            "Slide 1: Results covering retention improved from 88% to 93%."
        ),
        _make_source_pack(),
        quiz_bank_service=EmptyQuizBankService(),
    )


def _make_stale_white_editor() -> PptxEditor:
    editor = PptxEditor()
    slide_id = editor.get_slide_id(editor.add_slide())
    editor.set_slide_background_by_id(slide_id, "FFFFFF")
    title_id = editor.add_textbox_by_id(slide_id, 0.8, 0.8, 8.0, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.9, 7.0, 1.0)
    editor.insert_text_by_id(slide_id, title_id, "Results")
    editor.insert_text_by_id(slide_id, body_id, "Retention improved from 88% to 93%.")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=28, color_hex="000000")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=20, color_hex="000000")
    return editor


def _make_stale_tinted_editor() -> PptxEditor:
    editor = PptxEditor()
    slide_id = editor.get_slide_id(editor.add_slide())
    editor.set_slide_background_by_id(slide_id, "EEF3FA")
    title_id = editor.add_textbox_by_id(slide_id, 0.8, 0.8, 8.0, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.9, 7.0, 1.0)
    editor.insert_text_by_id(slide_id, title_id, "Results")
    editor.insert_text_by_id(slide_id, body_id, "Retention improved from 88% to 93%.")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=24, color_hex="1F2937")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=20, color_hex="1F2937")
    return editor


def _make_flat_hierarchy_editor() -> PptxEditor:
    editor = PptxEditor()
    slide_id = editor.get_slide_id(editor.add_slide())
    editor.set_slide_background_by_id(slide_id, "EEF3FA")
    title_id = editor.add_textbox_by_id(slide_id, 0.8, 0.8, 5.8, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.9, 6.8, 1.3)
    foot_id = editor.add_textbox_by_id(slide_id, 0.9, 3.4, 5.2, 0.7)
    editor.insert_text_by_id(slide_id, title_id, "Results")
    editor.insert_text_by_id(
        slide_id,
        body_id,
        "Retention improved from 88% to 93%. Northstar results summary.",
    )
    editor.insert_text_by_id(slide_id, foot_id, "Source-backed operating context")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=20, color_hex="334155")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=20, color_hex="334155")
    editor.style_text_by_id(slide_id, foot_id, font_size_pt=20, color_hex="334155")
    return editor


def _make_designed_editor() -> PptxEditor:
    editor = PptxEditor()
    slide_id = editor.get_slide_id(editor.add_slide())
    editor.set_slide_background_by_id(slide_id, "F6F8FC")
    title_id = editor.add_textbox_by_id(slide_id, 0.8, 0.7, 5.0, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.8, 6.8, 1.2)
    accent_id = editor.add_textbox_by_id(slide_id, 0.9, 3.3, 3.2, 0.8)
    editor.insert_text_by_id(slide_id, title_id, "Results")
    editor.insert_text_by_id(
        slide_id,
        body_id,
        "Retention improved from 88% to 93%. Northstar results summary.",
    )
    editor.insert_text_by_id(slide_id, accent_id, "Source-backed")
    editor.style_shape_fill_by_id(slide_id, accent_id, fill_color_hex="1F4E79")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=28, color_hex="183153")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=20, color_hex="243B53")
    editor.style_text_by_id(slide_id, accent_id, font_size_pt=18, color_hex="FFFFFF")
    return editor


def _make_minimal_title_editor() -> PptxEditor:
    editor = PptxEditor()
    slide_id = editor.get_slide_id(editor.add_slide())
    editor.set_slide_background_by_id(slide_id, "F8FAFC")
    accent_id = editor.add_textbox_by_id(slide_id, 0.0, 0.0, 0.35, 7.5)
    title_id = editor.add_textbox_by_id(slide_id, 0.9, 1.0, 7.8, 0.9)
    editor.insert_text_by_id(slide_id, title_id, "Northstar Growth Plan 2026")
    editor.style_shape_fill_by_id(slide_id, accent_id, fill_color_hex="2563EB")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=30, color_hex="0F172A")
    return editor


def test_staleness_penalizes_tinted_stale_slides_not_just_white() -> None:
    extractor = PptxExtractionService()
    stale_white = extractor.inspect_presentation(_make_stale_white_editor()).slides[0]
    stale_tinted = extractor.inspect_presentation(_make_stale_tinted_editor()).slides[0]
    designed = extractor.inspect_presentation(_make_designed_editor()).slides[0]

    white_penalty = compute_slide_staleness_penalty(stale_white, role="result")
    tinted_penalty = compute_slide_staleness_penalty(stale_tinted, role="result")
    designed_penalty = compute_slide_staleness_penalty(designed, role="result")

    assert white_penalty["penalty"] > designed_penalty["penalty"]
    assert tinted_penalty["penalty"] > designed_penalty["penalty"]
    assert tinted_penalty["plain_light_background"] is False
    assert tinted_penalty["visual_flatness"] > designed_penalty["visual_flatness"]
    assert (
        tinted_penalty["structural_thinness"] > designed_penalty["structural_thinness"]
    )


def test_staleness_detects_weak_hierarchy() -> None:
    extractor = PptxExtractionService()
    flat_slide = extractor.inspect_presentation(_make_flat_hierarchy_editor()).slides[0]
    designed_slide = extractor.inspect_presentation(_make_designed_editor()).slides[0]

    flat_penalty = compute_slide_staleness_penalty(flat_slide, role="result")
    designed_penalty = compute_slide_staleness_penalty(designed_slide, role="result")

    assert flat_penalty["hierarchy_weakness"] > designed_penalty["hierarchy_weakness"]
    assert flat_penalty["visual_flatness"] > designed_penalty["visual_flatness"]
    assert flat_penalty["penalty"] > designed_penalty["penalty"]


def test_minimal_title_slide_gets_role_aware_leniency() -> None:
    extractor = PptxExtractionService()
    title_slide = extractor.inspect_presentation(_make_minimal_title_editor()).slides[0]

    title_penalty = compute_slide_staleness_penalty(title_slide, role="title")
    results_penalty = compute_slide_staleness_penalty(title_slide, role="result")

    assert title_penalty["role_profile"] == "minimal"
    assert results_penalty["role_profile"] == "standard"
    assert title_penalty["penalty"] < results_penalty["penalty"]


def test_staleness_penalty_reduces_intermediate_and_terminal_rewards() -> None:
    eval_spec = _make_eval_spec()
    extractor = PptxExtractionService()
    stale_editor = _make_stale_tinted_editor()
    designed_editor = _make_designed_editor()

    with patch("server.utils.presentbench.metrics.text_match_score", _local_match):
        stale_slide = extractor.inspect_presentation(stale_editor).slides[0]
        designed_slide = extractor.inspect_presentation(designed_editor).slides[0]
        stale_intermediate = evaluate_slide(eval_spec, 1, slide_extraction=stale_slide)
        designed_intermediate = evaluate_slide(
            eval_spec, 1, slide_extraction=designed_slide
        )
        stale_terminal = evaluate_presentation(
            eval_spec,
            stale_editor,
            inspection_service=extractor,
            quantitative_quiz_judge_service=NoopQuantJudge(),
        )
        designed_terminal = evaluate_presentation(
            eval_spec,
            designed_editor,
            inspection_service=extractor,
            quantitative_quiz_judge_service=NoopQuantJudge(),
        )

    assert stale_intermediate.soft_penalties["staleness"] > 0.0
    assert (
        stale_intermediate.soft_penalties["staleness"]
        > designed_intermediate.soft_penalties["staleness"]
    )
    assert stale_intermediate.metadata["staleness"]["visual_flatness"] > 0.0
    assert stale_intermediate.reward_total < designed_intermediate.reward_total
    assert stale_terminal.soft_penalties["staleness"] > 0.0
    assert stale_terminal.reward_total < designed_terminal.reward_total
