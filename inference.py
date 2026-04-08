from __future__ import annotations

import asyncio
import json
import os
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
MAX_STEPS = int(os.getenv("MAX_STEPS", "15"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

BENCHMARK = "ppt_agent"

OPENAI_TOOLS = build_openai_tools()

_FALLBACK_SAVE_PATH = "outputs/presentation.pptx"

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an elite presentation designer and PowerPoint author.

    Your job is to choose exactly one next environment tool call that moves the deck toward a polished, professional final presentation.

    You are given:
    - the full task prompt
    - the source context
    - the current slide count
    - the remaining step budget
    - the last action error/result
    - recent action history
    - known named shapes by slide
    - the current theme
    - slide constraints
    - the default save path

    Available tools:
    - create_slide
    - update_slide
    - delete_slide
    - set_theme
    - save_presentation

    Return no prose. Produce exactly one tool call.

    Presentation quality bar:
    - Make slides look like strong professional consulting, strategy, product, or investor decks.
    - Build a clear narrative, not a random collection of slides.
    - Each slide should have one main message.
    - Prefer strong hierarchy, clean alignment, generous whitespace, and restrained color usage.
    - Avoid clutter, overcrowded text, and weak visual balance.
    - Use charts or tables when they communicate evidence better than paragraphs.
    - Use concise text with meaningful headlines and clear supporting points.
    - Keep the design consistent across the whole deck.

    Design guidance:
    - Prefer a cohesive deck-level theme. Use set_theme early if the current theme is weak or mismatched to the task.
    - Use 1 primary accent color plus neutral background/text colors.
    - Keep typography consistent across slides.
    - Use accent color sparingly for emphasis, not everywhere.
    - Prefer readable layouts with clear margins and spacing.
    - Do not overfill slides; fewer stronger elements are better than many weak ones.
    - When using body text, keep it compact and readable.
    - Use word_wrap, space_before_pt, space_after_pt, and line_spacing when helpful for clean text layout.

    Content guidance:
    - Ground claims in the provided source context.
    - Do not invent facts, numbers, or citations not supported by the inputs.
    - If quantitative data is present, present it clearly and faithfully.
    - If the task implies a specific slide structure, satisfy it.
    - If slide constraints exist, do not save too early.

    Tool-use rules:
    - Use only the tool schema fields exactly as defined.
    - Never invent shorthand slide DSL fields such as:
      - background -> use background_color
      - type: title/body -> use type: text
      - font -> use style.font_name
      - size -> use style.font_size_pt
      - color -> use style.color_hex
    - Use the provided tools directly. Do not emit plans, explanations, or pseudo-actions.

    Shape rules:
    - Text shapes require explicit geometry in slide inches: x, y, w, h.
    - For new text shapes use type: text.
    - For accent bars use type: accent_bar.
    - For charts use type: chart with chart_type, chart_data, x, y, w, h.
    - For tables use type: table with table_data, x, y, w, h.
    - For images use type: image with image_path, x, y, and optional w, h.

    Update rules:
    - Use create_slide to add a new slide.
    - Use update_slide to revise an existing slide.
    - update_slide requires slide_index.
    - Existing shapes must be updated by shape_id.
    - Use known_named_shapes_by_slide and prior tool results to find the correct shape_id.
    - Only use delete_slide when a slide is clearly wrong, redundant, or should be removed.
    - Use save_presentation only when the deck is complete enough to submit.

    Theme token rules:
    - You may use these theme tokens inside payload values:
      - <bg>, <surface>, <accent>, <primary>, <secondary>
      - <font>, <title_size>, <body_size>, <caption_size>
    - Prefer theme tokens over hardcoded repeated style values for consistent design.
    - Use set_theme to update one or more of:
      - bg, surface, accent, primary, secondary, font, title_size, body_size, caption_size
    - Omitted theme keys remain unchanged.

    Recommended workflow:
    - If needed, set or refine the theme first.
    - Create the slide structure.
    - Refine slides with targeted updates.
    - Save only when the deck is coherent, complete, and professionally presented.

    Example create_slide payload:
    {
      "background_color": "<bg>",
      "shapes": [
        {
          "type": "text",
          "name": "title",
          "text": "Harbor Retail Expansion 2026",
          "x": 0.7,
          "y": 0.6,
          "w": 8.6,
          "h": 0.8,
          "style": {
            "font_name": "<font>",
            "font_size_pt": "<title_size>",
            "color_hex": "<primary>",
            "bold": true,
            "word_wrap": true,
            "space_after_pt": 4
          }
        },
        {
          "type": "text",
          "name": "subtitle",
          "text": "Growth priorities, risks, and operating implications",
          "x": 0.7,
          "y": 1.45,
          "w": 7.8,
          "h": 0.9,
          "style": {
            "font_name": "<font>",
            "font_size_pt": "<body_size>",
            "color_hex": "<secondary>",
            "word_wrap": true,
            "line_spacing": 1.15
          }
        }
      ]
    }

    Example update_slide payload:
    {
      "slide_index": 1,
      "update_shapes": [
        {
          "type": "text",
          "shape_id": 11,
          "text": "Harbor Retail Expansion 2026",
          "style": {
            "font_name": "<font>",
            "font_size_pt": "<title_size>",
            "color_hex": "<primary>",
            "bold": true
          }
        }
      ],
      "add_shapes": [
        {
          "type": "accent_bar",
          "name": "accent",
          "color_hex": "<accent>"
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


def _observation_metadata(observation: Any) -> dict[str, Any]:
    metadata = getattr(observation, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _planning_payload(
    observation: Any, history: list[dict[str, Any]]
) -> dict[str, Any]:
    metadata = _observation_metadata(observation)
    current_theme = metadata.get("current_theme")
    known_named_shapes = metadata.get("known_named_shapes_by_slide")
    slide_constraints = metadata.get("slide_constraints")
    default_save_path = metadata.get("default_save_path")

    return {
        "task_prompt": observation.task_prompt,
        "source_context": observation.source_context,
        "slide_count": observation.slide_count,
        "remaining_steps": max(
            0,
            int(metadata.get("max_steps", MAX_STEPS))
            - int(metadata.get("step_count", 0)),
        ),
        "last_action_error": observation.last_action_error,
        "last_action_result": observation.last_action_result,
        "recent_actions": history[-5:],
        "known_named_shapes_by_slide": (
            known_named_shapes if isinstance(known_named_shapes, dict) else {}
        ),
        "current_theme": current_theme if isinstance(current_theme, dict) else {},
        "slide_constraints": (
            slide_constraints if isinstance(slide_constraints, dict) else {}
        ),
        "default_save_path": (
            default_save_path
            if isinstance(default_save_path, str) and default_save_path
            else _FALLBACK_SAVE_PATH
        ),
    }


def _validate_tool_choice(invocation: AgentToolInvocation, observation: Any) -> None:
    if invocation.tool_name == "save_presentation":
        constraints = _observation_metadata(observation).get("slide_constraints")
        min_slides = (
            constraints.get("min_slides") if isinstance(constraints, dict) else None
        )
        if isinstance(min_slides, int) and observation.slide_count < min_slides:
            raise ValueError(
                "cannot save before reaching the required minimum slide count"
            )
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


def _history_entry_from_tool_call(
    invocation: AgentToolInvocation, observation: Any
) -> dict[str, Any]:
    last_action_result = (
        observation.last_action_result
        if isinstance(observation.last_action_result, dict)
        else {}
    )
    slide_index = last_action_result.get("slide_index")
    raw_tool_result = last_action_result.get("tool_result")
    tool_result = raw_tool_result if isinstance(raw_tool_result, dict) else None

    return {
        "tool_name": invocation.tool_name,
        "arguments": invocation.arguments,
        "slide_index": slide_index if isinstance(slide_index, int) else None,
        "tool_result": tool_result,
        "error": observation.last_action_error,
    }


def choose_action(
    client: OpenAI, observation: Any, history: list[dict[str, Any]]
) -> tuple[PptAgentAction, str, AgentToolInvocation]:
    metadata = _observation_metadata(observation)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                _planning_payload(observation, history),
                separators=(",", ":"),
            ),
        },
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
            default_save_path=(
                metadata.get("default_save_path")
                if isinstance(metadata.get("default_save_path"), str)
                else _FALLBACK_SAVE_PATH
            ),
        )
        return (
            action,
            json.dumps(
                {
                    "action_type": action.action_type,
                    "slide_index": action.slide_index,
                    "payload": action.payload,
                },
                separators=(",", ":"),
            ),
            invocation,
        )
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
