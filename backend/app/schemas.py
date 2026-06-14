from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Point(BaseModel):
    x: float
    y: float


class ShapeBase(BaseModel):
    id: str = Field(description="场景内唯一 ID，例如 cloud_1_part_1")
    group_id: str = Field(default="", description="同一语义对象共享的分组 ID")
    label: str = Field(default="图形", description="中文语义标签")
    tags: list[str] = Field(default_factory=list, max_length=12)
    fill: str = Field(default="transparent", max_length=64)
    stroke: str = Field(default="#111827", max_length=64)
    stroke_width: float = Field(default=2, ge=0, le=30)
    opacity: float = Field(default=1, ge=0, le=1)
    z_index: int = Field(default=0, ge=-1000, le=1000)
    rotation: float = Field(default=0, ge=-3600, le=3600)

    @field_validator("id", "group_id", "label")
    @classmethod
    def clean_short_text(cls, value: str) -> str:
        return value.strip()[:80]


class CircleShape(ShapeBase):
    type: Literal["circle"]
    cx: float
    cy: float
    r: float = Field(gt=0)


class EllipseShape(ShapeBase):
    type: Literal["ellipse"]
    cx: float
    cy: float
    rx: float = Field(gt=0)
    ry: float = Field(gt=0)


class RectShape(ShapeBase):
    type: Literal["rect"]
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    radius: float = Field(default=0, ge=0)


class LineShape(ShapeBase):
    type: Literal["line"]
    x1: float
    y1: float
    x2: float
    y2: float
    line_cap: Literal["butt", "round", "square"] = "round"


class PolygonShape(ShapeBase):
    type: Literal["polygon"]
    points: list[Point] = Field(min_length=3, max_length=80)


class PolylineShape(ShapeBase):
    type: Literal["polyline"]
    points: list[Point] = Field(min_length=2, max_length=100)
    line_cap: Literal["butt", "round", "square"] = "round"
    line_join: Literal["round", "bevel", "miter"] = "round"


class BezierShape(ShapeBase):
    type: Literal["bezier"]
    p0: Point
    p1: Point
    p2: Point
    p3: Point
    line_cap: Literal["butt", "round", "square"] = "round"


class ArcShape(ShapeBase):
    type: Literal["arc"]
    cx: float
    cy: float
    r: float = Field(gt=0)
    start_angle: float
    end_angle: float
    counterclockwise: bool = False


class TextShape(ShapeBase):
    type: Literal["text"]
    x: float
    y: float
    text: str = Field(max_length=120)
    font_size: float = Field(default=28, ge=6, le=200)
    font_family: str = Field(default="sans-serif", max_length=80)
    align: Literal["left", "center", "right"] = "center"
    baseline: Literal["top", "middle", "alphabetic", "bottom"] = "middle"


Shape = Annotated[
    Union[
        CircleShape,
        EllipseShape,
        RectShape,
        LineShape,
        PolygonShape,
        PolylineShape,
        BezierShape,
        ArcShape,
        TextShape,
    ],
    Field(discriminator="type"),
]


class CreateOperation(BaseModel):
    op: Literal["create"]
    shape: Shape


class BackgroundOperation(BaseModel):
    op: Literal["background"]
    mode: Literal["solid", "linear_gradient"] = "solid"
    color1: str = Field(default="#ffffff", max_length=64)
    color2: str = Field(default="#ffffff", max_length=64)
    direction: Literal["vertical", "horizontal", "diagonal"] = "vertical"


class TransformOperation(BaseModel):
    op: Literal["transform"]
    target_ids: list[str] = Field(default_factory=list, max_length=80)
    target_group_ids: list[str] = Field(default_factory=list, max_length=30)
    dx: float = Field(default=0, ge=-2000, le=2000)
    dy: float = Field(default=0, ge=-2000, le=2000)
    scale: float = Field(default=1, gt=0.05, le=20)
    rotation_delta: float = Field(default=0, ge=-3600, le=3600)


class RecolorOperation(BaseModel):
    op: Literal["recolor"]
    target_ids: list[str] = Field(default_factory=list, max_length=80)
    target_group_ids: list[str] = Field(default_factory=list, max_length=30)
    fill: str | None = Field(default=None, max_length=64)
    stroke: str | None = Field(default=None, max_length=64)


