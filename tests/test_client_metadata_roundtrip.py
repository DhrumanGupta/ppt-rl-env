from ppt_agent.client import PptAgentEnv


def test_client_preserves_observation_metadata() -> None:
    env = PptAgentEnv(base_url="http://localhost:7860")
    result = env._parse_result(
        {
            "reward": 0.04,
            "done": False,
            "observation": {
                "task_name": "demo",
                "difficulty": "easy",
                "slide_count": 1,
                "task_prompt": "prompt",
                "source_context": "context",
                "score": 0.0,
                "prompt_summary": "summary",
                "metadata": {
                    "reward_details": {
                        "kind": "intermediate_slide",
                        "result": {
                            "reward_breakdown": {
                                "C_slide_text_layout_hard": 0.05,
                            }
                        },
                    }
                },
            },
        }
    )

    assert result.observation.metadata["reward_details"]["kind"] == "intermediate_slide"
    assert (
        result.observation.metadata["reward_details"]["result"]["reward_breakdown"][
            "C_slide_text_layout_hard"
        ]
        == 0.05
    )


def test_client_preserves_last_action_result_reward_details() -> None:
    env = PptAgentEnv(base_url="http://localhost:7860")
    result = env._parse_result(
        {
            "reward": 0.04,
            "done": False,
            "observation": {
                "task_name": "demo",
                "difficulty": "easy",
                "slide_count": 1,
                "task_prompt": "prompt",
                "source_context": "context",
                "score": 0.0,
                "prompt_summary": "summary",
                "metadata": {},
                "last_action_result": {
                    "action_type": "create_slide",
                    "tool_result": {"slide_id": 1},
                    "reward_details": {
                        "kind": "intermediate_slide",
                        "result": {
                            "reward_breakdown": {
                                "C_slide_text_layout_hard": 0.05,
                            }
                        },
                    },
                },
            },
        }
    )

    assert (
        result.observation.last_action_result["reward_details"]["kind"]
        == "intermediate_slide"
    )
