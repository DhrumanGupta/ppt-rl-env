import pytest

from src.tools.pptx_tools import (
    add_blank_slide,
    add_citation_block,
    add_chart_block,
    add_table_block,
    add_text_block,
    create_presentation,
    get_theme_preset,
)


def test_add_blank_slide_applies_background_and_accent_bar():
    editor = create_presentation()

    slide_index = add_blank_slide(
        editor, background_color="#112233", accent_color="#445566"
    )

    slide = editor.prs.slides[slide_index]
    assert str(slide.background.fill.fore_color.rgb) == "112233"
    assert len(slide.shapes) == 1
    assert str(slide.shapes[0].fill.fore_color.rgb) == "445566"


def test_add_text_block_creates_and_styles_textbox():
    editor = create_presentation()
    slide_index = add_blank_slide(editor)

    shape_index = add_text_block(
        editor,
        slide_index,
        "Hello world",
        1,
        1,
        4,
        1,
        font_name="Arial",
        font_size=20,
        color_hex="#123456",
        bold=True,
    )

    shape = editor.prs.slides[slide_index].shapes[shape_index]
    font = shape.text_frame.paragraphs[0].font
    assert shape.text_frame.text == "Hello world"
    assert font.name == "Arial"
    assert font.size.pt == 20
    assert font.bold is True
    assert str(font.color.rgb) == "123456"


def test_add_chart_block_returns_created_chart_shape_index():
    editor = create_presentation()
    slide_index = add_blank_slide(editor)

    shape_index = add_chart_block(
        editor,
        slide_index,
        "column_clustered",
        {"categories": ["A"], "series": [{"name": "S1", "values": [1]}]},
        1,
        1,
        4,
        3,
        style={"title": "Chart Title"},
    )

    shape = editor.prs.slides[slide_index].shapes[shape_index]
    assert shape.has_chart
    assert shape.chart.chart_title.text_frame.text == "Chart Title"


def test_add_table_block_infers_rows_and_cols_and_styles_table():
    editor = create_presentation()
    slide_index = add_blank_slide(editor)

    shape_index = add_table_block(
        editor,
        slide_index,
        [["H1", "H2"], ["V1"]],
        1,
        1,
        4,
        2,
        style={
            "header_fill_hex": "#000000",
            "body_fill_hex": "#EEEEEE",
            "header_font_color_hex": "#FFFFFF",
        },
    )

    table = editor.prs.slides[slide_index].shapes[shape_index].table
    assert len(table.rows) == 2
    assert len(table.columns) == 2
    assert table.cell(0, 0).text == "H1"
    assert table.cell(1, 0).text == "V1"
    assert str(table.cell(0, 0).fill.fore_color.rgb) == "000000"
    assert str(table.cell(1, 0).fill.fore_color.rgb) == "EEEEEE"


def test_add_table_block_rejects_empty_data():
    editor = create_presentation()
    slide_index = add_blank_slide(editor)

    with pytest.raises(ValueError, match="table_data must include"):
        add_table_block(editor, slide_index, [], 1, 1, 4, 2)


def test_add_citation_block_can_override_default_style():
    editor = create_presentation()
    slide_index = add_blank_slide(editor)

    shape_index = add_citation_block(
        editor,
        slide_index,
        "Source: Example",
        font_name="Georgia",
        font_size_pt=12,
        color_hex="#654321",
    )

    paragraph = (
        editor.prs.slides[slide_index].shapes[shape_index].text_frame.paragraphs[0]
    )
    assert paragraph.text == "Source: Example"
    assert paragraph.font.name == "Georgia"
    assert paragraph.font.size.pt == 12
    assert str(paragraph.font.color.rgb) == "654321"


def test_get_theme_preset_returns_copy_and_rejects_unknown_names():
    modern = get_theme_preset("modern_business")
    modern["accent"] = "#000000"

    assert get_theme_preset("modern_business")["accent"] == "#0F62FE"

    with pytest.raises(ValueError, match="Unknown theme preset"):
        get_theme_preset("missing")
