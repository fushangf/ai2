from backend.app.schemas import PlanRequest
from backend.app.services.local_router import route_local_edit


def scene_request(text: str) -> PlanRequest:
    return PlanRequest.model_validate(
        {
            "text": text,
            "canvas": {"width": 1000, "height": 700},
            "scene": {
                "background": {"mode": "solid", "color1": "#fff"},
                "objects": [
                    {"id": "sun_body", "group_id": "sun", "label": "太阳", "type": "circle", "bbox": [760, 50, 120, 120], "fill": "gold", "stroke": "orange", "tags": ["太阳", "天空"]},
                    {"id": "cloud_1", "group_id": "cloud", "label": "云朵", "type": "ellipse", "bbox": [100, 90, 180, 80], "fill": "white", "stroke": "#ddd", "tags": ["白云", "云朵"]},
                    {"id": "bird_1", "group_id": "bird", "label": "小鸟", "type": "bezier", "bbox": [500, 120, 40, 20], "fill": "transparent", "stroke": "black", "tags": ["鸟", "海鸥"]},
                ],
            },
        }
    )


def test_local_router_decomposes_multi_step_edit():
    result = route_local_edit(scene_request("把太阳向右移动80像素，然后把云朵变成粉色，再删除小鸟"))
    assert result is not None
    assert result.plan.intent == "edit"
    assert len(result.plan.operations) == 3
    assert [op.op for op in result.plan.operations] == ["transform", "recolor", "delete"]
    assert result.plan.operations[0].dx == 80
    assert result.plan.operations[1].fill == "#ec4899"


def test_local_router_falls_back_when_clause_is_uncertain():
    result = route_local_edit(scene_request("让整幅画更有电影感并增加空间层次"))
    assert result is None


def multi_cloud_request(text: str) -> PlanRequest:
    return PlanRequest.model_validate(
        {
            "text": text,
            "canvas": {"width": 1000, "height": 700},
            "scene": {
                "objects": [
                    {"id": "cloud_left", "group_id": "cloud_left", "label": "云朵", "type": "ellipse", "bbox": [80, 80, 100, 50], "tags": ["云朵", "白云"]},
                    {"id": "cloud_middle", "group_id": "cloud_middle", "label": "云朵", "type": "ellipse", "bbox": [400, 100, 160, 80], "tags": ["云朵", "白云"]},
                    {"id": "cloud_right", "group_id": "cloud_right", "label": "云朵", "type": "ellipse", "bbox": [760, 70, 120, 60], "tags": ["云朵", "白云"]},
                ]
            },
        }
    )


def test_local_router_resolves_spatial_reference():
    result = route_local_edit(multi_cloud_request("把最右边的云朵变成粉色"))
    assert result is not None
    assert result.plan.operations[0].target_group_ids == ["cloud_right"]


def test_local_router_resolves_ordinal_reference():
    result = route_local_edit(multi_cloud_request("把第二个云朵向下移动50像素"))
    assert result is not None
    operation = result.plan.operations[0]
    assert operation.target_group_ids == ["cloud_middle"]
    assert operation.dy == 50


def test_local_router_can_target_all_matching_objects():
    result = route_local_edit(multi_cloud_request("把所有云朵变成蓝色"))
    assert result is not None
    assert result.plan.operations[0].target_group_ids == ["cloud_left", "cloud_middle", "cloud_right"]
