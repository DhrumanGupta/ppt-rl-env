from __future__ import annotations

import asyncio
import json
import os
import re
import textwrap
from typing import Any

from openai import OpenAI

from agent_action_tools import (
    AgentToolInvocation,
    build_openai_tools,
    parse_tool_invocation,
    tool_invocation_to_action,
)

try:
    from ppt_agent import PptAgentAction, PptAgentEnv
except ImportError:  # pragma: no cover
    from client import PptAgentEnv
    from models import PptAgentAction


HF_TOKEN = os.getenv("HF_TOKEN")

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-27B")
ENV_BASE_URL = os.getenv("ENV_BASE_URL", "http://localhost:8000")
TASK_DIFFICULTY = os.getenv("TASK_DIFFICULTY", "easy")
MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))

BENCHMARK = "ppt_agent"

OPENAI_TOOLS = build_openai_tools()
print(len(str(OPENAI_TOOLS)))
quit()

_THEME_TOKENS = {
    "bg": "primary page background",
    "surface": "content surface background",
    "accent": "accent color",
    "primary": "primary text color",
    "secondary": "secondary text color",
    "font": "default font family",
    "title_size": "title font size",
    "body_size": "body font size",
    "caption_size": "caption font size",
}

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
    You are an expert PowerPoint author making a presentation to address the given task.

    Your input always includes:
    - the full task prompt from the environment
    - the source-pack context from the environment
    - the current slide count
    - the current max step budget
    - recent action history, including prior tool results and named shape ids when available

    Your job is to choose exactly one next environment tool call. Use the provided tools directly:
    - create_slide
    - update_slide
    - delete_slide
    - set_theme
    - save_presentation

    Theme tokens available inside payloads:
    - <bg>, <surface>, <accent>, <primary>, <secondary>
    - <font>, <title_size>, <body_size>, <caption_size>

    You may call set_theme to overwrite one or more default theme tokens for the whole deck.
    set_theme only updates these default keys:
    - bg, surface, accent, primary, secondary, font, title_size, body_size, caption_size
    Omitted keys remain unchanged.

    Use only the tool schema fields exactly as defined.
    Never invent shorthand slide DSL fields such as:
    - background -> use background_color
    - type: title/body -> use type: text
    - font -> use style.font_name
    - size -> use style.font_size_pt
    - color -> use style.color_hex

    Text shapes require explicit geometry in slide inches:
    - x, y, w, h

    Example create_slide payload:
    {
      "background_color": "<bg>",
      "shapes": [
        {
          "type": "text",
          "text": "Harbor Retail Expansion 2026",
          "x": 0.7,
          "y": 0.6,
          "w": 8.8,
          "h": 0.8,
          "style": {
            "font_name": "<font>",
            "font_size_pt": "<title_size>",
            "color_hex": "<primary>",
            "bold": true
          }
        }
      ]
    }

    Example set_theme payload:
    {
      "bg": "#F8FAFC",
      "surface": "#FFFFFF",
      "accent": "#2563EB",
      "primary": "#0F172A",
      "secondary": "#475569",
      "font": "Aptos",
      "title_size": 28,
      "body_size": 16,
      "caption_size": 10
    }

    Make the slides visually appealing and well-structured, and ensure the content addresses the task prompt effectively. This should include a good color scheme, readable fonts, and an appropriate amount of content per slide, with sufficient spacing.

    Always make discord theme dark presentations.

    Return no prose. Produce exactly one tool call.
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


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
                    continue
                if item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part)
    return str(content)


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


def _known_named_shapes_by_slide(
    history: list[dict[str, Any]],
) -> dict[int, dict[str, int]]:
    slide_shapes: dict[int, dict[str, int]] = {}

    for entry in history:
        if not isinstance(entry, dict):
            continue

        tool_name = entry.get("tool_name")
        slide_index = entry.get("slide_index")
        tool_result = entry.get("tool_result")
        if not isinstance(tool_result, dict):
            tool_result = {}

        named_shapes = tool_result.get("named_shapes")
        if not isinstance(named_shapes, dict):
            named_shapes = {}
        normalized_named_shapes = {
            name: shape_id
            for name, shape_id in named_shapes.items()
            if isinstance(name, str) and isinstance(shape_id, int)
        }

        if tool_name == "create_slide" and isinstance(slide_index, int):
            slide_shapes[slide_index] = dict(normalized_named_shapes)
            continue

        if tool_name == "update_slide" and isinstance(slide_index, int):
            current = slide_shapes.setdefault(slide_index, {})
            deleted_shape_ids = {
                shape_id
                for shape_id in tool_result.get("deleted_shape_ids") or []
                if isinstance(shape_id, int)
            }
            if deleted_shape_ids:
                current = {
                    name: shape_id
                    for name, shape_id in current.items()
                    if shape_id not in deleted_shape_ids
                }
            current.update(normalized_named_shapes)
            slide_shapes[slide_index] = current
            continue

        if tool_name == "delete_slide" and isinstance(slide_index, int):
            reindexed: dict[int, dict[str, int]] = {}
            for existing_index, existing_shapes in slide_shapes.items():
                if existing_index < slide_index:
                    reindexed[existing_index] = existing_shapes
                elif existing_index > slide_index:
                    reindexed[existing_index - 1] = existing_shapes
            slide_shapes = reindexed

    return slide_shapes


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
            "last_action_result": observation.last_action_result,
            "max_steps": MAX_STEPS,
            "target_slide_count_hint": _infer_target_slide_count(
                observation.task_prompt
            ),
            "recent_actions": history[-5:],
            "known_named_shapes_by_slide": _known_named_shapes_by_slide(history),
            "requirements": {
                "save_path": _default_output_path(
                    observation.task_name, observation.difficulty
                ),
                "supported_tools": [
                    "create_slide",
                    "update_slide",
                    "delete_slide",
                    "set_theme",
                    "save_presentation",
                ],
                "theme_tokens": _THEME_TOKENS,
                "current_theme": observation.metadata.get("current_theme", {}),
            },
        },
        separators=(",", ":"),
    )


