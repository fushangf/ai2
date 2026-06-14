from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..schemas import DrawingPlan, PlanRequest
from ..settings import Settings
from .guardrails import compact_scene, sanitize_plan
from .plan_cache import PlanCache
from .prompt import REPAIR_PROMPT, SYSTEM_PROMPT, json_schema_hint


class AIConfigurationError(RuntimeError):
    pass


class AIPlanningError(RuntimeError):
    pass


@dataclass(slots=True)
class AIPlanResult:
    plan: DrawingPlan
    latency_ms: int
    repair_attempted: bool = False
    cache_hit: bool = False


class AIPlanner:
    """Compile natural-language drawing requests into validated Drawing DSL.

    The planner keeps one pooled HTTP client instead of rebuilding a TCP/TLS
    connection for each request. Successful plans can be served from a bounded
    TTL cache, while all cached values remain validated and sanitized.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self.cache = PlanCache(
            max_entries=settings.plan_cache_max_entries,
            ttl_seconds=settings.plan_cache_ttl_seconds,
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.ai_api_key)

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def cache_stats(self) -> dict[str, int]:
        return self.cache.stats()

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

    async def plan(self, request: PlanRequest) -> AIPlanResult:
        if not self.configured:
            raise AIConfigurationError(
                "尚未配置 AI_API_KEY。请复制 .env.example 为 .env，并填写七牛云控制台创建的 API Key。"
            )

        cache_key = self.cache.key_for(request, self.settings.max_scene_objects_sent)
        if self.settings.plan_cache_enabled:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return AIPlanResult(plan=cached, latency_ms=0, cache_hit=True)

        scene_json = json.dumps(
            compact_scene(request.scene, self.settings.max_scene_objects_sent),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        user_content = (
            f"画布尺寸：{request.canvas.width}x{request.canvas.height}\n"
            f"当前场景摘要：<scene>{scene_json}</scene>\n"
            f"用户语音转写：<voice>{request.text}</voice>\n"
            "请输出一份可执行 DrawingPlan JSON。"
        )

        started = time.perf_counter()
        payload = {
            "model": self.settings.resolved_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + json_schema_hint()},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.15,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }

        content = await self._request_completion(payload)
        repair_attempted = False
        plan: DrawingPlan | None = None
        validation_error: Exception | None = None

        try:
            plan = self._validate_content(content)
        except Exception as exc:
            validation_error = exc

        if plan is None and self.settings.ai_repair_retries > 0:
            repair_attempted = True
            repair_payload = {
                "model": self.settings.resolved_model,
                "messages": [
                    {"role": "system", "content": REPAIR_PROMPT + "\n\n" + json_schema_hint()},
                    {
                        "role": "user",
                        "content": (
                            "下面是未通过校验的模型输出，请只修复结构，不改变用户意图。\n"
                            f"校验错误：{str(validation_error)[:1200]}\n"
                            f"原始输出：{content[:12000]}"
                        ),
                    },
                ],
                "temperature": 0,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            }
            repaired_content = await self._request_completion(repair_payload)
            try:
                plan = self._validate_content(repaired_content)
            except Exception as exc:
                raise AIPlanningError(f"模型输出经自动修复后仍无法通过校验：{exc}") from exc

        if plan is None:
            raise AIPlanningError(f"模型返回的 JSON 无法通过校验：{validation_error}")

        plan = sanitize_plan(
            plan,
            request.canvas.width,
            request.canvas.height,
            self.settings.max_operations,
        )
        if self.settings.plan_cache_enabled:
            self.cache.put(cache_key, plan)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return AIPlanResult(
            plan=plan,
            latency_ms=elapsed_ms,
            repair_attempted=repair_attempted,
            cache_hit=False,
        )

    def _validate_content(self, content: str) -> DrawingPlan:
        if not content:
            raise ValueError("模型没有返回可执行的 JSON 方案")
        plan_payload = self._extract_json(content)
        return DrawingPlan.model_validate(plan_payload)

    async def _request_completion(self, payload: dict[str, Any]) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        attempts = max(1, self.settings.ai_max_retries + 1)

        for attempt in range(attempts):
            try:
                response = await self._get_http_client().post(
                    self.settings.endpoint_url,
                    headers=headers,
                    json=payload,
                )
                if response.status_code >= 400:
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = AIPlanningError(self._format_http_error(response))
                        if attempt < attempts - 1:
                            retry_after = self._retry_after_seconds(response)
                            await asyncio.sleep(retry_after if retry_after is not None else self._backoff(attempt))
                            continue
                    raise AIPlanningError(self._format_http_error(response))
                data = response.json()
                return self._extract_content(data)
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

        raise AIPlanningError(f"AI 请求失败：{last_error}") from last_error

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0, 0.25 * (2**attempt)) + random.uniform(0, 0.12)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After", "").strip()
        try:
            return max(0.0, min(5.0, float(value))) if value else None
        except ValueError:
            return None

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
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("未找到 JSON 对象")
        return json.loads(text[start : end + 1])

    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = response.text
        return f"七牛云 AI 服务返回错误（HTTP {response.status_code}）：{payload}"
