from __future__ import annotations

import asyncio
import json
import os
import re
import textwrap
from typing import Any

from openai import OpenAI

try:
    from ppt_agent import PptAgentAction, PptAgentEnv
except ImportError:  # pragma: no cover
    from client import PptAgentEnv
    from models import PptAgentAction


HF_TOKEN = os.getenv("HF_TOKEN")
if HF_TOKEN is None:
    raise ValueError("HF_TOKEN environment variable is required")

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-27B")
ENV_BASE_URL = os.getenv("ENV_BASE_URL", "http://localhost:8000")
TASK_DIFFICULTY = os.getenv("TASK_DIFFICULTY", "easy")
MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))

BENCHMARK = "ppt_agent"

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an expert PowerPoint author operating a prompt-to-PPT benchmark.

    Your input always includes:
    - the full task prompt from the environment
    - the source-pack context from the environment
    - the current slide count
    - the current max step budget

    Your job is to decide the next deck-building action and provide only the content needed
    for that action. The number of slides is not fixed here: infer it from the task prompt.
    Use only information grounded in the provided source context.
    Keep the writing concise, professional, and presentation-ready.

    Presentation quality expectations:
    - Build a deck that reads like a polished consulting or executive review, not raw notes.
    - Give each slide a clear purpose and avoid repeating the same message across slides.
    - Prefer strong, informative slide titles over generic titles like "Overview" unless the prompt clearly calls for them.
    - Use short, high-signal bullets that highlight decisions, outcomes, comparisons, or implications.
    - Make the slide sequence feel intentional: opening context first, evidence and analysis in the middle, quantitative visuals where appropriate, then save.
    - When a metric or claim comes from the source pack, preserve the factual wording and numbers accurately.
    - Keep density reasonable. It is better to make an additional focused slide than to overload one slide.

    Examples of good presentation judgment:
    - Good: one clear headline, two or three supporting bullets, and enough whitespace for the slide to breathe.
    - Good: a chart slide with a specific takeaway title and only the data needed to support that takeaway.
    - Good: splitting two different ideas into separate slides when the prompt gives enough slide budget.
    - Bad: many bullet points packed tightly at the top while large empty areas remain below or to the side.
    - Bad: repeating the same title slide style and message multiple times instead of advancing the story.
    - Bad: turning every fact from the source pack into a bullet when a smaller number of sharper points would communicate better.
    - Bad: using a chart when there is no meaningful quantitative series to show.

    The environment also supports update_slide for targeted refinements to an existing slide.
    In this client, prefer create_slide for forward progress and save_presentation when complete.
    Avoid many update-style revisions; only make a refinement if there is a clear omission or correction that materially improves the deck.

    Return exactly one JSON object with this shape:
    {
      "action_type": "create_slide" | "save_presentation",
      "slide_kind": "title" | "bullets" | "chart" | null,
      "content": {...},
      "reason": "short explanation"
    }

    If action_type is create_slide, slide_kind must be one of:

    1. title
       content = {
         "title": "short title",
         "subtitle": "one concise subtitle"
       }

    2. bullets
       content = {
         "title": "slide title",
         "body_lines": ["fact line 1", "fact line 2"]
       }

    3. chart
       content = {
         "title": "chart slide title",
         "chart_title": "chart title",
         "categories": ["Q1", "Q2", "Q3", "Q4"],
         "series_name": "series label",
         "values": [1, 2, 3, 4]
        }

    If action_type is save_presentation:
    - set slide_kind to null
    - set content to {}

    Rules:
    - Return exactly one JSON object.
    - Do not wrap the JSON in markdown.
    - Do not invent facts that are not in the source context.
    - Keep slide titles short.
    - Make each new slide meaningfully different from prior slides.
    - For bullets, use 2 to 4 body_lines.
    - For chart, categories and values must have equal length.
    - Save only when the prompt requirements appear fully covered.
    - Prefer a small number of high-quality steps over many small revisions.
    - Use plain ASCII text.
    """
).strip()


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int, action: str, reward: float, done: bool, error: str | None
) -> None:
    error_value = (error or "null").replace("\n", " ")
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error={error_value}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


def _default_output_path(task_name: str, difficulty: str) -> str:
    safe_task = task_name or "presentation"
    safe_difficulty = difficulty or "unknown"
    return os.path.join("outputs", f"{safe_task}_{safe_difficulty}_inference.pptx")


def _infer_target_slide_count(task_prompt: str) -> int | None:
    lowered = task_prompt.lower()
    match = re.search(r"(\d+)\s*-?slide", lowered)
    if match:
        return int(match.group(1))
    for word, value in _NUMBER_WORDS.items():
        if f"{word}-slide" in lowered or f"{word} slide" in lowered:
            return value
    return None


def _planning_prompt(observation: Any, history: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task_name": observation.task_name,
            "difficulty": observation.difficulty,
            "task_prompt": observation.task_prompt,
            "source_context": observation.source_context,
            "prompt_summary": observation.prompt_summary,
            "slide_count": observation.slide_count,
            "last_action_error": observation.last_action_error,
            "max_steps": MAX_STEPS,
            "target_slide_count_hint": _infer_target_slide_count(
                observation.task_prompt
            ),
            "recent_slides": history[-5:],
            "requirements": {
                "save_path": _default_output_path(
                    observation.task_name, observation.difficulty
                ),
                "supported_slide_kinds": ["title", "bullets", "chart"],
                "allowed_action_types": ["create_slide", "save_presentation"],
            },
        },
        separators=(",", ":"),
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} must contain non-empty strings")
        normalized.append(item.strip())
    return normalized


def _require_number_list(payload: dict[str, Any], key: str) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{key} must contain numbers")
        normalized.append(float(item))
    return normalized


def _normalize_create_slide_payload(
    slide_kind: str, content: dict[str, Any]
) -> dict[str, Any]:
    if slide_kind == "title":
        return {
            "background_color": "<bg>",
            "shapes": [
                {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
                {
                    "type": "text",
                    "name": "title",
                    "text": _require_string(content, "title"),
                    "x": 0.8,
                    "y": 0.9,
                    "w": 8.2,
                    "h": 0.8,
                    "style": {
                        "font_name": "<font>",
                        "font_size_pt": "<title_size>",
                        "color_hex": "<primary>",
                        "bold": True,
                    },
                },
                {
                    "type": "text",
                    "name": "subtitle",
                    "text": _require_string(content, "subtitle"),
                    "x": 0.85,
                    "y": 1.9,
                    "w": 8.4,
                    "h": 0.9,
                    "style": {
                        "font_name": "<font>",
                        "font_size_pt": "<body_size>",
                        "color_hex": "<secondary>",
                    },
                },
            ],
        }

    if slide_kind == "bullets":
        body_lines = _require_string_list(content, "body_lines")[:4]
        return {
            "background_color": "<surface>",
            "shapes": [
                {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
                {
                    "type": "text",
                    "name": "title",
                    "text": _require_string(content, "title"),
                    "x": 0.8,
                    "y": 0.8,
                    "w": 3.8,
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
                    "text": "\n".join(f"- {line}" for line in body_lines),
                    "x": 0.9,
                    "y": 1.7,
                    "w": 7.2,
                    "h": 2.3,
                    "style": {
                        "font_name": "<font>",
                        "font_size_pt": "<body_size>",
                        "color_hex": "<secondary>",
                    },
                },
            ],
        }

    if slide_kind == "chart":
        categories = _require_string_list(content, "categories")
        values = _require_number_list(content, "values")
        if len(categories) != len(values):
            raise ValueError("categories and values must have the same length")
        return {
            "background_color": "<surface>",
            "shapes": [
                {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
                {
                    "type": "text",
                    "name": "title",
                    "text": _require_string(content, "title"),
                    "x": 0.8,
                    "y": 0.8,
                    "w": 4.8,
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
                        "categories": categories,
                        "series": [
                            {
                                "name": _require_string(content, "series_name"),
                                "values": values,
                            }
                        ],
                    },
                    "x": 0.9,
                    "y": 1.6,
                    "w": 7.0,
                    "h": 3.9,
                    "style": {
                        "title": _require_string(content, "chart_title"),
                        "series_colors": ["<accent>"],
                    },
                },
            ],
        }

    raise ValueError(f"Unsupported slide_kind '{slide_kind}'")


def _validate_payload_choice(
    payload: dict[str, Any], observation: Any, history: list[dict[str, Any]]
) -> None:
    action_type = payload.get("action_type")
    target_slide_count = _infer_target_slide_count(observation.task_prompt)

    if action_type == "save_presentation":
        if (
            target_slide_count is not None
            and observation.slide_count < target_slide_count
        ):
            raise ValueError("cannot save before reaching the requested slide count")
        return

    if action_type != "create_slide":
        raise ValueError("action_type must be create_slide or save_presentation")

    slide_kind = payload.get("slide_kind")
    if slide_kind == "title" and observation.slide_count > 0:
        raise ValueError("title slide should only be created first")

    used_slide_kinds = {
        entry.get("slide_kind")
        for entry in history
        if isinstance(entry, dict) and entry.get("action_type") == "create_slide"
    }
    if slide_kind == "chart" and "chart" in used_slide_kinds:
        raise ValueError("chart slide already created")


def _build_action(payload: dict[str, Any], observation: Any) -> PptAgentAction:
    action_type = payload.get("action_type")
    if action_type == "create_slide":
        slide_kind = payload.get("slide_kind")
        if not isinstance(slide_kind, str):
            raise ValueError("slide_kind must be a string for create_slide")
        content = payload.get("content")
        if not isinstance(content, dict):
            raise ValueError("content must be an object for create_slide")
        return PptAgentAction(
            action_type="create_slide",
            payload=_normalize_create_slide_payload(slide_kind, content),
        )
    if action_type == "save_presentation":
        return PptAgentAction(
            action_type="save_presentation",
            payload={
                "path": _default_output_path(
                    observation.task_name,
                    observation.difficulty,
                )
            },
        )
    raise ValueError(f"Unsupported action_type '{action_type}'")


def _action_log_payload(action: PptAgentAction) -> str:
    return json.dumps(
        {
            "action_type": action.action_type,
            "slide_index": action.slide_index,
            "payload": action.payload,
        },
        separators=(",", ":"),
    )


def _history_entry_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if not isinstance(content, dict):
        content = {}
    return {
        "action_type": payload.get("action_type"),
        "slide_kind": payload.get("slide_kind"),
        "title": content.get("title"),
        "reason": payload.get("reason"),
    }


def choose_action(
    client: OpenAI, observation: Any, history: list[dict[str, Any]]
) -> tuple[PptAgentAction, str, dict[str, Any]]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _planning_prompt(observation, history)},
    ]
    last_error: Exception | None = None

    for _ in range(3):
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or "{}"
            payload = _extract_json_object(raw)
            _validate_payload_choice(payload, observation, history)
            action = _build_action(payload, observation)
            return (
                action,
                _action_log_payload(action),
                _history_entry_from_payload(payload),
            )
        except Exception as error:
            last_error = error
            messages.append(
                {"role": "assistant", "content": raw if "raw" in locals() else "{}"}
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON was invalid for the requested stage. "
                        f"Error: {error}. Return one corrected JSON object only."
                    ),
                }
            )

    raise RuntimeError(f"LLM failed to produce valid stage content: {last_error}")


async def main() -> None:
    client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN)
    rewards: list[float] = []
    history: list[dict[str, Any]] = []
    steps_taken = 0
    score = 0.0
    success = False
    started = False

    try:
        async with PptAgentEnv(base_url=ENV_BASE_URL, message_timeout_s=180.0) as env:
            result = await env.reset(difficulty=TASK_DIFFICULTY)
            observation = result.observation
            log_start(
                task=observation.task_name or "unknown",
                env=BENCHMARK,
                model=MODEL_NAME,
            )
            started = True

            for step in range(1, MAX_STEPS + 1):
                if result.done:
                    break
                action, action_str, history_entry = choose_action(
                    client, observation, history
                )
                result = await env.step(action)
                observation = result.observation
                reward = float(result.reward or 0.0)
                rewards.append(reward)
                history.append(history_entry)
                steps_taken = step
                log_step(
                    step=step,
                    action=action_str,
                    reward=reward,
                    done=result.done,
                    error=observation.last_action_error,
                )
                if result.done:
                    break

            success = bool(
                started
                and result.done
                and not observation.last_action_error
                and observation.score > 0.0
            )
            score = float(observation.score or 0.0)
    except Exception as error:
        print(f"[DEBUG] inference failed: {error}", flush=True)
        success = False
    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


if __name__ == "__main__":
    asyncio.run(main())
