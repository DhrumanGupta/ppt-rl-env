from __future__ import annotations

import copy

from server.utils.reward_metrics import deck_text_corpus
from server.utils.reward_models import ExtractedPresentation, QuizQuestion
from server.utils.slidesgenbench.quizbank_service import SlidesGenQuizBankService
from server.utils.slidesgenbench.quantitative_judge import (
    SlidesGenQuantitativeJudgeService,
)


class FakeLLMClient:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if not self._responses:
            raise AssertionError("No fake LLM responses remaining")
        response = self._responses.pop(0)
        return copy.deepcopy(response)


def build_valid_quizbank_stage_responses() -> list[dict]:
    extraction_payload = {
        "quantitative_evidence": [
            {
                "evidence_id": "quantitative_01",
                "statement": "Enterprise retention improved from 88% to 93%.",
                "source_quote": "Enterprise retention improved from 88% to 93%.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {"numbers": ["88%", "93%"]},
            },
            {
                "evidence_id": "quantitative_02",
                "statement": "Guided automation reduced onboarding time by 35%.",
                "source_quote": "Guided automation reduced onboarding time by 35%.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {"numbers": ["35%"]},
            },
            {
                "evidence_id": "quantitative_03",
                "statement": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "source_quote": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {"numbers": ["18", "24", "28", "32"]},
            },
            {
                "evidence_id": "quantitative_04",
                "statement": "The memo lists a retention baseline of 88%.",
                "source_quote": "Enterprise retention improved from 88% to 93%.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {"numbers": ["88%"]},
            },
            {
                "evidence_id": "quantitative_05",
                "statement": "The highest quarterly target mentioned is 32 million dollars.",
                "source_quote": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {"numbers": ["32"]},
            },
        ],
        "qualitative_evidence": [
            {
                "evidence_id": "qualitative_01",
                "statement": "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                "source_quote": "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {},
            },
            {
                "evidence_id": "qualitative_02",
                "statement": "Enterprise retention improved from 88% to 93%.",
                "source_quote": "Enterprise retention improved from 88% to 93%.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {},
            },
            {
                "evidence_id": "qualitative_03",
                "statement": "Guided automation reduced onboarding time by 35%.",
                "source_quote": "Guided automation reduced onboarding time by 35%.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {},
            },
            {
                "evidence_id": "qualitative_04",
                "statement": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "source_quote": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {},
            },
            {
                "evidence_id": "qualitative_05",
                "statement": "The plan memo emphasizes measurable operational improvements.",
                "source_quote": "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                "source_ref": "memo",
                "doc_id": "memo",
                "page": None,
                "metadata": {},
            },
        ],
        "metadata": {"stage": "extraction"},
    }

    refinement_payload = {
        "quantitative_evidence": extraction_payload["quantitative_evidence"],
        "qualitative_evidence": extraction_payload["qualitative_evidence"],
        "metadata": {"stage": "refinement"},
    }

    generation_payload = {
        "questions": [
            {
                "question_id": "quiz_qualitative_01",
                "question_type": "qualitative",
                "question": "Which statement best reflects the memo's main focus?",
                "options": [
                    "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                    "Northstar Growth Plan 2026 focuses on market expansion only.",
                    "Northstar Growth Plan 2026 focuses on hiring freezes.",
                    "Northstar Growth Plan 2026 focuses on office relocation.",
                ],
                "correct_answer": "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                "explanation": "The memo states this directly in memo.",
                "source_refs": ["memo"],
                "source_quotes": [
                    "Northstar Growth Plan 2026 focuses on retention and onboarding."
                ],
            },
            {
                "question_id": "quiz_qualitative_02",
                "question_type": "qualitative",
                "question": "Which outcome is explicitly supported by the memo?",
                "options": [
                    "Enterprise retention improved from 88% to 93%.",
                    "Enterprise retention fell from 93% to 88%.",
                    "Enterprise retention stayed flat at 90%.",
                    "Enterprise retention was not measured.",
                ],
                "correct_answer": "Enterprise retention improved from 88% to 93%.",
                "explanation": "This supported result appears in memo.",
                "source_refs": ["memo"],
                "source_quotes": ["Enterprise retention improved from 88% to 93%."],
            },
            {
                "question_id": "quiz_qualitative_03",
                "question_type": "qualitative",
                "question": "What operational change does the memo attribute to guided automation?",
                "options": [
                    "Guided automation reduced onboarding time by 35%.",
                    "Guided automation doubled onboarding time.",
                    "Guided automation removed quarterly targets.",
                    "Guided automation replaced retention tracking.",
                ],
                "correct_answer": "Guided automation reduced onboarding time by 35%.",
                "explanation": "The supported operational improvement is cited in memo.",
                "source_refs": ["memo"],
                "source_quotes": ["Guided automation reduced onboarding time by 35%."],
            },
            {
                "question_id": "quiz_qualitative_04",
                "question_type": "qualitative",
                "question": "Which statement about quarterly revenue targets is supported?",
                "options": [
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                    "Quarterly revenue targets are 12, 18, 24, and 30 million dollars.",
                    "Quarterly revenue targets were not specified.",
                    "Quarterly revenue targets decline each quarter.",
                ],
                "correct_answer": "Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
                "explanation": "The memo lists these targets in memo.",
                "source_refs": ["memo"],
                "source_quotes": [
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
                ],
            },
            {
                "question_id": "quiz_qualitative_05",
                "question_type": "qualitative",
                "question": "Which high-level theme is grounded in the source?",
                "options": [
                    "The plan memo emphasizes measurable operational improvements.",
                    "The plan memo argues against operational metrics.",
                    "The plan memo is focused on office design.",
                    "The plan memo is about seasonal staffing only.",
                ],
                "correct_answer": "The plan memo emphasizes measurable operational improvements.",
                "explanation": "This synthesis is grounded in memo.",
                "source_refs": ["memo"],
                "source_quotes": [
                    "Northstar Growth Plan 2026 focuses on retention and onboarding."
                ],
            },
            {
                "question_id": "quiz_quantitative_01",
                "question_type": "quantitative",
                "question": "What retention rate did the memo report after improvement?",
                "options": ["93%", "90%", "95%", "98%"],
                "correct_answer": "93%",
                "explanation": "The post-improvement value is stated in memo.",
                "source_refs": ["memo"],
                "source_quotes": ["Enterprise retention improved from 88% to 93%."],
            },
            {
                "question_id": "quiz_quantitative_02",
                "question_type": "quantitative",
                "question": "By what percentage did guided automation reduce onboarding time?",
                "options": ["35%", "20%", "25%", "40%"],
                "correct_answer": "35%",
                "explanation": "The memo gives this percentage directly in memo.",
                "source_refs": ["memo"],
                "source_quotes": ["Guided automation reduced onboarding time by 35%."],
            },
            {
                "question_id": "quiz_quantitative_03",
                "question_type": "quantitative",
                "question": "What was the starting retention rate before the improvement?",
                "options": ["88%", "82%", "91%", "96%"],
                "correct_answer": "88%",
                "explanation": "The baseline is part of the cited result in memo.",
                "source_refs": ["memo"],
                "source_quotes": ["Enterprise retention improved from 88% to 93%."],
            },
            {
                "question_id": "quiz_quantitative_04",
                "question_type": "quantitative",
                "question": "Which quarterly revenue target appears first in the memo's list?",
                "options": ["18", "16", "20", "22"],
                "correct_answer": "18",
                "explanation": "The first listed target appears in memo.",
                "source_refs": ["memo"],
                "source_quotes": [
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
                ],
            },
            {
                "question_id": "quiz_quantitative_05",
                "question_type": "quantitative",
                "question": "What is the highest quarterly revenue target named in the memo?",
                "options": ["32", "28", "24", "36"],
                "correct_answer": "32",
                "explanation": "The highest target is explicitly listed in memo.",
                "source_refs": ["memo"],
                "source_quotes": [
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
                ],
            },
        ],
        "metadata": {"stage": "generation"},
    }

    return [extraction_payload, refinement_payload, generation_payload]


