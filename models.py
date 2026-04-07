from __future__ import annotations

from typing import Any, Literal

from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class PptAgentAction(Action):
    """Structured action for the prompt-to-PPT environment skeleton."""

    action_type: Literal["create_slide", "update_slide"] = Field(
        ..., description="Macro action to execute"
    )
    slide_index: int | None = Field(
        default=None,
        ge=1,
        description="Target slide index using 1-based indexing",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific arguments for the macro action",
    )


class PptAgentObservation(Observation):
    """Observation for the prompt-to-PPT environment skeleton."""

    task_name: str = Field(default="", description="Current task identifier")
    slide_count: int = Field(default=0, ge=0, description="Current number of slides")
    last_action_error: str | None = Field(
        default=None,
        description="Last action validation or execution error",
    )
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized score")
    prompt_summary: str = Field(default="", description="Current prompt summary")
