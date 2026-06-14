from backend.app.schemas import DrawingPlan
from backend.app.services.guardrails import sanitize_plan


def sample_plan():
    return DrawingPlan.model_validate({
        "title": "测试",
        "plan_summary": "动态生成若干图元",
        "spoken_feedback": "完成",
        "operations": [
            {"op": "background", "mode": "linear_gradient", "color1": "#87CEEB", "color2": "#ffffff", "direction": "vertical"},
            {"op": "create", "shape": {"type": "circle", "id": "sun", "group_id": "sky", "label": "太阳", "tags": ["天空"], "fill": "gold", "stroke": "orange", "stroke_width": 2, "opacity": 1, "z_index": 1, "rotation": 0, "cx": 850, "cy": 100, "r": 60}},
            {"op": "transform", "target_ids": ["sun"], "target_group_ids": [], "dx": -50, "dy": 10, "scale": 1.2, "rotation_delta": 0},
        ],
    })


def test_structured_plan_accepts_mixed_operations():
    plan = sample_plan()
    assert len(plan.operations) == 3
    assert plan.operations[1].shape.type == "circle"


def test_guardrail_clamps_coordinates_and_colors():
    plan = sample_plan()
    circle = plan.operations[1].shape
    circle.cx = 999999
    circle.fill = "url(javascript:alert(1))"
    safe = sanitize_plan(plan, 1000, 700, 220)
    circle = safe.operations[1].shape
    assert circle.cx <= 1350
    assert circle.fill == "transparent"


def test_guardrail_renames_duplicate_ids():
    plan = sample_plan()
    duplicate = plan.operations[1].model_copy(deep=True)
    plan.operations.append(duplicate)
    safe = sanitize_plan(plan, 1000, 700, 220)
    ids = [op.shape.id for op in safe.operations if getattr(op, "op", None) == "create"]
    assert ids == ["sun", "sun_2"]


def test_operation_limit():
    plan = sample_plan()
    plan.operations = plan.operations * 20
    safe = sanitize_plan(plan, 1000, 700, 8)
    assert len(safe.operations) == 8
