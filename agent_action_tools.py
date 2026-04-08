from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

try:
    from ppt_agent import PptAgentAction
except ImportError:  # pragma: no cover
    from models import PptAgentAction


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextStyleArgs(_StrictModel):
    font_name: str | None = None
    font_size_pt: float | str | None = None
    bold: bool | None = None
    italic: bool | None = None
    color_hex: str | None = None
    word_wrap: bool | None = None
    space_before_pt: float | str | None = None
    space_after_pt: float | str | None = None
    line_spacing: float | None = None


class ChartStyleArgs(_StrictModel):
    title: str | None = None
    title_font_name: str | None = None
    title_font_size_pt: float | str | None = None
    title_bold: bool | None = None
    title_italic: bool | None = None
    title_color_hex: str | None = None
    legend_font_name: str | None = None
    legend_font_size_pt: float | str | None = None
    legend_bold: bool | None = None
    legend_italic: bool | None = None
    legend_color_hex: str | None = None
    axis_font_name: str | None = None
    axis_font_size_pt: float | str | None = None
    axis_bold: bool | None = None
    axis_italic: bool | None = None
    axis_color_hex: str | None = None
    series_colors: list[str] | None = None


class TableStyleArgs(_StrictModel):
    header_fill_hex: str | None = None
    body_fill_hex: str | None = None
    header_font_name: str | None = None
    body_font_name: str | None = None
    header_font_size_pt: float | str | None = None
    body_font_size_pt: float | str | None = None
    header_bold: bool | None = None
    body_bold: bool | None = None
    header_italic: bool | None = None
    body_italic: bool | None = None
    header_font_color_hex: str | None = None
    body_font_color_hex: str | None = None


class ThemeArgs(_StrictModel):
    bg: str | None = None
    surface: str | None = None
    accent: str | None = None
    primary: str | None = None
    secondary: str | None = None
    font: str | None = None
    title_size: float | None = None
    body_size: float | None = None
    caption_size: float | None = None


class _NamedShapeArgs(_StrictModel):
    name: str | None = None


class _UpdateShapeArgs(_NamedShapeArgs):
    shape_id: int = Field(ge=1)


class CreateAccentBarArgs(_NamedShapeArgs):
    type: Literal["accent_bar"]
    color_hex: str
    height: float | None = None


class UpdateAccentBarArgs(_UpdateShapeArgs):
    type: Literal["accent_bar"]
    color_hex: str | None = None
    height: float | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


class CreateTextArgs(_NamedShapeArgs):
    type: Literal["text"]
    text: str
    x: float
    y: float
    w: float
    h: float
    style: TextStyleArgs | None = None


class UpdateTextArgs(_UpdateShapeArgs):
    type: Literal["text"]
    text: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: TextStyleArgs | None = None


class CreateChartArgs(_NamedShapeArgs):
    type: Literal["chart"]
    chart_type: str
    chart_data: dict[str, Any]
    x: float
    y: float
    w: float
    h: float
    style: ChartStyleArgs | None = None


class UpdateChartArgs(_UpdateShapeArgs):
    type: Literal["chart"]
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: ChartStyleArgs | None = None


class CreateTableArgs(_NamedShapeArgs):
    type: Literal["table"]
    table_data: list[list[str]]
    x: float
    y: float
    w: float
    h: float
    style: TableStyleArgs | None = None


class UpdateTableArgs(_UpdateShapeArgs):
    type: Literal["table"]
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: TableStyleArgs | None = None


class CreateImageArgs(_NamedShapeArgs):
    type: Literal["image"]
    image_path: str
    x: float
    y: float
    w: float | None = None
    h: float | None = None


class UpdateImageArgs(_UpdateShapeArgs):
    type: Literal["image"]
    image_path: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


CreateShapeArgs = Annotated[
    CreateAccentBarArgs
    | CreateTextArgs
    | CreateChartArgs
    | CreateTableArgs
    | CreateImageArgs,
    Field(discriminator="type"),
]

