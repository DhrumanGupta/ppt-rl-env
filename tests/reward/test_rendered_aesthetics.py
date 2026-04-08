from pathlib import Path

import numpy as np
from PIL import Image

from server.utils.pptx_functions import PptxEditor
from server.utils.reward_models import (
    ExtractedPresentation,
    ExtractedSlide,
    RenderedPresentation,
    RenderedSlideImage,
)
from server.utils.slidesgenbench.rendered_aesthetics import (
    compute_rendered_aesthetics_scores,
)


OUTPUT_ROOT = Path("outputs/rendered_aesthetics_tests")


def _save_rgb_image(path, pixels: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="RGB").save(path)
    return str(path)


def _persist_inspection_artifacts(
    deck_name: str,
    image_paths: list[str],
) -> list[str]:
    deck_root = OUTPUT_ROOT / deck_name
    deck_root.mkdir(parents=True, exist_ok=True)

    persisted_paths: list[str] = []
    for index, source_path in enumerate(image_paths, start=1):
        target_path = deck_root / f"slide_{index:02d}.png"
        with Image.open(source_path) as image:
            image.save(target_path)
        persisted_paths.append(str(target_path))

    editor = PptxEditor()
    for image_path in persisted_paths:
        slide_index = editor.add_slide()
        editor.add_image(slide_index, image_path, 0.0, 0.0, cx=10.0, cy=7.5)
    editor.prs.save(str(deck_root / f"{deck_name}.pptx"))
    return persisted_paths


