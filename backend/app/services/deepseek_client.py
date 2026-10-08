"""DeepSeek httpx 同步客户端（chat / chat_stream）"""
import json
import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)

BASE_URL = "https://api.deepseek.com"


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, timeout: float = 180.0):
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key or settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
        )

    def _payload(self, messages, model, temperature, max_tokens, stream: bool) -> dict:
        payload: dict = {
            "model": model or settings.chat_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # deepseek-reasoner 不支持 temperature，传了会被忽略/报错，故不传
        if not str(payload["model"]).endswith("reasoner"):
            payload["temperature"] = temperature
        if stream:
            payload["stream"] = True
        return payload

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """同步对话，返回完整 content 文本；异常向上抛（调用方自行 try/except）"""
        r = self._client.post(
            "/chat/completions",
            json=self._payload(messages, model, temperature, max_tokens, stream=False),
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """流式对话生成器，逐块 yield {"reasoning": str, "content": str}
        reasoning 仅 deepseek-reasoner 会输出思维链增量"""
        with self._client.stream(
            "POST",
            "/chat/completions",
            json=self._payload(messages, model, temperature, max_tokens, stream=True),
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or ""
                content = delta.get("content") or ""
                if reasoning or content:
                    yield {"reasoning": reasoning, "content": content}

    def close(self):
        self._client.close()


client = DeepSeekClient()
