from __future__ import annotations

import numpy as np

from server.utils.presentbench.metrics import redundancy_score
from server.utils.reward_metrics import text_match_score
from server.utils.reward_models import ExtractedSlide


class FakeSentenceTransformer:
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        del convert_to_numpy, normalize_embeddings
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "retention" in lowered and (
                "improved" in lowered or "increased" in lowered
            ):
                vector = np.array([1.0, 0.0, 0.0])
            elif "onboarding" in lowered and (
                "reduced" in lowered or "faster" in lowered
            ):
                vector = np.array([0.0, 1.0, 0.0])
            else:
                vector = np.array([0.0, 0.0, 1.0])
            vectors.append(vector / np.linalg.norm(vector))
        return np.vstack(vectors)


def _slide(*, slide_index: int, text: str) -> ExtractedSlide:
    return ExtractedSlide(slide_index=slide_index, slide_id=slide_index, all_text=text)


def test_text_match_score_short_circuits_exact_match(monkeypatch):
    import server.utils.reward_metrics as reward_metrics

    def fail_if_called():
        raise AssertionError("semantic model should not load for exact matches")

    monkeypatch.setattr(reward_metrics, "_similarity_model", fail_if_called)

    assert (
        text_match_score(
            "Enterprise retention improved from 88% to 93%.",
            "retention improved from 88% to 93%",
        )
        == 1.0
    )


def test_text_match_score_uses_semantic_similarity(monkeypatch):
    import server.utils.reward_metrics as reward_metrics

    monkeypatch.setattr(
        reward_metrics,
        "_similarity_model",
        lambda: FakeSentenceTransformer(),
    )

    assert (
        text_match_score(
            "Customer retention increased meaningfully this quarter.",
            "Retention improved.",
        )
        > 0.8
    )
    assert (
        text_match_score(
            "Office relocation plans were discussed.",
            "Retention improved.",
        )
        < 0.2
    )


def test_redundancy_score_uses_semantic_similarity(monkeypatch):
    import server.utils.reward_metrics as reward_metrics

    monkeypatch.setattr(
        reward_metrics,
        "_similarity_model",
        lambda: FakeSentenceTransformer(),
    )

    score = redundancy_score(
        _slide(slide_index=2, text="Retention increased across enterprise accounts."),
        [
            _slide(
                slide_index=1,
                text="Enterprise retention improved significantly year over year.",
            )
        ],
    )

    assert score > 0.8
