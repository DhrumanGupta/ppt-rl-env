from __future__ import annotations

from unittest.mock import patch

from server.utils.pptx_extraction import PptxExtractionService
from server.utils.pptx_functions import PptxEditor
from server.utils.reward_kernel import (
    build_eval_spec,
    evaluate_presentation,
    evaluate_slide,
)
from server.utils.reward_models import SourceDocument, SourcePack


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
        task_id="visual-sparsity",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Memo",
                path=None,
                mime_type="text/plain",
                text="Retention improved from 88% to 93%. Northstar results summary.",
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


def _make_sparse_white_editor() -> PptxEditor:
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


def _make_contentful_editor() -> PptxEditor:
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


def test_sparse_white_slide_is_penalized_in_intermediate_reward() -> None:
    eval_spec = _make_eval_spec()
    extractor = PptxExtractionService()
    sparse_editor = _make_sparse_white_editor()
    contentful_editor = _make_contentful_editor()

    with patch("server.utils.presentbench.metrics.text_match_score", _local_match):
        sparse_slide = extractor.inspect_presentation(sparse_editor).slides[0]
        contentful_slide = extractor.inspect_presentation(contentful_editor).slides[0]
        sparse_result = evaluate_slide(eval_spec, 1, slide_extraction=sparse_slide)
        contentful_result = evaluate_slide(
            eval_spec, 1, slide_extraction=contentful_slide
        )

    assert sparse_result.soft_penalties["visual_sparsity"] > 0.15
    assert (
        sparse_result.soft_penalties["visual_sparsity"]
        > contentful_result.soft_penalties["visual_sparsity"]
    )
    assert sparse_result.metadata["visual_sparsity"]["plain_light_background"] is True
    assert sparse_result.reward_total < contentful_result.reward_total


def test_sparse_white_slide_is_penalized_in_terminal_reward() -> None:
    eval_spec = _make_eval_spec()
    extractor = PptxExtractionService()
    sparse_editor = _make_sparse_white_editor()
    contentful_editor = _make_contentful_editor()

    with patch("server.utils.presentbench.metrics.text_match_score", _local_match):
        sparse_result = evaluate_presentation(
            eval_spec,
            sparse_editor,
            inspection_service=extractor,
            quantitative_quiz_judge_service=NoopQuantJudge(),
        )
        contentful_result = evaluate_presentation(
            eval_spec,
            contentful_editor,
            inspection_service=extractor,
            quantitative_quiz_judge_service=NoopQuantJudge(),
        )

    assert sparse_result.soft_penalties["visual_sparsity"] > 0.15
    assert (
        sparse_result.soft_penalties["visual_sparsity"]
        > contentful_result.soft_penalties["visual_sparsity"]
    )
    assert sparse_result.reward_total < contentful_result.reward_total
