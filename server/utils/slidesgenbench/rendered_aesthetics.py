from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image

from ..reward_metrics import clamp, compute_overlap_ratio
from ..reward_models import (
    ExtractedPresentation,
    ExtractedSlide,
    RenderedPresentation,
    RenderedSlideImage,
)


def _load_rgb(path: str) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


def _resize_rgb(rgb: np.ndarray, *, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return rgb
    height, width = rgb.shape[:2]
    longest_side = max(height, width)
    if longest_side <= max_side:
        return rgb
    scale = max_side / float(longest_side)
    resized = Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), mode="RGB")
    resized = resized.resize(
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        Image.Resampling.BILINEAR,
    )
    return np.asarray(resized, dtype=np.float32) / 255.0


def _rgb_to_luminance(rgb: np.ndarray) -> np.ndarray:
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    return 0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2]


def _colorfulness(rgb: np.ndarray) -> float:
    red = rgb[..., 0] * 255.0
    green = rgb[..., 1] * 255.0
    blue = rgb[..., 2] * 255.0
    rg = red - green
    yb = 0.5 * (red + green) - blue
    return float(
        np.sqrt(np.var(rg) + np.var(yb))
        + 0.3 * np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2)
    )


def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    delta = maxc - minc

    hue = np.zeros_like(maxc)
    nonzero = delta > 1e-8

    red_mask = nonzero & (maxc == red)
    green_mask = nonzero & (maxc == green)
    blue_mask = nonzero & (maxc == blue)

    hue[red_mask] = ((green[red_mask] - blue[red_mask]) / delta[red_mask]) % 6.0
    hue[green_mask] = ((blue[green_mask] - red[green_mask]) / delta[green_mask]) + 2.0
    hue[blue_mask] = ((red[blue_mask] - green[blue_mask]) / delta[blue_mask]) + 4.0
    hue /= 6.0

    saturation = np.zeros_like(maxc)
    value_mask = maxc > 1e-8
    saturation[value_mask] = delta[value_mask] / maxc[value_mask]
    value = maxc
    return np.stack([hue, saturation, value], axis=-1)


_HARMONY_TEMPLATES = {
    "i": [(0.00, 0.05)],
    "V": [(0.00, 0.26)],
    "L": [(0.00, 0.05), (0.25, 0.22)],
    "I": [(0.00, 0.05), (0.50, 0.05)],
    "T": [(0.25, 0.50)],
    "Y": [(0.00, 0.26), (0.50, 0.05)],
    "X": [(0.00, 0.26), (0.50, 0.26)],
}


def _circular_distance(first: np.ndarray, second: float) -> np.ndarray:
    diff = np.abs(first - second)
    return np.minimum(diff, 1.0 - diff)


def _template_distance(
    hue: np.ndarray,
    saturation: np.ndarray,
    template_name: str,
    rotation: float,
) -> float:
    sectors = _HARMONY_TEMPLATES[template_name]
    min_distance = np.full_like(hue, 0.5)
    for center, width in sectors:
        rotated_center = (center + rotation) % 1.0
        center_distance = _circular_distance(hue, rotated_center)
        sector_distance = np.maximum(center_distance - (width / 2.0), 0.0)
        min_distance = np.minimum(min_distance, sector_distance)
    weights = np.clip(saturation, 1e-8, None)
    return float(np.sum(min_distance * weights) / np.sum(weights))


def _slide_harmony_score(
    rgb: np.ndarray,
    *,
    saturation_threshold: float,
    rotation_steps: int,
    gaussian_sigma_degrees: float,
    downsample_max_side: int,
) -> tuple[float, dict[str, Any]]:
    sample_rgb = _resize_rgb(rgb, max_side=downsample_max_side)
    hsv = _rgb_to_hsv(sample_rgb)
    hue = hsv[..., 0].reshape(-1)
    saturation = hsv[..., 1].reshape(-1)
    mask = saturation >= saturation_threshold
    if not np.any(mask):
        return 0.6, {
            "template": None,
            "rotation": None,
            "deviation_degrees": None,
            "chromatic_pixel_ratio": 0.0,
        }

    hue = hue[mask]
    saturation = saturation[mask]
    best_template = None
    best_rotation = 0.0
    best_distance = float("inf")
    steps = max(rotation_steps, 1)
    for template_name in _HARMONY_TEMPLATES:
        for step in range(steps):
            rotation = step / steps
            distance = _template_distance(hue, saturation, template_name, rotation)
            if distance < best_distance:
                best_distance = distance
                best_template = template_name
                best_rotation = rotation
    sigma_fraction = max(gaussian_sigma_degrees / 360.0, 1e-6)
    score = math.exp(-((best_distance**2) / (2.0 * sigma_fraction * sigma_fraction)))
    return clamp(score), {
        "template": best_template,
        "rotation": best_rotation,
        "deviation_degrees": best_distance * 360.0,
        "chromatic_pixel_ratio": float(np.mean(mask.astype(np.float32))),
    }


