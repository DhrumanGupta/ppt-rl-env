from __future__ import annotations

from pathlib import Path

from models import PptAgentAction

from server.ppt_agent_environment import PptAgentEnvironment
from server.task_registry import DEFAULT_TASK_REGISTRY, TaskRegistry
from server.utils.reward_kernel import evaluate_presentation, evaluate_slide
from tests.reward.quizbank_test_utils import (
    DeterministicQuantitativeJudgeService,
    make_quizbank_service,
)


class NullRenderService:
    pass


def _single_scenario_registry() -> TaskRegistry:
    return TaskRegistry([DEFAULT_TASK_REGISTRY.get("northstar_growth_easy")])


def _slide_one_payload() -> dict:
    return {
        "background_color": "<bg>",
        "shapes": [
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
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
    }


def _slide_two_payload() -> dict:
    return {
        "background_color": "<surface>",
        "shapes": [
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
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
                "name": "body",
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
                "name": "citation",
                "text": "Source: Northstar plan memo",
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<caption_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    }


def _slide_three_payload() -> dict:
    return {
        "background_color": "<surface>",
        "shapes": [
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
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
                "name": "chart",
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
    }


def _make_env(max_steps: int = 3) -> PptAgentEnvironment:
    quiz_bank_service, _ = make_quizbank_service()
    return PptAgentEnvironment(
        max_steps=max_steps,
        task_registry=_single_scenario_registry(),
        quiz_bank_service=quiz_bank_service,
        quantitative_quiz_judge_service=DeterministicQuantitativeJudgeService(),
        render_service=NullRenderService(),
    )


def test_create_slide_step_uses_intermediate_reward() -> None:
    env = _make_env(max_steps=3)
    observation = env.reset(seed=7)

    assert observation.task_name == "northstar_growth_easy"
    assert observation.reward == 0.0
    assert observation.score == 0.0

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_one_payload())
    )

    assert observation.done is False
    assert observation.slide_count == 1
    assert observation.score == 0.0
    assert observation.last_action_result is not None
    assert observation.last_action_result["action_type"] == "create_slide"
    assert (
        observation.last_action_result["tool_result"]["named_shapes"]["title"]
        in observation.last_action_result["tool_result"]["shape_ids"]
    )

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_two_payload())
    )

    inspection = env._inspection_service.inspect_presentation(env._editor)
    expected = evaluate_slide(
        env._eval_spec,
        2,
        slide_extraction=inspection.slides[1],
        previous_slide_extractions=inspection.slides[:1],
    )

    assert observation.done is False
    assert observation.slide_count == 2
    assert observation.reward == expected.reward_total
    assert observation.score == 0.0


def test_reset_exposes_source_pack_brief_and_page_labeled_context() -> None:
    env = _make_env(max_steps=3)

    observation = env.reset(seed=7)

    assert "[Source Pack Brief]" in observation.source_context
    assert "Page 1:" in observation.source_context
    assert "| retail_memo]" in observation.source_context


def test_update_slide_returns_tool_metadata_for_agent_followup() -> None:
    env = _make_env(max_steps=5)
    env.reset(seed=7)

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_one_payload())
    )
    assert observation.last_action_result is not None
    created = observation.last_action_result["tool_result"]

    observation = env.step(
        PptAgentAction(
            action_type="update_slide",
            slide_index=1,
            payload={
                "update_shapes": [
                    {
                        "shape_id": created["named_shapes"]["title"],
                        "type": "text",
                        "name": "title",
                        "text": "Northstar Growth Plan 2026 Updated",
                    }
                ],
                "add_shapes": [
                    {
                        "type": "text",
                        "name": "summary",
                        "text": "Added in update step.",
                        "x": 0.9,
                        "y": 1.8,
                        "w": 5.0,
                        "h": 0.8,
                        "style": {
                            "font_name": "<font>",
                            "font_size_pt": "<body_size>",
                            "color_hex": "<secondary>",
                        },
                    }
                ],
            },
        )
    )

    update_result = observation.last_action_result

    assert observation.done is False
    assert update_result is not None
    assert update_result["action_type"] == "update_slide"
    assert (
        created["named_shapes"]["title"]
        in update_result["tool_result"]["updated_shape_ids"]
    )
    assert "summary" in update_result["tool_result"]["named_shapes"]
    assert (
        update_result["tool_result"]["named_shapes"]["summary"]
        in update_result["tool_result"]["created_shape_ids"]
    )


def test_delete_slide_returns_zero_reward_and_deletes_slide() -> None:
    env = _make_env(max_steps=5)
    env.reset(seed=7)

    env.step(PptAgentAction(action_type="create_slide", payload=_slide_one_payload()))
    env.step(PptAgentAction(action_type="create_slide", payload=_slide_two_payload()))

    observation = env.step(PptAgentAction(action_type="delete_slide", slide_index=1))

    delete_result = observation.last_action_result

    assert observation.done is False
    assert observation.reward == 0.0
    assert observation.slide_count == 1
    assert delete_result is not None
    assert delete_result["action_type"] == "delete_slide"
    assert delete_result["tool_result"]["deleted_slide_index"] == 1
    assert delete_result["tool_result"]["remaining_slide_count"] == 1


def test_terminal_step_uses_full_presentation_reward() -> None:
    env = _make_env(max_steps=3)
    env.reset(seed=7)

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_one_payload())
    )
    assert observation.done is False

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_two_payload())
    )
    assert observation.done is False

    observation = env.step(
        PptAgentAction(action_type="create_slide", payload=_slide_three_payload())
    )

    expected = evaluate_presentation(
        env._eval_spec,
        env._editor,
        render_service=env._render_service,
        inspection_service=env._inspection_service,
        quantitative_quiz_judge_service=env._quantitative_quiz_judge_service,
    )

    assert observation.done is True
    assert observation.slide_count == 3
    assert observation.reward == expected.reward_total
    assert observation.score == observation.reward


def test_save_presentation_writes_file_and_finishes_episode(tmp_path: Path) -> None:
    env = _make_env(max_steps=20)
    env.reset(seed=7)

    env.step(PptAgentAction(action_type="create_slide", payload=_slide_one_payload()))
    env.step(PptAgentAction(action_type="create_slide", payload=_slide_two_payload()))
    env.step(PptAgentAction(action_type="create_slide", payload=_slide_three_payload()))

    output_path = tmp_path / "saved_deck.pptx"
    observation = env.step(
        PptAgentAction(
            action_type="save_presentation",
            payload={"path": str(output_path)},
        )
    )

    expected = evaluate_presentation(
        env._eval_spec,
        env._editor,
        render_service=env._render_service,
        inspection_service=env._inspection_service,
        quantitative_quiz_judge_service=env._quantitative_quiz_judge_service,
    )

    assert observation.done is True
    assert observation.termination_reason == "presentation_saved"
    assert observation.last_action_result is not None
    assert observation.last_action_result["action_type"] == "save_presentation"
    assert observation.last_action_result["tool_result"]["path"] == str(
        output_path.resolve()
    )
    assert output_path.exists()
    assert observation.reward == expected.reward_total
    assert observation.score == expected.reward_total
