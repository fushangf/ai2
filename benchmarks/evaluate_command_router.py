from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import statistics
import time

from backend.app.schemas import PlanRequest
from backend.app.services.local_router import route_local_edit

SCENE = {
    "background": {"mode": "solid", "color1": "#ffffff"},
    "objects": [
        {"id": "sun_body", "group_id": "sun", "label": "太阳", "type": "circle", "bbox": [760, 50, 120, 120], "fill": "gold", "stroke": "orange", "tags": ["太阳", "天空"]},
        {"id": "cloud_left", "group_id": "cloud_left", "label": "云朵", "type": "ellipse", "bbox": [100, 90, 140, 70], "fill": "white", "stroke": "#ddd", "tags": ["白云", "云朵"]},
        {"id": "cloud_middle", "group_id": "cloud_middle", "label": "云朵", "type": "ellipse", "bbox": [390, 105, 180, 90], "fill": "white", "stroke": "#ddd", "tags": ["白云", "云朵"]},
        {"id": "cloud_right", "group_id": "cloud_right", "label": "云朵", "type": "ellipse", "bbox": [690, 75, 120, 60], "fill": "white", "stroke": "#ddd", "tags": ["白云", "云朵"]},
        {"id": "bird_1", "group_id": "bird", "label": "小鸟", "type": "bezier", "bbox": [500, 120, 40, 20], "fill": "transparent", "stroke": "black", "tags": ["鸟", "海鸥"]},
    ],
}

CASES = [
    ("把太阳向右移动80像素", True, ["transform"]),
    ("太阳往左移一点", True, ["transform"]),
    ("把云朵向上移动", True, ["transform"]),
    ("把太阳放大20%", True, ["transform"]),
    ("把云朵缩小一点", True, ["transform"]),
    ("让小鸟顺时针旋转30度", True, ["transform"]),
    ("把云朵变成粉色", True, ["recolor"]),
    ("把太阳改成红色", True, ["recolor"]),
    ("删除小鸟", True, ["delete"]),
    ("把太阳右移80像素，然后把云朵变成粉色，再删除小鸟", True, ["transform", "recolor", "delete"]),
    ("清空画布", True, ["clear"]),
    ("把最右边的云朵变成粉色", True, ["recolor"]),
    ("把第二个云朵向下移动50像素", True, ["transform"]),
    ("把所有云朵变成蓝色", True, ["recolor"]),
    ("让画面更有电影感", False, []),
    ("画一座未来城市", False, []),
    ("在海面上增加一艘帆船并营造夕阳氛围", False, []),
    ("把整体构图改成对角线并增强层次", False, []),
    ("生成一个儿童科普海报", False, []),
]


def request(text: str) -> PlanRequest:
    return PlanRequest.model_validate({"text": text, "canvas": {"width": 1000, "height": 700}, "scene": SCENE})


def main() -> None:
    correct = 0
    timings: list[float] = []
    rows: list[str] = []
    for text, should_route, expected_ops in CASES:
        started = time.perf_counter_ns()
        result = route_local_edit(request(text))
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        timings.append(elapsed_ms)
        routed = result is not None
        operations = [op.op for op in result.plan.operations] if result else []
        passed = routed == should_route and (not should_route or operations == expected_ops)
        correct += int(passed)
        rows.append(f"{'PASS' if passed else 'FAIL'} | {elapsed_ms:.4f} ms | {text} | {operations or 'AI fallback'}")

    print("\n".join(rows))
    print("-")
    print(f"cases={len(CASES)}")
    print(f"routing_and_decomposition_accuracy={correct / len(CASES) * 100:.1f}%")
    print(f"median_router_latency_ms={statistics.median(timings):.4f}")
    print(f"p95_router_latency_ms={sorted(timings)[max(0, int(len(timings) * .95) - 1)]:.4f}")


if __name__ == "__main__":
    main()
