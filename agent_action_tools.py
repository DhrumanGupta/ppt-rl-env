from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ppt_agent.models import PptAgentAction


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextStyleArgs(_StrictModel):
    font_name: str = ""
    font_size_pt: float | None = None
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
    title_font_size_pt: float | None = None
    title_bold: bool | None = None
    title_italic: bool | None = None
    title_color_hex: str = ""
    legend_font_name: str = ""
    legend_font_size_pt: float | None = None
    legend_bold: bool | None = None
    legend_italic: bool | None = None
    legend_color_hex: str = ""
    axis_font_name: str = ""
    axis_font_size_pt: float | None = None
    axis_bold: bool | None = None
    axis_italic: bool | None = None
    axis_color_hex: str = ""
    series_colors: list[str] = Field(default_factory=list)


class TableStyleArgs(_StrictModel):
    header_fill_hex: str = ""
    body_fill_hex: str = ""
    header_font_name: str = ""
    body_font_name: str = ""
    header_font_size_pt: float | None = None
    body_font_size_pt: float | None = None
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

_STYLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "font_name": {"type": "string"},
        "font_size_pt": {"type": "number"},
        "bold": {"type": "boolean"},
        "italic": {"type": "boolean"},
        "color_hex": {"type": "string"},
        "word_wrap": {"type": "boolean"},
        "space_before_pt": {"type": "number"},
        "space_after_pt": {"type": "number"},
        "line_spacing": {"type": "number"},
        "title": {"type": "string"},
        "title_font_name": {"type": "string"},
        "title_font_size_pt": {"type": "number"},
        "title_bold": {"type": "boolean"},
        "title_italic": {"type": "boolean"},
        "title_color_hex": {"type": "string"},
        "legend_font_name": {"type": "string"},
        "legend_font_size_pt": {"type": "number"},
        "legend_bold": {"type": "boolean"},
        "legend_italic": {"type": "boolean"},
        "legend_color_hex": {"type": "string"},
        "axis_font_name": {"type": "string"},
        "axis_font_size_pt": {"type": "number"},
        "axis_bold": {"type": "boolean"},
        "axis_italic": {"type": "boolean"},
        "axis_color_hex": {"type": "string"},
        "series_colors": {"type": "array", "items": {"type": "string"}},
        "header_fill_hex": {"type": "string"},
        "body_fill_hex": {"type": "string"},
        "header_font_name": {"type": "string"},
        "body_font_name": {"type": "string"},
        "header_font_size_pt": {"type": "number"},
        "body_font_size_pt": {"type": "number"},
        "header_bold": {"type": "boolean"},
        "body_bold": {"type": "boolean"},
        "header_italic": {"type": "boolean"},
        "body_italic": {"type": "boolean"},
        "header_font_color_hex": {"type": "string"},
        "body_font_color_hex": {"type": "string"},
    },
}

_SHAPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {
            "type": "string",
            "enum": ["accent_bar", "text", "chart", "table", "image"],
        },
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "text": {"type": "string"},
        "ct": {"type": "string"},
        "cd": {"type": "object", "additionalProperties": True},
        "td": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        },
        "img": {"type": "string"},
        "hex": {"type": "string"},
        "color_hex": {"type": "string"},
        "height": {"type": "number"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "w": {"type": "number"},
        "h": {"type": "number"},
        "style": _STYLE_SCHEMA,
    },
    "required": ["type"],
}

_COMPACT_TOOL_PARAMETERS = {
    "create_slide": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "bg": {"type": "string"},
            "shapes": {"type": "array", "items": _SHAPE_SCHEMA},
        },
    },
    "update_slide": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "si": {"type": "integer", "minimum": 1},
            "bg": {"type": "string"},
            "del": {"type": "array", "items": {"type": "integer"}},
            "add": {"type": "array", "items": _SHAPE_SCHEMA},
            "upd": {"type": "array", "items": _SHAPE_SCHEMA},
        },
        "required": ["si"],
    },
    "delete_slide": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"si": {"type": "integer", "minimum": 1}},
        "required": ["si"],
    },
    "save_presentation": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}},
    },
    "set_theme": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "bg": {"type": "string"},
            "surface": {"type": "string"},
            "accent": {"type": "string"},
            "primary": {"type": "string"},
            "secondary": {"type": "string"},
            "font": {"type": "string"},
            "ts": {"type": "number"},
            "bs": {"type": "number"},
            "cs": {"type": "number"},
        },
    },
}

_TOOL_FIELD_ALIASES = {
    "create_slide": {"bg": "background_color"},
    "update_slide": {
        "si": "slide_index",
        "bg": "background_color",
        "del": "delete_shape_ids",
        "add": "add_shapes",
        "upd": "update_shapes",
    },
    "delete_slide": {"si": "slide_index"},
    "save_presentation": {},
    "set_theme": {"ts": "title_size", "bs": "body_size", "cs": "caption_size"},
}

_SHAPE_FIELD_ALIASES = {
    "id": "shape_id",
    "ct": "chart_type",
    "cd": "chart_data",
    "td": "table_data",
    "img": "image_path",
    "hex": "color_hex",
}

_ROOT_FLOAT_FIELDS = {
    "x",
    "y",
    "w",
    "h",
    "height",
    "title_size",
    "body_size",
    "caption_size",
}

