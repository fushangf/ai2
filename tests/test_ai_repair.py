from unittest.mock import AsyncMock

import asyncio

from backend.app.schemas import PlanRequest
from backend.app.services.ai_planner import AIPlanner
from backend.app.settings import Settings


def test_invalid_ai_json_is_repaired_once():
    planner = AIPlanner(Settings(ai_api_key="fake", ai_repair_retries=1))
    valid = """{
      "title":"修复成功",
      "intent":"create",
      "confidence":0.9,
      "plan_summary":"生成一个圆",
      "execution_steps":["创建圆形"],
      "spoken_feedback":"完成",
      "operations":[{"op":"create","shape":{"type":"circle","id":"c1","group_id":"g1","label":"圆","tags":[],"fill":"#fff","stroke":"#000","stroke_width":1,"opacity":1,"z_index":0,"rotation":0,"cx":50,"cy":50,"r":20}}]
    }"""
    planner._request_completion = AsyncMock(side_effect=["{bad json", valid])
    result = asyncio.run(planner.plan(PlanRequest(text="画一个圆")))
    assert result.repair_attempted is True
    assert result.plan.title == "修复成功"
    assert planner._request_completion.await_count == 2
