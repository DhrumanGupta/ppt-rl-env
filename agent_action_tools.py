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
    font_name: str = ""
    font_size_pt: str = ""
    bold: bool | None = None
    italic: bool | None = None
    color_hex: str = ""
    word_wrap: bool | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing: float | None = None


class ChartStyleArgs(_StrictModel):
    title: str = ""
    title_font_name: str = ""
    title_font_size_pt: str = ""
    title_bold: bool | None = None
    title_italic: bool | None = None
    title_color_hex: str = ""
    legend_font_name: str = ""
    legend_font_size_pt: str = ""
    legend_bold: bool | None = None
    legend_italic: bool | None = None
    legend_color_hex: str = ""
    axis_font_name: str = ""
    axis_font_size_pt: str = ""
    axis_bold: bool | None = None
    axis_italic: bool | None = None
    axis_color_hex: str = ""
    series_colors: list[str] = Field(default_factory=list)


class TableStyleArgs(_StrictModel):
    header_fill_hex: str = ""
    body_fill_hex: str = ""
    header_font_name: str = ""
    body_font_name: str = ""
    header_font_size_pt: str = ""
    body_font_size_pt: str = ""
    header_bold: bool | None = None
    body_bold: bool | None = None
    header_italic: bool | None = None
    body_italic: bool | None = None
    header_font_color_hex: str = ""
    body_font_color_hex: str = ""


class ThemeArgs(_StrictModel):
    bg: str = ""
    surface: str = ""
    accent: str = ""
    primary: str = ""
    secondary: str = ""
    font: str = ""
    title_size: float | None = None
    body_size: float | None = None
    caption_size: float | None = None


class AccentBarShapeArgs(_StrictModel):
    type: Literal["accent_bar"]
    shape_id: int | None = None
    name: str = ""
    color_hex: str = ""
    height: float | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


class TextShapeArgs(_StrictModel):
    type: Literal["text"]
    shape_id: int | None = None
    name: str = ""
    text: str = ""
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: TextStyleArgs = Field(default_factory=TextStyleArgs)


class ChartShapeArgs(_StrictModel):
    type: Literal["chart"]
    shape_id: int | None = None
    name: str = ""
    chart_type: str = ""
    chart_data: dict[str, Any] = Field(default_factory=dict)
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: ChartStyleArgs = Field(default_factory=ChartStyleArgs)


class TableShapeArgs(_StrictModel):
    type: Literal["table"]
    shape_id: int | None = None
    name: str = ""
    table_data: list[list[str]] = Field(default_factory=list)
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: TableStyleArgs = Field(default_factory=TableStyleArgs)


class ImageShapeArgs(_StrictModel):
    type: Literal["image"]
    shape_id: int | None = None
    name: str = ""
    image_path: str = ""
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


ShapeArgs = Annotated[
    AccentBarShapeArgs
    | TextShapeArgs
    | ChartShapeArgs
    | TableShapeArgs
    | ImageShapeArgs,
    Field(discriminator="type"),
]


class CreateSlideArgs(_StrictModel):
    background_color: str = ""
    shapes: list[ShapeArgs] = Field(default_factory=list)


class UpdateSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)
    background_color: str = ""
    delete_shape_ids: list[int] = Field(default_factory=list)
    add_shapes: list[ShapeArgs] = Field(default_factory=list)
    update_shapes: list[ShapeArgs] = Field(default_factory=list)


class DeleteSlideArgs(_StrictModel):
    slide_index: int = Field(ge=1)


class SavePresentationArgs(_StrictModel):
    path: str = ""


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
    "create_slide": "Create slide with shapes.",
    "update_slide": "Update one slide.",
    "delete_slide": "Delete one slide by index.",
    "save_presentation": "Save the presentation.",
    "set_theme": "Set default theme tokens.",
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
        return self.arguments_model.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude_defaults=True,
        )


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")


def _validate_create_shape(shape: dict[str, Any]) -> None:
    shape_type = shape["type"]
    if shape_type == "accent_bar":
        _require_keys(shape, ("color_hex",), "accent_bar shape")
        return
    if shape_type == "text":
        _require_keys(shape, ("text", "x", "y", "w", "h"), "text shape")
        return
    if shape_type == "chart":
        _require_keys(
            shape,
            ("chart_type", "chart_data", "x", "y", "w", "h"),
            "chart shape",
        )
        return
    if shape_type == "table":
        _require_keys(shape, ("table_data", "x", "y", "w", "h"), "table shape")
        return
    if shape_type == "image":
        _require_keys(shape, ("image_path", "x", "y"), "image shape")
        return


def _validate_update_shape(shape: dict[str, Any]) -> None:
    _require_keys(shape, ("shape_id",), f"{shape['type']} update")


def _validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    if tool_name == "create_slide":
        for shape in arguments.get("shapes", []):
            _validate_create_shape(shape)
        return

    if tool_name == "update_slide":
        for shape in arguments.get("add_shapes", []):
            _validate_create_shape(shape)
        for shape in arguments.get("update_shapes", []):
            _validate_update_shape(shape)
        return


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

    arguments_model = model.model_validate(raw_arguments)
    compact_arguments = arguments_model.model_dump(
        exclude_none=True,
        exclude_unset=True,
        exclude_defaults=True,
    )
    _validate_tool_arguments(tool_name, compact_arguments)

    return AgentToolInvocation(
        tool_name=tool_name,
        arguments_model=arguments_model,
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
