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


class TextStyle(_StrictModel):
    font_name: str | None = Field(
        default=None, description="Font family or theme token like <font>."
    )
    font_size_pt: int | float | str | None = Field(
        default=None,
        description="Font size in points or a theme token like <title_size>.",
    )
    bold: bool | None = None
    italic: bool | None = None
    color_hex: str | None = Field(
        default=None, description="Hex color or theme token like <primary>."
    )


class ChartStyle(_StrictModel):
    title: str | None = None
    title_font_name: str | None = None
    title_font_size_pt: int | float | str | None = None
    title_bold: bool | None = None
    title_italic: bool | None = None
    title_color_hex: str | None = None
    legend_font_name: str | None = None
    legend_font_size_pt: int | float | str | None = None
    legend_bold: bool | None = None
    legend_italic: bool | None = None
    legend_color_hex: str | None = None
    axis_font_name: str | None = None
    axis_font_size_pt: int | float | str | None = None
    axis_bold: bool | None = None
    axis_italic: bool | None = None
    axis_color_hex: str | None = None
    series_colors: list[str] | None = None


class TableStyle(_StrictModel):
    header_fill_hex: str | None = None
    body_fill_hex: str | None = None
    header_font_name: str | None = None
    body_font_name: str | None = None
    header_font_size_pt: int | float | str | None = None
    body_font_size_pt: int | float | str | None = None
    header_bold: bool | None = None
    body_bold: bool | None = None
    header_italic: bool | None = None
    body_italic: bool | None = None
    header_font_color_hex: str | None = None
    body_font_color_hex: str | None = None


class ChartSeries(_StrictModel):
    name: str
    values: list[int | float]


class ChartData(_StrictModel):
    categories: list[str]
    series: list[ChartSeries]


class CreateAccentBarShape(_StrictModel):
    type: Literal["accent_bar"]
    name: str | None = None
    color_hex: str
    height: int | float | None = None


class CreateTextShape(_StrictModel):
    type: Literal["text"]
    name: str | None = None
    text: str
    x: int | float = Field(
        description="Left position in slide inches. Use values around 0 to 9 on a standard slide."
    )
    y: int | float = Field(
        description="Top position in slide inches. Use values around 0 to 7 on a standard slide."
    )
    w: int | float = Field(
        description="Width in slide inches, typically less than 9.5."
    )
    h: int | float = Field(description="Height in slide inches, typically less than 7.")
    style: TextStyle | None = None


class CreateCitationShape(_StrictModel):
    type: Literal["citation"]
    name: str | None = None
    text: str
    x: int | float | None = Field(
        default=None, description="Left position in slide inches."
    )
    y: int | float | None = Field(
        default=None, description="Top position in slide inches."
    )
    w: int | float | None = Field(default=None, description="Width in slide inches.")
    h: int | float | None = Field(default=None, description="Height in slide inches.")
    style: TextStyle | None = None


class CreateChartShape(_StrictModel):
    type: Literal["chart"]
    name: str | None = None
    chart_type: str
    chart_data: ChartData
    x: int | float = Field(
        description="Left position in slide inches. Use values around 0 to 9 on a standard slide."
    )
    y: int | float = Field(
        description="Top position in slide inches. Use values around 0 to 7 on a standard slide."
    )
    w: int | float = Field(
        description="Width in slide inches, typically less than 9.5."
    )
    h: int | float = Field(description="Height in slide inches, typically less than 7.")
    style: ChartStyle | None = None


class CreateTableShape(_StrictModel):
    type: Literal["table"]
    name: str | None = None
    table_data: list[list[str]]
    x: int | float = Field(
        description="Left position in slide inches. Use values around 0 to 9 on a standard slide."
    )
    y: int | float = Field(
        description="Top position in slide inches. Use values around 0 to 7 on a standard slide."
    )
    w: int | float = Field(
        description="Width in slide inches, typically less than 9.5."
    )
    h: int | float = Field(description="Height in slide inches, typically less than 7.")
    style: TableStyle | None = None


class CreateImageShape(_StrictModel):
    type: Literal["image"]
    name: str | None = None
    image_path: str
    x: int | float = Field(
        description="Left position in slide inches. Use values around 0 to 9 on a standard slide."
    )
    y: int | float = Field(
        description="Top position in slide inches. Use values around 0 to 7 on a standard slide."
    )
    w: int | float | None = Field(
        default=None, description="Optional width in slide inches."
    )
    h: int | float | None = Field(
        default=None, description="Optional height in slide inches."
    )


CreateShapeSpec = Annotated[
    CreateAccentBarShape
    | CreateTextShape
    | CreateCitationShape
    | CreateChartShape
    | CreateTableShape
    | CreateImageShape,
    Field(discriminator="type"),
]


class UpdateAccentBarShape(_StrictModel):
    type: Literal["accent_bar"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    color_hex: str | None = None
    height: int | float | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None


class UpdateTextShape(_StrictModel):
    type: Literal["text"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    text: str | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None
    style: TextStyle | None = None


class UpdateCitationShape(_StrictModel):
    type: Literal["citation"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    text: str | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None
    style: TextStyle | None = None


class UpdateChartShape(_StrictModel):
    type: Literal["chart"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None
    style: ChartStyle | None = None


class UpdateTableShape(_StrictModel):
    type: Literal["table"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None
    style: TableStyle | None = None


class UpdateImageShape(_StrictModel):
    type: Literal["image"]
    shape_id: int = Field(ge=1)
    name: str | None = None
    x: int | float | None = None
    y: int | float | None = None
    w: int | float | None = None
    h: int | float | None = None


UpdateShapeSpec = Annotated[
    UpdateAccentBarShape
    | UpdateTextShape
    | UpdateCitationShape
    | UpdateChartShape
    | UpdateTableShape
    | UpdateImageShape,
    Field(discriminator="type"),
]


class CreateSlideArgs(_StrictModel):
    layout_index: int = Field(
        default=6,
        description="Slide layout index. Prefer 6 for a blank slide unless a different layout is clearly needed.",
    )
    background_color: str | None = Field(
        default=None,
        description="Background fill color or theme token like <bg> or <surface>.",
    )
    shapes: list[CreateShapeSpec] = Field(default_factory=list)


class UpdateSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)
    background_color: str | None = Field(
        default=None,
        description="Background fill color or theme token like <bg> or <surface>.",
    )
    delete_shape_ids: list[int] = Field(default_factory=list)
    add_shapes: list[CreateShapeSpec] = Field(default_factory=list)
    update_shapes: list[UpdateShapeSpec] = Field(default_factory=list)


class DeleteSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)


class SavePresentationArgs(_StrictModel):
    path: str | None = None


_TOOL_MODELS = {
    "create_slide": CreateSlideArgs,
    "update_slide": UpdateSlideArgs,
    "delete_slide": DeleteSlideArgs,
    "save_presentation": SavePresentationArgs,
}

_TOOL_DESCRIPTIONS = {
    "create_slide": "Create a new slide with an explicit layout, background, and full shape list.",
    "update_slide": "Refine one existing slide by updating, adding, or deleting shapes.",
    "delete_slide": "Delete one existing slide by its 1-based slide index.",
    "save_presentation": "Write the current presentation to disk when the deck is complete.",
}


@dataclass(frozen=True, slots=True)
class AgentToolInvocation:
    tool_name: str
    arguments_model: (
        CreateSlideArgs | UpdateSlideArgs | DeleteSlideArgs | SavePresentationArgs
    )

    @property
    def arguments(self) -> dict[str, Any]:
        return self.arguments_model.model_dump(exclude_none=True)


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
