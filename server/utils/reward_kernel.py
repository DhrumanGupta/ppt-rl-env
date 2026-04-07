from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pptx.presentation import Presentation as PptxPresentation

from server.utils.pptx_functions import PptxEditor
from server.utils.presentbench.scoring import (
    score_presentbench,
    score_presentbench_slide,
)
from server.utils.presentbench.spec_builder import build_presentbench_eval_spec
from server.utils.pptx_extraction import PptxExtractionService
from server.utils.reward_metrics import clamp
from server.utils.reward_models import (
    EvalSpec,
    IntermediateSlideRewardResult,
    RewardResult,
    ExtractedSlide,
    SourcePack,
    TaskConstraints,
    to_serializable,
)
from server.utils.reward_prompts import build_task_spec
from server.utils.slidesgenbench.quizbank_service import QuizBankGenerationService
from server.utils.slidesgenbench.quantitative_judge import (
    QuantitativeQuizJudgeService,
)
from server.utils.slidesgenbench.scoring import score_slidesgenbench
from server.utils.slidesgenbench.spec_builder import build_slidesgenbench_eval_spec

SPEC_VERSION = "1.0"

DEFAULT_REWARD_KERNEL_CONFIG: dict[str, Any] = {
    "branch_weights": {"presentbench": 0.6, "slidesgenbench": 0.4},
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _persist_eval_spec(cache_dir: str, eval_spec: EvalSpec) -> dict[str, str]:
    root = Path(cache_dir) / eval_spec.spec_hash
    root.mkdir(parents=True, exist_ok=True)
    task_spec_path = root / "task_spec.json"
    presentbench_path = root / "presentbench_eval_spec.json"
    slidesgenbench_path = root / "slidesgenbench_eval_spec.json"
    scoring_config_path = root / "scoring_config.json"
    eval_spec_path = root / "eval_spec.json"

    _write_json(task_spec_path, to_serializable(eval_spec.task_spec))
    _write_json(presentbench_path, to_serializable(eval_spec.presentbench))
    _write_json(slidesgenbench_path, to_serializable(eval_spec.slidesgenbench))
    _write_json(scoring_config_path, eval_spec.scoring_config)
    _write_json(eval_spec_path, to_serializable(eval_spec))
    return {
        "cache_root": str(root),
        "task_spec": str(task_spec_path),
        "presentbench_eval_spec": str(presentbench_path),
        "slidesgenbench_eval_spec": str(slidesgenbench_path),
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

    task_spec = build_task_spec(prompt, source_pack, task_constraints)
    slidesgenbench = build_slidesgenbench_eval_spec(
        task_spec,
        source_pack,
        quiz_bank_service=quiz_bank_service,
        mode=mode,
    )
    presentbench = build_presentbench_eval_spec(task_spec, mode=mode)
    payload = {
        "task_spec": to_serializable(task_spec),
        "presentbench": to_serializable(presentbench),
        "slidesgenbench": to_serializable(slidesgenbench),
        "scoring_config": {**DEFAULT_REWARD_KERNEL_CONFIG, "mode": mode},
        "spec_version": SPEC_VERSION,
    }
    spec_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    eval_spec = EvalSpec(
        task_spec=task_spec,
        presentbench=presentbench,
        slidesgenbench=slidesgenbench,
        scoring_config={**DEFAULT_REWARD_KERNEL_CONFIG, "mode": mode},
        spec_version=SPEC_VERSION,
        spec_hash=spec_hash,
    )
    if cache_dir:
        artifact_paths = _persist_eval_spec(cache_dir, eval_spec)
        eval_spec.task_spec.metadata["cache_artifacts"] = artifact_paths
    return eval_spec


def _reward_result_for_failure(
    eval_spec: EvalSpec,
    *,
    error: Exception,
    mode: str,
) -> RewardResult:
    return RewardResult(
        reward_total=0.0,
        reward_breakdown={"R_total": 0.0, "R_pb": 0.0, "R_sg": 0.0},
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
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PptxExtractionService | None = None,
    aesthetics_service: Any | None = None,
    quantitative_quiz_judge_service: QuantitativeQuizJudgeService,
    mode: str = "eval",
) -> RewardResult:
    del judge
    inspection_service = inspection_service or PptxExtractionService()

    try:
        presentation_extraction = inspection_service.inspect_presentation(presentation)
    except Exception as error:
        return _reward_result_for_failure(eval_spec, error=error, mode=mode)

    rendered_presentation = None
    render_error: str | None = None
    if render_service and hasattr(render_service, "render_presentation"):
        try:
            rendered_presentation = render_service.render_presentation(presentation)
        except Exception as error:
            render_error = str(error)

    presentbench_result = score_presentbench(
        eval_spec.task_spec,
        presentation_extraction,
        eval_spec.presentbench,
        aesthetics_service=aesthetics_service,
    )
    slidesgenbench_result = score_slidesgenbench(
        eval_spec.task_spec,
        presentation_extraction,
        eval_spec.slidesgenbench,
        quantitative_quiz_judge_service=quantitative_quiz_judge_service,
        rendered_presentation=rendered_presentation,
    )

    branch_weights = eval_spec.scoring_config["branch_weights"]
    reward_total = clamp(
        branch_weights["presentbench"] * presentbench_result.reward_total
        + branch_weights["slidesgenbench"] * slidesgenbench_result.reward_total
    )

    return RewardResult(
        reward_total=reward_total,
        reward_breakdown={
            "R_total": reward_total,
            "R_pb": presentbench_result.reward_total,
            "R_sg": slidesgenbench_result.reward_total,
            **presentbench_result.reward_breakdown,
            **slidesgenbench_result.reward_breakdown,
        },
        hard_caps=presentbench_result.hard_caps,
        soft_penalties=presentbench_result.soft_penalties,
        checklist_results=presentbench_result.checklist_results,
        quiz_results=slidesgenbench_result.quiz_results,
        aesthetics_results=(
            slidesgenbench_result.aesthetics_results
            if slidesgenbench_result.aesthetics_results
            else presentbench_result.aesthetics_results
        ),
        artifacts={
            "presentation_digest": presentation_extraction.metadata.get(
                "presentation_digest"
            ),
            "rendered_presentation": to_serializable(rendered_presentation)
            if rendered_presentation is not None
            else None,
        },
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "spec_hash": eval_spec.spec_hash,
            "presentbench_spec_hash": eval_spec.presentbench.spec_hash,
            "slidesgenbench_spec_hash": eval_spec.slidesgenbench.spec_hash,
            "spec_version": eval_spec.spec_version,
            "mode": mode,
            "slide_count": presentation_extraction.slide_count,
            "presentbench_item_count": len(eval_spec.presentbench.checklist),
            "slidesgenbench_question_count": len(eval_spec.slidesgenbench.quiz_bank),
            "judge_call_count": 0,
            "failure_counts": {
                "inspection": 0,
                "judge": 0,
                "render": 0 if render_error is None else 1,
            },
            "used_mllm": use_mllm,
            "inspection_mode": presentation_extraction.metadata.get("inspection_mode"),
            "presentation_digest": presentation_extraction.metadata.get(
                "presentation_digest"
            ),
            "render_backend": getattr(rendered_presentation, "backend", None),
            "render_error": render_error,
        },
    )


def evaluate_slide(
    eval_spec: EvalSpec,
    slide_index: int,
    *,
    presentation: PptxEditor | PptxPresentation | None = None,
    slide_extraction: ExtractedSlide | None = None,
    use_mllm: bool = False,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PptxExtractionService | None = None,
    aesthetics_service: Any | None = None,
    previous_slide_extractions: list[ExtractedSlide] | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    del judge, render_service, aesthetics_service
    inspection_service = inspection_service or PptxExtractionService()
    try:
        if slide_extraction is None:
            if presentation is None:
                raise ValueError("presentation or slide_extraction is required")
            slide_extraction = inspection_service.inspect_slide(
                slide_index,
                presentation=presentation,
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

    return score_presentbench_slide(
        eval_spec.task_spec,
        eval_spec.presentbench,
        slide_index,
        slide_extraction,
        previous_slide_extractions=previous_slide_extractions,
        use_mllm=use_mllm,
        mode=mode,
    )


def compute_presentation_reward(
    prompt: str,
    source_pack: SourcePack,
    presentation: PptxEditor | PptxPresentation | str,
    *,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PptxExtractionService | None = None,
    aesthetics_service: Any | None = None,
    quiz_bank_service: QuizBankGenerationService,
    quantitative_quiz_judge_service: QuantitativeQuizJudgeService,
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
        judge=judge,
        render_service=render_service,
        inspection_service=inspection_service,
        aesthetics_service=aesthetics_service,
        quantitative_quiz_judge_service=quantitative_quiz_judge_service,
        mode=mode,
    )


def compute_intermediate_slide_reward(
    prompt: str,
    source_pack: SourcePack,
    *,
    slide_index: int,
    presentation: PptxEditor | PptxPresentation | None = None,
    slide_extraction: ExtractedSlide | None = None,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    judge: Any | None = None,
    render_service: Any | None = None,
    inspection_service: PptxExtractionService | None = None,
    aesthetics_service: Any | None = None,
    previous_slide_extractions: list[ExtractedSlide] | None = None,
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
