from __future__ import annotations

from typing import Any

from server.utils.presentbench.metrics import (
    compute_aesthetics_scores,
    compute_presentation_diagnostics,
    mean_scores_by_dimension,
    redundancy_score,
    score_checklist_item,
    score_slide_checklist_item,
)
from server.utils.reward_metrics import (
    clamp,
    compute_overlap_ratio,
    is_blank_or_title_only,
)
from server.utils.reward_models import (
    IntermediateSlideRewardResult,
    PresentBenchEvalSpec,
    PresentBenchScoreResult,
    ExtractedPresentation,
    ExtractedSlide,
    TaskSpec,
)


def score_presentbench(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    eval_spec: PresentBenchEvalSpec,
    *,
    aesthetics_service: Any | None = None,
) -> PresentBenchScoreResult:
    diagnostics = compute_presentation_diagnostics(presentation_extraction, task_spec)
    checklist_results = [
        score_checklist_item(item, presentation_extraction, task_spec)
        for item in eval_spec.checklist
    ]
    dimension_scores = mean_scores_by_dimension(checklist_results)
    aesthetics_scores = (
        aesthetics_service.score_presentation(presentation_extraction)
        if aesthetics_service and hasattr(aesthetics_service, "score_presentation")
        else compute_aesthetics_scores(presentation_extraction)
    )

    s_fund = dimension_scores.get("fundamentals", 0.0)
    s_visual = dimension_scores.get("visual_layout", 0.0)
    s_complete = dimension_scores.get("completeness", 0.0)
    s_correct = dimension_scores.get("correctness", 0.0)
    s_fidelity = dimension_scores.get("fidelity", 0.0)

    dimension_weights = eval_spec.scoring_config["dimension_weights"]
    r_pb = (
        dimension_weights["fundamentals"] * s_fund
        + dimension_weights["visual_layout"] * s_visual
        + dimension_weights["completeness"] * s_complete
        + dimension_weights["correctness"] * s_correct
        + dimension_weights["fidelity"] * s_fidelity
    )

    c_open = 1.0
    c_safety = 1.0
    c_fidelity_critical = (
        0.5
        if s_fidelity < 1.0
        and any(
            result["dimension"] == "fidelity" and result["verdict"] == "no"
            for result in checklist_results
        )
        else 1.0
    )
    blankness_threshold = eval_spec.scoring_config["hard_caps"][
        "blank_title_only_ratio_threshold"
    ]
    c_blankness = (
        0.6 if diagnostics["blank_title_only_ratio"] > blankness_threshold else 1.0
    )
    c_hard = min(c_open, c_safety, c_fidelity_critical, c_blankness)

    penalty_config = eval_spec.scoring_config["soft_penalties"]
    soft_penalties = {
        "slide_count_violation": penalty_config["slide_count_violation"]
        * diagnostics["slide_count_violation"],
        "overlap": penalty_config["overlap"] * diagnostics["max_overlap_ratio"],
        "missing_citations": penalty_config["missing_citations"]
        * max(0.0, 1.0 - diagnostics["citation_coverage_ratio"]),
        "tiny_text": penalty_config["tiny_text"]
        * (
            1.0
            if diagnostics["min_font_size_pt"] is not None
            and diagnostics["min_font_size_pt"] < 10
            else 0.0
        ),
    }
    p_soft = sum(soft_penalties.values())
    aesthetic_weight = eval_spec.scoring_config.get("aesthetic_weight", 0.15)
    reward_total = clamp(
        c_hard
        * (
            (1.0 - aesthetic_weight) * r_pb
            + aesthetic_weight * aesthetics_scores["aesthetic"]
        )
        - p_soft
    )

    return PresentBenchScoreResult(
        reward_total=reward_total,
        reward_breakdown={
            "R_pb": reward_total,
            "S_fundamentals": s_fund,
            "S_visual_layout": s_visual,
            "S_completeness": s_complete,
            "S_correctness": s_correct,
            "S_fidelity": s_fidelity,
            "S_aesthetic": aesthetics_scores["aesthetic"],
            "S_harmony": aesthetics_scores["harmony"],
            "S_engagement": aesthetics_scores["engagement"],
            "S_usability": aesthetics_scores["usability"],
            "S_rhythm": aesthetics_scores["rhythm"],
            "deterministic_visual_score": s_visual,
        },
        hard_caps={
            "C_open": c_open,
            "C_safety": c_safety,
            "C_fidelity_critical": c_fidelity_critical,
            "C_blankness": c_blankness,
            "C_hard": c_hard,
        },
        soft_penalties=soft_penalties,
        checklist_results=checklist_results,
        aesthetics_results=aesthetics_scores,
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "item_count": len(eval_spec.checklist),
            "slide_count": presentation_extraction.slide_count,
            "spec_hash": eval_spec.spec_hash,
        },
    )


