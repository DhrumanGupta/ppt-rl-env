from __future__ import annotations

from dataclasses import replace
import logging
import re
from typing import Any, Protocol

from server.debug_logging import write_debug_event
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
    build_quiz_source_context,
)

_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_WHITESPACE_PATTERN = re.compile(r"\s+")

logger = logging.getLogger(__name__)


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


def _sanitize_evidence(
    raw: Any, *, expected_type: str, default_id: str
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    doc_id = raw.get("doc_id")
    source_ref = raw.get("source_ref")
    if not isinstance(doc_id, str) or not doc_id.strip():
        if isinstance(source_ref, str) and source_ref.strip():
            doc_id = source_ref.split(":p", 1)[0].strip()
    if not isinstance(doc_id, str) or not doc_id.strip():
        return None
    try:
        page = _coerce_page(raw.get("page"))
    except Exception:
        page = None
    statement = raw.get("statement")
    source_quote = raw.get("source_quote")
    if not isinstance(statement, str) or not statement.strip():
        statement = source_quote
    if not isinstance(statement, str) or not statement.strip():
        return None
    if not isinstance(source_quote, str) or not source_quote.strip():
        source_quote = statement
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if not isinstance(source_ref, str) or not source_ref.strip():
        source_ref = _source_ref(doc_id.strip(), page)
    return {
        "evidence_id": str(raw.get("evidence_id") or default_id),
        "evidence_type": expected_type,
        "statement": statement.strip(),
        "source_quote": source_quote.strip(),
        "source_ref": source_ref.strip(),
        "doc_id": doc_id.strip(),
        "page": page,
        "metadata": metadata,
    }


def _sanitize_evidence_bundle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    quantitative = [
        item
        for index, raw in enumerate(payload.get("quantitative_evidence") or [], start=1)
        if (
            item := _sanitize_evidence(
                raw,
                expected_type="quantitative",
                default_id=f"quantitative_{index:02d}",
            )
        )
        is not None
    ]
    qualitative = [
        item
        for index, raw in enumerate(payload.get("qualitative_evidence") or [], start=1)
        if (
            item := _sanitize_evidence(
                raw,
                expected_type="qualitative",
                default_id=f"qualitative_{index:02d}",
            )
        )
        is not None
    ]
    metadata = payload.get("metadata")
    return {
        "quantitative_evidence": quantitative,
        "qualitative_evidence": qualitative,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


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
        max_source_section_chars: int = 1200,
    ):
        if llm_client is None:
            raise ValueError("SlidesGenQuizBankService requires an llm_client")
        self.llm_client = llm_client
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
        target_total = max(2, self._target_question_count(source_pack, mode=mode))
        qualitative_target = max(1, target_total // 2)
        quantitative_target = max(1, target_total - qualitative_target)
        try:
            extracted_evidence, extraction_diagnostics = self._extract_evidence(
                task_spec, source_context
            )
            verified_evidence, refinement_diagnostics = self._refine_evidence(
                task_spec,
                source_pack,
                source_context,
                extracted_evidence,
            )
            questions, generation_diagnostics = self._generate_questions(
                task_spec,
                source_pack,
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
        except Exception as error:
            logger.warning("quizbank fallback enabled: %s", error)
            write_debug_event(
                "quizbank.fallback",
                {
                    "error": str(error),
                    "target_total": target_total,
                    "qualitative_target": qualitative_target,
                    "quantitative_target": quantitative_target,
                },
            )
            questions = self._build_fallback_questions(
                task_spec,
                source_pack,
                target_total=target_total,
                qualitative_target=qualitative_target,
                quantitative_target=quantitative_target,
            )
            return questions, {
                "service_name": self.__class__.__name__,
                "generation_mode": "deterministic_fallback",
                "llm_client_type": self.llm_client.__class__.__name__,
                "source_section_count": source_section_count,
                "question_count": len(questions),
                "question_types": sorted(
                    {question.question_type for question in questions}
                ),
                "error": str(error),
            }

    def _call_stage_json(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        logger.info("quizbank stage start stage=%s", stage_name)
        try:
            payload = self.llm_client.chat_json(
                system_prompt,
                user_prompt,
                temperature=0.0,
                max_tokens=max_tokens,
                debug_stage=stage_name,
            )
        except Exception as error:
            logger.warning("quizbank stage failed stage=%s error=%s", stage_name, error)
            raise ValueError(f"{stage_name} failed: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"{stage_name} must return a JSON object")
        logger.info("quizbank stage success stage=%s", stage_name)
        write_debug_event(
            "quizbank.stage_success",
            {
                "stage": stage_name,
                "max_tokens": max_tokens,
            },
        )
        return payload, {"max_tokens": max_tokens}

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
            max_tokens=1800,
        )
        evidence_bundle = _parse_evidence_bundle(
            _sanitize_evidence_bundle_payload(payload)
        )
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

    def _verify_bundle(
        self,
        bundle: QuizEvidenceBundle,
        *,
        source_pack: SourcePack,
    ) -> QuizEvidenceBundle:
        source_texts = _document_source_texts(source_pack)
        return QuizEvidenceBundle(
            quantitative_evidence=_unique_evidence(
                [
                    evidence
                    for evidence in bundle.quantitative_evidence
                    if self._verify_evidence(evidence, source_texts=source_texts)
                ]
            ),
            qualitative_evidence=_unique_evidence(
                [
                    evidence
                    for evidence in bundle.qualitative_evidence
                    if self._verify_evidence(evidence, source_texts=source_texts)
                ]
            ),
            metadata=bundle.metadata,
        )

    def _refine_evidence(
        self,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        source_context: str,
        evidence_bundle: QuizEvidenceBundle,
    ) -> tuple[QuizEvidenceBundle, dict[str, Any]]:
        verified_extraction_bundle = self._verify_bundle(
            evidence_bundle, source_pack=source_pack
        )
        if verified_extraction_bundle.qualitative_evidence and (
            not task_spec.require_quantitative_content
            or verified_extraction_bundle.quantitative_evidence
        ):
            return verified_extraction_bundle, {
                "max_tokens": 0,
                "used_verified_extraction": True,
                "verified_quantitative_evidence_count": len(
                    verified_extraction_bundle.quantitative_evidence
                ),
                "verified_qualitative_evidence_count": len(
                    verified_extraction_bundle.qualitative_evidence
                ),
            }

        system_prompt, user_prompt = build_quiz_refinement_prompts(
            task_spec,
            source_context,
            evidence_bundle,
        )
        payload, diagnostics = self._call_stage_json(
            stage_name="quiz_refinement",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1800,
        )
        candidate_bundle = _parse_evidence_bundle(
            _sanitize_evidence_bundle_payload(payload)
        )
        verified_bundle = self._verify_bundle(candidate_bundle, source_pack=source_pack)
        if not verified_bundle.qualitative_evidence:
            logger.warning(
                "quizbank refinement empty, falling back to extraction evidence"
            )
            verified_bundle = self._verify_bundle(
                evidence_bundle, source_pack=source_pack
            )
            diagnostics["used_extraction_fallback"] = True
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

    def _build_local_repair_questions(
        self,
        *,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        failed_slots: list[dict[str, Any]],
    ) -> list[QuizQuestion]:
        qualitative_target = sum(
            1 for slot in failed_slots if slot.get("question_type") == "qualitative"
        )
        quantitative_target = len(failed_slots) - qualitative_target
        fallback_questions = self._build_fallback_questions(
            task_spec,
            source_pack,
            target_total=len(failed_slots),
            qualitative_target=qualitative_target,
            quantitative_target=quantitative_target,
        )

        qualitative_fallbacks = [
            question
            for question in fallback_questions
            if question.question_type == "qualitative"
        ]
        quantitative_fallbacks = [
            question
            for question in fallback_questions
            if question.question_type == "quantitative"
        ]
        qualitative_index = 0
        quantitative_index = 0
        repaired: list[QuizQuestion] = []

        for slot in failed_slots:
            question_type = str(slot["question_type"])
            if question_type == "qualitative":
                template = qualitative_fallbacks[qualitative_index]
                qualitative_index += 1
            else:
                template = quantitative_fallbacks[quantitative_index]
                quantitative_index += 1
            repaired.append(
                replace(
                    template,
                    question_id=str(slot["question_id"]),
                    question_type=question_type,
                )
            )
        return repaired

    def _generate_questions(
        self,
        task_spec: TaskSpec,
        source_pack: SourcePack,
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
        payload = self.llm_client.chat_json(
            system_prompt, user_prompt, temperature=0.0, max_tokens=2200
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

        if failures:
            repaired_questions = self._build_local_repair_questions(
                task_spec=task_spec,
                source_pack=source_pack,
                failed_slots=failures,
            )
            valid_questions.extend(repaired_questions)

        final_questions = self._merge_questions_by_slot(
            questions=valid_questions,
            expected_slots=question_slots,
        )
        diagnostics = {
            "max_tokens": 2200,
            "question_count": len(final_questions),
            "full_generation_invalid_count": len(failures),
        }
        if extra_question_ids:
            diagnostics["extra_question_ids"] = sorted(extra_question_ids)
        if failures:
            diagnostics["repaired_slots"] = failures
            diagnostics["repair_mode"] = "deterministic_fallback"
        return final_questions, diagnostics

    def _target_question_count(self, source_pack: SourcePack, *, mode: str) -> int:
        text_volume = 0
        for document in source_pack.documents:
            for page_text in document.pages or [document.text or ""]:
                text_volume += len(page_text)
        if text_volume < 4_000:
            target = 4
        elif text_volume < 9_000:
            target = 5
        else:
            target = 6
        if mode == "train":
            return min(target, 4)
        return target

    def _build_fallback_questions(
        self,
        task_spec: TaskSpec,
        source_pack: SourcePack,
        *,
        target_total: int,
        qualitative_target: int,
        quantitative_target: int,
    ) -> list[QuizQuestion]:
        facts = task_spec.metadata.get("source_facts") or []
        evidence: list[tuple[str, str, str]] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            text = fact.get("text")
            doc_id = fact.get("doc_id")
            if not isinstance(text, str) or not text.strip():
                continue
            if not isinstance(doc_id, str) or not doc_id.strip():
                doc_id = source_pack.documents[0].doc_id
            evidence.append(
                (text.strip(), doc_id.strip(), _source_ref(doc_id.strip(), None))
            )
        if not evidence:
            for document in source_pack.documents:
                for text in document.pages or [document.text or ""]:
                    for sentence in re.split(r"(?<=[.!?])\s+", text):
                        if sentence.strip():
                            evidence.append(
                                (
                                    sentence.strip(),
                                    document.doc_id,
                                    _source_ref(document.doc_id, None),
                                )
                            )
        qualitative_evidence = [
            item for item in evidence if not _NUMBER_PATTERN.search(item[0])
        ]
        quantitative_evidence = [
            item for item in evidence if _NUMBER_PATTERN.search(item[0])
        ]

        def distractor_statements(
            correct: str, pool: list[tuple[str, str, str]]
        ) -> list[str]:
            options = [item[0] for item in pool if item[0] != correct]
            options.extend(
                [
                    "The source does not mention this.",
                    "The source describes a different operational goal.",
                    "The source reports the opposite outcome.",
                ]
            )
            unique: list[str] = []
            seen: set[str] = set()
            for option in options:
                key = option.lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(option)
                if len(unique) == 3:
                    break
            return unique

        all_numbers = [
            number
            for text, _, _ in quantitative_evidence
            for number in _NUMBER_PATTERN.findall(text)
        ]

        def distractor_numbers(correct: str) -> list[str]:
            candidates = [value for value in all_numbers if value != correct]
            candidates.extend(
                [
                    f"{int(correct.rstrip('%')) + 1}%"
                    if correct.endswith("%") and correct.rstrip("%").isdigit()
                    else "99",
                    f"{int(correct) + 1}" if correct.isdigit() else "0",
                    f"{int(correct) - 1}"
                    if correct.isdigit() and int(correct) > 0
                    else "1",
                ]
            )
            unique: list[str] = []
            seen: set[str] = {correct}
            for candidate in candidates:
                if candidate in seen:
                    continue
                seen.add(candidate)
                unique.append(candidate)
                if len(unique) == 3:
                    break
            pad_value = 1
            while len(unique) < 3:
                candidate = str(pad_value)
                pad_value += 1
                if candidate in seen:
                    continue
                seen.add(candidate)
                unique.append(candidate)
            return unique

        questions: list[QuizQuestion] = []
        qualitative_pool = (
            qualitative_evidence
            or evidence
            or [
                (
                    task_spec.prompt,
                    source_pack.documents[0].doc_id,
                    source_pack.documents[0].doc_id,
                )
            ]
        )
        quantitative_pool = quantitative_evidence or evidence or qualitative_pool
        for index in range(1, qualitative_target + 1):
            statement, _, source_ref = qualitative_pool[
                (index - 1) % len(qualitative_pool)
            ]
            options = [
                statement,
                *distractor_statements(statement, qualitative_evidence or evidence),
            ]
            questions.append(
                QuizQuestion(
                    question_id=f"quiz_qualitative_{index:02d}",
                    question_type="qualitative",
                    question=f"Which statement is directly supported by {source_ref}?",
                    options=options[:4],
                    correct_answer=statement,
                    explanation=f"The source states this directly in {source_ref}.",
                    source_refs=[source_ref],
                    source_quotes=[statement],
                )
            )
        for index in range(1, quantitative_target + 1):
            statement, _, source_ref = quantitative_pool[
                (index - 1) % len(quantitative_pool)
            ]
            numbers = _NUMBER_PATTERN.findall(statement)
            correct = numbers[0] if numbers else "0"
            options = [correct, *distractor_numbers(correct)]
            questions.append(
                QuizQuestion(
                    question_id=f"quiz_quantitative_{index:02d}",
                    question_type="quantitative",
                    question=f"Which numeric value is directly stated in {source_ref}?",
                    options=options[:4],
                    correct_answer=correct,
                    explanation=f"The cited value appears in {source_ref}.",
                    source_refs=[source_ref],
                    source_quotes=[statement],
                )
            )
        return questions[:target_total]


__all__ = [
    "QuizBankGenerationService",
    "SlidesGenQuizBankService",
]
