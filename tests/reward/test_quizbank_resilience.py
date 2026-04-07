from __future__ import annotations

from server.task_registry import DEFAULT_TASK_REGISTRY
from server.utils.reward_prompts import build_task_spec
from server.utils.slidesgenbench.prompts import build_quiz_source_context
from tests.reward.quizbank_test_utils import (
    build_valid_quizbank_stage_responses,
    make_quizbank_service,
)


def _scenario():
    return DEFAULT_TASK_REGISTRY.get("northstar_growth_easy")


def _task_spec_and_context():
    scenario = _scenario()
    task_spec = build_task_spec(
        scenario.prompt_text,
        scenario.source_pack,
        scenario.task_constraints,
    )
    source_context, _ = build_quiz_source_context(scenario.source_pack)
    return scenario, task_spec, source_context


def test_extract_evidence_sanitizes_common_llm_schema_mistakes() -> None:
    scenario, task_spec, source_context = _task_spec_and_context()
    extraction_payload = {
        "quantitative_evidence": [
            {
                "doc_id": "memo",
                "statement": "Enterprise retention improved from 88% to 93%.",
                "source_quote": "",
                "source_ref": "memo",
                "page": None,
                "metadata": [],
            }
        ],
        "qualitative_evidence": [
            {
                "doc_id": "memo",
                "statement": "Northstar Growth Plan 2026 focuses on retention and onboarding.",
                "source_quote": "",
                "source_ref": "memo",
                "page": None,
                "metadata": "bad",
            }
        ],
        "metadata": [],
    }
    service, _ = make_quizbank_service([extraction_payload])

    bundle, diagnostics = service._extract_evidence(task_spec, source_context)

    assert len(bundle.qualitative_evidence) == 1
    assert (
        bundle.qualitative_evidence[0].source_quote
        == bundle.qualitative_evidence[0].statement
    )
    assert bundle.qualitative_evidence[0].metadata == {}
    assert diagnostics["qualitative_evidence_count"] == 1
    assert bundle.qualitative_evidence[0].doc_id == "memo"


def test_generate_quiz_bank_falls_back_when_refinement_or_generation_breaks() -> None:
    scenario, task_spec, _ = _task_spec_and_context()
    extraction_payload, _, generation_payload = build_valid_quizbank_stage_responses()
    refinement_payload = {
        "quantitative_evidence": extraction_payload["quantitative_evidence"],
        "qualitative_evidence": [
            {"doc_id": "memo", "statement": "", "source_quote": ""}
        ],
        "metadata": {"stage": "refinement"},
    }
    broken_generation_payload = {"questions": "bad"}
    service, _ = make_quizbank_service(
        [extraction_payload, refinement_payload, broken_generation_payload]
    )

    questions, metadata = service.generate_quiz_bank(
        task_spec=task_spec,
        source_pack=scenario.source_pack,
    )

    assert len(questions) == 4
    assert metadata["generation_mode"] == "deterministic_fallback"
    assert metadata["question_count"] == 4
    assert metadata["question_types"] == ["qualitative", "quantitative"]
