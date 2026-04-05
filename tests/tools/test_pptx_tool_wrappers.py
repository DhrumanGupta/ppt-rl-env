import pytest

from src.tools.pptx_tools import (
    create_slide,
    register_theme,
    update_slide,
    update_theme,
)
from src.utils.pptx_functions import PptxEditor


@pytest.fixture
def themed_editor():
    editor = PptxEditor()
    register_theme(
        editor,
        {
            "bg": "#112233",
            "surface": "#F8FAFC",
            "accent": "#445566",
            "primary": "#102A43",
            "secondary": "#486581",
            "font": "Arial",
            "title_size": 24,
            "body_size": 14,
            "caption_size": 10,
        },
    )
    return editor


def slide_for_id(editor, slide_id):
    return editor.prs.slides[editor.get_slide_index(slide_id)]


def shape_for_id(editor, slide_id, shape_id):
    slide = slide_for_id(editor, slide_id)
    return slide.shapes[editor.get_shape_index(slide_id, shape_id)]


def test_create_slide_creates_mixed_shapes_and_named_shape_mapping(themed_editor):
    result = create_slide(
        themed_editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
                "text": "Hello world",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                },
            },
            {
                "type": "citation",
                "name": "citation",
                "text": "Source: Example",
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<caption_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    slide = slide_for_id(themed_editor, result["slide_id"])
    title_shape = shape_for_id(
        themed_editor, result["slide_id"], result["named_shapes"]["title"]
    )

    assert str(slide.background.fill.fore_color.rgb) == "112233"
    assert result["named_shapes"]["accent"] in result["shape_ids"]
    assert title_shape.text_frame.text == "Hello world"
    assert title_shape.text_frame.paragraphs[0].font.name == "Arial"
    assert title_shape.text_frame.paragraphs[0].font.size.pt == 24
    assert str(title_shape.text_frame.paragraphs[0].font.color.rgb) == "102A43"


def test_update_slide_can_delete_add_and_update_in_one_call(themed_editor):
    created = create_slide(
        themed_editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
                "text": "Original",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                },
            },
            {
                "type": "text",
                "name": "summary",
                "text": "Delete me",
                "x": 1,
                "y": 2,
                "w": 4,
                "h": 1,
                "style": {"font_name": "<font>", "font_size_pt": "<body_size>"},
            },
        ],
    )

    updated = update_slide(
        themed_editor,
        created["slide_id"],
        background_color="#FFFFFF",
        delete_shape_ids=[created["named_shapes"]["summary"]],
        update_shapes=[
            {
                "shape_id": created["named_shapes"]["title"],
                "type": "text",
                "name": "title",
                "text": "Updated title",
                "x": 1.5,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": 26,
                    "color_hex": "#AA5500",
                    "bold": True,
                },
            },
            {
                "shape_id": created["named_shapes"]["accent"],
                "type": "accent_bar",
                "name": "accent",
                "color_hex": "#123456",
                "height": 0.45,
            },
        ],
        add_shapes=[
            {
                "type": "chart",
                "name": "chart",
                "chart_type": "column_clustered",
                "chart_data": {
                    "categories": ["A", "B"],
                    "series": [{"name": "S1", "values": [1, 2]}],
                },
                "x": 1,
                "y": 3,
                "w": 4,
                "h": 3,
                "style": {"title": "Added chart", "series_colors": ["<accent>"]},
            }
        ],
    )

    slide = slide_for_id(themed_editor, created["slide_id"])
    title = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["title"]
    )
    accent = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["accent"]
    )

    assert str(slide.background.fill.fore_color.rgb) == "FFFFFF"
    assert created["named_shapes"]["summary"] in updated["deleted_shape_ids"]
    with pytest.raises(KeyError):
        shape_for_id(
            themed_editor, created["slide_id"], created["named_shapes"]["summary"]
        )
    assert title.text_frame.text == "Updated title"
    assert title.left.inches == 1.5
    assert title.text_frame.paragraphs[0].font.size.pt == 26
    assert str(title.text_frame.paragraphs[0].font.color.rgb) == "AA5500"
    assert str(accent.fill.fore_color.rgb) == "123456"
    assert round(accent.height.inches, 2) == 0.45
    assert updated["named_shapes"]["chart"] in updated["created_shape_ids"]


def test_theme_updates_reapply_after_create_slide_and_update_slide(themed_editor):
    created = create_slide(
        themed_editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
                "text": "Bound title",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                },
            },
        ],
    )

    update_slide(
        themed_editor,
        created["slide_id"],
        update_shapes=[
            {
                "shape_id": created["named_shapes"]["title"],
                "type": "text",
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            }
        ],
    )

    update_theme(
        themed_editor,
        {
            "surface": "#EEF2F7",
            "accent": "#778899",
            "font": "Georgia",
            "body_size": 18,
            "secondary": "#AABBCC",
        },
    )

    slide = slide_for_id(themed_editor, created["slide_id"])
    accent = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["accent"]
    )
    title = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["title"]
    )
    paragraph = title.text_frame.paragraphs[0]

    assert str(slide.background.fill.fore_color.rgb) == "EEF2F7"
    assert str(accent.fill.fore_color.rgb) == "778899"
    assert paragraph.font.name == "Georgia"
    assert paragraph.font.size.pt == 18
    assert str(paragraph.font.color.rgb) == "AABBCC"


