import asyncio
from unittest.mock import AsyncMock

from backend.app.schemas import PlanRequest
from backend.app.services.ai_planner import AIPlanner
from backend.app.services.plan_cache import PlanCache
from backend.app.settings import Settings


VALID_PLAN = """{
  "title":"缓存测试",
  "intent":"create",
  "confidence":0.92,
  "plan_summary":"生成一个圆",
  "execution_steps":["创建圆形"],
  "spoken_feedback":"完成",
  "operations":[{"op":"create","shape":{"type":"circle","id":"c1","group_id":"g1","label":"圆","tags":[],"fill":"#fff","stroke":"#000","stroke_width":1,"opacity":1,"z_index":0,"rotation":0,"cx":50,"cy":50,"r":20}}]
}"""


def test_ai_planner_reuses_validated_cached_plan():
    planner = AIPlanner(Settings(ai_api_key="fake", plan_cache_enabled=True))
    planner._request_completion = AsyncMock(return_value=VALID_PLAN)
    request = PlanRequest(text="画一个圆")

    first = asyncio.run(planner.plan(request))
    second = asyncio.run(planner.plan(request))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.latency_ms == 0
    assert planner._request_completion.await_count == 1
    second.plan.title = "被修改"
    third = asyncio.run(planner.plan(request))
    assert third.plan.title == "缓存测试"


def test_plan_cache_key_changes_with_scene():
    cache = PlanCache()
    first = PlanRequest(text="把太阳变成红色")
    second = PlanRequest.model_validate({
        "text": "把太阳变成红色",
        "scene": {"objects": [{"id": "sun", "group_id": "sun", "label": "太阳", "type": "circle", "bbox": [0, 0, 10, 10]}]},
    })
    assert cache.key_for(first, 160) != cache.key_for(second, 160)
