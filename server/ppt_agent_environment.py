from __future__ import annotations

import random
from typing import Any
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from server.grader import grade_dummy_presentation
from server.task_registry import DEFAULT_SCENARIOS, ScenarioSpec
from server.tools.pptx_tools import create_slide, register_theme, update_slide
from server.utils.pptx_extraction import PptxExtractionService
from server.utils.pptx_functions import PptxEditor
from server.utils.reward_models import TaskSpec
from server.utils.reward_prompts import build_task_spec

try:
    from ..models import PptAgentAction, PptAgentObservation
except ImportError:
    from models import PptAgentAction, PptAgentObservation


_DEFAULT_MAX_STEPS = 20
_INVALID_ACTION_PENALTY = 0.0
_ACTION_REWARDS = {
    "create_slide": 0.05,
    "update_slide": 0.03,
}


class PptAgentEnvironment(Environment):
    """Prompt-to-PPT OpenEnv skeleton backed by ``PptxEditor``."""

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self, max_steps: int = _DEFAULT_MAX_STEPS):
        super().__init__()
        self._max_steps = max_steps
        self._rng = random.Random()
        self._inspection_service = PptxExtractionService()
        self._scenarios = list(DEFAULT_SCENARIOS)
        self._scenario_queue: list[ScenarioSpec] = []
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._done = False
        self._termination_reason: str | None = None
        self._scenario: ScenarioSpec | None = None
        self._task_spec: TaskSpec | None = None
        self._editor: PptxEditor | None = None
        self._action_count = 0
        self._last_score = 0.0

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        **kwargs: Any,
    ) -> PptAgentObservation:
        del kwargs
        self._reset_rubric()
        if seed is not None:
            self._rng.seed(seed)
            self._scenario_queue = []

        self._done = False
        self._termination_reason = None
        self._action_count = 0
        self._last_score = 0.0
        self._scenario = self._sample_scenario()
        self._task_spec = build_task_spec(
            self._scenario.prompt_text,
            self._scenario.source_pack,
            self._scenario.task_constraints,
        )
        self._editor = self._initialize_editor(self._scenario.theme)
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)

        return self._build_observation(
            reward=0.0,
            done=False,
            last_action_error=None,
        )

    def step(
        self,
        action: PptAgentAction,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> PptAgentObservation:
        del timeout_s, kwargs
        if self._editor is None or self._scenario is None or self._task_spec is None:
            raise RuntimeError("Environment must be reset before step()")
        if self._done:
            return self._build_observation(
                reward=0.0,
                done=True,
                last_action_error="Episode already terminated",
            )

        self._state.step_count += 1
        reward = 0.0
        invalid_reason: str | None = None

        try:
            self._action_count += 1
            reward = self._execute_action(action)
        except (IndexError, KeyError, ValueError) as error:
            invalid_reason = str(error)
            reward = _INVALID_ACTION_PENALTY

        termination_reason = self._should_terminate()
        reward = max(0.0, min(1.0, float(reward)))

        if termination_reason is not None:
            reward = self._finalize_episode(termination_reason)

        return self._build_observation(
            reward=reward,
            done=self._done,
            last_action_error=invalid_reason,
        )

    @property
    def state(self) -> State:
        slide_count = len(self._editor.prs.slides) if self._editor is not None else 0
        return State(
            episode_id=self._state.episode_id,
            step_count=self._state.step_count,
            done=self._done,
            slide_count=slide_count,
            max_steps=self._max_steps,
            task_name=self._scenario.scenario_id
            if self._scenario is not None
            else None,
            score=self._last_score,
        )

    def _sample_scenario(self) -> ScenarioSpec:
        if not self._scenario_queue:
            self._scenario_queue = list(self._scenarios)
            self._rng.shuffle(self._scenario_queue)
        return self._scenario_queue.pop(0)

    def _initialize_editor(self, theme: dict[str, Any]) -> PptxEditor:
        editor = PptxEditor()
        register_theme(editor, theme)
        return editor

    def _build_observation(
        self,
        *,
        reward: float,
        done: bool,
        last_action_error: str | None,
    ) -> PptAgentObservation:
        inspection = self._inspection_service.inspect_presentation(self._editor)
        return PptAgentObservation(
            task_name=self._scenario.scenario_id if self._scenario is not None else "",
            slide_count=inspection.slide_count,
            last_action_error=last_action_error,
            score=self._last_score,
            prompt_summary=self._prompt_summary(),
            done=done,
            reward=reward,
        )

    def _prompt_summary(self) -> str:
        if self._scenario is None:
            return ""
        prompt = self._scenario.prompt_text.strip()
        return prompt if len(prompt) <= 220 else f"{prompt[:217]}..."

    def _execute_action(self, action: PptAgentAction) -> float:
        handler = getattr(self, f"_handle_{action.action_type.lower()}", None)
        if handler is None:
            raise ValueError(f"Unsupported action type '{action.action_type}'")
        return handler(action)

    def _resolve_slide_id(self, action: PptAgentAction) -> int:
        if self._editor is None:
            raise RuntimeError("Environment must be reset before resolving slide ids")
        if action.slide_index is None:
            raise ValueError(f"{action.action_type} requires slide_index")
        return self._editor.get_slide_id(action.slide_index - 1)

    def _handle_create_slide(self, action: PptAgentAction) -> float:
        payload = dict(action.payload)
        create_slide(
            self._editor,
            layout_index=int(payload.get("layout_index", 6)),
            background_color=payload.get("background_color", "<surface>"),
            shapes=payload.get("shapes") or [],
        )
        return _ACTION_REWARDS[action.action_type]

    def _handle_update_slide(self, action: PptAgentAction) -> float:
        slide_id = self._resolve_slide_id(action)
        payload = dict(action.payload)
        update_slide(
            self._editor,
            slide_id,
            background_color=payload.get("background_color"),
            delete_shape_ids=payload.get("delete_shape_ids") or [],
            add_shapes=payload.get("add_shapes") or [],
            update_shapes=payload.get("update_shapes") or [],
        )
        return _ACTION_REWARDS[action.action_type]

    def _should_terminate(self) -> str | None:
        if self._state.step_count >= self._max_steps:
            return "step_budget_exhausted"
        return None

    def _finalize_episode(self, termination_reason: str) -> float:
        self._done = True
        self._termination_reason = termination_reason
        inspection = self._inspection_service.inspect_presentation(self._editor)
        self._last_score = grade_dummy_presentation(
            inspection=inspection,
            task_spec=self._task_spec,
            action_count=self._action_count,
        )
        return self._last_score


if __name__ == "__main__":  # pragma: no cover
    env = PptAgentEnvironment()
    observation = env.reset(seed=7)
    print("Reset prompt:", observation.prompt_summary)
    observation = env.step(PptAgentAction(action_type="create_slide"))
    print("Slides after create_slide:", observation.slide_count)
    observation = env.step(
        PptAgentAction(
            action_type="update_slide",
            slide_index=1,
            payload={
                "add_shapes": [
                    {
                        "type": "text",
                        "text": "Hello from the PPT skeleton",
                        "x": 0.8,
                        "y": 1.2,
                        "w": 8.4,
                        "h": 1.0,
                        "style": {
                            "font_name": "<font>",
                            "font_size_pt": "<body_size>",
                            "color_hex": "<primary>",
                        },
                    }
                ]
            },
        )
    )
    while not observation.done:
        observation = env.step(PptAgentAction(action_type="create_slide"))
    print("Terminal reward:", observation.reward)
