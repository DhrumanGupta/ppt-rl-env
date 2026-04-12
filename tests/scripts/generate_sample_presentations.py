import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ppt_agent.server.tools.pptx_tools import (
    create_presentation,
    create_slide,
    register_theme,
    save_presentation,
)

OUTPUT_DIR = ROOT / "outputs" / "test_slides"


def build_modern_business_deck(output_path: Path):
    editor = create_presentation()
    register_theme(
        editor,
        {
            "bg": "#F6F9FC",
            "surface": "#FFFFFF",
            "accent": "#0F62FE",
            "primary": "#102A43",
            "secondary": "#486581",
            "font": "Aptos",
            "title_size": 28,
            "section_size": 22,
            "body_size": 16,
            "summary_size": 18,
            "chart_title_size": 18,
            "table_header_size": 14,
            "table_body_size": 12,
            "citation_size": 10,
        },
    )

    create_slide(
        editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "name": "accent", "color_hex": "<accent>"},
            {
                "type": "text",
                "name": "title",
                "text": "Northstar Growth Plan 2026",
                "x": 0.9,
                "y": 0.8,
                "w": 10.5,
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
                "text": "A focused strategy for revenue expansion, retention, and operational leverage.",
                "x": 0.9,
                "y": 1.8,
                "w": 10.5,
                "h": 0.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Executive Summary",
                "x": 0.8,
                "y": 0.7,
                "w": 4.5,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "text",
                "text": "Expand into two adjacent verticals\nRaise enterprise retention from 88% to 93%\nReduce onboarding time by 35% with automation",
                "x": 0.9,
                "y": 1.6,
                "w": 6.0,
                "h": 2.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<summary_size>",
                    "color_hex": "<secondary>",
                },
            },
            {
                "type": "text",
                "text": "Source: Internal planning memo, Q1 2026",
                "x": 0.5,
                "y": 6.8,
                "w": 9.0,
                "h": 0.4,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<citation_size>",
                    "color_hex": "<secondary>",
                    "italic": True,
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Quarterly Revenue Outlook",
                "x": 0.8,
                "y": 0.7,
                "w": 5.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "chart",
                "name": "revenue_chart",
                "chart_type": "column_clustered",
                "chart_data": {
                    "categories": ["Q1", "Q2", "Q3", "Q4"],
                    "series": [
                        {"name": "Baseline", "values": [18, 21, 23, 25]},
                        {"name": "Target", "values": [19, 24, 28, 32]},
                    ],
                },
                "x": 0.9,
                "y": 1.6,
                "w": 7.5,
                "h": 4.1,
                "style": {
                    "title": "Revenue trajectory ($M)",
                    "title_font_name": "<font>",
                    "title_font_size_pt": "<chart_title_size>",
                    "title_bold": True,
                    "title_color_hex": "<primary>",
                    "legend_font_name": "<font>",
                    "legend_font_size_pt": "<table_body_size>",
                    "legend_color_hex": "<secondary>",
                    "axis_font_name": "<font>",
                    "axis_font_size_pt": "<table_body_size>",
                    "axis_color_hex": "<secondary>",
                    "series_colors": ["<secondary>", "<accent>"],
                },
            },
            {
                "type": "text",
                "text": "Target upside comes from enterprise upsell and partner-sourced pipeline.",
                "x": 8.7,
                "y": 2.0,
                "w": 3.2,
                "h": 1.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Key Initiatives",
                "x": 0.8,
                "y": 0.7,
                "w": 4.5,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "table",
                "table_data": [
                    ["Initiative", "Owner", "Impact"],
                    ["Pricing refresh", "Revenue Ops", "+6% ARR"],
                    ["Guided onboarding", "Product", "-35% setup time"],
                    ["Partner motion", "Sales", "+$4M pipeline"],
                ],
                "x": 0.9,
                "y": 1.6,
                "w": 8.5,
                "h": 2.5,
                "style": {
                    "header_fill_hex": "<accent>",
                    "body_fill_hex": "#EAF2FF",
                    "header_font_name": "<font>",
                    "body_font_name": "<font>",
                    "header_font_size_pt": "<table_header_size>",
                    "body_font_size_pt": "<table_body_size>",
                    "header_font_color_hex": "#FFFFFF",
                    "body_font_color_hex": "<primary>",
                },
            },
        ],
    )

    save_presentation(editor, output_path)