UpdateShapeArgs = Annotated[
    UpdateAccentBarArgs
    | UpdateTextArgs
    | UpdateChartArgs
    | UpdateTableArgs
    | UpdateImageArgs,
    Field(discriminator="type"),
]


class CreateSlideArgs(_StrictModel):
    background_color: str | None = None
    shapes: list[CreateShapeArgs] = Field(default_factory=list)


class UpdateSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)
    background_color: str | None = None
    delete_shape_ids: list[int] = Field(default_factory=list)
    add_shapes: list[CreateShapeArgs] = Field(default_factory=list)
    update_shapes: list[UpdateShapeArgs] = Field(default_factory=list)


class DeleteSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)


class SavePresentationArgs(_StrictModel):
    path: str | None = None


class SetThemeArgs(ThemeArgs):
    pass


_TOOL_MODELS = {
    "create_slide": CreateSlideArgs,
    "update_slide": UpdateSlideArgs,
    "delete_slide": DeleteSlideArgs,
    "save_presentation": SavePresentationArgs,
    "set_theme": SetThemeArgs,
}

_TOOL_DESCRIPTIONS = {
    "create_slide": "Create a new slide with optional background and shapes.",
    "update_slide": "Refine one existing slide by updating, adding, or deleting shapes.",
    "delete_slide": "Delete one existing slide by its 1-based slide index.",
    "save_presentation": "Write the current presentation to disk when the deck is complete.",
    "set_theme": "Set default theme tokens by overwriting provided keys on the default theme.",
}


@dataclass(frozen=True, slots=True)
class AgentToolInvocation:
    tool_name: str
    arguments_model: (
        CreateSlideArgs
        | UpdateSlideArgs
        | DeleteSlideArgs
        | SavePresentationArgs
        | SetThemeArgs
    )

    @property
    def arguments(self) -> dict[str, Any]:
        return self.arguments_model.model_dump(exclude_none=True, exclude_unset=True)


def build_openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _TOOL_DESCRIPTIONS[tool_name],
                "parameters": model.model_json_schema(),
            },
        }
        for tool_name, model in _TOOL_MODELS.items()
    ]


def parse_tool_invocation(
    tool_name: str, arguments: str | dict[str, Any]
) -> AgentToolInvocation:
    model = _TOOL_MODELS.get(tool_name)
    if model is None:
        raise ValueError(f"Unsupported tool '{tool_name}'")

    if isinstance(arguments, str):
        raw_arguments = json.loads(arguments or "{}")
    elif isinstance(arguments, dict):
        raw_arguments = arguments
    else:
        raise ValueError("Tool arguments must be a JSON object or JSON string")

    if not isinstance(raw_arguments, dict):
        raise ValueError("Tool arguments must decode to a JSON object")

    return AgentToolInvocation(
        tool_name=tool_name,
        arguments_model=model.model_validate(raw_arguments),
    )


def tool_invocation_to_action(
    invocation: AgentToolInvocation, default_save_path: str
) -> PptAgentAction:
    arguments = invocation.arguments

    if invocation.tool_name == "create_slide":
        return PptAgentAction(action_type="create_slide", payload=arguments)

    if invocation.tool_name == "update_slide":
        return PptAgentAction(
            action_type="update_slide",
            slide_index=arguments["slide_index"],
            payload={
                key: value for key, value in arguments.items() if key != "slide_index"
            },
        )

    if invocation.tool_name == "delete_slide":
        return PptAgentAction(
            action_type="delete_slide",
            slide_index=arguments["slide_index"],
        )

    if invocation.tool_name == "save_presentation":
        return PptAgentAction(
            action_type="save_presentation",
            payload={"path": arguments.get("path") or default_save_path},
        )

    if invocation.tool_name == "set_theme":
        return PptAgentAction(action_type="set_theme", payload=arguments)

    raise ValueError(f"Unsupported tool '{invocation.tool_name}'")


__all__ = [
    "AgentToolInvocation",
    "CreateSlideArgs",
    "DeleteSlideArgs",
    "SavePresentationArgs",
    "UpdateSlideArgs",
    "build_openai_tools",
    "parse_tool_invocation",
    "tool_invocation_to_action",
]
