from __future__ import annotations

import re
from dataclasses import dataclass

from ..schemas import (
    ClearOperation,
    DeleteOperation,
    DrawingPlan,
    Operation,
    PlanRequest,
    RecolorOperation,
    SceneObjectSummary,
    TransformOperation,
)


@dataclass(slots=True)
class LocalRouteResult:
    plan: DrawingPlan
    reason: str


_COLOR_MAP = {
    "红色": "#ef4444",
    "红": "#ef4444",
    "橙色": "#f97316",
    "橙": "#f97316",
    "黄色": "#facc15",
    "黄": "#facc15",
    "绿色": "#22c55e",
    "绿": "#22c55e",
    "青色": "#06b6d4",
    "青": "#06b6d4",
    "蓝色": "#3b82f6",
    "蓝": "#3b82f6",
    "紫色": "#a855f7",
    "紫": "#a855f7",
    "粉色": "#ec4899",
    "粉红色": "#ec4899",
    "粉": "#ec4899",
    "黑色": "#111827",
    "黑": "#111827",
    "白色": "#ffffff",
    "白": "#ffffff",
    "灰色": "#6b7280",
    "灰": "#6b7280",
    "棕色": "#92400e",
    "褐色": "#92400e",
    "金色": "#f59e0b",
    "银色": "#cbd5e1",
    "透明": "transparent",
}

_SPLIT_PATTERN = re.compile(r"(?:然后|接着|随后|再把|再将|并且|同时|最后|；|;|。|，|,)+")
_FILLER_PATTERN = re.compile(r"^(请|请你|帮我|麻烦|把|将|再|然后|接着)+")


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:'\"“”‘’（）()【】\[\]]+", "", text or "").lower()


def _target_tokens(item: SceneObjectSummary) -> set[str]:
    tokens = {item.id, item.group_id, item.label, *item.tags}
    return {_compact(token) for token in tokens if token and _compact(token) not in {"图形", "对象", "元素"}}


def _resolve_target(
    clause: str,
    objects: list[SceneObjectSummary],
    previous: tuple[list[str], list[str]] | None,
) -> tuple[list[str], list[str]] | None:
    compact = _compact(clause)
    if previous and any(word in compact for word in ("它", "它们", "这个", "这些", "该对象", "再", "继续")):
        return previous

    matches: list[tuple[int, SceneObjectSummary]] = []
    for item in objects:
        best = max((len(token) for token in _target_tokens(item) if token and token in compact), default=0)
        if best:
            matches.append((best, item))
    if not matches:
        if previous:
            return previous
        unique_groups = {item.group_id for item in objects if item.group_id}
        if len(unique_groups) == 1:
            return [], list(unique_groups)
        if len(objects) == 1:
            return [objects[0].id], []
        return None

    max_score = max(score for score, _ in matches)
    selected = [item for score, item in matches if score == max_score]

    def center_x(item: SceneObjectSummary) -> float:
        return item.bbox[0] + item.bbox[2] / 2 if len(item.bbox) == 4 else 0

    def center_y(item: SceneObjectSummary) -> float:
        return item.bbox[1] + item.bbox[3] / 2 if len(item.bbox) == 4 else 0

    def area(item: SceneObjectSummary) -> float:
        return item.bbox[2] * item.bbox[3] if len(item.bbox) == 4 else 0

    # 同名对象的空间和序号消歧，例如“最左边的云”“第二棵树”“最大的圆”。
    if len(selected) > 1 and not any(word in compact for word in ("所有", "全部", "每个", "这些", "它们")):
        ordered = sorted(selected, key=lambda item: (center_x(item), center_y(item), item.id))
        ordinal_map = {
            "第一个": 0, "第一": 0, "最左": 0, "左边": 0,
            "第二个": 1, "第二": 1,
            "第三个": 2, "第三": 2,
            "第四个": 3, "第四": 3,
        }
        chosen_index = next((index for word, index in ordinal_map.items() if word in compact), None)
        if chosen_index is not None:
            selected = [ordered[min(chosen_index, len(ordered) - 1)]]
        elif any(word in compact for word in ("最右", "右边")):
            selected = [max(selected, key=center_x)]
        elif any(word in compact for word in ("最上", "上面", "顶部")):
            selected = [min(selected, key=center_y)]
        elif any(word in compact for word in ("最下", "下面", "底部")):
            selected = [max(selected, key=center_y)]
        elif any(word in compact for word in ("最大", "最大的")):
            selected = [max(selected, key=area)]
        elif any(word in compact for word in ("最小", "最小的")):
            selected = [min(selected, key=area)]

    groups = sorted({item.group_id for item in selected if item.group_id})
    if groups:
        return [], groups
    return sorted({item.id for item in selected}), []


def _direction_delta(clause: str, width: int, height: int) -> tuple[float, float]:
    compact = _compact(clause)
    dx = 0.0
    dy = 0.0
    default_x = max(30, round(width * 0.08))
    default_y = max(24, round(height * 0.08))

    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:像素|px|个单位)?", clause, re.I)
    amount = float(amount_match.group(1)) if amount_match else None

    if any(word in compact for word in ("向左", "往左", "左移", "移到左边")):
        dx -= amount if amount is not None else default_x
    if any(word in compact for word in ("向右", "往右", "右移", "移到右边")):
        dx += amount if amount is not None else default_x
    if any(word in compact for word in ("向上", "往上", "上移", "移到上面")):
        dy -= amount if amount is not None else default_y
    if any(word in compact for word in ("向下", "往下", "下移", "移到下面")):
        dy += amount if amount is not None else default_y
    return dx, dy


