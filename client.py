from __future__ import annotations

from typing import Any, Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from ppt_agent.models import PptAgentAction, PptAgentObservation


class PptAgentEnv(EnvClient[PptAgentAction, PptAgentObservation, State]):
    """Client for the prompt-to-PPT OpenEnv skeleton."""

    def _step_payload(self, action: PptAgentAction) -> Dict[str, Any]:
        return action.model_dump(mode="json")

    def _parse_result(self, payload: Dict[str, Any]) -> StepResult[PptAgentObservation]:
        obs_data = dict(payload.get("observation", {}))
        observation = PptAgentObservation.model_validate(
            {
                **obs_data,
                "done": payload.get("done", obs_data.get("done", False)),
                "reward": payload.get("reward", obs_data.get("reward")),
                "metadata": obs_data.get("metadata", {}),
            }
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward", observation.reward),
            done=payload.get("done", observation.done),
        )

    def _parse_state(self, payload: Dict[str, Any]) -> State:
        return State.model_validate(payload)