def _solid_rgb(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = color
    return image


def _striped_rgb(
    width: int,
    height: int,
    colors: list[tuple[int, int, int]],
    *,
    stripe_width: int,
) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for start in range(0, width, stripe_width):
        color = colors[(start // stripe_width) % len(colors)]
        image[:, start : start + stripe_width] = color
    return image


def _checker_rgb(
    width: int,
    height: int,
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    *,
    block: int,
) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for row in range(0, height, block):
        for col in range(0, width, block):
            color = first if ((row // block) + (col // block)) % 2 == 0 else second
            image[row : row + block, col : col + block] = color
    return image


def _noise_rgb(width: int, height: int, *, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def _make_extraction(slide_count: int) -> ExtractedPresentation:
    slides = [
        ExtractedSlide(
            slide_index=index,
            slide_id=index,
            all_text="",
            metadata={"slide_width_in": 10.0, "slide_height_in": 7.5},
        )
        for index in range(1, slide_count + 1)
    ]
    return ExtractedPresentation(
        slide_count=slide_count,
        slide_ids=[slide.slide_id for slide in slides],
        slides=slides,
        metadata={"slide_width_in": 10.0, "slide_height_in": 7.5},
    )


def _make_rendered_presentation(image_paths: list[str]) -> RenderedPresentation:
    slide_images = [
        RenderedSlideImage(
            slide_index=index,
            image_path=path,
            width_px=400,
            height_px=300,
        )
        for index, path in enumerate(image_paths, start=1)
    ]
    return RenderedPresentation(
        slide_images=slide_images,
        backend="test-fixture",
    )


def test_harmony_prefers_coherent_hues_over_chaotic_palette(tmp_path):
    coherent_paths = [
        _save_rgb_image(
            tmp_path / "coherent_1.png", _solid_rgb(400, 300, (25, 88, 180))
        ),
        _save_rgb_image(
            tmp_path / "coherent_2.png", _solid_rgb(400, 300, (38, 110, 210))
        ),
    ]
    chaotic_paths = [
        _save_rgb_image(
            tmp_path / "chaotic_1.png",
            _striped_rgb(
                400,
                300,
                [
                    (230, 30, 30),
                    (30, 200, 70),
                    (35, 70, 230),
                    (235, 220, 30),
                    (220, 30, 220),
                    (30, 220, 220),
                ],
                stripe_width=24,
            ),
        ),
        _save_rgb_image(
            tmp_path / "chaotic_2.png",
            _striped_rgb(
                400,
                300,
                [
                    (245, 120, 20),
                    (40, 210, 180),
                    (120, 30, 220),
                    (240, 35, 120),
                    (35, 150, 35),
                    (20, 60, 210),
                ],
                stripe_width=18,
            ),
        ),
    ]
    coherent_paths = _persist_inspection_artifacts("harmony_coherent", coherent_paths)
    chaotic_paths = _persist_inspection_artifacts("harmony_chaotic", chaotic_paths)

    coherent_scores = compute_rendered_aesthetics_scores(
        _make_rendered_presentation(coherent_paths),
        _make_extraction(len(coherent_paths)),
    )
    chaotic_scores = compute_rendered_aesthetics_scores(
        _make_rendered_presentation(chaotic_paths),
        _make_extraction(len(chaotic_paths)),
    )

    assert coherent_scores["harmony"] > chaotic_scores["harmony"]
    assert coherent_scores["per_slide"][0]["template"] is not None
    assert chaotic_scores["per_slide"][0]["deviation_degrees"] > 0


def test_rhythm_prefers_moderate_pacing_over_flat_and_chaotic_sequences(tmp_path):
    flat_paths = [
        _save_rgb_image(
            tmp_path / f"flat_{index}.png", _solid_rgb(400, 300, (245, 245, 245))
        )
        for index in range(4)
    ]
    moderate_paths = [
        _save_rgb_image(
            tmp_path / "moderate_1.png", _solid_rgb(400, 300, (245, 245, 245))
        ),
        _save_rgb_image(
            tmp_path / "moderate_2.png",
            _striped_rgb(
                400, 300, [(245, 245, 245), (235, 235, 235)], stripe_width=100
            ),
        ),
        _save_rgb_image(
            tmp_path / "moderate_3.png",
            _striped_rgb(400, 300, [(245, 245, 245), (228, 228, 228)], stripe_width=88),
        ),
        _save_rgb_image(
            tmp_path / "moderate_4.png",
            _striped_rgb(400, 300, [(245, 245, 245), (220, 220, 220)], stripe_width=76),
        ),
    ]
    chaotic_paths = [
        _save_rgb_image(
            tmp_path / "chaotic_rhythm_1.png", _solid_rgb(400, 300, (245, 245, 245))
        ),
        _save_rgb_image(
            tmp_path / "chaotic_rhythm_2.png", _noise_rgb(400, 300, seed=7)
        ),
        _save_rgb_image(
            tmp_path / "chaotic_rhythm_3.png", _solid_rgb(400, 300, (245, 245, 245))
        ),
        _save_rgb_image(
            tmp_path / "chaotic_rhythm_4.png", _noise_rgb(400, 300, seed=11)
        ),
    ]
    flat_paths = _persist_inspection_artifacts("rhythm_flat", flat_paths)
    moderate_paths = _persist_inspection_artifacts("rhythm_moderate", moderate_paths)
    chaotic_paths = _persist_inspection_artifacts("rhythm_chaotic", chaotic_paths)

    flat_scores = compute_rendered_aesthetics_scores(
        _make_rendered_presentation(flat_paths),
        _make_extraction(len(flat_paths)),
    )
    moderate_scores = compute_rendered_aesthetics_scores(
        _make_rendered_presentation(moderate_paths),
        _make_extraction(len(moderate_paths)),
    )
    chaotic_scores = compute_rendered_aesthetics_scores(
        _make_rendered_presentation(chaotic_paths),
        _make_extraction(len(chaotic_paths)),
    )

    assert moderate_scores["rhythm"] > flat_scores["rhythm"]
    assert moderate_scores["rhythm"] > chaotic_scores["rhythm"]
    assert (
        flat_scores["deck_metrics"]["complexity_rmssd"]
        < chaotic_scores["deck_metrics"]["complexity_rmssd"]
    )
