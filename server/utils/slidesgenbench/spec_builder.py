from __future__ import annotations

import hashlib
import json

from server.utils.reward_models import (
    SlidesGenBenchEvalSpec,
    SourcePack,
    TaskSpec,
    to_serializable,
)
from server.utils.slidesgenbench.quizbank_service import QuizBankGenerationService

SPEC_VERSION = "1.0"

DEFAULT_SLIDESGENBENCH_SCORING_CONFIG = {
    "quiz_split": {"qualitative": 0.5, "quantitative": 0.5},
}


def build_slidesgenbench_eval_spec(
    task_spec: TaskSpec,
    source_pack: SourcePack,
    *,
    quiz_bank_service: QuizBankGenerationService,
    mode: str = "eval",
) -> SlidesGenBenchEvalSpec:
    quiz_bank, quiz_bank_metadata = quiz_bank_service.generate_quiz_bank(
        task_spec=task_spec,
        source_pack=source_pack,
        mode=mode,
    )
    task_spec.metadata["quiz_bank_generation"] = quiz_bank_metadata
    payload = {
        "task_spec": to_serializable(task_spec),
        "quiz_bank": to_serializable(quiz_bank),
        "scoring_config": DEFAULT_SLIDESGENBENCH_SCORING_CONFIG,
        "spec_version": SPEC_VERSION,
    }
    spec_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SlidesGenBenchEvalSpec(
        task_spec=task_spec,
        quiz_bank=quiz_bank,
        scoring_config={
            **DEFAULT_SLIDESGENBENCH_SCORING_CONFIG,
            "mode": mode,
        },
        spec_version=SPEC_VERSION,
        spec_hash=spec_hash,
    )


__all__ = [
    "DEFAULT_SLIDESGENBENCH_SCORING_CONFIG",
    "SPEC_VERSION",
    "build_slidesgenbench_eval_spec",
]
