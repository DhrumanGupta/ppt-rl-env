from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

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

_DATA_PATH = Path(__file__).with_name("data.json")


@dataclass(frozen=True, slots=True)
class TaskScenario:
    task_id: str
    prompt_text: str
    source_pack: SourcePack
    task_constraints: TaskConstraints
    theme: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def difficulty(self) -> str:
        return str(self.metadata.get("difficulty", ""))


class TaskRegistry:
    def __init__(self, scenarios: Iterable[TaskScenario]):
        ordered_scenarios = tuple(scenarios)
        if not ordered_scenarios:
            raise ValueError("TaskRegistry requires at least one scenario")

        scenarios_by_id = {scenario.task_id: scenario for scenario in ordered_scenarios}
        if len(scenarios_by_id) != len(ordered_scenarios):
            raise ValueError("TaskRegistry task ids must be unique")

        self._ordered_scenarios = ordered_scenarios
        self._scenarios_by_id = scenarios_by_id

    def __len__(self) -> int:
        return len(self._ordered_scenarios)

    def all(self) -> tuple[TaskScenario, ...]:
        return self._ordered_scenarios

    def get(self, task_id: str) -> TaskScenario:
        try:
            return self._scenarios_by_id[task_id]
        except KeyError as error:
            raise KeyError(f"Unknown task id '{task_id}'") from error

    def by_difficulty(self, difficulty: str) -> tuple[TaskScenario, ...]:
        normalized = difficulty.strip().lower()
        matches = tuple(
            scenario
            for scenario in self._ordered_scenarios
            if scenario.difficulty.lower() == normalized
        )
        if not matches:
            raise KeyError(f"Unknown difficulty '{difficulty}'")
        return matches

    def sample(
        self,
        rng: random.Random,
        *,
        difficulty: str | None = None,
    ) -> TaskScenario:
        candidates = (
            self.by_difficulty(difficulty)
            if difficulty is not None
            else self._ordered_scenarios
        )
        return rng.choice(candidates)


def _load_raw_scenarios() -> list[dict[str, Any]]:
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("server/data.json must contain a non-empty 'scenarios' list")
    return scenarios


def _build_source_document(payload: dict[str, Any]) -> SourceDocument:
    return SourceDocument(
        doc_id=str(payload["doc_id"]),
        title=str(payload["title"]),
        path=payload.get("path"),
        mime_type=str(payload.get("mime_type", "text/plain")),
        text=payload.get("text"),
        pages=payload.get("pages"),
        images=payload.get("images"),
        metadata=payload.get("metadata")
        if isinstance(payload.get("metadata"), dict)
        else {},
    )


def _build_task_constraints(payload: dict[str, Any]) -> TaskConstraints:
    return TaskConstraints(
        min_slides=payload.get("min_slides"),
        max_slides=payload.get("max_slides"),
        target_audience=payload.get("target_audience"),
        tone=payload.get("tone"),
        extra_constraints=payload.get("extra_constraints")
        if isinstance(payload.get("extra_constraints"), dict)
        else {},
    )


def _build_scenario(payload: dict[str, Any]) -> TaskScenario:
    task_id = str(payload["task_id"])
    difficulty = str(payload["difficulty"]).lower()
    source_documents = payload.get("source_documents")
    if not isinstance(source_documents, list) or not source_documents:
        raise ValueError(f"Scenario '{task_id}' must define source_documents")

    source_pack = SourcePack(
        task_id=task_id,
        documents=[_build_source_document(item) for item in source_documents],
        metadata={
            **(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
            "difficulty": difficulty,
        },
    )

    return TaskScenario(
        task_id=task_id,
        prompt_text=str(payload["prompt_text"]),
        source_pack=source_pack,
        task_constraints=_build_task_constraints(payload.get("task_constraints") or {}),
        theme={**DEFAULT_THEME, **dict(payload.get("theme") or {})},
        metadata={
            **(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
            "difficulty": difficulty,
        },
    )


def _load_default_task_registry() -> TaskRegistry:
    return TaskRegistry(_build_scenario(item) for item in _load_raw_scenarios())


DEFAULT_TASK_REGISTRY = _load_default_task_registry()


__all__ = [
    "DEFAULT_TASK_REGISTRY",
    "DEFAULT_THEME",
    "TaskRegistry",
    "TaskScenario",
]
