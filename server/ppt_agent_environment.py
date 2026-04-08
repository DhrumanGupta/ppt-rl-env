from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import random
from typing import Any
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from server.llm_client import LLMClient
from server.task_registry import DEFAULT_TASK_REGISTRY, TaskRegistry, TaskScenario
from server.tools.pptx_tools import (
    create_slide,
    delete_slide,
    register_theme,
    save_presentation,
    update_slide,
)
from server.utils.pptx_extraction import PptxExtractionService
from server.utils.pptx_functions import PptxEditor
from server.utils.rendering.pptx_render_service import PptxRenderService
from server.utils.reward_kernel import (
    build_eval_spec,
    evaluate_presentation,
    evaluate_slide,
)
from server.utils.reward_models import EvalSpec, ExtractedPresentation
from server.utils.slidesgenbench import (
    QuantitativeQuizJudgeService,
    QuizBankGenerationService,
    SlidesGenQuantitativeJudgeService,
    SlidesGenQuizBankService,
)

try:
    from ..models import PptAgentAction, PptAgentObservation
except ImportError:
    from models import PptAgentAction, PptAgentObservation


_DEFAULT_MAX_STEPS = 20
_INVALID_ACTION_PENALTY = 0.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ActionExecutionResult:
    action_type: str
    tool_result: dict[str, Any]
    affected_slide_index: int | None = None
    reward: float = 0.0


