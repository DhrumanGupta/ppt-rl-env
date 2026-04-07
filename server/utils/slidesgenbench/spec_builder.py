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
    "branch_split": {"content": 0.65, "aesthetics": 0.35},
    "quiz_split": {"qualitative": 0.5, "quantitative": 0.5},
    "aesthetic_weights": {
        "harmony": 0.20,
        "engagement": 0.20,
        "usability": 0.35,
        "rhythm": 0.25,
    },
    "harmony_config": {
        "saturation_threshold": 0.1,
        "downsample_max_side": 256,
        "rotation_steps": 72,
        "gaussian_sigma_degrees": 28.0,
        "deck_mean_weight": 1.0,
        "deck_std_penalty": 0.3,
    },
    "rhythm_config": {
        "downsample_max_side": 256,
        "entropy_bins": 32,
        "luminance_weight": 0.84,
        "chroma_weight": 0.08,
        "rmssd_target": 0.12,
        "rmssd_spread": 0.08,
        "overload_threshold": 0.82,
        "overload_penalty_weight": 0.15,
    },
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
