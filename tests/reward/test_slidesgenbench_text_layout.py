from __future__ import annotations

from server.utils.pptx_extraction import PptxExtractionService
from server.utils.pptx_functions import PptxEditor
from server.utils.reward_kernel import compute_intermediate_slide_reward
from server.utils.reward_models import SourceDocument, SourcePack
from server.utils.slidesgenbench.text_layout import (
    compute_presentation_text_layout_scores,
    compute_slide_text_layout_scores,
)


class EmptyQuizBankService:
    def generate_quiz_bank(self, *, task_spec, source_pack, mode="eval"):
        del task_spec, source_pack, mode
        return [], {"stage": "empty"}


def _make_source_pack() -> SourcePack:
    return SourcePack(
        task_id="slidesgenbench-text-layout",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Memo",
                path=None,
                mime_type="text/plain",
                text="Northstar overview, results, and operating updates.",
                pages=None,
                images=None,
                metadata={},
            )
        ],
        metadata={},
    )


def _make_editor() -> PptxEditor:
    editor = PptxEditor()

    slide_index = editor.add_slide()
    slide_id = editor.get_slide_id(slide_index)
    good_title = editor.add_textbox_by_id(slide_id, 0.8, 0.6, 5.6, 0.7)
    good_body = editor.add_textbox_by_id(slide_id, 0.9, 1.7, 6.8, 1.4)
    editor.insert_text_by_id(slide_id, good_title, "Northstar Overview")
    editor.insert_text_by_id(
        slide_id,
        good_body,
        "Balanced summary with readable spacing and clear hierarchy.",
    )
    editor.style_text_by_id(slide_id, good_title, font_size_pt=28, color_hex="183153")
    editor.style_text_by_id(slide_id, good_body, font_size_pt=18, color_hex="243B53")

    slide_index = editor.add_slide()
    slide_id = editor.get_slide_id(slide_index)
    cropped_title = editor.add_textbox_by_id(slide_id, 0.8, 0.5, 3.8, 0.6)
    dense_body = editor.add_textbox_by_id(slide_id, 0.8, 1.6, 7.2, 1.4)
    overlapping_box = editor.add_textbox_by_id(slide_id, 1.2, 2.0, 4.5, 1.0)
    editor.insert_text_by_id(
        slide_id,
        cropped_title,
        "Harbor Retail Expansion 2026 Initiative Overview",
    )
    editor.insert_text_by_id(
        slide_id,
        dense_body,
        " ".join(f"word{index}" for index in range(180)),
    )
    editor.insert_text_by_id(
        slide_id,
        overlapping_box,
        "This box overlaps the dense body block.",
    )
    editor.style_text_by_id(
        slide_id, cropped_title, font_size_pt=24, color_hex="183153"
    )
    editor.style_text_by_id(slide_id, dense_body, font_size_pt=14, color_hex="243B53")
    editor.style_text_by_id(
        slide_id,
        overlapping_box,
        font_size_pt=16,
        color_hex="7C2D12",
    )
    return editor


def test_slide_text_layout_detects_crop_density_and_overlap() -> None:
    editor = _make_editor()
    extraction = PptxExtractionService().inspect_presentation(editor)

    good_slide_scores = compute_slide_text_layout_scores(extraction.slides[0])
    bad_slide_scores = compute_slide_text_layout_scores(extraction.slides[1])

    assert good_slide_scores["text_layout"] == 1.0
    assert good_slide_scores["cropped_text_shape_count"] == 0
    assert good_slide_scores["overlapping_text_pair_count"] == 0

    assert bad_slide_scores["text_bounds"] < 1.0
    assert bad_slide_scores["text_density"] == 0.0
    assert bad_slide_scores["text_overlap"] < 1.0
    assert bad_slide_scores["cropped_text_shape_count"] >= 1
    assert bad_slide_scores["overflowing_text_shape_count"] >= 1
    assert bad_slide_scores["overlapping_text_pair_count"] >= 1
    assert bad_slide_scores["hard_cap"] == 0.05


def test_presentation_text_layout_aggregates_per_slide_scores() -> None:
    editor = _make_editor()
    extraction = PptxExtractionService().inspect_presentation(editor)

    scores = compute_presentation_text_layout_scores(extraction)

    assert scores["available"] is True
    assert scores["slide_count"] == 2
    assert len(scores["per_slide"]) == 2
    assert scores["text_layout"] < 1.0
    assert scores["deck_metrics"]["cropped_slide_count"] == 1
    assert scores["deck_metrics"]["overlap_slide_count"] == 1


def test_intermediate_reward_includes_text_layout_without_rendering() -> None:
    source_pack = _make_source_pack()
    editor = _make_editor()
    extractor = PptxExtractionService()
    previous_slide_extraction = extractor.inspect_slide(1, presentation=editor)

    result = compute_intermediate_slide_reward(
        prompt=(
            "Create a two-slide presentation.\n"
            "Slide 1: Northstar Overview.\n"
            "Slide 2: Operating update with summary text."
        ),
        source_pack=source_pack,
        slide_index=2,
        presentation=editor,
        render_service=None,
        inspection_service=extractor,
        previous_slide_extractions=[previous_slide_extraction],
        quiz_bank_service=EmptyQuizBankService(),
    )

    assert result.metadata["used_rendered_slide_aesthetics"] is False
    assert result.reward_breakdown["S_slide_aesthetic"] == 0.0
    assert result.reward_breakdown["S_slide_text_layout"] < 1.0
    assert result.reward_breakdown["S_slide_text_bounds"] < 1.0
    assert result.reward_breakdown["S_slide_text_density"] == 0.0
    assert result.reward_breakdown["S_slide_text_overlap"] < 1.0
    assert result.reward_breakdown["C_slide_text_layout_hard"] == 0.05
    assert result.reward_total < 0.05
    assert result.metadata["text_layout"]["cropped_text_shape_count"] >= 1
    assert result.metadata["text_layout"]["overflowing_text_shape_count"] >= 1
