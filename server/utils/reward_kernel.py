from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from pptx.presentation import Presentation as PptxPresentation

from server.utils.pptx_functions import PptxEditor
from server.utils.reward_inspection import PresentationInspectionService
from server.utils.reward_metrics import (
    clamp,
    compute_aesthetics_scores,
    compute_overlap_ratio,
    compute_presentation_diagnostics,
    is_blank_or_title_only,
    mean_scores_by_dimension,
    redundancy_score,
    score_checklist_item,
    score_slide_checklist_item,
    slide_text_corpus,
    text_match_score,
)
from server.utils.reward_models import (
    EvalSpec,
    IntermediateSlideRewardResult,
    PresentationExtraction,
    PresentationSemanticIndex,
    RewardResult,
    SlideExtraction,
    SourcePack,
    TaskConstraints,
    to_serializable,
)
from server.utils.reward_quizbank_service import QuizBankGenerationService
from server.utils.reward_prompts import build_eval_spec_payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _persist_eval_spec(cache_dir: str, eval_spec: EvalSpec) -> dict[str, str]:
    root = Path(cache_dir) / eval_spec.spec_hash
    root.mkdir(parents=True, exist_ok=True)
    task_spec_path = root / "task_spec.json"
    checklist_path = root / "checklist.json"
    slide_checklists_path = root / "slide_checklists.json"
    quiz_bank_path = root / "quiz_bank.json"
    scoring_config_path = root / "scoring_config.json"
    eval_spec_path = root / "eval_spec.json"

    _write_json(task_spec_path, to_serializable(eval_spec.task_spec))
    _write_json(checklist_path, to_serializable(eval_spec.checklist))
    _write_json(slide_checklists_path, to_serializable(eval_spec.slide_checklists))
    _write_json(quiz_bank_path, to_serializable(eval_spec.quiz_bank))
    _write_json(scoring_config_path, eval_spec.scoring_config)
    _write_json(eval_spec_path, to_serializable(eval_spec))
    return {
        "cache_root": str(root),
        "task_spec": str(task_spec_path),
        "checklist": str(checklist_path),
        "slide_checklists": str(slide_checklists_path),
        "quiz_bank": str(quiz_bank_path),
        "scoring_config": str(scoring_config_path),
        "eval_spec": str(eval_spec_path),
    }


def build_eval_spec(
    prompt: str,
    source_pack: SourcePack,
    task_constraints: TaskConstraints | None = None,
    *,
    quiz_bank_service: QuizBankGenerationService,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> EvalSpec:
    if not source_pack.task_id:
        raise ValueError("source_pack.task_id is required")
    if not source_pack.documents:
        raise ValueError("source_pack.documents must not be empty")

    eval_spec = build_eval_spec_payload(
        prompt,
        source_pack,
        task_constraints,
        quiz_bank_service=quiz_bank_service,
        mode=mode,
    )
    eval_spec.scoring_config = {
        **eval_spec.scoring_config,
        "mode": mode,
    }
    if cache_dir:
        artifact_paths = _persist_eval_spec(cache_dir, eval_spec)
        eval_spec.task_spec.metadata["cache_artifacts"] = artifact_paths
    return eval_spec


def _score_quiz_bank(
    eval_spec: EvalSpec,
    presentation_extraction: PresentationExtraction,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    deck_text = "\n".join(
        slide_text_corpus(slide) for slide in presentation_extraction.slides
    )
    quiz_results: list[dict[str, Any]] = []
    concept_correct = 0
    concept_total = 0
    data_correct = 0
    data_total = 0

    for question in eval_spec.quiz_bank:
        correct = False
        if question.question_type == "data":
            data_total += 1
            correct = question.correct_answer in deck_text
            data_correct += int(correct)
        else:
            concept_total += 1
            correct = text_match_score(deck_text, question.correct_answer) >= 0.6
            concept_correct += int(correct)
        quiz_results.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "selected_answer": question.correct_answer if correct else None,
                "correct": correct,
                "reasoning": "deterministic slides-only answer matching",
            }
        )

    s_quiz_concept = (concept_correct / concept_total) if concept_total else 0.0
    s_quiz_data = (data_correct / data_total) if data_total else 0.0
    s_quiz = 0.5 * s_quiz_concept + 0.5 * s_quiz_data
    return quiz_results, {
        "S_quiz": s_quiz,
        "S_quiz_concept": s_quiz_concept,
        "S_quiz_data": s_quiz_data,
    }


