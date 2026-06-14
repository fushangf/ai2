from __future__ import annotations
import asyncio
import json
import random
import time
from typing import Any
import httpx
from pydantic import BaseModel, Field
from ..schemas import VoiceChatRequest, VoiceChatResponse, VoiceChatTurn
from ..settings import Settings
from .ai_planner import AIConfigurationError, AIPlanningError
class _VoiceChatPayload(BaseModel):
    answer: str = Field(max_length=500)
    spoken_feedback: str = Field(max_length=500)
    intent: str = Field(default="general", max_length=40)
    suggested_action: str = Field(default="none", max_length=40)
SYSTEM_PROMPT = """
你是“AI 语音交流模型 V2”，服务于一个纯语音绘图工具。
目标：用自然、简短、适合语音播报的中文回答用户。
要求：
1. 只输出一个 JSON 对象，不要 markdown。
2. answer 控制在 120 个汉字以内，spoken_feedback 通常与 answer 一致或更口语化。
3. 如果用户在问如何使用绘图工具，优先给出可直接说出口的语音指令示例。
4. 如果用户想切回绘图，suggested_action 可填 switch_draw_mode。
5. 如果用户只是闲聊或追问，保持自然对话，不要编造能力。
6. 不要要求用户点击按钮；默认面向纯语音场景。
""".strip()
class VoiceChatV2Service:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http_client: httpx.AsyncClient | None = None
    @property
    def configured(self) -> bool:
        return bool(self.settings.ai_api_key)
    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            timeout = httpx.Timeout(
                self.settings.ai_timeout_seconds,
                connect=min(self.settings.ai_connect_timeout_seconds, self.settings.ai_timeout_seconds),
            )
            limits = httpx.Limits(
                max_connections=max(1, self.settings.ai_pool_max_connections),
                max_keepalive_connections=max(1, min(10, self.settings.ai_pool_max_connections)),
                keepalive_expiry=30,
            )
            self._http_client = httpx.AsyncClient(timeout=timeout, limits=limits, http2=False)
        return self._http_client
    async def chat(self, request: VoiceChatRequest) -> VoiceChatResponse:
        if not self.configured:
            raise AIConfigurationError("尚未配置 AI_API_KEY，无法启用语音交流模型 V2。")
        trimmed_history = request.history[-max(0, self.settings.voice_chat_history_turns * 2):]
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in trimmed_history:
            messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": request.text})
        payload = {
            "model": self.settings.resolved_voice_chat_model_v2,
            "messages": messages,
            "temperature": self.settings.voice_chat_temperature,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        }
        started = time.perf_counter()
        content = await self._request_completion(payload)
        result = _VoiceChatPayload.model_validate(self._extract_json(content))
        latency_ms = int((time.perf_counter() - started) * 1000)
        new_history = [*trimmed_history, VoiceChatTurn(role="user", content=request.text), VoiceChatTurn(role="assistant", content=result.answer)]
        new_history = new_history[-12:]
        return VoiceChatResponse(
            ok=True,
            model=self.settings.resolved_voice_chat_model_v2,
            latency_ms=latency_ms,
            answer=result.answer,
            spoken_feedback=result.spoken_feedback or result.answer,
            intent=result.intent or "general",
            suggested_action=result.suggested_action or "none",
            history=new_history,
        )
    async def _request_completion(self, payload: dict[str, Any]) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        attempts = max(1, self.settings.ai_max_retries + 1)
        for attempt in range(attempts):
            try:
                response = await self._get_http_client().post(self.settings.endpoint_url, headers=headers, json=payload)
                if response.status_code >= 400:
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = AIPlanningError(self._format_http_error(response))
                        if attempt < attempts - 1:
                            await asyncio.sleep(self._backoff(attempt))
                            continue
                    raise AIPlanningError(self._format_http_error(response))
                return self._extract_content(response.json())
            except AIPlanningError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
            except Exception as exc:
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
        raise AIPlanningError(f"语音交流模型 V2 请求失败：{last_error}") from last_error
    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0, 0.25 * (2**attempt)) + random.uniform(0, 0.12)
    @staticmethod
    def _extract_content(completion: Any) -> str:
        choices = completion.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif "text" in item:
                        parts.append(str(item.get("text", "")))
            return "\n".join(part for part in parts if part).strip()
        return ""
    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise AIPlanningError("语音交流模型 V2 未返回有效 JSON")
        return json.loads(text[start:end + 1])
    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = response.text
        return f"七牛云 AI 服务返回错误（HTTP {response.status_code}）：{payload}"