def _normalized_colorfulness_score(value: float) -> float:
    return clamp(value / 90.0)


def _downsample_channel(channel: np.ndarray) -> np.ndarray:
    return 0.25 * (
        channel[0::2, 0::2]
        + channel[0::2, 1::2]
        + channel[1::2, 0::2]
        + channel[1::2, 1::2]
    )


def _subband_residuals(channel: np.ndarray) -> list[np.ndarray]:
    residuals: list[np.ndarray] = []
    current = channel.astype(np.float32)
    while min(current.shape) >= 8:
        even_height = (current.shape[0] // 2) * 2
        even_width = (current.shape[1] // 2) * 2
        if even_height < 8 or even_width < 8:
            break
        cropped = current[:even_height, :even_width]
        low = _downsample_channel(cropped)
        up = np.repeat(np.repeat(low, 2, axis=0), 2, axis=1)
        residuals.append(cropped - up)
        current = low
    if current.size:
        residuals.append(current - float(np.mean(current)))
    return residuals


def _normalized_entropy(values: np.ndarray, *, bins: int) -> float:
    flattened = values.reshape(-1)
    if flattened.size == 0:
        return 0.0
    min_value = float(np.min(flattened))
    max_value = float(np.max(flattened))
    if math.isclose(min_value, max_value):
        return 0.0
    histogram, _ = np.histogram(
        flattened,
        bins=bins,
        range=(min_value, max_value),
        density=False,
    )
    probabilities = histogram.astype(np.float64)
    probabilities /= max(probabilities.sum(), 1.0)
    probabilities = probabilities[probabilities > 0]
    if probabilities.size == 0:
        return 0.0
    entropy = -float(np.sum(probabilities * np.log2(probabilities)))
    return clamp(entropy / math.log2(bins))


def _lab_like_channels(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    luminance = _rgb_to_luminance(rgb)
    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    chroma_a = red - green
    chroma_b = 0.5 * (red + green) - blue
    return luminance, chroma_a, chroma_b


def _subband_entropy_score(
    rgb: np.ndarray,
    *,
    downsample_max_side: int,
    bins: int,
    luminance_weight: float,
    chroma_weight: float,
) -> tuple[float, dict[str, Any]]:
    sample_rgb = _resize_rgb(rgb, max_side=downsample_max_side)
    luminance, chroma_a, chroma_b = _lab_like_channels(sample_rgb)

    def channel_entropy(channel: np.ndarray) -> float:
        residuals = _subband_residuals(channel)
        if not residuals:
            return 0.0
        return float(
            np.mean(
                [_normalized_entropy(residual, bins=bins) for residual in residuals]
            )
        )

    entropy_l = channel_entropy(luminance)
    entropy_a = channel_entropy(chroma_a)
    entropy_b = channel_entropy(chroma_b)
    composite = (
        luminance_weight * entropy_l
        + chroma_weight * entropy_a
        + chroma_weight * entropy_b
    ) / max(luminance_weight + 2.0 * chroma_weight, 1e-8)
    return clamp(composite), {
        "entropy_l": entropy_l,
        "entropy_a": entropy_a,
        "entropy_b": entropy_b,
        "subband_entropy": composite,
    }


def _sequence_rmssd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    diffs = np.diff(np.asarray(values, dtype=np.float32))
    return float(np.sqrt(np.mean(np.square(diffs))))


def _paced_variation_score(rmssd: float, *, target: float, spread: float) -> float:
    if spread <= 0:
        return 0.0
    return clamp(math.exp(-((rmssd - target) ** 2) / (2.0 * spread * spread)))


def _shape_to_pixels(
    shape: Any,
    *,
    slide_width_in: float,
    slide_height_in: float,
    width_px: int,
    height_px: int,
) -> tuple[int, int, int, int] | None:
    if slide_width_in <= 0 or slide_height_in <= 0 or width_px <= 0 or height_px <= 0:
        return None
    left = int(round((shape.x / slide_width_in) * width_px))
    top = int(round((shape.y / slide_height_in) * height_px))
    right = int(round(((shape.x + shape.w) / slide_width_in) * width_px))
    bottom = int(round(((shape.y + shape.h) / slide_height_in) * height_px))
    left = max(0, min(width_px, left))
    right = max(0, min(width_px, right))
    top = max(0, min(height_px, top))
    bottom = max(0, min(height_px, bottom))
    if right - left < 4 or bottom - top < 4:
        return None
    return left, top, right, bottom


def _region_contrast_score(rgb: np.ndarray) -> float:
    luminance = _rgb_to_luminance(rgb).reshape(-1)
    if luminance.size == 0:
        return 0.0
    low = float(np.quantile(luminance, 0.1))
    high = float(np.quantile(luminance, 0.9))
    if math.isclose(low, high):
        return 0.0
    contrast_ratio = (max(low, high) + 0.05) / (min(low, high) + 0.05)
    return clamp(math.log(contrast_ratio) / math.log(21.0))


def _font_size_score(font_size_pt: float | None) -> float:
    if font_size_pt is None:
        return 0.75
    if font_size_pt <= 8:
        return 0.0
    return clamp((font_size_pt - 8.0) / 10.0)


def _slide_usability(
    rgb: np.ndarray, slide: Any, *, slide_width_in: float, slide_height_in: float
) -> tuple[float, dict[str, Any]]:
    height_px, width_px = rgb.shape[:2]
    region_scores: list[float] = []
    region_count = 0
    for shape in slide.shapes:
        if shape.shape_kind not in {"text", "citation"}:
            continue
        bounds = _shape_to_pixels(
            shape,
            slide_width_in=slide_width_in,
            slide_height_in=slide_height_in,
            width_px=width_px,
            height_px=height_px,
        )
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        region_scores.append(_region_contrast_score(rgb[top:bottom, left:right]))
        region_count += 1
    contrast_score = (
        float(np.mean(region_scores)) if region_scores else _region_contrast_score(rgb)
    )
    font_score = _font_size_score(slide.text_metrics.get("min_font_size_pt"))
    overlap_score = 1.0 - min(compute_overlap_ratio(slide) / 0.1, 1.0)
    score = clamp(0.45 * contrast_score + 0.30 * font_score + 0.25 * overlap_score)
    return score, {
        "contrast_score": contrast_score,
        "font_score": font_score,
        "overlap_score": overlap_score,
        "text_region_count": region_count,
    }


def compute_rendered_aesthetics_scores(
    rendered_presentation: RenderedPresentation | None,
    extraction: ExtractedPresentation,
    *,
    metric_weights: dict[str, float] | None = None,
    harmony_config: dict[str, Any] | None = None,
    rhythm_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weights = metric_weights or {
        "harmony": 0.20,
        "engagement": 0.20,
        "usability": 0.35,
        "rhythm": 0.25,
    }
    harmony_config = harmony_config or {
        "saturation_threshold": 0.1,
        "downsample_max_side": 256,
        "rotation_steps": 72,
        "gaussian_sigma_degrees": 28.0,
        "deck_mean_weight": 1.0,
        "deck_std_penalty": 0.3,
    }
    rhythm_config = rhythm_config or {
        "downsample_max_side": 256,
        "entropy_bins": 32,
        "luminance_weight": 0.84,
        "chroma_weight": 0.08,
        "rmssd_target": 0.12,
        "rmssd_spread": 0.08,
        "overload_threshold": 0.82,
        "overload_penalty_weight": 0.15,
    }
    if rendered_presentation is None or not rendered_presentation.slide_images:
        return {
            "harmony": 0.0,
            "engagement": 0.0,
            "usability": 0.0,
            "rhythm": 0.0,
            "aesthetic": 0.0,
            "available": False,
            "reason": "rendered images unavailable",
        }
    if len(rendered_presentation.slide_images) != extraction.slide_count:
        return {
            "harmony": 0.0,
            "engagement": 0.0,
            "usability": 0.0,
            "rhythm": 0.0,
            "aesthetic": 0.0,
            "available": False,
            "reason": "rendered slide count mismatch",
            "rendered_slide_count": len(rendered_presentation.slide_images),
            "extracted_slide_count": extraction.slide_count,
        }

    slide_width_in = float(extraction.metadata.get("slide_width_in") or 0.0)
    slide_height_in = float(extraction.metadata.get("slide_height_in") or 0.0)
    per_slide: list[dict[str, Any]] = []
    harmony_values: list[float] = []
    colorfulness_values: list[float] = []
    entropy_values: list[float] = []
    usability_values: list[float] = []

    for rendered_slide, extracted_slide in zip(
        rendered_presentation.slide_images,
        extraction.slides,
        strict=True,
    ):
        rgb = _load_rgb(rendered_slide.image_path)
        harmony, harmony_details = _slide_harmony_score(
            rgb,
            saturation_threshold=float(harmony_config.get("saturation_threshold", 0.1)),
            rotation_steps=int(harmony_config.get("rotation_steps", 72)),
            gaussian_sigma_degrees=float(
                harmony_config.get("gaussian_sigma_degrees", 28.0)
            ),
            downsample_max_side=int(harmony_config.get("downsample_max_side", 256)),
        )
        colorfulness = _colorfulness(rgb)
        entropy_score, entropy_details = _subband_entropy_score(
            rgb,
            downsample_max_side=int(rhythm_config.get("downsample_max_side", 256)),
            bins=int(rhythm_config.get("entropy_bins", 32)),
            luminance_weight=float(rhythm_config.get("luminance_weight", 0.84)),
            chroma_weight=float(rhythm_config.get("chroma_weight", 0.08)),
        )
        usability, usability_details = _slide_usability(
            rgb,
            extracted_slide,
            slide_width_in=slide_width_in,
            slide_height_in=slide_height_in,
        )

        harmony_values.append(harmony)
        colorfulness_values.append(colorfulness)
        entropy_values.append(entropy_score)
        usability_values.append(usability)
        per_slide.append(
            {
                "slide_index": rendered_slide.slide_index,
                "image_path": rendered_slide.image_path,
                "harmony": harmony,
                "colorfulness": colorfulness,
                "subband_entropy": entropy_score,
                "usability": usability,
                **harmony_details,
                **entropy_details,
                **usability_details,
            }
        )

    harmony_mean = float(np.mean(harmony_values)) if harmony_values else 0.0
    harmony_std = float(np.std(harmony_values)) if len(harmony_values) > 1 else 0.0
    harmony = clamp(
        float(harmony_config.get("deck_mean_weight", 1.0)) * harmony_mean
        - float(harmony_config.get("deck_std_penalty", 0.3)) * harmony_std
    )

    mean_colorfulness_score = float(
        np.mean(
            [_normalized_colorfulness_score(value) for value in colorfulness_values]
        )
    )
    colorfulness_rmssd = _sequence_rmssd(colorfulness_values)
    engagement_pacing = _paced_variation_score(
        colorfulness_rmssd,
        target=14.0,
        spread=10.0,
    )
    engagement = clamp(0.75 * mean_colorfulness_score + 0.25 * engagement_pacing)

    usability = clamp(float(np.mean(usability_values)))

    complexity_rmssd = _sequence_rmssd(entropy_values)
    rhythm_variation = _paced_variation_score(
        complexity_rmssd,
        target=float(rhythm_config.get("rmssd_target", 0.12)),
        spread=float(rhythm_config.get("rmssd_spread", 0.08)),
    )
    overload_threshold = float(rhythm_config.get("overload_threshold", 0.82))
    overload_events = sum(1 for value in entropy_values if value > overload_threshold)
    overload_penalty = min(overload_events / max(len(entropy_values), 1), 1.0)
    overload_weight = float(rhythm_config.get("overload_penalty_weight", 0.15))
    rhythm = clamp(
        (1.0 - overload_weight) * rhythm_variation
        + overload_weight * (1.0 - overload_penalty)
    )

    aesthetic = clamp(
        weights.get("harmony", 0.20) * harmony
        + weights.get("engagement", 0.20) * engagement
        + weights.get("usability", 0.35) * usability
        + weights.get("rhythm", 0.25) * rhythm
    )
    return {
        "harmony": harmony,
        "engagement": engagement,
        "usability": usability,
        "rhythm": rhythm,
        "aesthetic": aesthetic,
        "available": True,
        "backend": rendered_presentation.backend,
        "slide_count": len(per_slide),
        "per_slide": per_slide,
        "deck_metrics": {
            "harmony_mean": harmony_mean,
            "harmony_std": harmony_std,
            "mean_colorfulness": float(np.mean(colorfulness_values)),
            "colorfulness_rmssd": colorfulness_rmssd,
            "complexity_rmssd": complexity_rmssd,
            "overload_events": overload_events,
        },
    }


def compute_intermediate_rendered_aesthetics_score(
    *,
    current_slide: ExtractedSlide,
    current_rendered_slide: RenderedSlideImage,
    previous_slide: ExtractedSlide | None,
    previous_rendered_slide: RenderedSlideImage | None,
    slide_width_in: float,
    slide_height_in: float,
    metric_weights: dict[str, float] | None = None,
    harmony_config: dict[str, Any] | None = None,
    rhythm_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weights = metric_weights or {
        "harmony": 0.20,
        "engagement": 0.20,
        "usability": 0.35,
        "rhythm": 0.25,
    }
    harmony_config = harmony_config or {
        "saturation_threshold": 0.1,
        "downsample_max_side": 256,
        "rotation_steps": 72,
        "gaussian_sigma_degrees": 28.0,
    }
    rhythm_config = rhythm_config or {
        "downsample_max_side": 256,
        "entropy_bins": 32,
        "luminance_weight": 0.84,
        "chroma_weight": 0.08,
        "rmssd_target": 0.12,
        "rmssd_spread": 0.08,
        "overload_threshold": 0.82,
        "overload_penalty_weight": 0.15,
    }

    current_rgb = _load_rgb(current_rendered_slide.image_path)
    current_harmony, harmony_details = _slide_harmony_score(
        current_rgb,
        saturation_threshold=float(harmony_config.get("saturation_threshold", 0.1)),
        rotation_steps=int(harmony_config.get("rotation_steps", 72)),
        gaussian_sigma_degrees=float(
            harmony_config.get("gaussian_sigma_degrees", 28.0)
        ),
        downsample_max_side=int(harmony_config.get("downsample_max_side", 256)),
    )
    current_engagement = _normalized_colorfulness_score(_colorfulness(current_rgb))
    current_usability, usability_details = _slide_usability(
        current_rgb,
        current_slide,
        slide_width_in=slide_width_in,
        slide_height_in=slide_height_in,
    )
    current_entropy, entropy_details = _subband_entropy_score(
        current_rgb,
        downsample_max_side=int(rhythm_config.get("downsample_max_side", 256)),
        bins=int(rhythm_config.get("entropy_bins", 32)),
        luminance_weight=float(rhythm_config.get("luminance_weight", 0.84)),
        chroma_weight=float(rhythm_config.get("chroma_weight", 0.08)),
    )

    sequence_scores = [current_entropy]
    previous_entropy = None
    if previous_rendered_slide is not None and previous_slide is not None:
        previous_rgb = _load_rgb(previous_rendered_slide.image_path)
        previous_entropy, _previous_entropy_details = _subband_entropy_score(
            previous_rgb,
            downsample_max_side=int(rhythm_config.get("downsample_max_side", 256)),
            bins=int(rhythm_config.get("entropy_bins", 32)),
            luminance_weight=float(rhythm_config.get("luminance_weight", 0.84)),
            chroma_weight=float(rhythm_config.get("chroma_weight", 0.08)),
        )
        sequence_scores.insert(0, previous_entropy)
    complexity_rmssd = _sequence_rmssd(sequence_scores)
    if len(sequence_scores) == 1:
        current_rhythm = 0.5
    else:
        overload_threshold = float(rhythm_config.get("overload_threshold", 0.82))
        overload_penalty = min(
            sum(1 for value in sequence_scores if value > overload_threshold)
            / len(sequence_scores),
            1.0,
        )
        overload_weight = float(rhythm_config.get("overload_penalty_weight", 0.15))
        rhythm_variation = _paced_variation_score(
            complexity_rmssd,
            target=float(rhythm_config.get("rmssd_target", 0.12)),
            spread=float(rhythm_config.get("rmssd_spread", 0.08)),
        )
        current_rhythm = clamp(
            (1.0 - overload_weight) * rhythm_variation
            + overload_weight * (1.0 - overload_penalty)
        )

    aesthetic = clamp(
        weights.get("harmony", 0.20) * current_harmony
        + weights.get("engagement", 0.20) * current_engagement
        + weights.get("usability", 0.35) * current_usability
        + weights.get("rhythm", 0.25) * current_rhythm
    )
    return {
        "aesthetic": aesthetic,
        "harmony": current_harmony,
        "engagement": current_engagement,
        "usability": current_usability,
        "rhythm": current_rhythm,
        "available": True,
        "backend": "rendered-slide-local",
        "slide_index": current_slide.slide_index,
        "current_entropy": current_entropy,
        "previous_entropy": previous_entropy,
        "complexity_rmssd": complexity_rmssd,
        **harmony_details,
        **entropy_details,
        **usability_details,
    }


__all__ = [
    "compute_intermediate_rendered_aesthetics_score",
    "compute_rendered_aesthetics_scores",
]