def _scale_value(clause: str) -> float:
    compact = _compact(clause)
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", clause)
    if any(word in compact for word in ("放大", "变大", "扩大")):
        if percent:
            return min(4.0, 1 + float(percent.group(1)) / 100)
        times = re.search(r"(\d+(?:\.\d+)?)\s*倍", clause)
        return min(4.0, float(times.group(1))) if times else 1.2
    if any(word in compact for word in ("缩小", "变小", "缩短")):
        if percent:
            return max(0.1, 1 - float(percent.group(1)) / 100)
        times = re.search(r"(\d+(?:\.\d+)?)\s*倍", clause)
        return max(0.1, float(times.group(1))) if times else 0.8
    return 1.0


def _rotation_value(clause: str) -> float:
    compact = _compact(clause)
    if not any(word in compact for word in ("旋转", "转动", "转一下", "顺时针", "逆时针")):
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:度|°)?", clause)
    angle = float(match.group(1)) if match else 15.0
    return -angle if "逆时针" in compact else angle


def _find_color(clause: str) -> str | None:
    compact = _compact(clause)
    for name in sorted(_COLOR_MAP, key=len, reverse=True):
        if _compact(name) in compact:
            return _COLOR_MAP[name]
    hex_match = re.search(r"#[0-9a-fA-F]{3,8}", clause)
    return hex_match.group(0) if hex_match else None


def _target_name(target_ids: list[str], target_groups: list[str]) -> str:
    values = target_groups or target_ids
    return "、".join(values[:3]) or "目标对象"


def route_local_edit(request: PlanRequest) -> LocalRouteResult | None:
    """把高频编辑语句编译为 DSL。只有全部子句都能可靠解析时才接管。"""
    text = request.text.strip()
    compact = _compact(text)
    if not compact:
        return None

    if any(word in compact for word in ("清空画布", "清除全部", "全部清除", "重新开始")):
        plan = DrawingPlan(
            title="本地快速清空",
            intent="edit",
            confidence=0.99,
            plan_summary="已通过本地快速通道清空画布，无需等待大模型。",
            execution_steps=["清空当前场景"],
            spoken_feedback="画布已清空",
            operations=[ClearOperation(op="clear")],
        )
        return LocalRouteResult(plan=plan, reason="命中本地系统级清空指令")

    objects = request.scene.objects
    if not objects:
        return None

    clauses = [part.strip() for part in _SPLIT_PATTERN.split(text) if part.strip()]
    if not clauses:
        clauses = [text]

    operations: list[Operation] = []
    steps: list[str] = []
    previous_target: tuple[list[str], list[str]] | None = None

    for raw_clause in clauses:
        clause = _FILLER_PATTERN.sub("", raw_clause).strip() or raw_clause
        clause_compact = _compact(clause)
        target = _resolve_target(clause, objects, previous_target)
        if not target:
            return None
        target_ids, target_groups = target
        previous_target = target
        target_label = _target_name(target_ids, target_groups)

        if any(word in clause_compact for word in ("删除", "去掉", "移除", "擦掉")):
            operations.append(
                DeleteOperation(op="delete", target_ids=target_ids, target_group_ids=target_groups)
            )
            steps.append(f"删除 {target_label}")
            continue

        color = _find_color(clause)
        recolor_requested = any(word in clause_compact for word in ("改成", "变成", "换成", "涂成", "颜色", "染成"))
        if recolor_requested:
            if not color:
                return None
            operations.append(
                RecolorOperation(
                    op="recolor",
                    target_ids=target_ids,
                    target_group_ids=target_groups,
                    fill=color,
                    stroke=None,
                )
            )
            steps.append(f"把 {target_label} 改为指定颜色")
            continue

        dx, dy = _direction_delta(clause, request.canvas.width, request.canvas.height)
        scale = _scale_value(clause)
        rotation = _rotation_value(clause)
        transform_requested = any(
            word in clause_compact
            for word in (
                "移动", "移到", "向左", "向右", "向上", "向下", "左移", "右移", "上移", "下移",
                "放大", "缩小", "变大", "变小", "旋转", "转动", "顺时针", "逆时针",
            )
        )
        if transform_requested and (dx or dy or scale != 1 or rotation):
            operations.append(
                TransformOperation(
                    op="transform",
                    target_ids=target_ids,
                    target_group_ids=target_groups,
                    dx=dx,
                    dy=dy,
                    scale=scale,
                    rotation_delta=rotation,
                )
            )
            actions: list[str] = []
            if dx or dy:
                actions.append("移动")
            if scale != 1:
                actions.append("缩放")
            if rotation:
                actions.append("旋转")
            steps.append(f"{''.join(actions)} {target_label}")
            continue

        return None

    if not operations:
        return None

    plan = DrawingPlan(
        title="本地低延迟编辑",
        intent="edit",
        confidence=0.98,
        plan_summary=f"已将语音拆解为 {len(operations)} 个本地编辑步骤，不调用远程模型。",
        execution_steps=steps,
        spoken_feedback=f"已完成 {len(operations)} 个编辑操作",
        operations=operations,
    )
    return LocalRouteResult(plan=plan, reason="高频编辑语句可由本地确定性路由完整解析")
