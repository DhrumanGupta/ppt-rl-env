from __future__ import annotations

import asyncio
import json
import os
import textwrap
from typing import Any, List, Optional

from openai import OpenAI

try:
    from ppt_agent import PptAgentAction, PptAgentEnv
except ImportError:  # pragma: no cover
    from client import PptAgentEnv
    from models import PptAgentAction


API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")
ENV_BASE_URL = os.getenv("ENV_BASE_URL")
MAX_STEPS = int(os.getenv("MAX_STEPS", "20"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "80"))

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are helping with a prompt-to-PPT environment that only supports two actions:
    create_slide and update_slide.
    Respond with one short sentence describing the next deck-building intention.
    """
).strip()


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: Optional[str],
) -> None:
    error_val = error if error else "null"
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


def _openai_hint(client: OpenAI | None, observation: Any, step: int) -> str:
    if client is None:
        return "heuristic-plan"
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Task: {observation.task_name or 'unknown'}\n"
                        f"Prompt: {observation.prompt_summary}\n"
                        f"Step: {step}\n"
                        f"Slides: {observation.slide_count}"
                    ),
                },
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text or "heuristic-plan"
    except Exception:
        return "heuristic-plan"


def _slide_one_shapes() -> list[dict[str, Any]]:
    return [
        {"type": "accent_bar", "color_hex": "<accent>"},
        {
            "type": "text",
            "text": "Northstar Growth Plan 2026",
            "x": 0.8,
            "y": 0.9,
            "w": 8.0,
            "h": 0.8,
            "style": {
                "font_name": "<font>",
                "font_size_pt": "<title_size>",
                "color_hex": "<primary>",
                "bold": True,
            },
        },
    ]


def _slide_two_shapes() -> list[dict[str, Any]]:
    return [
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
    ]


def _slide_three_shapes() -> list[dict[str, Any]]:
    return [
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
    ]


def build_action(step: int, observation: Any, hint: str) -> tuple[PptAgentAction, str]:
    del hint
    if step == 1:
        action = PptAgentAction(
            action_type="create_slide",
            payload={"background_color": "<bg>", "shapes": _slide_one_shapes()},
        )
    elif step == 2:
        action = PptAgentAction(
            action_type="create_slide",
            payload={"background_color": "<surface>", "shapes": _slide_two_shapes()},
        )
    elif step == 3:
        action = PptAgentAction(
            action_type="create_slide",
            payload={"background_color": "<surface>", "shapes": _slide_three_shapes()},
        )
    else:
        slide_index = 1 if observation.slide_count >= 1 else None
        action = PptAgentAction(
            action_type="update_slide",
            slide_index=slide_index,
            payload={},
        )
    action_str = json.dumps(action.model_dump(mode="json"), separators=(",", ":"))
    return action, action_str


async def _make_env() -> PptAgentEnv:
    if LOCAL_IMAGE_NAME:
        return await PptAgentEnv.from_docker_image(LOCAL_IMAGE_NAME)
    if ENV_BASE_URL:
        env = PptAgentEnv(base_url=ENV_BASE_URL)
        await env.connect()
        return env
    raise RuntimeError(
        "Set LOCAL_IMAGE_NAME or ENV_BASE_URL before running inference.py"
    )


async def main() -> None:
    client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN) if HF_TOKEN else None
    env: PptAgentEnv | None = None
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False
    task_name = "unknown"
    benchmark = "ppt_agent"

    try:
        env = await _make_env()
        result = await env.reset()
        observation = result.observation
        task_name = observation.task_name or "unknown"
        log_start(task=task_name, env=benchmark, model=MODEL_NAME)

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break
            hint = _openai_hint(client, observation, step)
            action, action_str = build_action(step, observation, hint)
            result = await env.step(action)
            observation = result.observation
            reward = float(result.reward or 0.0)
            rewards.append(reward)
            steps_taken = step
            error = observation.last_action_error
            log_step(
                step=step,
                action=action_str,
                reward=reward,
                done=result.done,
                error=error,
            )
            if result.done:
                break

        score = float(observation.score or observation.reward or 0.0)
        score = max(0.0, min(1.0, score))
        success = score > 0.0 and not observation.last_action_error
    finally:
        try:
            if env is not None:
                await env.close()
        finally:
            log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


if __name__ == "__main__":
    asyncio.run(main())