_STYLE_KEYS_BY_SHAPE_TYPE = {
    "text": {
        "font_name",
        "font_size_pt",
        "bold",
        "italic",
        "color_hex",
        "word_wrap",
        "space_before_pt",
        "space_after_pt",
        "line_spacing",
    },
    "chart": {
        "title",
        "title_font_name",
        "title_font_size_pt",
        "title_bold",
        "title_italic",
        "title_color_hex",
        "legend_font_name",
        "legend_font_size_pt",
        "legend_bold",
        "legend_italic",
        "legend_color_hex",
        "axis_font_name",
        "axis_font_size_pt",
        "axis_bold",
        "axis_italic",
        "axis_color_hex",
        "series_colors",
    },
    "table": {
        "header_fill_hex",
        "body_fill_hex",
        "header_font_name",
        "body_font_name",
        "header_font_size_pt",
        "body_font_size_pt",
        "header_bold",
        "body_bold",
        "header_italic",
        "body_italic",
        "header_font_color_hex",
        "body_font_color_hex",
    },
}

_STYLE_FLOAT_FIELDS = {
    "font_size_pt",
    "space_before_pt",
    "space_after_pt",
    "line_spacing",
    "title_font_size_pt",
    "legend_font_size_pt",
    "axis_font_size_pt",
    "header_font_size_pt",
    "body_font_size_pt",
}

_SHAPE_ALLOWED_KEYS = {
    "accent_bar": {
        "type",
        "shape_id",
        "name",
        "color_hex",
        "height",
        "x",
        "y",
        "w",
        "h",
    },
    "text": {"type", "shape_id", "name", "text", "x", "y", "w", "h", "style"},
    "chart": {
        "type",
        "shape_id",
        "name",
        "chart_type",
        "chart_data",
        "x",
        "y",
        "w",
        "h",
        "style",
    },
    "table": {"type", "shape_id", "name", "table_data", "x", "y", "w", "h", "style"},
    "image": {"type", "shape_id", "name", "image_path", "x", "y", "w", "h"},
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
        return _normalize_tool_arguments(
            self.arguments_model.model_dump(
                exclude_none=True,
                exclude_unset=True,
            )
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


def _coerce_float(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        try:
            return float(stripped)
        except ValueError:
            return value
    return value


def _normalize_style(shape_type: str, style: Any) -> dict[str, Any]:
    if not isinstance(style, dict):
        return {}

    allowed_keys = _STYLE_KEYS_BY_SHAPE_TYPE.get(shape_type)
    if allowed_keys is None:
        return {}

    normalized_style: dict[str, Any] = {}
    for key, value in style.items():
        if key not in allowed_keys:
            continue
        normalized_style[key] = (
            _coerce_float(value) if key in _STYLE_FLOAT_FIELDS else value
        )
    return normalized_style


def _normalize_shape(shape: Any) -> Any:
    if not isinstance(shape, dict):
        return shape

    canonical_shape = {
        _SHAPE_FIELD_ALIASES.get(key, key): value for key, value in shape.items()
    }
    shape_type = canonical_shape.get("type")
    if not isinstance(shape_type, str):
        return canonical_shape

    normalized_shape: dict[str, Any] = {}
    allowed_keys = _SHAPE_ALLOWED_KEYS.get(shape_type)
    if allowed_keys is None:
        return canonical_shape

    raw_style = canonical_shape.get("style")
    style_payload = raw_style if isinstance(raw_style, dict) else {}

    if shape_type == "accent_bar" and not canonical_shape.get("color_hex"):
        if (
            isinstance(style_payload.get("color_hex"), str)
            and style_payload["color_hex"]
        ):
            canonical_shape["color_hex"] = style_payload["color_hex"]
        elif "shape_id" not in canonical_shape:
            canonical_shape["color_hex"] = "<accent>"

    for key, value in canonical_shape.items():
        if key == "style":
            continue
        if key in _STYLE_KEYS_BY_SHAPE_TYPE.get(shape_type, set()):
            style_payload.setdefault(key, value)
            continue
        if key not in allowed_keys:
            continue
        normalized_shape[key] = (
            _coerce_float(value) if key in _ROOT_FLOAT_FIELDS else value
        )

    normalized_style = _normalize_style(shape_type, style_payload)
    if normalized_style and "style" in allowed_keys:
        normalized_shape["style"] = normalized_style

    return normalized_shape


def _normalize_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized_arguments: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in _ROOT_FLOAT_FIELDS:
            normalized_arguments[key] = _coerce_float(value)
            continue
        if key in {"shapes", "add_shapes", "update_shapes"} and isinstance(value, list):
            normalized_arguments[key] = [_normalize_shape(shape) for shape in value]
            continue
        normalized_arguments[key] = value
    return normalized_arguments


def _canonicalize_tool_arguments(
    tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    aliases = _TOOL_FIELD_ALIASES[tool_name]
    canonical_arguments: dict[str, Any] = {}

    for key, value in arguments.items():
        canonical_key = aliases.get(key, key)
        if canonical_key in {"shapes", "add_shapes", "update_shapes"} and isinstance(
            value, list
        ):
            canonical_arguments[canonical_key] = [
                _normalize_shape(shape) for shape in value
            ]
            continue
        canonical_arguments[canonical_key] = value

    return _normalize_tool_arguments(canonical_arguments)


def build_openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _TOOL_DESCRIPTIONS[tool_name],
                "parameters": _COMPACT_TOOL_PARAMETERS[tool_name],
            },
        }
        for tool_name in _TOOL_MODELS
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

    arguments_model = model.model_validate(
        _canonicalize_tool_arguments(tool_name, raw_arguments)
    )
    compact_arguments = _normalize_tool_arguments(
        arguments_model.model_dump(
            exclude_none=True,
            exclude_unset=True,
        )
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