def _validate_tool_choice(invocation: AgentToolInvocation, observation: Any) -> None:
    if invocation.tool_name == "save_presentation":
        target_slide_count = _infer_target_slide_count(observation.task_prompt)
        if (
            target_slide_count is not None
            and observation.slide_count < target_slide_count
        ):
            raise ValueError("cannot save before reaching the requested slide count")
        return

    if invocation.tool_name in {"update_slide", "delete_slide"}:
        slide_index = invocation.arguments.get("slide_index")
        if not isinstance(slide_index, int):
            raise ValueError(f"{invocation.tool_name} requires slide_index")
        if slide_index > observation.slide_count:
            raise ValueError(
                f"slide_index {slide_index} is out of range for {observation.slide_count} slides"
            )


def _extract_tool_invocation(
    message: Any,
) -> tuple[AgentToolInvocation, dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        if len(tool_calls) != 1:
            raise ValueError("LLM must emit exactly one tool call")
        tool_call = tool_calls[0]
        function = getattr(tool_call, "function", None)
        tool_name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None) or "{}"
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Tool call missing function name")
        return (
            parse_tool_invocation(tool_name, arguments),
            {"tool_name": tool_name, "arguments": arguments},
        )

    raw = _extract_message_text(getattr(message, "content", None))
    payload = _extract_json_object(raw)
    tool_name = payload.get("tool_name")
    arguments = payload.get("arguments")
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        raise ValueError("LLM must emit exactly one tool call")
    return (
        parse_tool_invocation(tool_name, arguments),
        {"tool_name": tool_name, "arguments": arguments},
    )


def _action_log_payload(action: PptAgentAction) -> str:
    return json.dumps(
        {
            "action_type": action.action_type,
            "slide_index": action.slide_index,
            "payload": action.payload,
        },
        separators=(",", ":"),
    )


def _history_entry_from_tool_call(
    invocation: AgentToolInvocation, observation: Any
) -> dict[str, Any]:
    slide_index: int | None = None
    if (
        invocation.tool_name == "create_slide"
        and observation.last_action_result is not None
    ):
        slide_index = observation.slide_count
    elif invocation.tool_name in {"update_slide", "delete_slide"}:
        slide_index = invocation.arguments.get("slide_index")

    tool_result: dict[str, Any] | None = None
    if isinstance(observation.last_action_result, dict):
        raw_tool_result = observation.last_action_result.get("tool_result")
        if isinstance(raw_tool_result, dict):
            tool_result = raw_tool_result

    return {
        "tool_name": invocation.tool_name,
        "arguments": invocation.arguments,
        "slide_index": slide_index,
        "tool_result": tool_result,
        "error": observation.last_action_error,
    }


def choose_action(
    client: OpenAI, observation: Any, history: list[dict[str, Any]]
) -> tuple[PptAgentAction, str, AgentToolInvocation]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _planning_prompt(observation, history)},
    ]
    raw_response: dict[str, Any] | None = None

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            tools=OPENAI_TOOLS,
            tool_choice="required",
        )
        message = completion.choices[0].message
        invocation, raw_response = _extract_tool_invocation(message)
        _validate_tool_choice(invocation, observation)
        action = tool_invocation_to_action(
            invocation,
            default_save_path=_default_output_path(
                observation.task_name,
                observation.difficulty,
            ),
        )
        return action, _action_log_payload(action), invocation
    except Exception as error:
        print(f"[DEBUG] choose_action failed: {error}", flush=True)
        if raw_response is not None:
            print(
                "[DEBUG] choose_action response="
                + json.dumps(raw_response, separators=(",", ":")),
                flush=True,
            )
        raise


async def main() -> None:
    if HF_TOKEN is None:
        raise ValueError("HF_TOKEN environment variable is required")

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
                # choose_action performs a synchronous model request. Keep it off
                # the event loop so websocket heartbeat traffic can still flow.
                action, action_str, invocation = await asyncio.to_thread(
                    choose_action,
                    client,
                    observation,
                    history,
                )
                result = await env.step(action)
                observation = result.observation
                reward = float(result.reward or 0.0)
                rewards.append(reward)
                history.append(_history_entry_from_tool_call(invocation, observation))
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
