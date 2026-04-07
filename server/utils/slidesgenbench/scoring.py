from __future__ import annotations

from server.utils.reward_metrics import slide_text_corpus, text_match_score
from server.utils.reward_models import (
    ExtractedPresentation,
    SlidesGenBenchEvalSpec,
    SlidesGenBenchScoreResult,
    TaskSpec,
)
from server.utils.slidesgenbench.quantitative_judge import QuantitativeQuizJudgeService


def score_slidesgenbench(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    eval_spec: SlidesGenBenchEvalSpec,
    *,
    quantitative_quiz_judge_service: QuantitativeQuizJudgeService,
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
    return SlidesGenBenchScoreResult(
        reward_total=s_quiz,
        reward_breakdown={
            "R_sg": s_quiz,
            "S_quiz": s_quiz,
            "S_quiz_qualitative": s_quiz_qualitative,
            "S_quiz_quantitative": s_quiz_quantitative,
        },
        quiz_results=quiz_results,
        metadata={
            "task_id": eval_spec.task_spec.task_id,
            "question_count": len(eval_spec.quiz_bank),
            "slide_count": presentation_extraction.slide_count,
            "spec_hash": eval_spec.spec_hash,
            "quantitative_judge": judge_metadata,
        },
    )


__all__ = ["score_slidesgenbench"]
