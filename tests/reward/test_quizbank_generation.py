from server.utils.reward_kernel import build_eval_spec
from server.utils.reward_models import QuizQuestion, SourceDocument, SourcePack

from tests.reward.quizbank_test_utils import (
    build_valid_quizbank_stage_responses,
    make_quizbank_service,
)

PROMPT = """
Create a factual three-slide presentation for a professional audience.
Slide 1: Title slide introducing Northstar Growth Plan 2026.
Slide 2: Results slide covering retention increased from 88% to 93% and onboarding time reduced by 35%, with a source citation.
Slide 3: Revenue chart slide showing quarterly target values 18, 24, 28, and 32.
""".strip()


def make_source_pack() -> SourcePack:
    return SourcePack(
        task_id="northstar-plan",
        documents=[
            SourceDocument(
                doc_id="memo",
                title="Northstar plan memo",
                path=None,
                mime_type="text/plain",
                text=(
                    "Northstar Growth Plan 2026 focuses on retention and onboarding. "
                    "Enterprise retention improved from 88% to 93%. "
                    "Guided automation reduced onboarding time by 35%. "
                    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
                ),
                pages=None,
                images=None,
                metadata={},
            )
        ],
        metadata={},
    )


class StubQuizBankService:
    def generate_quiz_bank(self, *, task_spec, source_pack, mode="eval"):
        del task_spec, source_pack, mode
        return (
            [
                QuizQuestion(
                    question_id="quiz_stub_01",
                    question_type="concept",
                    question="Stub question?",
                    options=["A", "B", "C", "D"],
                    correct_answer="A",
                    explanation="stub explanation",
                    source_refs=["memo"],
                    source_quotes=["stub quote"],
                )
            ],
            {"service_name": "StubQuizBankService", "question_count": 1},
        )


def test_build_eval_spec_uses_injected_quizbank_service():
    eval_spec = build_eval_spec(
        PROMPT,
        make_source_pack(),
        quiz_bank_service=StubQuizBankService(),
    )

    assert [question.question_id for question in eval_spec.quiz_bank] == [
        "quiz_stub_01"
    ]
    assert (
        eval_spec.task_spec.metadata["quiz_bank_generation"]["service_name"]
        == "StubQuizBankService"
    )


def test_explicit_quizbank_service_produces_source_grounded_questions():
    quiz_bank_service, llm_client = make_quizbank_service()
    eval_spec = build_eval_spec(
        PROMPT,
        make_source_pack(),
        quiz_bank_service=quiz_bank_service,
    )

    assert {question.question_type for question in eval_spec.quiz_bank} == {
        "concept",
        "data",
    }
    assert len(llm_client.calls) == 3
    assert eval_spec.task_spec.metadata["quiz_bank_generation"]["service_name"]
    assert all(question.source_refs for question in eval_spec.quiz_bank)
    assert all(question.source_quotes for question in eval_spec.quiz_bank)


def test_quiz_generation_retries_invalid_generation_payload_once():
    responses = build_valid_quizbank_stage_responses()
    invalid_generation = dict(responses[2])
    invalid_generation["questions"] = invalid_generation["questions"][:-1]
    quiz_bank_service, llm_client = make_quizbank_service(
        [responses[0], responses[1], invalid_generation, responses[2]]
    )

    eval_spec = build_eval_spec(
        PROMPT,
        make_source_pack(),
        quiz_bank_service=quiz_bank_service,
    )

    assert len(eval_spec.quiz_bank) == 10
    assert len(llm_client.calls) == 4
    assert (
        eval_spec.task_spec.metadata["quiz_bank_generation"]["stage_diagnostics"][
            "generation"
        ]["full_generation_invalid_count"]
        == 1
    )
    assert (
        eval_spec.task_spec.metadata["quiz_bank_generation"]["stage_diagnostics"][
            "generation"
        ]["repair"]["repaired_question_count"]
        == 1
    )


def test_quiz_generation_repairs_only_failed_subset():
    responses = build_valid_quizbank_stage_responses()
    invalid_generation = dict(responses[2])
    invalid_questions = list(invalid_generation["questions"])
    invalid_questions[0] = {
        **invalid_questions[0],
        "options": invalid_questions[0]["options"][:3],
    }
    invalid_generation["questions"] = invalid_questions
    repair_payload = {
        "questions": [responses[2]["questions"][0]],
        "metadata": {"stage": "repair"},
    }
    quiz_bank_service, llm_client = make_quizbank_service(
        [responses[0], responses[1], invalid_generation, repair_payload]
    )

    eval_spec = build_eval_spec(
        PROMPT,
        make_source_pack(),
        quiz_bank_service=quiz_bank_service,
    )

    generation_diagnostics = eval_spec.task_spec.metadata["quiz_bank_generation"][
        "stage_diagnostics"
    ]["generation"]

    assert len(eval_spec.quiz_bank) == 10
    assert len(llm_client.calls) == 4
    assert generation_diagnostics["full_generation_invalid_count"] == 1
    assert generation_diagnostics["repair"]["repaired_question_count"] == 1
    assert (
        generation_diagnostics["repaired_slots"][0]["question_id"] == "quiz_concept_01"
    )
    assert "Failed slots to repair" in llm_client.calls[-1]["user"]