def test_update_slide_replaces_old_binding_when_literal_style_is_applied(themed_editor):
    created = create_slide(
        themed_editor,
        shapes=[
            {
                "type": "text",
                "name": "title",
                "text": "Literal test",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<title_size>",
                    "color_hex": "<primary>",
                },
            }
        ],
    )

    update_slide(
        themed_editor,
        created["slide_id"],
        update_shapes=[
            {
                "shape_id": created["named_shapes"]["title"],
                "type": "text",
                "style": {
                    "font_name": "Verdana",
                    "font_size_pt": 20,
                    "color_hex": "#FF0000",
                },
            }
        ],
    )
    update_theme(
        themed_editor,
        {"font": "Georgia", "title_size": 30, "primary": "#00FF00"},
    )

    paragraph = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["title"]
    ).text_frame.paragraphs[0]
    assert paragraph.font.name == "Verdana"
    assert paragraph.font.size.pt == 20
    assert str(paragraph.font.color.rgb) == "FF0000"


def test_update_slide_supports_chart_and_table_style_updates(themed_editor):
    created = create_slide(
        themed_editor,
        shapes=[
            {
                "type": "chart",
                "name": "chart",
                "chart_type": "column_clustered",
                "chart_data": {
                    "categories": ["A", "B"],
                    "series": [
                        {"name": "S1", "values": [1, 2]},
                        {"name": "S2", "values": [3, 4]},
                    ],
                },
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 3,
                "style": {"series_colors": ["<accent>", "<primary>"]},
            },
            {
                "type": "table",
                "name": "table",
                "table_data": [["H1", "H2"], ["V1", "V2"]],
                "x": 1,
                "y": 4,
                "w": 4,
                "h": 2,
                "style": {
                    "header_fill_hex": "<accent>",
                    "body_font_color_hex": "<primary>",
                },
            },
        ],
    )

    update_slide(
        themed_editor,
        created["slide_id"],
        update_shapes=[
            {
                "shape_id": created["named_shapes"]["chart"],
                "type": "chart",
                "style": {
                    "title": "Updated Chart",
                    "title_font_name": "<font>",
                    "title_font_size_pt": "<title_size>",
                    "series_colors": ["#111111", "<secondary>"],
                },
            },
            {
                "shape_id": created["named_shapes"]["table"],
                "type": "table",
                "style": {
                    "header_fill_hex": "#000000",
                    "body_font_name": "<font>",
                    "body_font_size_pt": "<body_size>",
                    "body_font_color_hex": "<secondary>",
                },
            },
        ],
    )

    update_theme(
        themed_editor,
        {"font": "Calibri", "title_size": 30, "secondary": "#778899", "body_size": 16},
    )

    chart = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["chart"]
    ).chart
    table = shape_for_id(
        themed_editor, created["slide_id"], created["named_shapes"]["table"]
    ).table

    assert chart.chart_title.text_frame.text == "Updated Chart"
    assert chart.chart_title.text_frame.paragraphs[0].font.name == "Calibri"
    assert chart.chart_title.text_frame.paragraphs[0].font.size.pt == 30
    assert str(chart.series[0].format.fill.fore_color.rgb) == "111111"
    assert str(chart.series[1].format.fill.fore_color.rgb) == "778899"
    assert str(table.cell(0, 0).fill.fore_color.rgb) == "000000"
    assert table.cell(1, 0).text_frame.paragraphs[0].font.name == "Calibri"
    assert table.cell(1, 0).text_frame.paragraphs[0].font.size.pt == 16
    assert str(table.cell(1, 0).text_frame.paragraphs[0].font.color.rgb) == "778899"


def test_update_slide_bindings_survive_slide_reorder(themed_editor):
    first = create_slide(
        themed_editor,
        shapes=[
            {
                "type": "text",
                "name": "title",
                "text": "Reorder me",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
                "style": {"font_name": "<font>", "font_size_pt": "<title_size>"},
            }
        ],
    )
    second = create_slide(themed_editor)

    themed_editor.reorder_slide(
        themed_editor.get_slide_index(first["slide_id"]),
        themed_editor.get_slide_index(second["slide_id"]),
    )
    update_theme(themed_editor, {"font": "Tahoma", "title_size": 26})

    paragraph = shape_for_id(
        themed_editor, first["slide_id"], first["named_shapes"]["title"]
    ).text_frame.paragraphs[0]
    assert paragraph.font.name == "Tahoma"
    assert paragraph.font.size.pt == 26


def test_update_slide_rejects_conflicting_delete_and_update(themed_editor):
    created = create_slide(
        themed_editor,
        shapes=[
            {
                "type": "text",
                "name": "title",
                "text": "X",
                "x": 1,
                "y": 1,
                "w": 4,
                "h": 1,
            }
        ],
    )

    with pytest.raises(ValueError, match="cannot be both updated and deleted"):
        update_slide(
            themed_editor,
            created["slide_id"],
            delete_shape_ids=[created["named_shapes"]["title"]],
            update_shapes=[
                {
                    "shape_id": created["named_shapes"]["title"],
                    "type": "text",
                    "text": "Y",
                }
            ],
        )


def test_create_slide_rejects_unknown_shape_type(themed_editor):
    with pytest.raises(ValueError, match="Unsupported shape type"):
        create_slide(themed_editor, shapes=[{"type": "unknown"}])


def test_missing_theme_token_raises_error(themed_editor):
    with pytest.raises(ValueError, match="has no token 'missing'"):
        create_slide(
            themed_editor,
            shapes=[
                {
                    "type": "text",
                    "text": "Broken",
                    "x": 1,
                    "y": 1,
                    "w": 4,
                    "h": 1,
                    "style": {"font_size_pt": "<missing>"},
                }
            ],
        )