def _reward_result_for_failure(
    eval_spec: EvalSpec,
    *,
    error: Exception,
    mode: str,
) -> RewardResult:
    return RewardResult(
        reward_total=0.0,
        reward_breakdown={
            "R_total": 0.0,
            "R_pb": 0.0,
            "R_sg": 0.0,
            "S_fundamentals": 0.0,
            "S_visual_layout": 0.0,
            "S_completeness": 0.0,
            "S_correctness": 0.0,
            "S_fidelity": 0.0,
            "S_quiz": 0.0,
            "S_quiz_concept": 0.0,
            "S_quiz_data": 0.0,
            "S_aesthetic": 0.0,
            "S_harmony": 0.0,
            "S_engagement": 0.0,
            "S_usability": 0.0,
            "S_rhythm": 0.0,
            "deterministic_visual_score": 0.0,
        },
        hard_caps={
            "C_open": 0.0,
            "C_safety": 1.0,
            "C_fidelity_critical": 1.0,
            "C_blankness": 1.0,
            "C_hard": 0.0,
        },
        soft_penalties={},
        checklist_results=[],
        quiz_results=[],
        aesthetics_results={},
        artifacts={},
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "spec_hash": eval_spec.spec_hash,
            "spec_version": eval_spec.spec_version,
            "mode": mode,
            "used_mllm": False,
            "failure_counts": {"inspection": 1},
            "error": str(error),
        },
    )


def evaluate_presentation(
    eval_spec: EvalSpec,
    presentation: PptxEditor | PptxPresentation | str,
    *,
    use_mllm: bool = False,
    presentation_semantics: PresentationSemanticIndex | None = None,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: Any | None = None,
    mode: str = "eval",
) -> RewardResult:
    del judge, render_service
    inspection_service = inspection_service or PresentationInspectionService()

    try:
        presentation_extraction = inspection_service.inspect_presentation(
            presentation,
            presentation_semantics=presentation_semantics,
        )
    except Exception as error:
        return _reward_result_for_failure(eval_spec, error=error, mode=mode)

    diagnostics = compute_presentation_diagnostics(
        presentation_extraction,
        eval_spec.task_spec,
    )
    checklist_results = [
        score_checklist_item(item, presentation_extraction, eval_spec.task_spec)
        for item in eval_spec.checklist
    ]
    dimension_scores = mean_scores_by_dimension(checklist_results)
    aesthetics_scores = (
        aesthetics_service.score_presentation(presentation_extraction)
        if aesthetics_service and hasattr(aesthetics_service, "score_presentation")
        else compute_aesthetics_scores(presentation_extraction)
    )
    quiz_results, quiz_scores = _score_quiz_bank(eval_spec, presentation_extraction)

    s_fund = dimension_scores.get("fundamentals", 0.0)
    s_visual = dimension_scores.get("visual_layout", 0.0)
    s_complete = dimension_scores.get("completeness", 0.0)
    s_correct = dimension_scores.get("correctness", 0.0)
    s_fidelity = dimension_scores.get("fidelity", 0.0)

    r_pb = (
        0.15 * s_fund
        + 0.10 * s_visual
        + 0.20 * s_complete
        + 0.25 * s_correct
        + 0.30 * s_fidelity
    )
    r_sg = 0.55 * quiz_scores["S_quiz"] + 0.45 * aesthetics_scores["aesthetic"]

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
    reward_total = clamp(c_hard * (0.60 * r_pb + 0.40 * r_sg) - p_soft)

    return RewardResult(
        reward_total=reward_total,
        reward_breakdown={
            "R_total": reward_total,
            "R_pb": r_pb,
            "R_sg": r_sg,
            "S_fundamentals": s_fund,
            "S_visual_layout": s_visual,
            "S_completeness": s_complete,
            "S_correctness": s_correct,
            "S_fidelity": s_fidelity,
            "S_quiz": quiz_scores["S_quiz"],
            "S_quiz_concept": quiz_scores["S_quiz_concept"],
            "S_quiz_data": quiz_scores["S_quiz_data"],
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
        quiz_results=quiz_results,
        aesthetics_results=aesthetics_scores,
        artifacts={
            "presentation_digest": presentation_extraction.metadata.get(
                "presentation_digest"
            ),
        },
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "spec_hash": eval_spec.spec_hash,
            "spec_version": eval_spec.spec_version,
            "mode": mode,
            "slide_count": presentation_extraction.slide_count,
            "item_count": len(eval_spec.checklist),
            "question_count": len(eval_spec.quiz_bank),
            "judge_call_count": 0,
            "failure_counts": {"inspection": 0, "judge": 0, "render": 0},
            "used_mllm": use_mllm,
            "inspection_mode": presentation_extraction.metadata.get("inspection_mode"),
            "presentation_digest": presentation_extraction.metadata.get(
                "presentation_digest"
            ),
        },
    )