def build_dark_analytics_deck(output_path: Path):
    editor = create_presentation()
    register_theme(
        editor,
        {
            "bg": "#0B1020",
            "surface": "#131A2A",
            "accent": "#4FD1C5",
            "primary": "#F7FAFC",
            "secondary": "#A0AEC0",
            "warm": "#F6AD55",
            "font": "Aptos Display",
            "title_size": 30,
            "section_size": 22,
            "body_size": 16,
            "summary_size": 18,
            "chart_title_size": 18,
            "table_header_size": 14,
            "table_body_size": 12,
            "citation_size": 10,
        },
    )

    create_slide(
        editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Platform Reliability Deep Dive",
                "x": 0.8,
                "y": 0.9,
                "w": 8.5,
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
                "text": "Telemetry review of latency, incident rate, and regional capacity.",
                "x": 0.8,
                "y": 1.9,
                "w": 9.0,
                "h": 0.7,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "System Status Snapshot",
                "x": 0.8,
                "y": 0.7,
                "w": 5.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "text",
                "text": "Median latency improved by 18%\nError budget burn stabilized after week 6\nEU capacity remains the main scaling constraint",
                "x": 0.9,
                "y": 1.6,
                "w": 5.8,
                "h": 2.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<summary_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Incident Trend by Month",
                "x": 0.8,
                "y": 0.7,
                "w": 5.0,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "chart",
                "chart_type": "line_markers",
                "chart_data": {
                    "categories": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
                    "series": [
                        {"name": "P1 incidents", "values": [9, 8, 7, 5, 4, 3]},
                        {"name": "P2 incidents", "values": [18, 17, 15, 13, 11, 10]},
                    ],
                },
                "x": 0.9,
                "y": 1.6,
                "w": 7.2,
                "h": 4.2,
                "style": {
                    "title": "Monthly incident volume",
                    "title_font_name": "<font>",
                    "title_font_size_pt": "<chart_title_size>",
                    "title_bold": True,
                    "title_color_hex": "<primary>",
                    "legend_font_name": "<font>",
                    "legend_font_size_pt": "<table_body_size>",
                    "legend_color_hex": "<secondary>",
                    "axis_font_name": "<font>",
                    "axis_font_size_pt": "<table_body_size>",
                    "axis_color_hex": "<secondary>",
                    "series_colors": ["<accent>", "<warm>"],
                },
            },
            {
                "type": "text",
                "text": "The reliability program is reducing both severity and recurrence.",
                "x": 8.5,
                "y": 2.1,
                "w": 3.2,
                "h": 1.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Regional Capacity Allocation",
                "x": 0.8,
                "y": 0.7,
                "w": 5.3,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "table",
                "table_data": [
                    ["Region", "Utilization", "Headroom"],
                    ["US-East", "68%", "High"],
                    ["EU-West", "87%", "Low"],
                    ["APAC", "59%", "Medium"],
                ],
                "x": 0.9,
                "y": 1.6,
                "w": 8.0,
                "h": 2.5,
                "style": {
                    "header_fill_hex": "<accent>",
                    "body_fill_hex": "#1B2437",
                    "header_font_name": "<font>",
                    "body_font_name": "<font>",
                    "header_font_size_pt": "<table_header_size>",
                    "body_font_size_pt": "<table_body_size>",
                    "header_font_color_hex": "<bg>",
                    "body_font_color_hex": "<primary>",
                },
            },
            {
                "type": "text",
                "text": "Source: Weekly reliability metrics",
                "x": 0.5,
                "y": 6.8,
                "w": 9.0,
                "h": 0.4,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<citation_size>",
                    "color_hex": "<secondary>",
                    "italic": True,
                },
            },
        ],
    )

    save_presentation(editor, output_path)


