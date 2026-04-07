from __future__ import annotations

import re
from typing import Any, Protocol

from server.llm_client import LLMClient
from server.utils.reward_models import (
    QuizEvidence,
    QuizEvidenceBundle,
    QuizQuestion,
    SourcePack,
    TaskSpec,
    to_serializable,
)
from server.utils.slidesgenbench.prompts import (
    build_quiz_extraction_prompts,
    build_quiz_generation_prompts,
    build_quiz_refinement_prompts,
    build_quiz_regeneration_prompts,
    build_quiz_source_context,
)

_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class QuizBankGenerationService(Protocol):
    def generate_quiz_bank(
        self,
        *,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        mode: str = "eval",
    ) -> tuple[list[QuizQuestion], dict[str, Any]]: ...


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE_PATTERN.sub(" ", text).strip()


def _source_ref(doc_id: str, page: int | None) -> str:
    return f"{doc_id}:p{page}" if page is not None else doc_id


def _unique_evidence(items: list[QuizEvidence]) -> list[QuizEvidence]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[QuizEvidence] = []
    for item in items:
        key = (
            item.evidence_type,
            item.source_ref.lower(),
            item.statement.lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _document_source_texts(source_pack: SourcePack) -> dict[str, str]:
    source_texts: dict[str, str] = {}
    for document in source_pack.documents:
        parts = document.pages or [document.text or ""]
        source_texts[document.doc_id] = _normalize_text("\n".join(parts))
    return source_texts


def _coerce_page(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        raise ValueError("page must not be a boolean")
    return int(value)


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _parse_evidence(raw: Any, *, expected_type: str, default_id: str) -> QuizEvidence:
    if not isinstance(raw, dict):
        raise ValueError("evidence entry must be an object")
    doc_id = _require_string(raw, "doc_id")
    page = _coerce_page(raw.get("page"))
    source_ref = raw.get("source_ref") or _source_ref(doc_id, page)
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("source_ref must be a non-empty string")
    metadata = raw.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("evidence metadata must be an object")

    return QuizEvidence(
        evidence_id=str(raw.get("evidence_id") or default_id),
        evidence_type=expected_type,
        statement=_require_string(raw, "statement"),
        source_quote=_require_string(raw, "source_quote"),
        source_ref=source_ref.strip(),
        doc_id=doc_id,
        page=page,
        metadata=metadata,
    )


def _parse_evidence_bundle(payload: dict[str, Any]) -> QuizEvidenceBundle:
    quantitative = [
        _parse_evidence(
            raw, expected_type="quantitative", default_id=f"quantitative_{index:02d}"
        )
        for index, raw in enumerate(
            _require_list(payload, "quantitative_evidence"), start=1
        )
    ]
    qualitative = [
        _parse_evidence(
            raw, expected_type="qualitative", default_id=f"qualitative_{index:02d}"
        )
        for index, raw in enumerate(
            _require_list(payload, "qualitative_evidence"), start=1
        )
    ]
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    return QuizEvidenceBundle(
        quantitative_evidence=_unique_evidence(quantitative),
        qualitative_evidence=_unique_evidence(qualitative),
        metadata=metadata,
    )


def _parse_question(raw: Any, *, default_id: str) -> QuizQuestion:
    if not isinstance(raw, dict):
        raise ValueError("question entry must be an object")
    options = raw.get("options")
    if not isinstance(options, list):
        raise ValueError("question options must be a list")
    normalized_options = []
    for option in options:
        if not isinstance(option, str) or not option.strip():
            raise ValueError("question options must contain non-empty strings")
        normalized_options.append(option.strip())

    source_refs = raw.get("source_refs")
    source_quotes = raw.get("source_quotes")
    if not isinstance(source_refs, list) or not all(
        isinstance(ref, str) and ref.strip() for ref in source_refs
    ):
        raise ValueError("source_refs must be a list of non-empty strings")
    if not isinstance(source_quotes, list) or not all(
        isinstance(quote, str) and quote.strip() for quote in source_quotes
    ):
        raise ValueError("source_quotes must be a list of non-empty strings")

    return QuizQuestion(
        question_id=str(raw.get("question_id") or default_id),
        question_type=_require_string(raw, "question_type"),
        question=_require_string(raw, "question"),
        options=normalized_options,
        correct_answer=_require_string(raw, "correct_answer"),
        explanation=_require_string(raw, "explanation"),
        source_refs=[ref.strip() for ref in source_refs],
        source_quotes=[quote.strip() for quote in source_quotes],
    )


def _question_slot(question_id: str, question_type: str) -> dict[str, str]:
    return {"question_id": question_id, "question_type": question_type}


class SlidesGenQuizBankService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        max_attempts: int = 2,
        max_source_section_chars: int = 1200,
    ):
        if llm_client is None:
            raise ValueError("SlidesGenQuizBankService requires an llm_client")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.llm_client = llm_client
        self.max_attempts = max_attempts
        self.max_source_section_chars = max_source_section_chars

    def generate_quiz_bank(
        self,
        *,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        mode: str = "eval",
    ) -> tuple[list[QuizQuestion], dict[str, Any]]:
        source_context, source_section_count = build_quiz_source_context(
            source_pack,
            max_source_section_chars=self.max_source_section_chars,
        )
        extracted_evidence, extraction_diagnostics = self._extract_evidence(
            task_spec, source_context
        )
        verified_evidence, refinement_diagnostics = self._refine_evidence(
            task_spec,
            source_pack,
            source_context,
            extracted_evidence,
        )

        target_total = max(2, self._target_question_count(source_pack, mode=mode))
        qualitative_target = max(1, target_total // 2)
        quantitative_target = max(1, target_total - qualitative_target)
        questions, generation_diagnostics = self._generate_questions(
            task_spec,
            verified_evidence,
            target_total=target_total,
            qualitative_target=qualitative_target,
            quantitative_target=quantitative_target,
        )

        metadata = {
            "service_name": self.__class__.__name__,
            "generation_mode": "llm_source_grounded",
            "llm_client_type": self.llm_client.__class__.__name__,
            "source_section_count": source_section_count,
            "draft_quantitative_evidence_count": len(
                extracted_evidence.quantitative_evidence
            ),
            "draft_qualitative_evidence_count": len(
                extracted_evidence.qualitative_evidence
            ),
            "verified_quantitative_evidence_count": len(
                verified_evidence.quantitative_evidence
            ),
            "verified_qualitative_evidence_count": len(
                verified_evidence.qualitative_evidence
            ),
            "question_count": len(questions),
            "question_types": sorted(
                {question.question_type for question in questions}
            ),
            "stage_diagnostics": {
                "extraction": extraction_diagnostics,
                "refinement": refinement_diagnostics,
                "generation": generation_diagnostics,
            },
        }
        return questions, metadata

    def _call_stage_json(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = self.llm_client.chat_json(
                    system_prompt, user_prompt, temperature=0.0, max_tokens=max_tokens
                )
                if not isinstance(payload, dict):
                    raise ValueError(f"{stage_name} must return a JSON object")
                return payload, {"attempts": attempt, "max_tokens": max_tokens}
            except Exception as error:
                last_error = error
        raise ValueError(
            f"{stage_name} failed after {self.max_attempts} attempt(s): {last_error}"
        )

    def _extract_evidence(
        self,
        task_spec: TaskSpec,
        source_context: str,
    ) -> tuple[QuizEvidenceBundle, dict[str, Any]]:
        system_prompt, user_prompt = build_quiz_extraction_prompts(
            task_spec, source_context
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_extraction",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=3000,
        )
        evidence_bundle = _parse_evidence_bundle(payload)
        if not evidence_bundle.qualitative_evidence:
            raise ValueError("quiz_extraction returned no qualitative evidence")
        diagnostics.update(
            {
                "quantitative_evidence_count": len(
                    evidence_bundle.quantitative_evidence
                ),
                "qualitative_evidence_count": len(evidence_bundle.qualitative_evidence),
            }
        )
        return evidence_bundle, diagnostics

    def _verify_evidence(
        self,
        evidence: QuizEvidence,
        *,
        source_texts: dict[str, str],
    ) -> bool:
        source_text = source_texts.get(evidence.doc_id, "")
        if not source_text:
            return False
        expected_ref = _source_ref(evidence.doc_id, evidence.page)
        if evidence.source_ref != expected_ref:
            return False
        if _normalize_text(evidence.source_quote) not in source_text:
            return False
        if evidence.evidence_type == "quantitative" and not _NUMBER_PATTERN.search(
            f"{evidence.statement} {evidence.source_quote}"
        ):
            return False
        return True

    def _refine_evidence(
        self,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        source_context: str,
        evidence_bundle: QuizEvidenceBundle,
    ) -> tuple[QuizEvidenceBundle, dict[str, Any]]:
        system_prompt, user_prompt = build_quiz_refinement_prompts(
            task_spec,
            source_context,
            evidence_bundle,
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_refinement",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=3000,
        )
        candidate_bundle = _parse_evidence_bundle(payload)
        source_texts = _document_source_texts(source_pack)
        verified_quantitative = [
            evidence
            for evidence in candidate_bundle.quantitative_evidence
            if self._verify_evidence(evidence, source_texts=source_texts)
        ]
        verified_qualitative = [
            evidence
            for evidence in candidate_bundle.qualitative_evidence
            if self._verify_evidence(evidence, source_texts=source_texts)
        ]

        verified_bundle = QuizEvidenceBundle(
            quantitative_evidence=_unique_evidence(verified_quantitative),
            qualitative_evidence=_unique_evidence(verified_qualitative),
            metadata=candidate_bundle.metadata,
        )
        if not verified_bundle.qualitative_evidence:
            raise ValueError(
                "quiz_refinement returned no verified qualitative evidence"
            )
        if (
            task_spec.require_quantitative_content
            and not verified_bundle.quantitative_evidence
        ):
            raise ValueError(
                "quiz_refinement returned no verified quantitative evidence"
            )

        diagnostics.update(
            {
                "verified_quantitative_evidence_count": len(
                    verified_bundle.quantitative_evidence
                ),
                "verified_qualitative_evidence_count": len(
                    verified_bundle.qualitative_evidence
                ),
            }
        )
        return verified_bundle, diagnostics

    def _validate_question(
        self,
        question: QuizQuestion,
        *,
        evidence_bundle: QuizEvidenceBundle,
        expected_type: str | None = None,
    ) -> None:
        if expected_type is not None and question.question_type != expected_type:
            raise ValueError(
                f"question_type must be {expected_type} for question {question.question_id}"
            )
        if question.question_type not in {"qualitative", "quantitative"}:
            raise ValueError("question_type must be qualitative or quantitative")
        if len(question.options) != 4:
            raise ValueError("each question must have exactly 4 options")
        if len({option.lower() for option in question.options}) != 4:
            raise ValueError("question options must be distinct")
        if question.correct_answer not in question.options:
            raise ValueError("correct_answer must match one option exactly")
        if not any(ref in question.explanation for ref in question.source_refs):
            raise ValueError("explanation must mention at least one source_ref")

        all_evidence = (
            evidence_bundle.qualitative_evidence + evidence_bundle.quantitative_evidence
        )
        valid_refs = {item.source_ref for item in all_evidence}
        valid_quotes = {_normalize_text(item.source_quote) for item in all_evidence}
        if not set(question.source_refs).issubset(valid_refs):
            raise ValueError("question source_refs must come from verified evidence")
        if not {_normalize_text(quote) for quote in question.source_quotes}.issubset(
            valid_quotes
        ):
            raise ValueError("question source_quotes must come from verified evidence")
        if question.question_type == "quantitative" and not _NUMBER_PATTERN.search(
            question.correct_answer
        ):
            raise ValueError("quantitative questions must use a numeric correct answer")

    def _build_question_slots(
        self,
        *,
        qualitative_target: int,
        quantitative_target: int,
    ) -> list[dict[str, str]]:
        slots = [
            _question_slot(f"quiz_qualitative_{index:02d}", "qualitative")
            for index in range(1, qualitative_target + 1)
        ]
        slots.extend(
            _question_slot(f"quiz_quantitative_{index:02d}", "quantitative")
            for index in range(1, quantitative_target + 1)
        )
        return slots

    def _parse_questions_payload(self, payload: dict[str, Any]) -> list[QuizQuestion]:
        return [
            _parse_question(raw, default_id=f"quiz_{index:02d}")
            for index, raw in enumerate(_require_list(payload, "questions"), start=1)
        ]

    def _validate_question_collection(
        self,
        questions: list[QuizQuestion],
        *,
        evidence_bundle: QuizEvidenceBundle,
        expected_slots: list[dict[str, str]],
    ) -> tuple[list[QuizQuestion], list[dict[str, Any]], list[str]]:
        expected_by_id = {
            slot["question_id"]: slot["question_type"] for slot in expected_slots
        }
        valid_questions: list[QuizQuestion] = []
        failures: list[dict[str, Any]] = []
        seen_question_ids: set[str] = set()
        extra_question_ids: list[str] = []

        for question in questions:
            if question.question_id in seen_question_ids:
                failures.append(
                    {
                        "question_id": question.question_id,
                        "question_type": question.question_type,
                        "reason": "duplicate question_id in generated payload",
                    }
                )
                continue
            seen_question_ids.add(question.question_id)

            expected_type = expected_by_id.get(question.question_id)
            if expected_type is None:
                extra_question_ids.append(question.question_id)
                continue
            try:
                self._validate_question(
                    question,
                    evidence_bundle=evidence_bundle,
                    expected_type=expected_type,
                )
                valid_questions.append(question)
            except Exception as error:
                failures.append(
                    {
                        "question_id": question.question_id,
                        "question_type": expected_type,
                        "reason": str(error),
                    }
                )

        valid_ids = {question.question_id for question in valid_questions}
        failed_ids = {failure["question_id"] for failure in failures}
        for slot in expected_slots:
            if (
                slot["question_id"] not in valid_ids
                and slot["question_id"] not in failed_ids
            ):
                failures.append(
                    {
                        "question_id": slot["question_id"],
                        "question_type": slot["question_type"],
                        "reason": "missing required question slot",
                    }
                )

        return valid_questions, failures, extra_question_ids

    def _merge_questions_by_slot(
        self,
        *,
        questions: list[QuizQuestion],
        expected_slots: list[dict[str, str]],
    ) -> list[QuizQuestion]:
        by_id = {question.question_id: question for question in questions}
        return [by_id[slot["question_id"]] for slot in expected_slots]

    def _repair_failed_questions(
        self,
        *,
        task_spec: TaskSpec,
        evidence_bundle: QuizEvidenceBundle,
        failed_slots: list[dict[str, Any]],
        preserved_questions: list[QuizQuestion],
    ) -> tuple[list[QuizQuestion], dict[str, Any]]:
        system_prompt, user_prompt = build_quiz_regeneration_prompts(
            task_spec,
            evidence_bundle,
            failed_slots=failed_slots,
            preserved_questions=to_serializable(preserved_questions),
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_generation_repair",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=2500,
        )
        repaired_questions = self._parse_questions_payload(payload)
        expected_slots = [
            _question_slot(slot["question_id"], slot["question_type"])
            for slot in failed_slots
        ]
        valid_repaired, repair_failures, extra_question_ids = (
            self._validate_question_collection(
                repaired_questions,
                evidence_bundle=evidence_bundle,
                expected_slots=expected_slots,
            )
        )
        if repair_failures:
            raise ValueError(
                "quiz_generation_repair returned unresolved invalid questions: "
                + "; ".join(
                    f"{failure['question_id']}: {failure['reason']}"
                    for failure in repair_failures
                )
            )
        if extra_question_ids:
            diagnostics["extra_question_ids"] = sorted(extra_question_ids)
        diagnostics["repaired_question_count"] = len(valid_repaired)
        return valid_repaired, diagnostics

    def _generate_questions(
        self,
        task_spec: TaskSpec,
        evidence_bundle: QuizEvidenceBundle,
        *,
        target_total: int,
        qualitative_target: int,
        quantitative_target: int,
    ) -> tuple[list[QuizQuestion], dict[str, Any]]:
        question_slots = self._build_question_slots(
            qualitative_target=qualitative_target,
            quantitative_target=quantitative_target,
        )
        system_prompt, user_prompt = build_quiz_generation_prompts(
            task_spec,
            evidence_bundle,
            target_question_count=target_total,
            qualitative_target=qualitative_target,
            quantitative_target=quantitative_target,
            question_slots=question_slots,
        )

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = self.llm_client.chat_json(
                    system_prompt, user_prompt, temperature=0.0, max_tokens=4000
                )
                if not isinstance(payload, dict):
                    raise ValueError("quiz_generation must return a JSON object")
                generated_questions = self._parse_questions_payload(payload)
                valid_questions, failures, extra_question_ids = (
                    self._validate_question_collection(
                        generated_questions,
                        evidence_bundle=evidence_bundle,
                        expected_slots=question_slots,
                    )
                )

                repair_diagnostics: dict[str, Any] | None = None
                if failures:
                    repaired_questions, repair_diagnostics = (
                        self._repair_failed_questions(
                            task_spec=task_spec,
                            evidence_bundle=evidence_bundle,
                            failed_slots=failures,
                            preserved_questions=valid_questions,
                        )
                    )
                    valid_questions.extend(repaired_questions)

                final_questions = self._merge_questions_by_slot(
                    questions=valid_questions,
                    expected_slots=question_slots,
                )
                diagnostics = {
                    "attempts": attempt,
                    "max_tokens": 4000,
                    "question_count": len(final_questions),
                    "full_generation_invalid_count": len(failures),
                }
                if extra_question_ids:
                    diagnostics["extra_question_ids"] = sorted(extra_question_ids)
                if failures:
                    diagnostics["repaired_slots"] = failures
                if repair_diagnostics:
                    diagnostics["repair"] = repair_diagnostics
                return final_questions, diagnostics
            except Exception as error:
                last_error = error

        raise ValueError(
            f"quiz_generation failed after {self.max_attempts} attempt(s): {last_error}"
        )

    def _target_question_count(self, source_pack: SourcePack, *, mode: str) -> int:
        text_volume = 0
        for document in source_pack.documents:
            for page_text in document.pages or [document.text or ""]:
                text_volume += len(page_text)
        if text_volume < 4_000:
            target = 10
        elif text_volume < 9_000:
            target = 14
        else:
            target = 18
        if mode == "train":
            return min(target, 10)
        return target


__all__ = [
    "QuizBankGenerationService",
    "SlidesGenQuizBankService",
]
