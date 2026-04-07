from __future__ import annotations

import json
import re

from server.utils.reward_models import (
    ExtractionDraft,
    QuizContextChunk,
    QuizGenerationContext,
    RefinedQuizEvidence,
    SourcePack,
    TaskSpec,
    to_serializable,
)

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")


def _source_ref(doc_id: str, page: int | None) -> str:
    return f"{doc_id}:p{page}" if page is not None else doc_id


def _split_sentences(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        segment.strip()
        for segment in _SENTENCE_SPLIT_PATTERN.split(text)
        if segment.strip()
    ]


def _chunk_page_text(
    doc_id: str,
    title: str,
    page: int | None,
    text: str | None,
    *,
    max_chunk_chars: int,
) -> list[QuizContextChunk]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[QuizContextChunk] = []
    current_sentences: list[str] = []
    current_length = 0
    chunk_index = 1

    for sentence in sentences:
        sentence_length = len(sentence)
        would_overflow = (
            current_sentences and current_length + 1 + sentence_length > max_chunk_chars
        )
        if would_overflow:
            chunks.append(
                QuizContextChunk(
                    chunk_id=f"{doc_id}_p{page or 0:02d}_c{chunk_index:02d}",
                    doc_id=doc_id,
                    title=title,
                    page=page,
                    source_ref=_source_ref(doc_id, page),
                    text=" ".join(current_sentences),
                )
            )
            chunk_index += 1
            current_sentences = []
            current_length = 0
        current_sentences.append(sentence)
        current_length += sentence_length if not current_length else sentence_length + 1

    if current_sentences:
        chunks.append(
            QuizContextChunk(
                chunk_id=f"{doc_id}_p{page or 0:02d}_c{chunk_index:02d}",
                doc_id=doc_id,
                title=title,
                page=page,
                source_ref=_source_ref(doc_id, page),
                text=" ".join(current_sentences),
            )
        )
    return chunks


def build_quiz_generation_context(
    source_pack: SourcePack,
    *,
    max_chunk_chars: int = 1200,
) -> QuizGenerationContext:
    chunks: list[QuizContextChunk] = []
    for document in sorted(source_pack.documents, key=lambda doc: doc.doc_id):
        if document.pages:
            for page_index, page_text in enumerate(document.pages, start=1):
                chunks.extend(
                    _chunk_page_text(
                        document.doc_id,
                        document.title,
                        page_index,
                        page_text,
                        max_chunk_chars=max_chunk_chars,
                    )
                )
        else:
            chunks.extend(
                _chunk_page_text(
                    document.doc_id,
                    document.title,
                    None,
                    document.text,
                    max_chunk_chars=max_chunk_chars,
                )
            )

    return QuizGenerationContext(
        task_id=source_pack.task_id,
        document_count=len(source_pack.documents),
        chunks=chunks,
        metadata={"max_chunk_chars": max_chunk_chars},
    )


def render_quiz_generation_context(context: QuizGenerationContext) -> str:
    rendered_chunks = []
    for chunk in context.chunks:
        rendered_chunks.append(
            "\n".join(
                [
                    f"[CHUNK {chunk.chunk_id}]",
                    f"doc_id: {chunk.doc_id}",
                    f"title: {chunk.title}",
                    f"source_ref: {chunk.source_ref}",
                    f"page: {chunk.page if chunk.page is not None else 'null'}",
                    chunk.text,
                ]
            )
        )
    return "\n\n".join(rendered_chunks)


def build_quiz_extraction_prompts(
    task_spec: TaskSpec,
    source_context: QuizGenerationContext,
) -> tuple[str, str]:
    system_prompt = (
        "You are a Forensic Analyst building a source-grounded quiz bank for SlidesGenBench "
        "evaluation. Return strict JSON only. Extract anchors only when directly supported by "
        "the provided source text. Every anchor must include anchor_id, statement, source_quote, "
        "source_ref, doc_id, page, and metadata. Put numeric facts in quantitative_anchors and "
        "conceptual facts in qualitative_key_points."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_anchors": [...], "qualitative_key_points": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Extract 4 to 6 quantitative anchors when available.\n"
        "- Extract 6 to 8 qualitative anchors when available.\n"
        "- source_quote must be verbatim from the source text.\n"
        "- source_ref must match the provided source_ref field.\n"
        "- page must be null when unavailable.\n"
        "- metadata may include numbers or rationale.\n\n"
        "Source context:\n"
        f"{render_quiz_generation_context(source_context)}"
    )
    return system_prompt, user_prompt