def _low_out_of_range_slide_result(
    eval_spec: EvalSpec,
    slide_index: int,
    *,
    mode: str,
) -> IntermediateSlideRewardResult:
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
        soft_penalties={},
        checklist_results=[],
        aesthetics_results={},
        artifacts={},
        metadata={
            "slide_index": slide_index,
            "spec_hash": eval_spec.spec_hash,
            "mode": mode,
            "out_of_range": True,
        },
    )


def evaluate_slide(
    eval_spec: EvalSpec,
    slide_index: int,
    *,
    presentation: PptxEditor | PptxPresentation | None = None,
    slide_extraction: SlideExtraction | None = None,
    presentation_semantics: PresentationSemanticIndex | None = None,
    use_mllm: bool = False,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: Any | None = None,
    previous_slide_extractions: list[SlideExtraction] | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    del judge, render_service, aesthetics_service
    target_slides = {
        slide.slide_index: slide for slide in eval_spec.task_spec.required_slides or []
    }
    target_slide = target_slides.get(slide_index)
    if target_slide is None:
        return _low_out_of_range_slide_result(eval_spec, slide_index, mode=mode)

    inspection_service = inspection_service or PresentationInspectionService()
    try:
        if slide_extraction is None:
            if presentation is None:
                raise ValueError("presentation or slide_extraction is required")
            slide_extraction = inspection_service.inspect_slide(
                slide_index,
                presentation=presentation,
                presentation_semantics=presentation_semantics,
            )
    except Exception as error:
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
                "C_slide_open": 0.0,
                "C_slide_safety": 1.0,
                "C_slide_fidelity_critical": 1.0,
                "C_slide_blankness": 1.0,
                "C_slide_hard": 0.0,
            },
            metadata={
                "slide_index": slide_index,
                "spec_hash": eval_spec.spec_hash,
                "mode": mode,
                "error": str(error),
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
            eval_spec.task_spec,
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


def compute_presentation_reward(
    prompt: str,
    source_pack: SourcePack,
    presentation: PptxEditor | PptxPresentation | str,
    *,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    presentation_semantics: PresentationSemanticIndex | None = None,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: Any | None = None,
    quiz_bank_service: QuizBankGenerationService,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> RewardResult:
    eval_spec = build_eval_spec(
        prompt,
        source_pack,
        task_constraints,
        cache_dir=cache_dir,
        mode=mode,
        quiz_bank_service=quiz_bank_service,
    )
    return evaluate_presentation(
        eval_spec,
        presentation,
        use_mllm=use_mllm,
        presentation_semantics=presentation_semantics,
        judge=judge,
        render_service=render_service,
        inspection_service=inspection_service,
        aesthetics_service=aesthetics_service,
        mode=mode,
    )


def compute_intermediate_slide_reward(
    prompt: str,
    source_pack: SourcePack,
    *,
    slide_index: int,
    presentation: PptxEditor | PptxPresentation | None = None,
    slide_extraction: SlideExtraction | None = None,
    presentation_semantics: PresentationSemanticIndex | None = None,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: Any | None = None,
    previous_slide_extractions: list[SlideExtraction] | None = None,
    quiz_bank_service: QuizBankGenerationService,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    eval_spec = build_eval_spec(
        prompt,
        source_pack,
        task_constraints,
        cache_dir=cache_dir,
        mode=mode,
        quiz_bank_service=quiz_bank_service,
    )
    return evaluate_slide(
        eval_spec,
        slide_index,
        presentation=presentation,
        slide_extraction=slide_extraction,
        presentation_semantics=presentation_semantics,
        use_mllm=use_mllm,
        judge=judge,
        render_service=render_service,
        inspection_service=inspection_service,
        aesthetics_service=aesthetics_service,
        previous_slide_extractions=previous_slide_extractions,
        mode=mode,
    )


__all__ = [
    "build_eval_spec",
    "compute_intermediate_slide_reward",
    "compute_presentation_reward",
    "evaluate_presentation",
    "evaluate_slide",
]
