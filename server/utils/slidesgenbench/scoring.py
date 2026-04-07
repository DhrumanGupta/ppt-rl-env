from __future__ import annotations

from typing import Any

from server.utils.presentbench.metrics import compute_aesthetics_scores
from server.utils.reward_metrics import (
    normalized_number_match,
    slide_text_corpus,
    text_match_score,
)
from server.utils.reward_models import (
    ExtractedPresentation,
    SlidesGenBenchEvalSpec,
    SlidesGenBenchScoreResult,
    TaskSpec,
)
from server.utils.slidesgenbench.editability import evaluate_pei_level

DEFAULT_SG_BRANCH_WEIGHTS = {
    "quiz": 0.45,
    "aesthetic": 0.35,
    "editability": 0.20,
}


def score_slidesgenbench(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    eval_spec: SlidesGenBenchEvalSpec,
    *,
    presentation: Any | None = None,
    aesthetics_service: Any | None = None,
) -> SlidesGenBenchScoreResult:
    """R_SG = 0.45 * Quiz + 0.35 * Aesthetic + 0.20 * Editability"""
    del task_spec

    mode = eval_spec.scoring_config.get("mode", "eval")
    branch_weights = eval_spec.scoring_config.get(
        "sg_branch_weights", DEFAULT_SG_BRANCH_WEIGHTS
    )

    # --- Quiz (Content Fidelity) ---
    deck_text = "\n".join(
        slide_text_corpus(slide) for slide in presentation_extraction.slides
    )
    quiz_results: list[dict[str, object]] = []
    qualitative_correct = 0
    qualitative_total = 0
    quantitative_correct = 0
    quantitative_total = 0

    for question in eval_spec.quiz_bank:
        if question.question_type == "quantitative":
            correct = normalized_number_match(deck_text, question.correct_answer)
            quantitative_total += 1
            quantitative_correct += int(correct)
        else:
            correct = text_match_score(deck_text, question.correct_answer) >= 0.6
            qualitative_total += 1
            qualitative_correct += int(correct)

        quiz_results.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "selected_answer": question.correct_answer if correct else None,
                "correct": correct,
            }
        )

    s_quiz_qualitative = (
        (qualitative_correct / qualitative_total) if qualitative_total else 0.0
    )
    s_quiz_quantitative = (
        (quantitative_correct / quantitative_total) if quantitative_total else 0.0
    )
    quiz_split = eval_spec.scoring_config.get(
        "quiz_split", {"qualitative": 0.5, "quantitative": 0.5}
    )
    s_quiz = (
        quiz_split.get("qualitative", 0.5) * s_quiz_qualitative
        + quiz_split.get("quantitative", 0.5) * s_quiz_quantitative
    )

    # --- Aesthetics ---
    if aesthetics_service and hasattr(aesthetics_service, "score_presentation"):
        aesthetics_scores = aesthetics_service.score_presentation(
            presentation_extraction
        )
    else:
        aesthetics_scores = compute_aesthetics_scores(presentation_extraction)

    s_aesthetic = aesthetics_scores.get("aesthetic", 0.0)

    # --- Editability (PEI) ---
    if presentation is not None:
        try:
            editability_results = evaluate_pei_level(presentation)
        except Exception:
            editability_results = {"pei_level": 0, "pei_reward": 0.0}
    else:
        editability_results = {"pei_level": 0, "pei_reward": 0.0}
    s_editability = editability_results.get("pei_reward", 0.0)

    # --- Compose ---
    r_sg = (
        branch_weights.get("quiz", 0.45) * s_quiz
        + branch_weights.get("aesthetic", 0.35) * s_aesthetic
        + branch_weights.get("editability", 0.20) * s_editability
    )

    return SlidesGenBenchScoreResult(
        reward_total=r_sg,
        reward_breakdown={
            "R_sg": r_sg,
            "S_quiz": s_quiz,
            "S_quiz_qualitative": s_quiz_qualitative,
            "S_quiz_quantitative": s_quiz_quantitative,
            "S_aesthetic": s_aesthetic,
            "S_editability": s_editability,
            "pei_level": float(editability_results.get("pei_level", 0)),
        },
        quiz_results=quiz_results,
        editability_results=editability_results,
        aesthetics_results=aesthetics_scores,
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "question_count": len(eval_spec.quiz_bank),
            "slide_count": presentation_extraction.slide_count,
            "spec_hash": eval_spec.spec_hash,
        },
    )


__all__ = ["score_slidesgenbench"]
