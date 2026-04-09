from __future__ import annotations

import asyncio
import os
from pathlib import Path

from client import PptAgentEnv
from models import PptAgentAction


def _print_step(label: str, result) -> None:
    observation = result.observation
    print(label)
    print(f"  task: {observation.task_name}")
    print(f"  slides: {observation.slide_count}")
    print(f"  reward: {result.reward}")
    print(f"  score: {observation.score}")
    print(f"  done: {result.done}")
    print(f"  error: {observation.last_action_error}")
    print(f"  action_result: {observation.last_action_result}")
    print(f"  termination_reason: {observation.termination_reason}")
    print()


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


def _slide_one_update_payload(title_shape_id: int) -> dict:
    return {
        "update_shapes": [
            {
                "shape_id": title_shape_id,
                "type": "text",
                "name": "title",
                "text": "Northstar Growth Plan 2026 Updated",
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            }
        ],
        "add_shapes": [
            {
                "type": "text",
                "name": "summary",
                "text": "Professional deck generated through structured actions.",
                "x": 0.9,
                "y": 1.8,
                "w": 7.0,
                "h": 0.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            }
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


async def main() -> None:
    base_url = os.getenv("ENV_BASE_URL", "http://localhost:7860")
    env = PptAgentEnv(base_url=base_url, message_timeout_s=180.0)
    await env.connect()

    try:
        result = await env.reset()
        print("reset")
        print(f"  task: {result.observation.task_name}")
        print(f"  prompt: {result.observation.prompt_summary}")
        print()

        result = await env.step(
            PptAgentAction(action_type="create_slide", payload=_slide_one_payload())
        )
        _print_step("step 1: create slide 1", result)

        action_result = result.observation.last_action_result or {}
        tool_result = action_result.get("tool_result") or {}
        title_shape_id = tool_result.get("named_shapes", {}).get("title")
        if title_shape_id is not None:
            result = await env.step(
                PptAgentAction(
                    action_type="update_slide",
                    slide_index=1,
                    payload=_slide_one_update_payload(title_shape_id),
                )
            )
            _print_step("step 2: update slide 1", result)

        result = await env.step(
            PptAgentAction(action_type="create_slide", payload=_slide_two_payload())
        )
        _print_step("step 3: create slide 2", result)

        result = await env.step(
            PptAgentAction(action_type="create_slide", payload=_slide_three_payload())
        )
        _print_step("step 4: create slide 3", result)

        save_path = Path("outputs") / f"{result.observation.task_name}_client_test.pptx"
        if not result.done:
            result = await env.step(
                PptAgentAction(
                    action_type="save_presentation",
                    payload={"path": str(save_path)},
                )
            )
            _print_step("step 5: save presentation", result)

        if os.getenv("DEMO_DELETE_SLIDE") == "1" and not result.done:
            result = await env.step(
                PptAgentAction(action_type="delete_slide", slide_index=1)
            )
            _print_step("step 5: delete slide 1", result)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())
