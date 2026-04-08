"""Unified OpenAI-client wrapper for environment-side judge LLM calls."""

import json
import logging
import os
import re

from openai import OpenAI

from server.debug_logging import write_debug_event

logger = logging.getLogger(__name__)


def _exception_payload(error: Exception) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": str(error),
        "error_type": error.__class__.__name__,
        "error_repr": repr(error),
    }
    if getattr(error, "args", None):
        payload["error_args"] = [str(arg) for arg in error.args]
    cause = error.__cause__
    if cause is not None:
        payload["cause_type"] = cause.__class__.__name__
        payload["cause"] = str(cause)
        payload["cause_repr"] = repr(cause)
    context = error.__context__
    if context is not None and context is not cause:
        payload["context_type"] = context.__class__.__name__
        payload["context"] = str(context)
        payload["context_repr"] = repr(context)
    return payload


class LLMClient:
    """Thin wrapper around the OpenAI client using judge env vars."""

    def __init__(self):
        self.model = os.environ.get(
            "JUDGE_MODEL_NAME",
            "moonshotai/kimi-k2-instruct-0905",
        )
        self.base_url = os.environ.get(
            "JUDGE_API_BASE_URL",
            "https://router.huggingface.co/v1",
        )
        api_key = os.environ.get("JUDGE_API_KEY")
        if not api_key:
            raise ValueError("JUDGE_API_KEY must be set")

        self.client = OpenAI(base_url=self.base_url, api_key=api_key)
        logger.info(
            "Judge LLM client configured model=%s base_url=%s",
            self.model,
            self.base_url,
        )

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        *,
        debug_stage: str | None = None,
    ) -> str:
        """Send a chat completion request. Returns the raw response text."""
        return self._chat_openai(
            system,
            user,
            temperature,
            max_tokens,
            debug_stage=debug_stage,
        )

    def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        *,
        debug_stage: str | None = None,
    ) -> dict:
        """Send a chat request and parse the response as JSON."""
        raw = self._chat_openai(
            system,
            user,
            temperature,
            max_tokens,
            json_mode=True,
            debug_stage=debug_stage,
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Extract and parse JSON from LLM response, handling markdown fences."""
        if raw is None:
            raise ValueError("LLM returned empty content")
        raw = str(raw).strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Strip ```json ... ``` or ``` ... ``` wrappers
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
        if fence_match:
            raw = fence_match.group(1).strip()
        if not raw:
            raise ValueError("LLM returned empty content")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            object_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if object_match is None:
                raise
            return json.loads(object_match.group(0))

    @staticmethod
    def _extract_chat_content(message_content) -> str:
        if isinstance(message_content, str):
            return message_content
        if message_content is None:
            return ""
        if isinstance(message_content, list):
            parts: list[str] = []
            for item in message_content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
                    elif item.get("type") == "text" and isinstance(
                        item.get("content"), str
                    ):
                        parts.append(item["content"])
                    continue
                text_attr = getattr(item, "text", None)
                if isinstance(text_attr, str):
                    parts.append(text_attr)
            return "\n".join(part for part in parts if part)
        return str(message_content)

    def _chat_openai(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool = False,
        debug_stage: str | None = None,
    ) -> str:
        request_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}

        stage = debug_stage or "chat"
        write_debug_event(
            "llm.request",
            {
                "stage": stage,
                "model": self.model,
                "base_url": self.base_url,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "system": system,
                "user": user,
            },
        )

        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as error:
            if not json_mode:
                write_debug_event(
                    "llm.error",
                    {
                        "stage": stage,
                        "model": self.model,
                        "base_url": self.base_url,
                        "json_mode": json_mode,
                        **_exception_payload(error),
                    },
                )
                raise
            request_kwargs.pop("response_format", None)
            try:
                response = self.client.chat.completions.create(**request_kwargs)
            except Exception as retry_error:
                write_debug_event(
                    "llm.error",
                    {
                        "stage": stage,
                        "model": self.model,
                        "base_url": self.base_url,
                        "json_mode": json_mode,
                        **_exception_payload(retry_error),
                        "response_format_retry": True,
                    },
                )
                raise

        content = self._extract_chat_content(response.choices[0].message.content)
        write_debug_event(
            "llm.response",
            {
                "stage": stage,
                "model": self.model,
                "json_mode": json_mode,
                "content": content,
            },
        )
        return content
