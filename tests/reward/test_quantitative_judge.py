# COMMENTED OUT TEMPORARILY
# import pytest
#
# from server.utils.reward_models import (
#     ExtractedPresentation,
#     ExtractedSlide,
#     QuizQuestion,
#     SourceDocument,
#     SourcePack,
# )
# from server.utils.reward_prompts import build_task_spec
# from server.utils.slidesgenbench.quantitative_judge import (
#     SlidesGenQuantitativeJudgeService,
# )
#
# from tests.reward.quizbank_test_utils import (
#     FakeLLMClient,
#     build_valid_quantitative_judge_response,
#     build_valid_quizbank_stage_responses,
#     make_quantitative_judge_service,
# )
#
# PROMPT = """
# Create a factual three-slide presentation for a professional audience.
# Slide 1: Title slide introducing Northstar Growth Plan 2026.
# Slide 2: Results slide covering retention increased from 88% to 93% and onboarding time reduced by 35%, with a source citation.
# Slide 3: Revenue chart slide showing quarterly target values 18, 24, 28, and 32.
# """.strip()
#
#
# def make_task_spec_and_questions():
#     source_pack = SourcePack(
#         task_id="northstar-plan",
#         documents=[
#             SourceDocument(
#                 doc_id="memo",
#                 title="Northstar plan memo",
#                 path=None,
#                 mime_type="text/plain",
#                 text="Northstar Growth Plan 2026 focuses on retention and onboarding.",
#                 pages=None,
#                 images=None,
#                 metadata={},
#             )
#         ],
#         metadata={},
#     )
#     task_spec = build_task_spec(PROMPT, source_pack)
#     generation_payload = build_valid_quizbank_stage_responses()[2]
#     questions = [
#         QuizQuestion(**question)
#         for question in generation_payload["questions"]
#         if question["question_type"] == "quantitative"
#     ]
#     return task_spec, questions
#
#
# def make_extraction() -> ExtractedPresentation:
#     return ExtractedPresentation(
#         slide_count=2,
#         slides=[
#             ExtractedSlide(
#                 slide_index=1,
#                 slide_id=1,
#                 title_text="Results",
#                 all_text="Retention improved from 88% to 93%. Guided automation reduced onboarding time by 35%.",
#             ),
#             ExtractedSlide(
#                 slide_index=2,
#                 slide_id=2,
#                 title_text="Revenue Targets",
#                 all_text="Quarterly revenue targets are 18, 24, 28, and 32 million dollars.",
#             ),
#         ],
#     )
#
#
# def test_quantitative_judge_answers_all_requested_questions():
#     task_spec, questions = make_task_spec_and_questions()
#     judge_service, llm_client = make_quantitative_judge_service()
#
#     answers, metadata = judge_service.judge_quantitative_questions(
#         task_spec=task_spec,
#         presentation_extraction=make_extraction(),
#         questions=questions,
#     )
#
#     assert set(answers) == {question.question_id for question in questions}
#     assert metadata["question_count"] == len(questions)
#     assert len(llm_client.calls) == 1
#     assert "Deck context" in llm_client.calls[0]["user"]
#
#
# def test_quantitative_judge_rejects_invalid_selected_answer():
#     task_spec, questions = make_task_spec_and_questions()
#     invalid_payload = build_valid_quantitative_judge_response()
#     invalid_payload["answers"][0]["selected_answer"] = "999%"
#     judge_service = SlidesGenQuantitativeJudgeService(
#         FakeLLMClient([invalid_payload]),
#         max_attempts=1,
#     )
#
#     with pytest.raises(ValueError, match="selected_answer must equal an option"):
#         judge_service.judge_quantitative_questions(
#             task_spec=task_spec,
#             presentation_extraction=make_extraction(),
#             questions=questions,
#         )