def build_academic_report_deck(output_path: Path):
    editor = create_presentation()
    register_theme(
        editor,
        {
            "bg": "#F8F5EF",
            "surface": "#FFFDF9",
            "accent": "#7A5C3E",
            "primary": "#2D241D",
            "secondary": "#6B5B4D",
            "support": "#A3B18A",
            "font": "Georgia",
            "title_size": 28,
            "section_size": 22,
            "body_size": 16,
            "summary_size": 18,
            "chart_title_size": 18,
            "table_header_size": 14,
            "table_body_size": 12,
            "citation_size": 10,
        },
    )

    create_slide(
        editor,
        background_color="<bg>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Urban Tree Canopy Study",
                "x": 0.9,
                "y": 0.9,
                "w": 8.0,
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
                "text": "Findings from a five-year survey of neighborhood heat resilience.",
                "x": 0.9,
                "y": 1.9,
                "w": 8.8,
                "h": 0.7,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                    "italic": True,
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Research Questions",
                "x": 0.8,
                "y": 0.7,
                "w": 4.5,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "text",
                "text": "How does canopy density affect surface temperature?\nWhich districts show the largest seasonal benefit?\nWhat investments provide the fastest public-health return?",
                "x": 0.9,
                "y": 1.6,
                "w": 6.3,
                "h": 2.8,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<summary_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Cooling Effect by District",
                "x": 0.8,
                "y": 0.7,
                "w": 5.2,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "chart",
                "chart_type": "bar_clustered",
                "chart_data": {
                    "categories": ["North", "Central", "South", "West"],
                    "series": [
                        {"name": "Tree cover %", "values": [32, 24, 18, 28]},
                        {"name": "Temp reduction", "values": [5.1, 3.8, 2.6, 4.4]},
                    ],
                },
                "x": 0.9,
                "y": 1.6,
                "w": 7.4,
                "h": 4.0,
                "style": {
                    "title": "Canopy coverage and cooling effect",
                    "title_font_name": "<font>",
                    "title_font_size_pt": "<chart_title_size>",
                    "title_bold": True,
                    "title_color_hex": "<primary>",
                    "legend_font_name": "<font>",
                    "legend_font_size_pt": "<table_body_size>",
                    "legend_color_hex": "<secondary>",
                    "axis_font_name": "<font>",
                    "axis_font_size_pt": "<table_body_size>",
                    "axis_color_hex": "<secondary>",
                    "series_colors": ["<accent>", "<support>"],
                },
            },
            {
                "type": "text",
                "text": "Higher canopy density consistently corresponds to lower peak pavement temperature.",
                "x": 8.6,
                "y": 2.0,
                "w": 3.0,
                "h": 2.0,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<body_size>",
                    "color_hex": "<secondary>",
                },
            },
        ],
    )

    create_slide(
        editor,
        background_color="<surface>",
        shapes=[
            {"type": "accent_bar", "color_hex": "<accent>"},
            {
                "type": "text",
                "text": "Field Sample Summary",
                "x": 0.8,
                "y": 0.7,
                "w": 4.5,
                "h": 0.6,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<section_size>",
                    "color_hex": "<primary>",
                    "bold": True,
                },
            },
            {
                "type": "table",
                "table_data": [
                    ["District", "Sites", "Avg canopy"],
                    ["North", "18", "32%"],
                    ["Central", "21", "24%"],
                    ["South", "16", "18%"],
                ],
                "x": 0.9,
                "y": 1.6,
                "w": 7.6,
                "h": 2.5,
                "style": {
                    "header_fill_hex": "<accent>",
                    "body_fill_hex": "#EFE7DA",
                    "header_font_name": "<font>",
                    "body_font_name": "<font>",
                    "header_font_size_pt": "<table_header_size>",
                    "body_font_size_pt": "<table_body_size>",
                    "header_font_color_hex": "<surface>",
                    "body_font_color_hex": "<primary>",
                },
            },
            {
                "type": "text",
                "text": "Source: Urban Ecology Lab, field survey dataset",
                "x": 0.5,
                "y": 6.8,
                "w": 9.0,
                "h": 0.4,
                "style": {
                    "font_name": "<font>",
                    "font_size_pt": "<citation_size>",
                    "color_hex": "<secondary>",
                    "italic": True,
                },
            },
        ],
    )

    save_presentation(editor, output_path)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_paths = [
        OUTPUT_DIR / "presentation_modern_business.pptx",
        OUTPUT_DIR / "presentation_dark_analytics.pptx",
        OUTPUT_DIR / "presentation_academic_report.pptx",
    ]

    build_modern_business_deck(output_paths[0])
    build_dark_analytics_deck(output_paths[1])
    build_academic_report_deck(output_paths[2])

    for path in output_paths:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