def make_quizbank_service(
    responses: list[dict] | None = None,
) -> tuple[SlidesGenQuizBankService, FakeLLMClient]:
    client = FakeLLMClient(responses or build_valid_quizbank_stage_responses())
    return SlidesGenQuizBankService(client), client


def build_valid_quantitative_judge_response() -> dict:
    generation_payload = build_valid_quizbank_stage_responses()[2]
    answers = []
    for question in generation_payload["questions"]:
        if question["question_type"] != "quantitative":
            continue
        answers.append(
            {
                "question_id": question["question_id"],
                "selected_answer": question["correct_answer"],
                "reasoning": "Supported by the deck context.",
            }
        )
    return {"answers": answers, "metadata": {"stage": "quantitative_judge"}}


def make_quantitative_judge_service(
    responses: list[dict] | None = None,
) -> tuple[SlidesGenQuantitativeJudgeService, FakeLLMClient]:
    client = FakeLLMClient(responses or [build_valid_quantitative_judge_response()])
    return SlidesGenQuantitativeJudgeService(client), client


class DeterministicQuantitativeJudgeService:
    def judge_quantitative_questions(
        self,
        *,
        task_spec,
        presentation_extraction: ExtractedPresentation,
        questions: list[QuizQuestion],
    ) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
        del task_spec
        deck_text = deck_text_corpus(presentation_extraction)
        answers: dict[str, dict[str, str]] = {}
        for question in questions:
            selected_answer = (
                question.correct_answer
                if question.correct_answer in deck_text
                else question.options[0]
            )
            answers[question.question_id] = {
                "selected_answer": selected_answer,
                "reasoning": "deterministic quantitative answer matching",
            }
        return answers, {"question_count": len(questions)}
