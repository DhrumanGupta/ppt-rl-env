from server.tools.pptx_tools import create_slide, register_theme
from server.utils.pptx_functions import PptxEditor
from server.utils.pptx_extraction import PptxExtractionService
from server.utils.reward_kernel import (
    build_eval_spec,
    compute_intermediate_slide_reward,
    compute_presentation_reward,
)
from server.utils.reward_models import SourceDocument, SourcePack

from tests.reward.quizbank_test_utils import make_quizbank_service


PROMPT = """
Create a factual three-slide presentation for a professional audience.
Slide 1: Title slide introducing Northstar Growth Plan 2026.
Slide 2: Results slide covering retention increased from 88% to 93% and onboarding time reduced by 35%, with a source citation.
Slide 3: Revenue chart slide showing quarterly target values 18, 24, 28, and 32.
""".strip()


def make_source_pack() -> SourcePack:
    return SourcePack(
        task_id="northstar-plan",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Northstar plan memo",
                path=None,
                mime_type="text/plain",
                text=(
                    "Northstar Growth Plan 2026 focuses on retention and onboarding. "
                    "Enterprise retention improved from 88% to 93%. "
                    "Guided automation reduced onboarding time by 35%. "
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
                ),
                pages=None,
                images=None,
                metadata={},
            )
        ],
        metadata={},
    )


def make_theme(editor: PptxEditor) -> None:
    register_theme(
        editor,
        {
            "bg": "#F8FAFC",
            "surface": "#FFFFFF",
            "accent": "#2563EB",
            "primary": "#0F172A",
            "secondary": "#475569",
            "font": "Aptos",
            "title_size": 28,
            "body_size": 16,
            "caption_size": 10,
        },
    )


def make_grounded_editor() -> PptxEditor:
    editor = PptxEditor()
    make_theme(editor)
    create_slide(
        editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Northstar Growth Plan 2026",
                "x": 0.8,
                "y": 0.9,
                "w": 8.0,
                "h": 0.7,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
        ],
    )
    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Results",
                "x": 0.8,
                "y": 0.8,
                "w": 3.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": 24,
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "text",
                "text": "Retention improved from 88% to 93%.\nOnboarding time reduced by 35%.",
                "x": 0.9,
                "y": 1.7,
                "w": 6.5,
                "h": 1.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
            {
                "type": "citation",
                "text": "Source: Northstar plan memo",
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<caption_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )
    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Revenue Targets",
                "x": 0.8,
                "y": 0.8,
                "w": 4.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": 24,
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "chart",
                "chart_type": "column_clustered",
                "chart_data": {
                    "categories": ["Q1", "Q2", "Q3", "Q4"],
                    "series": [{"name": "Target", "values": [18, 24, 28, 32]}],
                },
                "x": 0.9,
                "y": 1.6,
                "w": 6.8,
                "h": 3.8,
                "style": {
                    "title": "Quarterly revenue targets",
                    "series_colors": ["<accent>"],
                },
            },
        ],
    )
    return editor


def make_hallucinated_editor() -> PptxEditor:
    editor = PptxEditor()
    make_theme(editor)
    create_slide(
        editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Northstar Growth Plan 2026",
                "x": 0.8,
                "y": 0.9,
                "w": 8.0,
                "h": 0.7,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
        ],
    )
    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Results",
                "x": 0.8,
                "y": 0.8,
                "w": 3.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": 24,
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "text",
                "text": "Retention improved from 70% to 99%.\nOnboarding time reduced by 80%.",
                "x": 0.9,
                "y": 1.7,
                "w": 6.5,
                "h": 1.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )
    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Revenue Targets",
                "x": 0.8,
                "y": 0.8,
                "w": 4.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": 24,
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "chart",
                "chart_type": "column_clustered",
                "chart_data": {
                    "categories": ["Q1", "Q2", "Q3", "Q4"],
                    "series": [{"name": "Target", "values": [10, 20, 30, 50]}],
                },
                "x": 0.9,
                "y": 1.6,
                "w": 6.8,
                "h": 3.8,
                "style": {
                    "title": "Quarterly revenue targets",
                    "series_colors": ["<accent>"],
                },
            },
        ],
    )
    return editor


def test_build_eval_spec_is_deterministic_and_complete(tmp_path):
    source_pack = make_source_pack()
    first_service, _ = make_quizbank_service()
    second_service, _ = make_quizbank_service()

    first = build_eval_spec(
        PROMPT,
        source_pack,
        quiz_bank_service=first_service,
        cache_dir=str(tmp_path),
    )
    second = build_eval_spec(
        PROMPT,
        source_pack,
        quiz_bank_service=second_service,
        cache_dir=str(tmp_path),
    )

    assert first.spec_hash == second.spec_hash
    assert {item.dimension for item in first.presentbench.checklist} == {
        "fundamentals",
        "visual_layout",
        "completeness",
        "correctness",
        "fidelity",
    }
    assert [slide.slide_index for slide in first.task_spec.required_slides or []] == [
        1,
        2,
        3,
    ]


def test_inspection_extracts_supported_shape_kinds():
    editor = make_grounded_editor()
    inspection = PptxExtractionService().inspect_presentation(editor)

    shape_kinds = {
        shape.shape_kind for slide in inspection.slides for shape in slide.shapes
    }
    assert "accent_bar" in shape_kinds
    assert "text" in shape_kinds
    assert "citation" in shape_kinds
    assert "chart" in shape_kinds
    assert inspection.slide_count == 3


def test_grounded_deck_scores_higher_than_hallucinated_deck(tmp_path):
    source_pack = make_source_pack()
    grounded = make_grounded_editor()
    hallucinated = make_hallucinated_editor()
    grounded_service, _ = make_quizbank_service()
    hallucinated_service, _ = make_quizbank_service()

    grounded_result = compute_presentation_reward(
        PROMPT,
        source_pack,
        grounded,
        quiz_bank_service=grounded_service,
        cache_dir=str(tmp_path),
    )
    hallucinated_result = compute_presentation_reward(
        PROMPT,
        source_pack,
        hallucinated,
        quiz_bank_service=hallucinated_service,
        cache_dir=str(tmp_path),
    )

    assert grounded_result.reward_total > hallucinated_result.reward_total
    assert (
        grounded_result.hard_caps["C_fidelity_critical"]
        >= hallucinated_result.hard_caps["C_fidelity_critical"]
    )


def test_intermediate_slide_reward_prefers_correct_slot_content(tmp_path):
    source_pack = make_source_pack()
    editor = make_grounded_editor()
    inspection_service = PptxExtractionService()
    correct_slide = inspection_service.inspect_slide(2, presentation=editor)
    wrong_slide = inspection_service.inspect_slide(1, presentation=editor)
    correct_service, _ = make_quizbank_service()
    wrong_service, _ = make_quizbank_service()

    correct_result = compute_intermediate_slide_reward(
        PROMPT,
        source_pack,
        slide_index=2,
        slide_extraction=correct_slide,
        quiz_bank_service=correct_service,
        cache_dir=str(tmp_path),
    )
    wrong_result = compute_intermediate_slide_reward(
        PROMPT,
        source_pack,
        slide_index=2,
        slide_extraction=wrong_slide,
        quiz_bank_service=wrong_service,
        cache_dir=str(tmp_path),
    )

    assert correct_result.reward_total > wrong_result.reward_total
    assert (
        correct_result.reward_breakdown["S_prompt_alignment"]
        >= wrong_result.reward_breakdown["S_prompt_alignment"]
    )
