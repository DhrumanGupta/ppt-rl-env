from __future__ import annotations

import re
from typing import Any, Protocol

from server.llm_client import LLMClient
from server.utils.reward_models import (
    ExtractionDraft,
    GeneratedQuizBankPayload,
    QuizAnchor,
    QuizQuestion,
    RefinedQuizEvidence,
    SourcePack,
    TaskSpec,
    to_serializable,
)
from server.utils.slidesgenbench.prompts import (
    build_quiz_extraction_prompts,
    build_quiz_generation_context,
    build_quiz_generation_prompts,
    build_quiz_regeneration_prompts,
    build_quiz_refinement_prompts,
)

_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class StructuredQuizLLMClient(Protocol):
    def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]: ...


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


def _unique_anchors(anchors: list[QuizAnchor]) -> list[QuizAnchor]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[QuizAnchor] = []
    for anchor in anchors:
        key = (anchor.anchor_type, anchor.source_ref.lower(), anchor.statement.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(anchor)
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


def _parse_anchor(raw: Any, *, expected_type: str, default_id: str) -> QuizAnchor:
    if not isinstance(raw, dict):
        raise ValueError("anchor entry must be an object")
    doc_id = _require_string(raw, "doc_id")
    page = _coerce_page(raw.get("page"))
    source_ref = raw.get("source_ref") or _source_ref(doc_id, page)
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("source_ref must be a non-empty string")
    metadata = raw.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("anchor metadata must be an object")

    return QuizAnchor(
        anchor_id=str(raw.get("anchor_id") or default_id),
        anchor_type=expected_type,
        statement=_require_string(raw, "statement"),
        source_quote=_require_string(raw, "source_quote"),
        source_ref=source_ref.strip(),
        doc_id=doc_id,
        page=page,
        metadata=metadata,
    )


def _parse_extraction_payload(payload: dict[str, Any]) -> ExtractionDraft:
    quantitative = [
        _parse_anchor(raw, expected_type="data", default_id=f"data_{index:02d}")
        for index, raw in enumerate(
            _require_list(payload, "quantitative_anchors"), start=1
        )
    ]
    qualitative_key = (
        "qualitative_key_points"
        if "qualitative_key_points" in payload
        else "qualitative_anchors"
    )
    qualitative = [
        _parse_anchor(raw, expected_type="concept", default_id=f"concept_{index:02d}")
        for index, raw in enumerate(_require_list(payload, qualitative_key), start=1)
    ]
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    return ExtractionDraft(
        quantitative_anchors=_unique_anchors(quantitative),
        qualitative_anchors=_unique_anchors(qualitative),
        metadata=metadata,
    )


def _parse_refined_payload(payload: dict[str, Any]) -> RefinedQuizEvidence:
    quantitative = [
        _parse_anchor(raw, expected_type="data", default_id=f"data_{index:02d}")
        for index, raw in enumerate(
            _require_list(payload, "quantitative_anchors"), start=1
        )
    ]
    qualitative = [
        _parse_anchor(raw, expected_type="concept", default_id=f"concept_{index:02d}")
        for index, raw in enumerate(
            _require_list(payload, "qualitative_anchors"), start=1
        )
    ]
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    return RefinedQuizEvidence(
        quantitative_anchors=_unique_anchors(quantitative),
        qualitative_anchors=_unique_anchors(qualitative),
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
        llm_client: StructuredQuizLLMClient | LLMClient,
        *,
        max_attempts: int = 2,
        max_chunk_chars: int = 1200,
    ):
        if llm_client is None:
            raise ValueError("SlidesGenQuizBankService requires an llm_client")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.llm_client = llm_client
        self.max_attempts = max_attempts
        self.max_chunk_chars = max_chunk_chars

    def generate_quiz_bank(
        self,
        *,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        mode: str = "eval",
    ) -> tuple[list[QuizQuestion], dict[str, Any]]:
        source_context = build_quiz_generation_context(
            source_pack, max_chunk_chars=self.max_chunk_chars
        )
        draft_bundle, draft_diagnostics = self._extract_source_truth(
            task_spec, source_context
        )
        refined_bundle, refine_diagnostics = self._verify_and_refine(
            task_spec, source_pack, source_context, draft_bundle
        )

        target_total = max(2, self._target_question_count(source_pack, mode=mode))
        concept_target = max(1, target_total // 2)
        data_target = max(1, target_total - concept_target)
        quiz_payload, generation_diagnostics = self._generate_mcqs(
            task_spec,
            refined_bundle,
            target_total=target_total,
            concept_target=concept_target,
            data_target=data_target,
        )

        metadata = {
            "service_name": self.__class__.__name__,
            "generation_mode": "llm_source_grounded",
            "llm_client_type": self.llm_client.__class__.__name__,
            "source_chunk_count": len(source_context.chunks),
            "draft_quantitative_anchor_count": len(draft_bundle.quantitative_anchors),
            "draft_qualitative_anchor_count": len(draft_bundle.qualitative_anchors),
            "verified_quantitative_anchor_count": len(
                refined_bundle.quantitative_anchors
            ),
            "verified_qualitative_anchor_count": len(
                refined_bundle.qualitative_anchors
            ),
            "question_count": len(quiz_payload.questions),
            "question_types": sorted(
                {question.question_type for question in quiz_payload.questions}
            ),
            "stage_diagnostics": {
                "extraction": draft_diagnostics,
                "refinement": refine_diagnostics,
                "generation": generation_diagnostics,
            },
        }
        if quiz_payload.metadata:
            metadata["generation_metadata"] = quiz_payload.metadata
        return quiz_payload.questions, metadata

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

    def _extract_source_truth(
        self,
        task_spec: TaskSpec,
        source_context,
    ) -> tuple[ExtractionDraft, dict[str, Any]]:
        system_prompt, user_prompt = build_quiz_extraction_prompts(
            task_spec, source_context
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_extraction",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=3000,
        )
        draft = _parse_extraction_payload(payload)
        if not draft.qualitative_anchors:
            raise ValueError("quiz_extraction returned no qualitative anchors")
        diagnostics.update(
            {
                "quantitative_anchor_count": len(draft.quantitative_anchors),
                "qualitative_anchor_count": len(draft.qualitative_anchors),
            }
        )
        return draft, diagnostics

    def _verify_anchor(
        self, anchor: QuizAnchor, *, source_texts: dict[str, str]
    ) -> bool:
        source_text = source_texts.get(anchor.doc_id, "")
        if not source_text:
            return False
        expected_ref = _source_ref(anchor.doc_id, anchor.page)
        if anchor.source_ref != expected_ref:
            return False
        if _normalize_text(anchor.source_quote) not in source_text:
            return False
        if anchor.anchor_type == "data" and not _NUMBER_PATTERN.search(
            f"{anchor.statement} {anchor.source_quote}"
        ):
            return False
        return True

    def _verify_and_refine(
        self,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        source_context,
        draft_bundle: ExtractionDraft,
    ) -> tuple[RefinedQuizEvidence, dict[str, Any]]:
        system_prompt, user_prompt = build_quiz_refinement_prompts(
            task_spec, source_context, draft_bundle
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_refinement",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=3000,
        )
        candidate_bundle = _parse_refined_payload(payload)
        source_texts = _document_source_texts(source_pack)
        verified_quantitative = [
            anchor
            for anchor in candidate_bundle.quantitative_anchors
            if self._verify_anchor(anchor, source_texts=source_texts)
        ]
        verified_qualitative = [
            anchor
            for anchor in candidate_bundle.qualitative_anchors
            if self._verify_anchor(anchor, source_texts=source_texts)
        ]

        refined = RefinedQuizEvidence(
            quantitative_anchors=_unique_anchors(verified_quantitative),
            qualitative_anchors=_unique_anchors(verified_qualitative),
            metadata=candidate_bundle.metadata,
        )
        if not refined.qualitative_anchors:
            raise ValueError("quiz_refinement returned no verified qualitative anchors")
        if task_spec.require_quantitative_content and not refined.quantitative_anchors:
            raise ValueError(
                "quiz_refinement returned no verified quantitative anchors"
            )

        diagnostics.update(
            {
                "verified_quantitative_anchor_count": len(refined.quantitative_anchors),
                "verified_qualitative_anchor_count": len(refined.qualitative_anchors),
            }
        )
        return refined, diagnostics

    def _validate_question(
        self,
        question: QuizQuestion,
        *,
        evidence: RefinedQuizEvidence,
        expected_type: str | None = None,
    ) -> None:
        if expected_type is not None and question.question_type != expected_type:
            raise ValueError(
                f"question_type must be {expected_type} for question {question.question_id}"
            )
        if question.question_type not in {"concept", "data"}:
            raise ValueError("question_type must be concept or data")
        if len(question.options) != 4:
            raise ValueError("each question must have exactly 4 options")
        if len({option.lower() for option in question.options}) != 4:
            raise ValueError("question options must be distinct")
        if question.correct_answer not in question.options:
            raise ValueError("correct_answer must match one option exactly")
        if not any(ref in question.explanation for ref in question.source_refs):
            raise ValueError("explanation must mention at least one source_ref")

        valid_refs = {
            anchor.source_ref
            for anchor in evidence.qualitative_anchors + evidence.quantitative_anchors
        }
        valid_quotes = {
            _normalize_text(anchor.source_quote)
            for anchor in evidence.qualitative_anchors + evidence.quantitative_anchors
        }
        if not set(question.source_refs).issubset(valid_refs):
            raise ValueError("question source_refs must come from verified evidence")
        if not {_normalize_text(quote) for quote in question.source_quotes}.issubset(
            valid_quotes
        ):
            raise ValueError("question source_quotes must come from verified evidence")
        if question.question_type == "data" and not _NUMBER_PATTERN.search(
            question.correct_answer
        ):
            raise ValueError("data questions must use a numeric correct answer")

    def _build_question_slots(
        self, *, concept_target: int, data_target: int
    ) -> list[dict[str, str]]:
        slots = [
            _question_slot(f"quiz_concept_{index:02d}", "concept")
            for index in range(1, concept_target + 1)
        ]
        slots.extend(
            _question_slot(f"quiz_data_{index:02d}", "data")
            for index in range(1, data_target + 1)
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
        evidence: RefinedQuizEvidence,
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
                    question, evidence=evidence, expected_type=expected_type
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
        self, *, questions: list[QuizQuestion], expected_slots: list[dict[str, str]]
    ) -> list[QuizQuestion]:
        by_id = {question.question_id: question for question in questions}
        return [by_id[slot["question_id"]] for slot in expected_slots]

    def _repair_failed_questions(
        self,
        *,
        task_spec: TaskSpec,
        evidence_bundle: RefinedQuizEvidence,
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
                evidence=evidence_bundle,
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

    def _generate_mcqs(
        self,
        task_spec: TaskSpec,
        evidence_bundle: RefinedQuizEvidence,
        *,
        target_total: int,
        concept_target: int,
        data_target: int,
    ) -> tuple[GeneratedQuizBankPayload, dict[str, Any]]:
        question_slots = self._build_question_slots(
            concept_target=concept_target, data_target=data_target
        )
        system_prompt, user_prompt = build_quiz_generation_prompts(
            task_spec,
            evidence_bundle,
            target_question_count=target_total,
            concept_target=concept_target,
            data_target=data_target,
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
                metadata = (
                    payload.get("metadata")
                    if isinstance(payload.get("metadata"), dict)
                    else {}
                )
                valid_questions, failures, extra_question_ids = (
                    self._validate_question_collection(
                        generated_questions,
                        evidence=evidence_bundle,
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
                    questions=valid_questions, expected_slots=question_slots
                )
                parsed = GeneratedQuizBankPayload(
                    questions=final_questions, metadata=metadata
                )
                diagnostics = {
                    "attempts": attempt,
                    "max_tokens": 4000,
                    "question_count": len(parsed.questions),
                    "full_generation_invalid_count": len(failures),
                }
                if extra_question_ids:
                    diagnostics["extra_question_ids"] = sorted(extra_question_ids)
                if failures:
                    diagnostics["repaired_slots"] = failures
                if repair_diagnostics:
                    diagnostics["repair"] = repair_diagnostics
                return parsed, diagnostics
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
    "StructuredQuizLLMClient",
]
