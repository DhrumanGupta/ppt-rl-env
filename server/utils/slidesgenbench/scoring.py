from __future__ import annotations

from typing import Any, Protocol

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


# ---------------------------------------------------------------------------
# LLM-based quiz evaluation protocol (mode="eval")
# ---------------------------------------------------------------------------

_QUIZ_SYSTEM_PROMPT = """\
You are a strict exam evaluator. You will be given context extracted from \
presentation slides and a multiple-choice question with exactly four options.

Answer the question ONLY using information present in the provided slide \
context. If the context does not contain enough information to answer, \
choose the option that is LEAST supported.

Respond with ONLY the letter (A, B, C, or D) of your chosen answer. \
Do not add any explanation."""


def _build_quiz_user_prompt(
    slide_context: str,
    question_text: str,
    options: list[str],
) -> str:
    option_lines = "\n".join(
        f"  {chr(65 + i)}. {opt}" for i, opt in enumerate(options)
    )
    return (
        f"### Slide Context\n{slide_context}\n\n"
        f"### Question\n{question_text}\n\n"
        f"### Options\n{option_lines}\n\n"
        "Your answer (A/B/C/D):"
    )


class QuizEvaluatorLLM(Protocol):
    """Minimal interface for the LLM used during quiz evaluation."""

    def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 16,
    ) -> dict[str, Any]: ...


def _evaluate_question_with_llm(
    slide_context: str,
    question_text: str,
    options: list[str],
    correct_answer: str,
    llm: QuizEvaluatorLLM,
) -> tuple[bool, str | None]:
    """Ask the LLM evaluator to answer a quiz question from slide context.

    Returns (is_correct, selected_answer_text).
    """
    user_prompt = _build_quiz_user_prompt(slide_context, question_text, options)
    try:
        response = llm.chat_json(
            _QUIZ_SYSTEM_PROMPT,
            user_prompt,
            temperature=0.0,
            max_tokens=16,
        )
        raw = (
            response.get("answer", "")
            if isinstance(response, dict)
            else str(response)
        ).strip().upper()
    except Exception:
        return False, None

    letter = raw[0] if raw and raw[0] in "ABCD" else None
    if letter is None:
        return False, None
    index = ord(letter) - 65
    if index < 0 or index >= len(options):
        return False, None
    selected = options[index]
    return selected == correct_answer, selected


# ---------------------------------------------------------------------------
# Deterministic quiz matching (mode="train")
# ---------------------------------------------------------------------------


def _match_quantitative_question(deck_text: str, correct_answer: str) -> bool:
    """Word-boundary-aware numeric matching for quantitative questions."""
    return normalized_number_match(deck_text, correct_answer)


def _match_qualitative_question(
    deck_text: str, correct_answer: str, threshold: float = 0.6
) -> bool:
    """Semantic matching for qualitative questions."""
    return text_match_score(deck_text, correct_answer) >= threshold


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

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
    quiz_evaluator_llm: QuizEvaluatorLLM | None = None,
) -> SlidesGenBenchScoreResult:
    """Score a presentation against the SlidesGenBench eval spec.

    The reward combines three branches per the paper:
        R_SG = w_quiz * S_quiz + w_aesthetic * S_aesthetic + w_edit * S_editability

    Parameters
    ----------
    quiz_evaluator_llm : optional
        If provided (and mode != "train"), uses LLM-based open-book exam
        evaluation per the paper.  Otherwise falls back to deterministic
        matching suitable for fast RL training.
    aesthetics_service : optional
        If provided and has ``score_presentation``, uses it for aesthetics.
        Otherwise computes object-graph-based aesthetics.
    presentation : optional
        The raw PptxEditor / Presentation object, needed for PEI evaluation.
    """
    del task_spec

    mode = eval_spec.scoring_config.get("mode", "eval")
    branch_weights = eval_spec.scoring_config.get(
        "sg_branch_weights", DEFAULT_SG_BRANCH_WEIGHTS
    )

    # ------------------------------------------------------------------
    # Branch A: Quiz (Content Fidelity)
    # ------------------------------------------------------------------
    deck_text = "\n".join(
        slide_text_corpus(slide) for slide in presentation_extraction.slides
    )
    quiz_results: list[dict[str, object]] = []
    qualitative_correct = 0
    qualitative_total = 0
    quantitative_correct = 0
    quantitative_total = 0

    use_llm = quiz_evaluator_llm is not None and mode != "train"

    for question in eval_spec.quiz_bank:
        correct = False
        selected_answer: str | None = None

        if use_llm:
            correct, selected_answer = _evaluate_question_with_llm(
                slide_context=deck_text,
                question_text=question.question,
                options=question.options,
                correct_answer=question.correct_answer,
                llm=quiz_evaluator_llm,
            )
        else:
            if question.question_type == "quantitative":
                correct = _match_quantitative_question(
                    deck_text, question.correct_answer
                )
            else:
                correct = _match_qualitative_question(
                    deck_text, question.correct_answer
                )
            selected_answer = question.correct_answer if correct else None

        if question.question_type == "quantitative":
            quantitative_total += 1
            quantitative_correct += int(correct)
        else:
            qualitative_total += 1
            qualitative_correct += int(correct)

        quiz_results.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "selected_answer": selected_answer,
                "correct": correct,
                "reasoning": (
                    "llm_open_book_exam" if use_llm else "deterministic_matching"
                ),
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

    # ------------------------------------------------------------------
    # Branch B: Computational Aesthetics
    # ------------------------------------------------------------------
    if aesthetics_service and hasattr(aesthetics_service, "score_presentation"):
        aesthetics_scores = aesthetics_service.score_presentation(
            presentation_extraction
        )
    else:
        aesthetics_scores = compute_aesthetics_scores(presentation_extraction)

    s_aesthetic = aesthetics_scores.get("aesthetic", 0.0)

    # ------------------------------------------------------------------
    # Branch C: Editability (PEI)
    # ------------------------------------------------------------------
    editability_results: dict[str, Any] = {}
    if presentation is not None:
        try:
            editability_results = evaluate_pei_level(presentation)
        except Exception:
            editability_results = {"pei_level": 0, "pei_reward": 0.0}
    else:
        editability_results = {
            "pei_level": 0,
            "pei_reward": 0.0,
            "note": "no presentation object provided for PEI evaluation",
        }
    s_editability = editability_results.get("pei_reward", 0.0)

    # ------------------------------------------------------------------
    # Compose R_SG
    # ------------------------------------------------------------------
    w_quiz = branch_weights.get("quiz", 0.45)
    w_aesthetic = branch_weights.get("aesthetic", 0.35)
    w_editability = branch_weights.get("editability", 0.20)

    r_sg = w_quiz * s_quiz + w_aesthetic * s_aesthetic + w_editability * s_editability

    return SlidesGenBenchScoreResult(
        reward_total=r_sg,
        reward_breakdown={
            "R_sg": r_sg,
            "S_quiz": s_quiz,
            "S_quiz_qualitative": s_quiz_qualitative,
            "S_quiz_quantitative": s_quiz_quantitative,
            "S_aesthetic": s_aesthetic,
            "S_aesthetic_harmony": aesthetics_scores.get("harmony", 0.0),
            "S_aesthetic_engagement": aesthetics_scores.get("engagement", 0.0),
            "S_aesthetic_usability": aesthetics_scores.get("usability", 0.0),
            "S_aesthetic_rhythm": aesthetics_scores.get("rhythm", 0.0),
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
            "quiz_evaluation_mode": "llm" if use_llm else "deterministic",
        },
    )


__all__ = ["score_slidesgenbench"]
