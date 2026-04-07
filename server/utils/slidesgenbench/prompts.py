from __future__ import annotations

import json
import re

from server.utils.reward_metrics import slide_text_corpus
from server.utils.reward_models import (
    ExtractedPresentation,
    QuizEvidenceBundle,
    QuizQuestion,
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
    max_source_section_chars: int,
) -> list[str]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_length = 0
    chunk_index = 1

    for sentence in sentences:
        sentence_length = len(sentence)
        would_overflow = (
            current_sentences
            and current_length + 1 + sentence_length > max_source_section_chars
        )
        if would_overflow:
            chunks.append(
                "\n".join(
                    [
                        f"[SOURCE {doc_id}_p{page or 0:02d}_c{chunk_index:02d}]",
                        f"doc_id: {doc_id}",
                        f"title: {title}",
                        f"source_ref: {_source_ref(doc_id, page)}",
                        f"page: {page if page is not None else 'null'}",
                        " ".join(current_sentences),
                    ]
                )
            )
            chunk_index += 1
            current_sentences = []
            current_length = 0
        current_sentences.append(sentence)
        current_length += sentence_length if not current_length else sentence_length + 1

    if current_sentences:
        chunks.append(
            "\n".join(
                [
                    f"[SOURCE {doc_id}_p{page or 0:02d}_c{chunk_index:02d}]",
                    f"doc_id: {doc_id}",
                    f"title: {title}",
                    f"source_ref: {_source_ref(doc_id, page)}",
                    f"page: {page if page is not None else 'null'}",
                    " ".join(current_sentences),
                ]
            )
        )
    return chunks


def build_quiz_source_context(
    source_pack: SourcePack,
    *,
    max_source_section_chars: int = 1200,
) -> tuple[str, int]:
    sections: list[str] = []
    for document in sorted(source_pack.documents, key=lambda doc: doc.doc_id):
        if document.pages:
            for page_index, page_text in enumerate(document.pages, start=1):
                sections.extend(
                    _chunk_page_text(
                        document.doc_id,
                        document.title,
                        page_index,
                        page_text,
                        max_source_section_chars=max_source_section_chars,
                    )
                )
        else:
            sections.extend(
                _chunk_page_text(
                    document.doc_id,
                    document.title,
                    None,
                    document.text,
                    max_source_section_chars=max_source_section_chars,
                )
            )
    return "\n\n".join(sections), len(sections)


def build_quiz_extraction_prompts(
    task_spec: TaskSpec,
    source_context: str,
) -> tuple[str, str]:
    system_prompt = (
        "You are a forensic analyst building a source-grounded quiz bank from reference "
        "materials. Return strict JSON only. Extract evidence only when directly supported by "
        "the provided source text. Every evidence item must include evidence_id, statement, "
        "source_quote, source_ref, doc_id, page, and metadata. Put numeric facts in "
        "quantitative_evidence and non-numeric factual claims in qualitative_evidence."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_evidence": [...], "qualitative_evidence": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Extract 4 to 6 quantitative evidence items when available.\n"
        "- Extract 6 to 8 qualitative evidence items when available.\n"
        "- source_quote must be verbatim from the source text.\n"
        "- source_ref must match the provided source_ref field.\n"
        "- page must be null when unavailable.\n"
        "- metadata may include numbers or rationale.\n\n"
        "Source context:\n"
        f"{source_context}"
    )
    return system_prompt, user_prompt


def build_quiz_refinement_prompts(
    task_spec: TaskSpec,
    source_context: str,
    evidence_bundle: QuizEvidenceBundle,
) -> tuple[str, str]:
    system_prompt = (
        "You are a strict editor refining extracted quiz evidence. Return "
        "strict JSON only. Keep only verified, high-value evidence. Remove duplicates, vague "
        "statements, and unsupported claims. Preserve exact source quotes and source locations."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"quantitative_evidence": [...], "qualitative_evidence": [...], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Keep only evidence directly supported by the source text.\n"
        "- Keep source_quote verbatim.\n"
        "- Keep source_ref, doc_id, and page aligned with the source text.\n"
        "- metadata may include edit notes or coverage notes.\n\n"
        "Draft evidence JSON:\n"
        f"{json.dumps(to_serializable(evidence_bundle), indent=2, sort_keys=True)}\n\n"
        "Source context:\n"
        f"{source_context}"
    )
    return system_prompt, user_prompt