def score_presentbench_slide(
    task_spec: TaskSpec,
    eval_spec: PresentBenchEvalSpec,
    slide_index: int,
    slide_extraction: ExtractedSlide,
    *,
    previous_slide_extractions: list[ExtractedSlide] | None = None,
    use_mllm: bool = False,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    target_slides = {
        slide.slide_index: slide for slide in task_spec.required_slides or []
    }
    target_slide = target_slides.get(slide_index)
    if target_slide is None:
        return IntermediateSlideRewardResult(
            slide_index=slide_index,
            reward_total=0.0,
            reward_breakdown={
                "R_slide": 0.0,
                "S_prompt_alignment": 0.0,
                "S_local_completeness": 0.0,
                "S_local_correctness": 0.0,
                "S_local_fidelity": 0.0,
                "S_local_usability": 0.0,
            },
            hard_caps={
                "C_slide_open": 1.0,
                "C_slide_safety": 1.0,
                "C_slide_fidelity_critical": 1.0,
                "C_slide_blankness": 1.0,
                "C_slide_hard": 1.0,
            },
            metadata={
                "slide_index": slide_index,
                "spec_hash": eval_spec.spec_hash,
                "mode": mode,
                "out_of_range": True,
            },
        )

    slide_checklist = eval_spec.slide_checklists.get(slide_index, [])
    checklist_results = [
        score_slide_checklist_item(
            item,
            slide_extraction,
            target_slide.slide_role,
            target_slide.title_hint,
            target_slide.required_points,
            target_slide.required_exact_values,
            target_slide.required_shape_kinds,
            task_spec,
        )
        for item in slide_checklist
    ]
    dimension_scores = mean_scores_by_dimension(checklist_results)

    s_prompt_alignment = dimension_scores.get("prompt_alignment", 0.0)
    s_local_completeness = dimension_scores.get("local_completeness", 0.0)
    s_local_correctness = dimension_scores.get("local_correctness", 0.0)
    s_local_fidelity = dimension_scores.get("local_fidelity", 0.0)
    s_local_usability = dimension_scores.get("local_usability", 0.0)

    c_slide_open = 1.0
    c_slide_safety = 1.0
    c_slide_fidelity_critical = (
        0.5 if (s_local_fidelity < 1.0 and target_slide.required_exact_values) else 1.0
    )
    c_slide_blankness = (
        0.4
        if is_blank_or_title_only(slide_extraction) and target_slide.required_points
        else 1.0
    )
    c_slide_hard = min(
        c_slide_open, c_slide_safety, c_slide_fidelity_critical, c_slide_blankness
    )

    penalty_config = eval_spec.scoring_config["soft_penalties"]
    overlap = compute_overlap_ratio(slide_extraction)
    min_font = slide_extraction.text_metrics.get("min_font_size_pt")
    redundancy = redundancy_score(slide_extraction, previous_slide_extractions)
    missing_citation = float(
        target_slide.citation_required and not slide_extraction.citations
    )
    wrong_slot_behavior = 0.0 if s_prompt_alignment >= 1.0 else 1.0

    soft_penalties = {
        "missing_citation": penalty_config["redundancy"] * 0.0
        + 0.03 * missing_citation,
        "redundancy": penalty_config["redundancy"] * redundancy,
        "wrong_slot_behavior": penalty_config["wrong_slot_behavior"]
        * wrong_slot_behavior,
        "tiny_text": 0.02 * (1.0 if min_font is not None and min_font < 10 else 0.0),
        "overlap": 0.02 * overlap,
    }
    p_slide_soft = sum(soft_penalties.values())
    reward_total = clamp(
        c_slide_hard
        * (
            0.35 * s_prompt_alignment
            + 0.20 * s_local_completeness
            + 0.15 * s_local_correctness
            + 0.20 * s_local_fidelity
            + 0.10 * s_local_usability
        )
        - p_slide_soft
    )

    return IntermediateSlideRewardResult(
        slide_index=slide_index,
        reward_total=reward_total,
        reward_breakdown={
            "R_slide": reward_total,
            "S_prompt_alignment": s_prompt_alignment,
            "S_local_completeness": s_local_completeness,
            "S_local_correctness": s_local_correctness,
            "S_local_fidelity": s_local_fidelity,
            "S_local_usability": s_local_usability,
        },
        hard_caps={
            "C_slide_open": c_slide_open,
            "C_slide_safety": c_slide_safety,
            "C_slide_fidelity_critical": c_slide_fidelity_critical,
            "C_slide_blankness": c_slide_blankness,
            "C_slide_hard": c_slide_hard,
        },
        soft_penalties=soft_penalties,
        checklist_results=checklist_results,
        aesthetics_results={},
        artifacts={},
        metadata={
            "slide_index": slide_index,
            "slide_id": slide_extraction.slide_id,
            "target_slide_role": target_slide.slide_role,
            "target_title_hint": target_slide.title_hint,
            "required_points": target_slide.required_points,
            "judge_call_count": 0,
            "used_previous_slide_context": previous_slide_extractions is not None,
            "used_mllm": use_mllm,
            "spec_hash": eval_spec.spec_hash,
            "mode": mode,
        },
    )


__all__ = ["score_presentbench", "score_presentbench_slide"]
