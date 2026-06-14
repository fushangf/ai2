from __future__ import annotations

import math
import re
from collections import Counter

from ..schemas import (
    BackgroundOperation,
    CreateOperation,
    DeleteOperation,
    DrawingPlan,
    RecolorOperation,
    SceneSummary,
    TransformOperation,
)

_COLOR_PATTERN = re.compile(
    r"^(transparent|[a-zA-Z]{1,24}|#[0-9a-fA-F]{3,8}|rgba?\([0-9.,%\s]+\)|hsla?\([0-9.,%\s]+\))$"
)
_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_\-]")


def _safe_color(value: str | None, fallback: str | None) -> str | None:
    if value is None:
        return fallback
    value = value.strip()
    return value if _COLOR_PATTERN.fullmatch(value) else fallback


def _clamp(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def _safe_id(value: str, fallback: str = "shape") -> str:
    cleaned = _ID_PATTERN.sub("_", value or fallback)[:64]
    return cleaned or fallback


def _safe_id_list(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for value in values[:limit]:
        cleaned = _safe_id(value, "")
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def sanitize_plan(plan: DrawingPlan, width: int, height: int, max_operations: int) -> DrawingPlan:
    """结构校验后的第二道安全边界：数量、坐标、颜色、ID、编辑幅度。"""
    width = max(320, min(2400, width))
    height = max(240, min(1600, height))
    margin_x = width * 0.35
    margin_y = height * 0.35

    plan.operations = plan.operations[:max_operations]
    plan.execution_steps = [str(item).strip()[:120] for item in plan.execution_steps[:10] if str(item).strip()]
    plan.confidence = _clamp(plan.confidence, 0, 1)
    seen: Counter[str] = Counter()

    for op in plan.operations:
        if isinstance(op, BackgroundOperation):
            op.color1 = _safe_color(op.color1, "#ffffff") or "#ffffff"
            op.color2 = _safe_color(op.color2, op.color1) or op.color1
            continue

        if isinstance(op, (TransformOperation, RecolorOperation, DeleteOperation)):
            op.target_ids = _safe_id_list(op.target_ids, 80)
            op.target_group_ids = _safe_id_list(op.target_group_ids, 30)
            if isinstance(op, TransformOperation):
                op.dx = _clamp(op.dx, -width * 2, width * 2)
                op.dy = _clamp(op.dy, -height * 2, height * 2)
                op.scale = _clamp(op.scale, 0.05, 20)
                op.rotation_delta = _clamp(op.rotation_delta, -3600, 3600)
            elif isinstance(op, RecolorOperation):
                op.fill = _safe_color(op.fill, None)
                op.stroke = _safe_color(op.stroke, None)
            continue

        if not isinstance(op, CreateOperation):
            continue

        shape = op.shape
        base_id = _safe_id(shape.id)
        seen[base_id] += 1
        shape.id = base_id if seen[base_id] == 1 else f"{base_id}_{seen[base_id]}"
        shape.group_id = _safe_id(shape.group_id, "")
        shape.fill = _safe_color(shape.fill, "transparent") or "transparent"
        shape.stroke = _safe_color(shape.stroke, "#111827") or "#111827"
        shape.stroke_width = _clamp(shape.stroke_width, 0, 30)
        shape.opacity = _clamp(shape.opacity, 0, 1)

        for key in ("cx", "x", "x1", "x2"):
            if hasattr(shape, key):
                setattr(shape, key, _clamp(getattr(shape, key), -margin_x, width + margin_x))
        for key in ("cy", "y", "y1", "y2"):
            if hasattr(shape, key):
                setattr(shape, key, _clamp(getattr(shape, key), -margin_y, height + margin_y))
        for key in ("r", "rx", "width"):
            if hasattr(shape, key):
                setattr(shape, key, _clamp(getattr(shape, key), 1, width * 2))
        for key in ("ry", "height"):
            if hasattr(shape, key):
                setattr(shape, key, _clamp(getattr(shape, key), 1, height * 2))
        if hasattr(shape, "radius"):
            shape.radius = _clamp(shape.radius, 0, min(width, height))
        if hasattr(shape, "font_size"):
            shape.font_size = _clamp(shape.font_size, 6, 200)
        if hasattr(shape, "points"):
            for point in shape.points:
                point.x = _clamp(point.x, -margin_x, width + margin_x)
                point.y = _clamp(point.y, -margin_y, height + margin_y)
        for point_name in ("p0", "p1", "p2", "p3"):
            if hasattr(shape, point_name):
                point = getattr(shape, point_name)
                point.x = _clamp(point.x, -margin_x, width + margin_x)
                point.y = _clamp(point.y, -margin_y, height + margin_y)

    return plan


def compact_scene(scene: SceneSummary, max_objects: int) -> dict:
    objects = scene.objects[-max_objects:]
    return {
        "background": scene.background,
        "objects": [item.model_dump(mode="json") for item in objects],
    }