def build_quiz_generation_prompts(
    task_spec: TaskSpec,
    evidence_bundle: QuizEvidenceBundle,
    *,
    target_question_count: int,
    qualitative_target: int,
    quantitative_target: int,
    question_slots: list[dict[str, str]],
) -> tuple[str, str]:
    slot_json = json.dumps(question_slots, indent=2, sort_keys=True)
    system_prompt = (
        "You are a professional exam setter. Return strict JSON only. Build a source-grounded "
        "multiple-choice quiz for a slides-only open-book task. Every "
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
        f"- Generate exactly {qualitative_target} qualitative questions.\n"
        f"- Generate exactly {quantitative_target} quantitative questions.\n"
        "- Follow the requested slot plan exactly; emit one question for each slot and reuse the provided question_id exactly.\n"
        "- Each question object must contain question_id, question_type, question, options, correct_answer, explanation, source_refs, and source_quotes.\n"
        "- question_type must be either qualitative or quantitative.\n"
        "- options must contain exactly 4 distinct strings.\n"
        "- correct_answer must equal one of the option texts.\n"
        "- explanation must mention at least one cited source_ref verbatim.\n"
        "- source_refs and source_quotes must come directly from the verified evidence.\n"
        "- Do not duplicate the same question stem or correct answer across slots unless the slot plan requires it.\n"
        "- Use only the verified evidence below.\n\n"
        "Question slot plan:\n"
        f"{slot_json}\n\n"
        "Verified evidence JSON:\n"
        f"{json.dumps(to_serializable(evidence_bundle), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


def build_quiz_regeneration_prompts(
    task_spec: TaskSpec,
    evidence_bundle: QuizEvidenceBundle,
    *,
    failed_slots: list[dict[str, object]],
    preserved_questions: list[dict[str, object]],
) -> tuple[str, str]:
    system_prompt = (
        "You are a professional exam setter repairing only invalid quiz "
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
        f"{json.dumps(to_serializable(evidence_bundle), indent=2, sort_keys=True)}"
    )
    return system_prompt, user_prompt


def build_quantitative_quiz_judging_prompts(
    task_spec: TaskSpec,
    presentation_extraction: ExtractedPresentation,
    questions: list[QuizQuestion],
    *,
    max_slide_chars: int = 1200,
) -> tuple[str, str]:
    sections: list[str] = []
    for slide in presentation_extraction.slides:
        content = slide_text_corpus(slide).strip()
        if len(content) > max_slide_chars:
            content = content[: max_slide_chars - 3].rstrip() + "..."
        sections.append(
            "\n".join(
                [
                    f"[SLIDE {slide.slide_index}]",
                    f"title: {slide.title_text or ''}",
                    "content:",
                    content,
                ]
            )
        )
    deck_context = "\n\n".join(sections)

    system_prompt = (
        "You are a strict quantitative quiz grader. Return strict JSON "
        "only. Answer each multiple-choice question using only the deck context. For each "
        "question, selected_answer must exactly match one provided option string."
    )
    user_prompt = (
        f"Task prompt:\n{task_spec.prompt}\n\n"
        "Return JSON with this exact top-level shape:\n"
        '{"answers": [{"question_id": "...", "selected_answer": "...", '
        '"reasoning": "..."}], "metadata": {...}}\n\n'
        "Requirements:\n"
        "- Answer every question exactly once.\n"
        "- selected_answer must exactly equal one provided option.\n"
        "- Use only the deck context below.\n"
        "- Do not leave any question unanswered.\n\n"
        "Quantitative questions JSON:\n"
        f"{json.dumps(to_serializable(questions), indent=2, sort_keys=True)}\n\n"
        "Deck context:\n"
        f"{deck_context}"
    )
    return system_prompt, user_prompt


__all__ = [
    "build_quiz_source_context",
    "build_quiz_extraction_prompts",
    "build_quiz_generation_prompts",
    "build_quantitative_quiz_judging_prompts",
    "build_quiz_regeneration_prompts",
    "build_quiz_refinement_prompts",
]
