from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.utils.reward_models import SourceDocument, SourcePack, TaskConstraints


DEFAULT_THEME = {
    "bg": "#F8FAFC",
    "surface": "#FFFFFF",
    "accent": "#2563EB",
    "primary": "#0F172A",
    "secondary": "#475569",
    "font": "Aptos",
    "title_size": 28,
    "body_size": 16,
    "caption_size": 10,
}
PROMPT_TEXT = (
    "Create a factual three-slide presentation for a professional audience. "
    "Slide 1: Title slide introducing Northstar Growth Plan 2026. "
    "Slide 2: Results slide covering retention increased from 88% to 93% "
    "and onboarding time reduced by 35%, with a source citation. "
    "Slide 3: Revenue chart slide showing quarterly target values 18, 24, 28, and 32."
)
SOURCE_TEXT = (
    "Northstar Growth Plan 2026 focuses on retention and onboarding. "
    "Enterprise retention improved from 88% to 93%. "
    "Guided automation reduced onboarding time by 35%. "
    "Quarterly revenue targets are 18, 24, 28, and 32 million dollars."
)
TASK_CONSTRAINTS = TaskConstraints(min_slides=3, max_slides=3)
SOURCE_DOCUMENT = SourceDocument(
    doc_id="memo",
    title="Northstar plan memo",
    path=None,
    mime_type="text/plain",
    text=SOURCE_TEXT,
    pages=None,
    images=None,
    metadata={},
)


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    scenario_id: str
    prompt_text: str
    source_pack: SourcePack
    task_constraints: TaskConstraints
    theme: dict[str, Any]


def _build_scenario(difficulty: str, curriculum_stage: int) -> ScenarioSpec:
    scenario_id = f"northstar_growth_{difficulty}"
    return ScenarioSpec(
        scenario_id=scenario_id,
        prompt_text=PROMPT_TEXT,
        source_pack=SourcePack(
            task_id=scenario_id,
            documents=[SOURCE_DOCUMENT],
            metadata={
                "domain": "business",
                "difficulty": difficulty,
                "curriculum_stage": curriculum_stage,
            },
        ),
        task_constraints=TASK_CONSTRAINTS,
        theme=DEFAULT_THEME,
    )


DEFAULT_SCENARIOS = [
    _build_scenario("easy", 1),
    _build_scenario("medium", 2),
    _build_scenario("hard", 3),
]


__all__ = [
    "DEFAULT_THEME",
    "DEFAULT_SCENARIOS",
    "PROMPT_TEXT",
    "ScenarioSpec",
    "SOURCE_DOCUMENT",
    "SOURCE_TEXT",
    "TASK_CONSTRAINTS",
]
