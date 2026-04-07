from server.utils.reward_models import SourceDocument, SourcePack
from server.utils.reward_prompts import build_task_spec

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


def make_task_spec():
    return build_task_spec(PROMPT, make_source_pack())


def test_generate_quiz_bank_returns_grounded_questions():
    quiz_bank_service, llm_client = make_quizbank_service()

    questions, metadata = quiz_bank_service.generate_quiz_bank(
        task_spec=make_task_spec(),
        source_pack=make_source_pack(),
    )

    assert {question.question_type for question in questions} == {
        "qualitative",
        "quantitative",
    }
    assert len(llm_client.calls) == 3
    assert metadata["service_name"] == "SlidesGenQuizBankService"
    assert all(question.source_refs for question in questions)
    assert all(question.source_quotes for question in questions)


def test_generate_quiz_bank_repairs_only_failed_subset():
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

    questions, metadata = quiz_bank_service.generate_quiz_bank(
        task_spec=make_task_spec(),
        source_pack=make_source_pack(),
    )

    generation = metadata["stage_diagnostics"]["generation"]
    assert len(questions) == 10
    assert len(llm_client.calls) == 4
    assert generation["full_generation_invalid_count"] == 1
    assert generation["repair"]["repaired_question_count"] == 1
    assert generation["repaired_slots"][0]["question_id"] == "quiz_qualitative_01"
    assert "Failed slots to repair" in llm_client.calls[-1]["user"]