def build_quiz_refinement_prompts(
    task_spec: TaskSpec,
    source_context: QuizGenerationContext,
    extraction_draft: ExtractionDraft,
) -> tuple[str, str]:
    system_prompt = (
        "You are a Strict Editor refining extracted quiz evidence for SlidesGenBench. Return "
        "strict JSON only. Keep only verified, high-value anchors. Remove duplicates, vague "
        "statements, and unsupported claims. Preserve exact source quotes and source locations."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_anchors": [...], "qualitative_anchors": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Keep only anchors directly supported by the source text.\n"
        "- Keep source_quote verbatim.\n"
        "- Keep source_ref, doc_id, and page aligned with the source text.\n"
        "- metadata may include edit notes or coverage notes.\n\n"
        "Draft extraction JSON:\n"
        f"{json.dumps(to_serializable(extraction_draft), indent=2, sort_keys=True)}\n\n"
        "Source context:\n"
        f"{render_quiz_generation_context(source_context)}"
    )
    return system_prompt, user_prompt


def build_quiz_generation_prompts(
    task_spec: TaskSpec,
    refined_evidence: RefinedQuizEvidence,
    *,
    target_question_count: int,
    concept_target: int,
    data_target: int,
    question_slots: list[dict[str, str]],
) -> tuple[str, str]:
    slot_json = json.dumps(question_slots, indent=2, sort_keys=True)
    system_prompt = (
        "You are a Professional Exam Setter. Return strict JSON only. Build a source-grounded "
        "multiple-choice quiz for slides-only open-book SlidesGenBench evaluation. Every "
        "question must have exactly 4 distinct options, one correct answer using the option "
        "text itself, an explanation, source_refs, and source_quotes. Do not emit commentary, "
        "markdown, or keys outside the requested schema."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"questions": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        f"- Generate exactly {target_question_count} questions.\n"
        f"- Generate exactly {concept_target} concept questions.\n"
        f"- Generate exactly {data_target} data questions.\n"
        "- Follow the requested slot plan exactly; emit one question for each slot and reuse the provided question_id exactly.\n"
        "- Each question object must contain question_id, question_type, question, options, correct_answer, explanation, source_refs, and source_quotes.\n"
        "- question_type must be either concept or data.\n"
        "- options must contain exactly 4 distinct strings.\n"
        "- correct_answer must equal one of the option texts.\n"
        "- explanation must mention at least one cited source_ref verbatim.\n"
        "- source_refs and source_quotes must come directly from the verified evidence.\n"
        "- Do not duplicate the same question stem or correct answer across slots unless the slot plan requires it.\n"
        "- Use only the verified evidence below.\n\n"
        "Question slot plan:\n"
        f"{slot_json}\n\n"
        "Verified evidence JSON:\n"
        f"{json.dumps(to_serializable(refined_evidence), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


def build_quiz_regeneration_prompts(
    task_spec: TaskSpec,
    refined_evidence: RefinedQuizEvidence,
    *,
    failed_slots: list[dict[str, object]],
    preserved_questions: list[dict[str, object]],
) -> tuple[str, str]:
    system_prompt = (
        "You are a Professional Exam Setter repairing only invalid SlidesGenBench quiz "
        "questions. Return strict JSON only. Regenerate only the requested failed slots and "
        "preserve the exact question_id and question_type for each repaired question."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"questions": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Generate questions only for the failed slots below.\n"
        "- Do not include preserved questions in the output.\n"
        "- Reuse each failed slot's question_id and question_type exactly.\n"
        "- Each repaired question must contain question_id, question_type, question, options, correct_answer, explanation, source_refs, and source_quotes.\n"
        "- options must contain exactly 4 distinct strings.\n"
        "- correct_answer must equal one of the option texts.\n"
        "- explanation must mention at least one cited source_ref verbatim.\n"
        "- source_refs and source_quotes must come directly from the verified evidence.\n"
        "- Avoid overlapping stems or correct answers with preserved questions unless unavoidable.\n\n"
        "Failed slots to repair:\n"
        f"{json.dumps(failed_slots, indent=2, sort_keys=True)}\n\n"
        "Already valid preserved questions:\n"
        f"{json.dumps(preserved_questions, indent=2, sort_keys=True)}\n\n"
        "Verified evidence JSON:\n"
        f"{json.dumps(to_serializable(refined_evidence), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


__all__ = [
    "build_quiz_extraction_prompts",
    "build_quiz_generation_context",
    "build_quiz_generation_prompts",
    "build_quiz_regeneration_prompts",
    "build_quiz_refinement_prompts",
    "render_quiz_generation_context",
]