class DeleteOperation(BaseModel):
    op: Literal["delete"]
    target_ids: list[str] = Field(default_factory=list, max_length=80)
    target_group_ids: list[str] = Field(default_factory=list, max_length=30)


class ClearOperation(BaseModel):
    op: Literal["clear"]


Operation = Annotated[
    Union[
        CreateOperation,
        BackgroundOperation,
        TransformOperation,
        RecolorOperation,
        DeleteOperation,
        ClearOperation,
    ],
    Field(discriminator="op"),
]


class DrawingPlan(BaseModel):
    title: str = Field(default="AI 绘图方案", max_length=80)
    intent: Literal["create", "edit", "mixed"] = "mixed"
    confidence: float = Field(default=0.82, ge=0, le=1)
    plan_summary: str = Field(description="面向用户的简短规划摘要，不输出隐藏思维过程", max_length=500)
    execution_steps: list[str] = Field(default_factory=list, max_length=10)
    spoken_feedback: str = Field(description="绘图完成后播报的一句话", max_length=180)
    operations: list[Operation] = Field(min_length=1, max_length=220)


class CanvasInfo(BaseModel):
    width: int = Field(default=1000, ge=320, le=2400)
    height: int = Field(default=700, ge=240, le=1600)


class SceneObjectSummary(BaseModel):
    id: str
    group_id: str = ""
    label: str = ""
    type: str
    bbox: list[float] = Field(default_factory=list, max_length=4)
    fill: str = ""
    stroke: str = ""
    tags: list[str] = Field(default_factory=list, max_length=12)


class SceneSummary(BaseModel):
    background: dict = Field(default_factory=dict)
    objects: list[SceneObjectSummary] = Field(default_factory=list, max_length=220)


class PlanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    canvas: CanvasInfo = Field(default_factory=CanvasInfo)
    scene: SceneSummary = Field(default_factory=SceneSummary)


class PlanResponse(BaseModel):
    ok: bool
    source: Literal["ai", "local", "cache"] = "ai"
    route_reason: str = ""
    model: str
    latency_ms: int
    server_total_ms: int = 0
    repair_attempted: bool = False
    cache_hit: bool = False
    operation_count: int = 0
    plan: DrawingPlan | None = None
    message: str = ""


class VoiceChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=600)


class VoiceChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    history: list[VoiceChatTurn] = Field(default_factory=list, max_length=12)


class VoiceChatResponse(BaseModel):
    ok: bool
    version: Literal["v2"] = "v2"
    mode: Literal["voice_chat_v2"] = "voice_chat_v2"
    model: str
    latency_ms: int
    answer: str = Field(max_length=500)
    spoken_feedback: str = Field(max_length=500)
    intent: str = Field(default="general", max_length=40)
    suggested_action: str = Field(default="none", max_length=40)
    history: list[VoiceChatTurn] = Field(default_factory=list, max_length=12)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip()


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120, description="用户名或邮箱")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_login_username(cls, value: str) -> str:
        return value.strip()


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    is_banned: bool
    usage_count: int
    last_login_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class AuthResponse(BaseModel):
    ok: bool = True
    token: str
    user: UserRead
    redirect_to: str


class ToggleBanRequest(BaseModel):
    banned: bool


class ArtworkScene(BaseModel):
    background: dict = Field(default_factory=dict)
    objects: list[dict] = Field(default_factory=list, max_length=220)


class ArtworkCreate(BaseModel):
    title: str = Field(default="语音绘画作品", min_length=1, max_length=100)
    scene: ArtworkScene

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return value.strip()[:100] or "语音绘画作品"


class ArtworkRead(BaseModel):
    id: int
    title: str
    scene: ArtworkScene
    object_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ArtworkListResponse(BaseModel):
    artworks: list[ArtworkRead]


class UsageLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    request_preview: str
    latency_ms: int
    success: bool
    source: str = "ai"
    operation_count: int = 0
    error_message: str = ""
    created_at: datetime | None = None


class AdminSummary(BaseModel):
    total_users: int
    banned_users: int
    admin_users: int
    total_usage_count: int
    today_usage_count: int = 0
    total_artworks: int = 0
    success_rate: float = 0
    average_latency_ms: int = 0
    local_route_count: int = 0
    ai_route_count: int = 0
    cache_route_count: int = 0
    voice_chat_route_count: int = 0
    recent_logs: list[UsageLogRead]


class AdminUsersResponse(BaseModel):
    users: list[UserRead]
