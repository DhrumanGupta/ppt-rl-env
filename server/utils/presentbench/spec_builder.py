from __future__ import annotations

import hashlib
import json

from server.utils.reward_models import (
    ChecklistItem,
    PresentBenchEvalSpec,
    TaskSpec,
    to_serializable,
)

SPEC_VERSION = "1.0"

DEFAULT_PRESENTBENCH_SCORING_CONFIG = {
    "dimension_weights": {
        "fundamentals": 0.20,
        "visual_layout": 0.20,
        "completeness": 0.20,
        "correctness": 0.20,
        "fidelity": 0.20,
    },
    "aesthetic_weight": 0.15,
    "hard_caps": {
        "blank_title_only_ratio_threshold": 0.4,
    },
    "soft_penalties": {
        "slide_count_violation": 0.02,
        "overlap": 0.01,
        "tiny_text": 0.01,
        "redundancy": 0.03,
        "wrong_slot_behavior": 0.02,
        "visual_sparsity": 0.30,
    },
}


def generate_checklist(task_spec: TaskSpec) -> list[ChecklistItem]:
    checklist: list[ChecklistItem] = [
        ChecklistItem(
            item_id="fundamentals_slide_count",
            dimension="fundamentals",
            prompt_text="Is the slide count within the requested range?",
            item_kind="slide_count_range",
        ),
        ChecklistItem(
            item_id="fundamentals_theme",
            dimension="fundamentals",
            prompt_text="Does the deck maintain a central theme aligned with the prompt?",
            item_kind="theme_alignment",
            relevant_sections=task_spec.required_sections,
        ),
        ChecklistItem(
            item_id="fundamentals_audience",
            dimension="fundamentals",
            prompt_text="Is the deck appropriate for the intended audience and tone?",
            item_kind="audience_tone",
        ),
        ChecklistItem(
            item_id="visual_readability",
            dimension="visual_layout",
            prompt_text="Is the text readable without tiny fonts?",
            item_kind="readable_text",
        ),
        ChecklistItem(
            item_id="visual_overlap",
            dimension="visual_layout",
            prompt_text="Are there no major overlaps or clipping risks?",
            item_kind="no_major_overlap",
        ),
        ChecklistItem(
            item_id="visual_consistency",
            dimension="visual_layout",
            prompt_text="Is the visual design reasonably consistent across slides?",
            item_kind="design_consistency",
        ),
    ]

    for index, section in enumerate(task_spec.required_sections, start=1):
        checklist.append(
            ChecklistItem(
                item_id=f"completeness_section_{index:02d}",
                dimension="completeness",
                prompt_text=f"Does the deck include a clear '{section}' section?",
                item_kind="required_section",
                relevant_sections=[section],
            )
        )

    for index, point in enumerate(task_spec.required_points, start=1):
        source_refs = [
            fact["ref"]
            for fact in task_spec.metadata.get("source_facts", [])
            if point in fact["text"]
        ][:2]
        checklist.append(
            ChecklistItem(
                item_id=f"completeness_point_{index:02d}",
                dimension="completeness",
                prompt_text=f"Does the deck cover this required point: {point}?",
                item_kind="required_point",
                source_refs=source_refs,
            )
        )
        checklist.append(
            ChecklistItem(
                item_id=f"correctness_point_{index:02d}",
                dimension="correctness",
                prompt_text=f"Is this required point stated correctly: {point}?",
                item_kind="correct_required_point",
                source_refs=source_refs,
            )
        )

    if task_spec.required_slides:
        for slide in task_spec.required_slides:
            checklist.append(
                ChecklistItem(
                    item_id=f"fidelity_slide_{slide.slide_index:02d}",
                    dimension="fidelity",
                    prompt_text=f"Is all content on Slide {slide.slide_index} supported by the source pack?",
                    item_kind="slide_fidelity",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                )
            )
    else:
        checklist.append(
            ChecklistItem(
                item_id="fidelity_deck",
                dimension="fidelity",
                prompt_text="Is all deck content supported by the source pack?",
                item_kind="deck_fidelity",
            )
        )

    return checklist


def generate_slide_checklists(task_spec: TaskSpec) -> dict[int, list[ChecklistItem]]:
    slide_checklists: dict[int, list[ChecklistItem]] = {}
    for slide in task_spec.required_slides or []:
        items = [
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_prompt_alignment",
                dimension="prompt_alignment",
                prompt_text=f"Does Slide {slide.slide_index} match the intended role '{slide.slide_role}'?",
                item_kind="slide_role_match",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_title_alignment",
                dimension="prompt_alignment",
                prompt_text=f"Is Slide {slide.slide_index} title aligned with '{slide.title_hint or slide.instructions}'?",
                item_kind="slide_title_alignment",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_fidelity",
                dimension="local_fidelity",
                prompt_text=f"Is all content on Slide {slide.slide_index} supported by the source pack?",
                item_kind="slide_fidelity",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
            ),
            ChecklistItem(
                item_id=f"slide_{slide.slide_index:02d}_usability",
                dimension="local_usability",
                prompt_text=f"Is Slide {slide.slide_index} readable and free of major clutter?",
                item_kind="slide_readability",
                required_slide_scope=[slide.slide_index],
                relevant_sections=[slide.slide_role],
            ),
        ]
        for point_index, point in enumerate(slide.required_points, start=1):
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_point_{point_index:02d}",
                    dimension="local_completeness",
                    prompt_text=f"Does Slide {slide.slide_index} cover this point: {point}?",
                    item_kind="slide_required_point",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                )
            )
        for exact_index, exact_value in enumerate(slide.required_exact_values, start=1):
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_exact_{exact_index:02d}",
                    dimension="local_correctness",
                    prompt_text=f"Does Slide {slide.slide_index} include the exact value '{exact_value}' correctly?",
                    item_kind="slide_exact_value",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                )
            )
        if slide.required_shape_kinds:
            items.append(
                ChecklistItem(
                    item_id=f"slide_{slide.slide_index:02d}_visual_kind",
                    dimension="local_completeness",
                    prompt_text=f"Does Slide {slide.slide_index} include the expected supported visual forms?",
                    item_kind="slide_required_visual",
                    required_slide_scope=[slide.slide_index],
                    relevant_sections=[slide.slide_role],
                )
            )
        slide_checklists[slide.slide_index] = items
    return slide_checklists


def build_presentbench_eval_spec(
    task_spec: TaskSpec, *, mode: str = "eval"
) -> PresentBenchEvalSpec:
    checklist = generate_checklist(task_spec)
    slide_checklists = generate_slide_checklists(task_spec)
    payload = {
        "task_spec": to_serializable(task_spec),
        "checklist": to_serializable(checklist),
        "slide_checklists": to_serializable(slide_checklists),
        "scoring_config": DEFAULT_PRESENTBENCH_SCORING_CONFIG,
        "spec_version": SPEC_VERSION,
    }
    spec_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return PresentBenchEvalSpec(
        task_spec=task_spec,
        checklist=checklist,
        slide_checklists=slide_checklists,
        scoring_config={**DEFAULT_PRESENTBENCH_SCORING_CONFIG, "mode": mode},
        spec_version=SPEC_VERSION,
        spec_hash=spec_hash,
    )


__all__ = [
    "DEFAULT_PRESENTBENCH_SCORING_CONFIG",
    "SPEC_VERSION",
    "build_presentbench_eval_spec",
    "generate_checklist",
    "generate_slide_checklists",
]
