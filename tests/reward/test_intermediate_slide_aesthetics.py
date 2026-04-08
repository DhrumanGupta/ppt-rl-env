from server.utils.pptx_extraction import PptxExtractionService
from server.utils.pptx_functions import PptxEditor
from server.utils.rendering import PptxRenderService
from server.utils.reward_kernel import compute_intermediate_slide_reward
from server.utils.reward_models import SourceDocument, SourcePack


class EmptyQuizBankService:
    def generate_quiz_bank(self, *, task_spec, source_pack, mode="eval"):
        del task_spec, source_pack, mode
        return [], {"stage": "empty"}


def _make_source_pack() -> SourcePack:
    return SourcePack(
        task_id="intermediate-aesthetics",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Memo",
                path=None,
                mime_type="text/plain",
                text="Northstar overview and results. Retention improved from 88% to 93%.",
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
    editor.set_slide_background_by_id(slide_id, "F6F8FC")
    title_id = editor.add_textbox_by_id(slide_id, 0.7, 0.6, 8.2, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.8, 7.4, 1.2)
    editor.insert_text_by_id(slide_id, title_id, "Northstar Overview")
    editor.insert_text_by_id(slide_id, body_id, "Plan summary and audience context.")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=28, color_hex="183153")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=18, color_hex="243B53")

    slide_index = editor.add_slide()
    slide_id = editor.get_slide_id(slide_index)
    editor.set_slide_background_by_id(slide_id, "FFF9F0")
    title_id = editor.add_textbox_by_id(slide_id, 0.7, 0.6, 8.2, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.8, 7.4, 1.4)
    accent_id = editor.add_textbox_by_id(slide_id, 0.9, 3.6, 4.6, 0.8)
    editor.insert_text_by_id(slide_id, title_id, "Results")
    editor.insert_text_by_id(
        slide_id,
        body_id,
        "Retention improved from 88% to 93%.\nReadable summary with balanced spacing.",
    )
    editor.insert_text_by_id(slide_id, accent_id, "Momentum is improving")
    editor.style_shape_fill_by_id(slide_id, accent_id, fill_color_hex="1F4E79")
    editor.style_text_by_id(slide_id, title_id, font_size_pt=26, color_hex="5A2A00")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=18, color_hex="3E2C1C")
    editor.style_text_by_id(slide_id, accent_id, font_size_pt=20, color_hex="FFFFFF")

    slide_index = editor.add_slide()
    slide_id = editor.get_slide_id(slide_index)
    editor.set_slide_background_by_id(slide_id, "F3F7FB")
    title_id = editor.add_textbox_by_id(slide_id, 0.7, 0.6, 8.2, 0.8)
    body_id = editor.add_textbox_by_id(slide_id, 0.9, 1.8, 7.4, 1.2)
    editor.insert_text_by_id(slide_id, title_id, "Retention Summary")
    editor.insert_text_by_id(
        slide_id,
        body_id,
        "Northstar overview recap with retention improved from 88% to 93%.",
    )
    editor.style_text_by_id(slide_id, title_id, font_size_pt=26, color_hex="183153")
    editor.style_text_by_id(slide_id, body_id, font_size_pt=18, color_hex="243B53")
    return editor


def test_compute_intermediate_slide_reward_includes_rendered_slidesgenbench_aesthetics():
    source_pack = _make_source_pack()
    editor = _make_editor()
    extractor = PptxExtractionService()
    previous_slide_extraction = extractor.inspect_slide(1, presentation=editor)

    result = compute_intermediate_slide_reward(
        prompt=(
            "Create a two-slide presentation.\n"
            "Slide 1: Northstar Overview.\n"
            "Slide 2: Results covering retention improved from 88% to 93%."
        ),
        source_pack=source_pack,
        slide_index=2,
        presentation=editor,
        render_service=PptxRenderService(),
        inspection_service=extractor,
        previous_slide_extractions=[previous_slide_extraction],
        quiz_bank_service=EmptyQuizBankService(),
    )

    assert result.aesthetics_results
    assert result.metadata["used_rendered_slide_aesthetics"] is True
    assert result.reward_breakdown["S_slide_aesthetic"] > 0.0
    assert result.reward_breakdown["S_slide_harmony"] >= 0.0
    assert result.reward_breakdown["S_slide_rhythm"] >= 0.0
    assert (
        result.reward_breakdown["R_slide"]
        != result.reward_breakdown["R_slide_presentbench"]
    )


def test_compute_intermediate_slide_reward_scores_relevant_extra_slide() -> None:
    source_pack = _make_source_pack()
    editor = _make_editor()
    extractor = PptxExtractionService()
    previous_slide_extractions = [
        extractor.inspect_slide(1, presentation=editor),
        extractor.inspect_slide(2, presentation=editor),
    ]

    result = compute_intermediate_slide_reward(
        prompt=(
            "Create a two-slide presentation.\n"
            "Slide 1: Northstar Overview.\n"
            "Slide 2: Results covering retention improved from 88% to 93%."
        ),
        source_pack=source_pack,
        slide_index=3,
        presentation=editor,
        inspection_service=extractor,
        previous_slide_extractions=previous_slide_extractions,
        quiz_bank_service=EmptyQuizBankService(),
    )

    assert result.metadata["target_mode"] == "fallback_generic"
    assert result.reward_breakdown["R_slide_presentbench"] > 0.0
    assert result.reward_breakdown["S_prompt_alignment"] > 0.0
    assert result.reward_breakdown["S_local_fidelity"] == 1.0
    assert result.soft_penalties["wrong_slot_behavior"] == 0.0
    assert result.reward_total > 0.0
