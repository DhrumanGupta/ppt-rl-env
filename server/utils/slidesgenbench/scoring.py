from __future__ import annotations

from server.utils.reward_metrics import slide_text_corpus, text_match_score
from server.utils.reward_models import (
    ExtractedPresentation,
    SlidesGenBenchEvalSpec,
    SlidesGenBenchScoreResult,
    TaskSpec,
)


def score_slidesgenbench(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    eval_spec: SlidesGenBenchEvalSpec,
) -> SlidesGenBenchScoreResult:
    del task_spec
    deck_text = "\n".join(
        slide_text_corpus(slide) for slide in presentation_extraction.slides
    )
    quiz_results: list[dict[str, object]] = []
    qualitative_correct = 0
    qualitative_total = 0
    quantitative_correct = 0
    quantitative_total = 0

    for question in eval_spec.quiz_bank:
        correct = False
        if question.question_type == "quantitative":
            quantitative_total += 1
            correct = question.correct_answer in deck_text
            quantitative_correct += int(correct)
        else:
            qualitative_total += 1
            correct = text_match_score(deck_text, question.correct_answer) >= 0.6
            qualitative_correct += int(correct)
        quiz_results.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "selected_answer": question.correct_answer if correct else None,
                "correct": correct,
                "reasoning": "deterministic slides-only answer matching",
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
        },
    )


__all__ = ["score_slidesgenbench"]
