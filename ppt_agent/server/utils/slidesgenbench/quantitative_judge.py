from __future__ import annotations

from typing import Any, Protocol

from ...llm_client import LLMClient
from .prompts import (
    build_quantitative_quiz_judging_prompts,
)
from ..reward_models import (
    ExtractedPresentation,
    QuizQuestion,
    TaskSpec,
)


class QuantitativeQuizJudgeService(Protocol):
    def judge_quantitative_questions(
        self,
        *,
        task_spec: TaskSpec,
        presentation_extraction: ExtractedPresentation,
        questions: list[QuizQuestion],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]: ...


class SlidesGenQuantitativeJudgeService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        max_slide_chars: int = 1200,
    ):
        if llm_client is None:
            raise ValueError("SlidesGenQuantitativeJudgeService requires an llm_client")
        self.llm_client = llm_client
        self.max_slide_chars = max_slide_chars

    def judge_quantitative_questions(
        self,
        *,
        task_spec: TaskSpec,
        presentation_extraction: ExtractedPresentation,
        questions: list[QuizQuestion],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        if not questions:
            return {}, {"question_count": 0}

        system_prompt, user_prompt = build_quantitative_quiz_judging_prompts(
            task_spec,
            presentation_extraction,
            questions,
            max_slide_chars=self.max_slide_chars,
        )

        payload = self.llm_client.chat_json(
            system_prompt,
            user_prompt,
            temperature=0.0,
            max_tokens=3000,
            debug_stage="quantitative_quiz_judge",
        )
        answers = self._parse_answers(payload, questions)
        metadata = (
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        )
        diagnostics = {
            "question_count": len(questions),
            "llm_client_type": self.llm_client.__class__.__name__,
            "slide_count": presentation_extraction.slide_count,
        }
        if metadata:
            diagnostics["metadata"] = metadata
        return answers, diagnostics

    @staticmethod
    def _parse_answers(
        payload: dict[str, Any],
        questions: list[QuizQuestion],
    ) -> dict[str, dict[str, Any]]:
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, list):
            raise ValueError("answers must be a list")

        question_by_id = {question.question_id: question for question in questions}
        parsed: dict[str, dict[str, Any]] = {}
        for raw in raw_answers:
            if not isinstance(raw, dict):
                raise ValueError("answer entry must be an object")
            question_id = raw.get("question_id")
            selected_answer = raw.get("selected_answer")
            reasoning = raw.get("reasoning")
            if not isinstance(question_id, str) or question_id not in question_by_id:
                raise ValueError("answer question_id must match a requested question")
            if question_id in parsed:
                raise ValueError(f"duplicate answer for question {question_id}")
            if not isinstance(selected_answer, str) or not selected_answer.strip():
                raise ValueError("selected_answer must be a non-empty string")
            if selected_answer not in question_by_id[question_id].options:
                raise ValueError(
                    f"selected_answer must equal an option for question {question_id}"
                )
            parsed[question_id] = {
                "selected_answer": selected_answer,
                "reasoning": reasoning if isinstance(reasoning, str) else "",
            }

        if set(parsed) != set(question_by_id):
            missing = sorted(set(question_by_id) - set(parsed))
            raise ValueError(f"missing answers for question_ids: {', '.join(missing)}")
        return parsed


__all__ = [
    "QuantitativeQuizJudgeService",
    "SlidesGenQuantitativeJudgeService",
]