class PptAgentEnvironment(Environment):
    """Prompt-to-PPT environment backed by ``PptxEditor`` and reward kernel."""

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(
        self,
        max_steps: int = _DEFAULT_MAX_STEPS,
        *,
        task_registry: TaskRegistry | None = None,
        quiz_bank_service: QuizBankGenerationService | None = None,
        quantitative_quiz_judge_service: QuantitativeQuizJudgeService | None = None,
        render_service: Any | None = None,
    ):
        super().__init__()
        self._max_steps = max_steps
        self._rng = random.Random()
        self._inspection_service = PptxExtractionService()
        self._task_registry = task_registry or DEFAULT_TASK_REGISTRY
        self._scenario_queue: list[TaskScenario] = []
        self._eval_spec_cache: dict[str, EvalSpec] = {}

        llm_client: LLMClient | None = None
        if quiz_bank_service is None or quantitative_quiz_judge_service is None:
            llm_client = LLMClient()

        self._quiz_bank_service = quiz_bank_service or SlidesGenQuizBankService(
            llm_client
        )
        self._quantitative_quiz_judge_service = (
            quantitative_quiz_judge_service
            or SlidesGenQuantitativeJudgeService(llm_client)
        )
        self._render_service = render_service or PptxRenderService()

        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._done = False
        self._termination_reason: str | None = None
        self._scenario: TaskScenario | None = None
        self._eval_spec: EvalSpec | None = None
        self._editor: PptxEditor | None = None
        self._last_score = 0.0
        self._last_action_result: dict[str, Any] | None = None

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        **kwargs: Any,
    ) -> PptAgentObservation:
        requested_task_id = kwargs.get("task_id")
        requested_difficulty = kwargs.get("difficulty")
        logger.info("env.reset start episode_id=%s seed=%s", episode_id, seed)
        self._reset_rubric()
        if seed is not None:
            self._rng.seed(seed)
            self._scenario_queue = []

        self._done = False
        self._termination_reason = None
        self._last_score = 0.0
        self._last_action_result = None
        self._scenario = self._resolve_scenario(
            task_id=requested_task_id,
            difficulty=requested_difficulty,
        )
        logger.info("env.reset sampled task task_id=%s", self._scenario.task_id)
        self._eval_spec = self._build_eval_spec(self._scenario)
        self._editor = self._initialize_editor(self._scenario.theme)
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        logger.info(
            "env.reset ready episode_id=%s task_id=%s max_steps=%s",
            self._state.episode_id,
            self._scenario.task_id,
            self._max_steps,
        )

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
        if self._editor is None or self._scenario is None or self._eval_spec is None:
            raise RuntimeError("Environment must be reset before step()")
        if self._done:
            return self._build_observation(
                reward=0.0,
                done=True,
                last_action_error="Episode already terminated",
            )

        self._state.step_count += 1
        logger.info(
            "env.step start episode_id=%s step=%s action_type=%s slide_index=%s",
            self._state.episode_id,
            self._state.step_count,
            action.action_type,
            action.slide_index,
        )
        reward = 0.0
        invalid_reason: str | None = None
        inspection: ExtractedPresentation | None = None

        try:
            execution_result = self._execute_action(action)
            self._last_action_result = {
                "action_type": execution_result.action_type,
                "tool_result": execution_result.tool_result,
            }
            if execution_result.affected_slide_index is not None:
                inspection = self._inspection_service.inspect_presentation(self._editor)
                reward = self._score_intermediate_step(
                    slide_index=execution_result.affected_slide_index,
                    inspection=inspection,
                )
            else:
                reward = execution_result.reward
            logger.info(
                "env.step action complete episode_id=%s step=%s action_type=%s reward=%s tool_result=%s",
                self._state.episode_id,
                self._state.step_count,
                action.action_type,
                reward,
                execution_result.tool_result,
            )
        except (IndexError, KeyError, ValueError) as error:
            invalid_reason = str(error)
            reward = _INVALID_ACTION_PENALTY
            self._last_action_result = None
            logger.warning(
                "env.step invalid action episode_id=%s step=%s action_type=%s error=%s",
                self._state.episode_id,
                self._state.step_count,
                action.action_type,
                invalid_reason,
            )

        termination_reason = self._should_terminate()
        reward = max(0.0, min(1.0, float(reward)))

        if termination_reason is not None:
            reward = self._finalize_episode(termination_reason)

        logger.info(
            "env.step end episode_id=%s step=%s done=%s reward=%s score=%s error=%s",
            self._state.episode_id,
            self._state.step_count,
            self._done,
            reward,
            self._last_score,
            invalid_reason,
        )

        return self._build_observation(
            reward=reward,
            done=self._done,
            last_action_error=invalid_reason,
            inspection=inspection,
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
            task_name=self._current_task_name(),
            score=self._last_score,
        )

    def _sample_scenario(self) -> TaskScenario:
        if not self._scenario_queue:
            self._scenario_queue = list(self._task_registry.all())
            self._rng.shuffle(self._scenario_queue)
        return self._scenario_queue.pop(0)

    def _resolve_scenario(
        self,
        *,
        task_id: Any | None,
        difficulty: Any | None,
    ) -> TaskScenario:
        if task_id is not None:
            return self._task_registry.get(str(task_id))
        if difficulty is not None:
            return self._task_registry.sample(self._rng, difficulty=str(difficulty))
        return self._sample_scenario()

    def _build_eval_spec(self, scenario: TaskScenario) -> EvalSpec:
        cached_eval_spec = self._eval_spec_cache.get(scenario.task_id)
        if cached_eval_spec is not None:
            logger.info("env.eval_spec cache hit task_id=%s", scenario.task_id)
            return cached_eval_spec

        logger.info("env.eval_spec build start task_id=%s", scenario.task_id)
        eval_spec = build_eval_spec(
            scenario.prompt_text,
            scenario.source_pack,
            scenario.task_constraints,
            quiz_bank_service=self._quiz_bank_service,
        )
        self._eval_spec_cache[scenario.task_id] = eval_spec
        logger.info(
            "env.eval_spec build complete task_id=%s question_count=%s spec_hash=%s",
            scenario.task_id,
            len(eval_spec.slidesgenbench.quiz_bank),
            eval_spec.spec_hash,
        )
        return eval_spec

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
        inspection: ExtractedPresentation | None = None,
    ) -> PptAgentObservation:
        if self._editor is None:
            raise RuntimeError("Environment must be reset before building observations")
        inspection = inspection or self._inspection_service.inspect_presentation(
            self._editor
        )
        return PptAgentObservation(
            task_name=self._current_task_name(),
            difficulty=self._difficulty(),
            slide_count=inspection.slide_count,
            task_prompt=self._task_prompt(),
            source_context=self._source_context(),
            last_action_error=last_action_error,
            score=self._last_score,
            prompt_summary=self._prompt_summary(),
            last_action_result=self._last_action_result,
            termination_reason=self._termination_reason,
            done=done,
            reward=reward,
        )

    def _current_task_name(self) -> str:
        return self._scenario.task_id if self._scenario is not None else ""

    def _prompt_summary(self) -> str:
        if self._scenario is None:
            return ""
        prompt = self._scenario.prompt_text.strip()
        return prompt if len(prompt) <= 220 else f"{prompt[:217]}..."

    def _task_prompt(self) -> str:
        if self._scenario is None:
            return ""
        return self._scenario.prompt_text

    def _source_context(self) -> str:
        if self._scenario is None:
            return ""

        sections: list[str] = []
        if self._scenario.source_pack.brief:
            sections.append(f"[Source Pack Brief]\n{self._scenario.source_pack.brief}")

        for document in self._scenario.source_pack.documents:
            title = document.title.strip() if document.title else document.doc_id
            if document.pages:
                body = "\n\n".join(
                    f"Page {page_index}:\n{page_text.strip()}"
                    for page_index, page_text in enumerate(document.pages, start=1)
                    if page_text and page_text.strip()
                )
            else:
                body_parts = [document.text] if document.text else []
                body = "\n".join(
                    part.strip() for part in body_parts if part and part.strip()
                )
            if body:
                sections.append(f"[{title} | {document.doc_id}]\n{body}")
        return "\n\n".join(sections)

    def _difficulty(self) -> str:
        if self._scenario is None:
            return ""
        return self._scenario.difficulty

    def _execute_action(self, action: PptAgentAction) -> _ActionExecutionResult:
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

    def _handle_create_slide(self, action: PptAgentAction) -> _ActionExecutionResult:
        if self._editor is None:
            raise RuntimeError("Environment must be reset before create_slide")
        payload = dict(action.payload)
        tool_result = create_slide(
            self._editor,
            layout_index=int(payload.get("layout_index", 6)),
            background_color=payload.get("background_color", "<surface>"),
            shapes=payload.get("shapes") or [],
        )
        return _ActionExecutionResult(
            action_type=action.action_type,
            tool_result=tool_result,
            affected_slide_index=len(self._editor.prs.slides),
        )

    def _handle_update_slide(self, action: PptAgentAction) -> _ActionExecutionResult:
        if action.slide_index is None:
            raise ValueError("update_slide requires slide_index")
        slide_id = self._resolve_slide_id(action)
        payload = dict(action.payload)
        tool_result = update_slide(
            self._editor,
            slide_id,
            background_color=payload.get("background_color"),
            delete_shape_ids=payload.get("delete_shape_ids") or [],
            add_shapes=payload.get("add_shapes") or [],
            update_shapes=payload.get("update_shapes") or [],
        )
        return _ActionExecutionResult(
            action_type=action.action_type,
            tool_result=tool_result,
            affected_slide_index=action.slide_index,
        )

    def _handle_delete_slide(self, action: PptAgentAction) -> _ActionExecutionResult:
        if self._editor is None:
            raise RuntimeError("Environment must be reset before delete_slide")
        slide_id = self._resolve_slide_id(action)
        tool_result = delete_slide(self._editor, slide_id)
        return _ActionExecutionResult(
            action_type=action.action_type,
            tool_result=tool_result,
            affected_slide_index=None,
            reward=0.0,
        )

    def _handle_save_presentation(
        self, action: PptAgentAction
    ) -> _ActionExecutionResult:
        if self._editor is None:
            raise RuntimeError("Environment must be reset before save_presentation")
        payload = dict(action.payload)
        tool_result = save_presentation(
            self._editor,
            payload.get("path") or self._default_output_path(),
        )
        return _ActionExecutionResult(
            action_type=action.action_type,
            tool_result=tool_result,
            affected_slide_index=None,
            reward=0.0,
        )

    def _default_output_path(self) -> str:
        task_name = self._current_task_name() or "presentation"
        episode_id = self._state.episode_id or str(uuid4())
        return str(Path("outputs") / f"{task_name}_{episode_id}.pptx")

    def _score_intermediate_step(
        self,
        *,
        slide_index: int,
        inspection: ExtractedPresentation,
    ) -> float:
        if self._eval_spec is None:
            raise RuntimeError("Environment must be reset before scoring")

        slide_extraction = inspection.slides[slide_index - 1]
        previous_slide_extractions = inspection.slides[: slide_index - 1] or None
        result = evaluate_slide(
            self._eval_spec,
            slide_index,
            slide_extraction=slide_extraction,
            previous_slide_extractions=previous_slide_extractions,
        )
        return result.reward_total

    def _should_terminate(self) -> str | None:
        if (
            self._last_action_result is not None
            and self._last_action_result.get("action_type") == "save_presentation"
        ):
            return "presentation_saved"
        if self._state.step_count >= self._max_steps:
            return "step_budget_exhausted"
        return None

    def _finalize_episode(self, termination_reason: str) -> float:
        if self._eval_spec is None or self._editor is None:
            raise RuntimeError("Environment must be reset before finalization")

        self._done = True
        self._termination_reason = termination_reason
        logger.info(
            "env.finalize start episode_id=%s reason=%s",
            self._state.episode_id,
            termination_reason,
        )
        result = evaluate_presentation(
            self._eval_spec,
            self._editor,
            render_service=self._render_service,
            inspection_service=self._inspection_service,
            quantitative_quiz_judge_service=self._quantitative_quiz_judge_service,
        )
        self._last_score = result.reward_total
        logger.info(
            "env.finalize complete episode_id=%s reward=%s metadata=%s",
            self._state.episode_id,
            self._last_score,
            result.metadata,
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
