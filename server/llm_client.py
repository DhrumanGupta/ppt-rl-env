"""
Unified LLM client for the environment.

Three backends:
  - OpenAI-compatible (vLLM/local) — for self-hosted models (default)
  - HF Inference API — free, serverless, no infra needed
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Thin wrapper that picks the right backend based on env vars.

    Config:
      LLM_BACKEND=openai     (default) → uses OpenAI-compatible endpoint (vLLM on H100)
      LLM_BACKEND=hf                   → uses HF Inference API (requires credits)

    OpenAI mode env vars:
      LLM_BASE_URL  — vLLM endpoint (default: http://localhost:8001/v1)
      LLM_API_KEY   — API key (default: "local")
      LLM_MODEL     — model name

    HF mode env vars:
      HF_TOKEN      — HuggingFace token
      LLM_MODEL     — model ID (default: Qwen/Qwen3.5-9B)

    """

    def __init__(self):
        self.backend = os.environ.get("LLM_BACKEND", "openai")
        default_model = "Qwen/Qwen3.5-9B"
        self.model = os.environ.get("LLM_MODEL", default_model)

        if self.backend == "hf":
            from huggingface_hub import InferenceClient

            self.client = InferenceClient(
                model=self.model,
                token=os.environ.get("HF_TOKEN"),
            )
            logger.info(f"LLM backend: HF Inference API ({self.model})")
        else:
            from openai import OpenAI

            self.client = OpenAI(
                base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8001/v1"),
                api_key=os.environ.get("LLM_API_KEY", "local"),
            )
            logger.info(f"LLM backend: OpenAI-compatible ({self.model})")

    def chat(
        self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        """Send a chat completion request. Returns the raw response text."""
        if self.backend == "hf":
            return self._chat_hf(system, user, temperature, max_tokens)
        return self._chat_openai(system, user, temperature, max_tokens)

    def chat_json(
        self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> dict:
        """Send a chat request and parse the response as JSON."""
        if self.backend == "hf":
            raw = self._chat_hf(system, user, temperature, max_tokens)
        else:
            raw = self._chat_openai(
                system,
                user,
                temperature,
                max_tokens,
                json_mode=True,
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

    def _chat_hf(
        self, system: str, user: str, temperature: float, max_tokens: int
    ) -> str:
        response = self.client.chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def _chat_openai(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool = False,
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

        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception:
            if not json_mode:
                raise
            request_kwargs.pop("response_format", None)
            response = self.client.chat.completions.create(**request_kwargs)

        return self._extract_chat_content(response.choices[0].message.content)
