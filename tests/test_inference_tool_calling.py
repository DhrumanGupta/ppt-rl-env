import json
from types import SimpleNamespace

import pytest

from agent_action_tools import parse_tool_invocation, tool_invocation_to_action
from inference import (
    SYSTEM_PROMPT,
    _planning_prompt,
    _validate_tool_choice,
    choose_action,
)


def _observation(**overrides):
    payload = {
        "task_name": "sample_task",
        "difficulty": "easy",
        "task_prompt": "Create a 3-slide executive summary.",
        "source_context": "[Doc]\nRevenue grew 12% year over year.",
        "prompt_summary": "Create a 3-slide executive summary.",
        "slide_count": 1,
        "last_action_error": None,
        "last_action_result": None,
        "score": 0.0,
        "metadata": {"current_theme": {"accent": "#2563EB", "font": "Aptos"}},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_tool_invocation_to_action_builds_create_slide_payload_directly():
    invocation = parse_tool_invocation(
        "create_slide",
        {
            "background_color": "<surface>",
            "shapes": [
                {
                    "type": "text",
                    "name": "title",
                    "text": "Growth remains resilient",
                    "x": 0.8,
                    "y": 0.8,
                    "w": 5.0,
                    "h": 0.8,
                    "style": {
                        "font_name": "<font>",
                        "font_size_pt": "<title_size>",
                        "color_hex": "<primary>",
                        "bold": True,
                        "word_wrap": True,
                        "space_after_pt": 6,
                        "line_spacing": 1.2,
                    },
                }
            ],
        },
    )

    action = tool_invocation_to_action(invocation, default_save_path="outputs/out.pptx")

    assert action.action_type == "create_slide"
    assert action.slide_index is None
    assert action.payload["background_color"] == "<surface>"
    assert action.payload["shapes"][0]["type"] == "text"
    assert action.payload["shapes"][0]["style"]["font_size_pt"] == "<title_size>"
    assert action.payload["shapes"][0]["style"]["word_wrap"] is True
    assert action.payload["shapes"][0]["style"]["space_after_pt"] == 6


def test_parse_tool_invocation_rejects_invalid_text_style_alias_keys():
    with pytest.raises(Exception):
        parse_tool_invocation(
            "create_slide",
            {
                "shapes": [
                    {
                        "type": "text",
                        "text": "Growth remains resilient",
                        "x": 0.8,
                        "y": 0.8,
                        "w": 5.0,
                        "h": 0.8,
                        "style": {"color": "<primary>", "font_size": 24},
                    }
                ]
            },
        )


def test_validate_tool_choice_blocks_early_save():
    observation = _observation(slide_count=2)
    invocation = parse_tool_invocation(
        "save_presentation", {"path": "outputs/out.pptx"}
    )

    with pytest.raises(ValueError, match="cannot save"):
        _validate_tool_choice(invocation, observation)


def test_tool_invocation_to_action_builds_set_theme_payload_directly():
    invocation = parse_tool_invocation(
        "set_theme",
        {
            "accent": "#112233",
            "font": "Inter",
            "title_size": 30,
        },
    )

    action = tool_invocation_to_action(invocation, default_save_path="outputs/out.pptx")

    assert action.action_type == "set_theme"
    assert action.payload == {
        "accent": "#112233",
        "font": "Inter",
        "title_size": 30,
    }


def test_parse_tool_invocation_rejects_removed_layout_index_field():
    with pytest.raises(Exception):
        parse_tool_invocation("create_slide", {"layout_index": 6, "shapes": []})


def test_parse_tool_invocation_rejects_removed_citation_shape_type():
    with pytest.raises(Exception):
        parse_tool_invocation(
            "create_slide",
            {
                "shapes": [
                    {
                        "type": "citation",
                        "text": "Source: quarterly report",
                    }
                ]
            },
        )


def test_planning_prompt_includes_named_shape_context():
    history = [
        {
            "tool_name": "create_slide",
            "arguments": {"background_color": "<surface>", "shapes": []},
            "slide_index": 1,
            "tool_result": {"named_shapes": {"title": 11, "accent": 12}},
            "error": None,
        },
        {
            "tool_name": "update_slide",
            "arguments": {"slide_index": 1, "update_shapes": []},
            "slide_index": 1,
            "tool_result": {
                "named_shapes": {"body": 13},
                "deleted_shape_ids": [12],
            },
            "error": None,
        },
    ]

    prompt = json.loads(_planning_prompt(_observation(), history))

    assert prompt["recent_actions"][0]["tool_name"] == "create_slide"
    assert prompt["known_named_shapes_by_slide"]["1"] == {"title": 11, "body": 13}
    assert prompt["requirements"]["supported_tools"] == [
        "create_slide",
        "update_slide",
        "delete_slide",
        "set_theme",
        "save_presentation",
    ]
    assert prompt["requirements"]["current_theme"] == {
        "accent": "#2563EB",
        "font": "Aptos",
    }


def test_system_prompt_warns_against_old_macro_dsl_fields():
    assert "background -> use background_color" in SYSTEM_PROMPT
    assert "type: title/body -> use type: text" in SYSTEM_PROMPT
    assert '"font_size_pt"' in SYSTEM_PROMPT
    assert '"color_hex"' in SYSTEM_PROMPT
    assert "set_theme" in SYSTEM_PROMPT


def test_choose_action_uses_tool_call_and_returns_agent_action():
    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="create_slide",
                                        arguments=json.dumps(
                                            {
                                                "background_color": "<surface>",
                                                "shapes": [
                                                    {
                                                        "type": "text",
                                                        "name": "title",
                                                        "text": "Growth outlook",
                                                        "x": 0.8,
                                                        "y": 0.8,
                                                        "w": 4.5,
                                                        "h": 0.7,
                                                    }
                                                ],
                                            }
                                        ),
                                    )
                                )
                            ],
                            content=None,
                        )
                    )
                ]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    action, action_str, invocation = choose_action(
        client, _observation(slide_count=0), []
    )

    assert invocation.tool_name == "create_slide"
    assert action.action_type == "create_slide"
    assert action.payload["shapes"][0]["text"] == "Growth outlook"
    assert json.loads(action_str)["action_type"] == "create_slide"
    assert completions.calls[0]["tool_choice"] == "required"
    assert completions.calls[0]["tools"]


def test_choose_action_does_not_retry_after_error():
    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="save_presentation",
                                        arguments=json.dumps(
                                            {"path": "outputs/out.pptx"}
                                        ),
                                    )
                                )
                            ],
                            content=None,
                        )
                    )
                ]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(ValueError, match="cannot save"):
        choose_action(client, _observation(slide_count=0), [])

    assert len(completions.calls) == 1
