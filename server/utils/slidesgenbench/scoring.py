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
    quiz_split = eval_spec.scoring_config.get(
        "quiz_split", {"concept": 0.5, "data": 0.5}
    )
    s_quiz = (
        quiz_split.get("concept", 0.5) * s_quiz_concept
        + quiz_split.get("data", 0.5) * s_quiz_data
    )
    return SlidesGenBenchScoreResult(
        reward_total=s_quiz,
        reward_breakdown={
            "R_sg": s_quiz,
            "S_quiz": s_quiz,
            "S_quiz_concept": s_quiz_concept,
            "S_quiz_data": s_quiz_data,
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
