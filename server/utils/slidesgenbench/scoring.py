from __future__ import annotations

from ..reward_metrics import clamp_reward
from ..reward_metrics import slide_text_corpus, text_match_score
from ..reward_models import (
    ExtractedPresentation,
    RenderedPresentation,
    SlidesGenBenchEvalSpec,
    SlidesGenBenchScoreResult,
    TaskSpec,
)
from .quantitative_judge import QuantitativeQuizJudgeService
from .rendered_aesthetics import (
    compute_rendered_aesthetics_scores,
)
from .text_layout import (
    compute_presentation_text_layout_scores,
)


def score_slidesgenbench(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    eval_spec: SlidesGenBenchEvalSpec,
    *,
    quantitative_quiz_judge_service: QuantitativeQuizJudgeService,
    rendered_presentation: RenderedPresentation | None = None,
) -> SlidesGenBenchScoreResult:
    deck_text = "\n".join(
        slide_text_corpus(slide) for slide in presentation_extraction.slides
    )
    quiz_results: list[dict[str, object]] = []
    qualitative_correct = 0
    qualitative_total = 0
    quantitative_correct = 0
    quantitative_total = 0
    quantitative_answers: dict[str, dict[str, object]] = {}
    quantitative_questions = [
        question
        for question in eval_spec.quiz_bank
        if question.question_type == "quantitative"
    ]
    judge_metadata: dict[str, object] = {}

    if quantitative_questions:
        try:
            quantitative_answers, judge_metadata = (
                quantitative_quiz_judge_service.judge_quantitative_questions(
                    task_spec=task_spec,
                    presentation_extraction=presentation_extraction,
                    questions=quantitative_questions,
                )
            )
        except Exception as error:
            judge_metadata = {"error": str(error)}

    for question in eval_spec.quiz_bank:
        selected_answer: str | None = None
        reasoning = "deterministic slides-only answer matching"
        correct = False
        if question.question_type == "quantitative":
            quantitative_total += 1
            answer = quantitative_answers.get(question.question_id, {})
            selected_answer = answer.get("selected_answer")
            reasoning = answer.get("reasoning") or "llm quantitative deck answer"
            correct = selected_answer == question.correct_answer
            quantitative_correct += int(correct)
        else:
            qualitative_total += 1
            correct = text_match_score(deck_text, question.correct_answer) >= 0.6
            selected_answer = question.correct_answer if correct else None
            qualitative_correct += int(correct)
        quiz_results.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "selected_answer": selected_answer,
                "correct": correct,
                "reasoning": reasoning,
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
    aesthetics_scores = compute_rendered_aesthetics_scores(
        rendered_presentation,
        presentation_extraction,
        metric_weights=eval_spec.scoring_config.get("aesthetic_weights"),
        harmony_config=eval_spec.scoring_config.get("harmony_config"),
        rhythm_config=eval_spec.scoring_config.get("rhythm_config"),
    )
    text_layout_scores = compute_presentation_text_layout_scores(
        presentation_extraction,
        config=eval_spec.scoring_config.get("text_layout_config"),
        weights=eval_spec.scoring_config.get("text_layout_weights"),
    )
    branch_split = eval_spec.scoring_config.get(
        "branch_split", {"content": 0.35, "aesthetics": 0.35, "text_layout": 0.30}
    )
    s_aesthetic = float(aesthetics_scores.get("aesthetic", 0.0))
    s_text_layout = float(text_layout_scores.get("text_layout", 0.0))
    text_layout_hard_cap = float(text_layout_scores.get("hard_cap", 1.0))
    reward_pre_cap = (
        branch_split.get("content", 0.35) * s_quiz
        + branch_split.get("aesthetics", 0.35) * s_aesthetic
        + branch_split.get("text_layout", 0.30) * s_text_layout
    )
    reward_total = clamp_reward(reward_pre_cap * text_layout_hard_cap)
    return SlidesGenBenchScoreResult(
        reward_total=reward_total,
        reward_breakdown={
            "R_sg": reward_total,
            "R_sg_pre_text_layout_cap": reward_pre_cap,
            "S_quiz": s_quiz,
            "S_quiz_qualitative": s_quiz_qualitative,
            "S_quiz_quantitative": s_quiz_quantitative,
            "S_aesthetic": s_aesthetic,
            "S_harmony": float(aesthetics_scores.get("harmony", 0.0)),
            "S_engagement": float(aesthetics_scores.get("engagement", 0.0)),
            "S_usability": float(aesthetics_scores.get("usability", 0.0)),
            "S_rhythm": float(aesthetics_scores.get("rhythm", 0.0)),
            "S_text_layout": s_text_layout,
            "S_text_bounds": float(text_layout_scores.get("text_bounds", 0.0)),
            "S_text_density": float(text_layout_scores.get("text_density", 0.0)),
            "S_text_overlap": float(text_layout_scores.get("text_overlap", 0.0)),
            "C_text_layout_hard": text_layout_hard_cap,
        },
        quiz_results=quiz_results,
        aesthetics_results=aesthetics_scores,
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "question_count": len(eval_spec.quiz_bank),
            "slide_count": presentation_extraction.slide_count,
            "spec_hash": eval_spec.spec_hash,
            "quantitative_judge": judge_metadata,
            "text_layout": text_layout_scores,
            "rendered_slide_count": len(rendered_presentation.slide_images)
            if rendered_presentation is not None
            else 0,
        },
    )


__all__ = ["score_slidesgenbench"]
