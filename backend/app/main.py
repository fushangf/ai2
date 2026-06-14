from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_admin, get_current_user
from .bootstrap import ensure_admin_user, ensure_competition_demo_user, init_database
from .database import SessionLocal, check_database_health, get_db
from .models import Artwork, UsageLog, User
from .schemas import (
    AdminSummary,
    AdminUsersResponse,
    ArtworkCreate,
    ArtworkListResponse,
    ArtworkRead,
    ArtworkScene,
    AuthResponse,
    LoginRequest,
    PlanRequest,
    PlanResponse,
    RegisterRequest,
    SceneSummary,
    ToggleBanRequest,
    UsageLogRead,
    UserRead,
    VoiceChatRequest,
    VoiceChatResponse,
)
from .security import hash_password, sign_token, verify_password
from .services.ai_planner import AIConfigurationError, AIPlanner, AIPlanningError
from .services.local_router import route_local_edit
from .services.rate_limit import SlidingWindowRateLimiter
from .services.voice_chat_v2 import VoiceChatV2Service
from .settings import get_settings

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
settings = get_settings()
planner = AIPlanner(settings)
voice_chat_v2 = VoiceChatV2Service(settings)
plan_limiter = SlidingWindowRateLimiter(settings.plan_rate_limit_per_minute)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    with SessionLocal() as db:
        ensure_admin_user(db)
        ensure_competition_demo_user(db)
    try:
        yield
    finally:
        await planner.aclose()
        await voice_chat_v2.aclose()


app = FastAPI(
    title="AI Voice Draw Competition Edition",
    description="纯语音 → 自适应静默检测 → 本地低延迟路由 / AI 复杂规划 → 安全 Drawing DSL → Canvas",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_allow_origins == "*" else [
        item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    if settings.competition_kiosk_mode:
        return RedirectResponse(url="/workspace", status_code=307)
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/register")
async def register_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "register.html")


@app.get("/workspace")
async def workspace_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app")
async def app_page():
    return RedirectResponse(url="/workspace", status_code=307)


@app.get("/admin/login")
async def admin_login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/admin/dashboard")
async def admin_dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/admin")
async def admin_page():
    return RedirectResponse(url="/admin/dashboard", status_code=307)


@app.get("/api/health")
async def health() -> dict:
    security_warnings: list[str] = []
    if len(settings.auth_secret_key) < 32 or settings.auth_secret_key == "change-me-in-production":
        security_warnings.append("AUTH_SECRET_KEY 需要设置为至少 32 位随机字符串")
    if settings.cors_allow_origins == "*":
        security_warnings.append("生产环境应限制 CORS_ALLOW_ORIGINS")
    if settings.competition_kiosk_mode:
        security_warnings.append("评委演示模式已开启，仅适用于本机比赛现场")
    return {
        "ok": True,
        "version": settings.app_version,
        "ai_configured": planner.configured,
        "provider": settings.ai_provider,
        "provider_label": settings.provider_label,
        "model": settings.resolved_model,
        "voice_chat_v2_model": settings.resolved_voice_chat_model_v2,
        "base_url": settings.resolved_base_url,
        "database_ok": check_database_health(),
        "database_backend": settings.resolved_database_url.split(":", 1)[0],
        "kiosk_mode": settings.competition_kiosk_mode,
        "local_edit_router": settings.local_edit_router_enabled,
        "plan_cache": {"enabled": settings.plan_cache_enabled, **planner.cache_stats()},
        "security_warnings": security_warnings,
        "architecture": "voice+VAD -> local edit router / validated cache / AI compiler -> guarded DSL -> transactional canvas",
        "auto_finish_policy": "adaptive voice activity detection; submit after 3 seconds silence",
    }


@app.get("/api/preflight")
async def preflight() -> dict:
    database_ok = check_database_health()
    checks = {
        "backend": {"ok": True, "message": "FastAPI 服务正常"},
        "database": {"ok": database_ok, "message": "数据库连接正常" if database_ok else "数据库连接失败"},
        "ai": {
            "ok": planner.configured,
            "message": f"已配置 {settings.provider_label}" if planner.configured else "尚未配置 AI_API_KEY",
        },
        "local_router": {
            "ok": settings.local_edit_router_enabled,
            "message": "本地低延迟编辑路由已启用" if settings.local_edit_router_enabled else "本地编辑路由已关闭",
        },
        "cache": {
            "ok": settings.plan_cache_enabled,
            "message": "验证后方案缓存已启用" if settings.plan_cache_enabled else "方案缓存已关闭",
            **planner.cache_stats(),
        },
    }
    required_ready = checks["backend"]["ok"] and checks["database"]["ok"] and (
        checks["ai"]["ok"] or checks["local_router"]["ok"]
    )
    recommendations: list[str] = []
    if not planner.configured:
        recommendations.append("配置 AI_API_KEY 后才能生成全新复杂场景")
    if settings.auth_secret_key == "change-me-in-production" or len(settings.auth_secret_key) < 32:
        recommendations.append("正式部署前设置至少 32 位 AUTH_SECRET_KEY")
    if settings.cors_allow_origins == "*":
        recommendations.append("公开部署时限制 CORS_ALLOW_ORIGINS")
    return {"ok": required_ready, "version": settings.app_version, "checks": checks, "recommendations": recommendations}


@app.get("/api/capabilities")
async def capabilities() -> dict:
    return {
        "voice_flow": ["说开始", "自然描述", "静默3秒自动提交", "语音继续编辑"],
        "interaction_modes": ["绘图模式", "语音交流模型V2"],
        "fast_local_commands": ["移动", "缩放", "旋转", "变色", "删除", "清空"],
        "system_commands": [
            "撤销", "重做", "停止", "清空画布", "保存图片", "保存作品", "打开上次作品",
            "重复上次描述", "朗读状态", "语音帮助", "系统自检", "恢复现场",
            "进入交流模式", "退出交流模式", "清空交流记录",
        ],
        "ai_capabilities": ["复杂场景生成", "多对象关系", "多步骤混合编辑", "上下文续画", "JSON自动修复", "验证后方案缓存", "语音交流模型V2"],
        "safety": ["Pydantic强校验", "颜色和坐标Guardrails", "操作数量上限", "账号限流"],
    }


def _issue_auth_response(user: User) -> AuthResponse:
    token = sign_token(
        {"sub": user.id, "username": user.username, "role": user.role},
        settings.auth_secret_key,
        settings.auth_token_expire_hours,
    )
    redirect_to = "/admin/dashboard" if user.role == "admin" else "/workspace"
    return AuthResponse(token=token, user=UserRead.model_validate(user), redirect_to=redirect_to)


@app.post("/api/register", response_model=AuthResponse)
async def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where((User.username == payload.username) | (User.email == payload.email)))
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password, settings.password_hash_iterations),
        role="user",
        is_active=True,
        is_banned=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="注册失败，用户名或邮箱重复") from exc
    db.refresh(user)
    return _issue_auth_response(user)


def _authenticate_login(payload: LoginRequest, db: Session, expected_role: str | None = None) -> AuthResponse:
    account = payload.username.strip()
    user = db.scalar(select(User).where((User.username == account) | (User.email == account)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if expected_role and user.role != expected_role:
        if expected_role == "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该账号不是管理员账号")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员账号请从管理员入口登录")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁，请联系管理员")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号不可用")
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue_auth_response(user)


@app.post("/api/login", response_model=AuthResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """兼容旧客户端：按账号角色自动跳转。"""
    return _authenticate_login(payload, db)


@app.post("/api/login/user", response_model=AuthResponse)
async def login_user_portal(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return _authenticate_login(payload, db, expected_role="user")


@app.post("/api/login/admin", response_model=AuthResponse)
async def login_admin_portal(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return _authenticate_login(payload, db, expected_role="admin")


@app.post("/api/demo-login", response_model=AuthResponse)
async def demo_login(request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    if not settings.competition_kiosk_mode:
        raise HTTPException(status_code=404, detail="评委演示模式未开启")
    client_host = request.client.host if request.client else ""
    allowed_hosts = {"127.0.0.1", "::1", "localhost", "testclient"}
    if settings.competition_demo_localhost_only and client_host not in allowed_hosts:
        raise HTTPException(status_code=403, detail="评委演示登录仅允许本机访问")
    user = ensure_competition_demo_user(db)
    if not user:
        raise HTTPException(status_code=503, detail="演示账号初始化失败")
    return _issue_auth_response(user)


@app.get("/api/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


def _record_usage(
    db: Session,
    *,
    user: User,
    text: str,
    latency_ms: int,
    success: bool,
    source: str,
    operation_count: int = 0,
    error_message: str = "",
) -> None:
    if success:
        user.usage_count += 1
        user.last_used_at = datetime.now(timezone.utc)
        db.add(user)
    db.add(
        UsageLog(
            user_id=user.id,
            username=user.username,
            request_preview=text[:200],
            latency_ms=max(0, latency_ms),
            success=success,
            source=source,
            operation_count=max(0, operation_count),
            error_message=error_message[:500],
        )
    )
    db.commit()


@app.post("/api/plan", response_model=PlanResponse)
async def create_plan(
    request: PlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanResponse:
    if not plan_limiter.allow(user.id):
        raise HTTPException(status_code=429, detail="语音绘图请求过于频繁，请稍后再试")

    server_started = time.perf_counter()
    if settings.local_edit_router_enabled:
        local_started = time.perf_counter()
        local_result = route_local_edit(request)
        if local_result:
            latency_ms = max(1, int((time.perf_counter() - local_started) * 1000))
            operation_count = len(local_result.plan.operations)
            _record_usage(
                db,
                user=user,
                text=request.text,
                latency_ms=latency_ms,
                success=True,
                source="local",
                operation_count=operation_count,
            )
            return PlanResponse(
                ok=True,
                source="local",
                route_reason=local_result.reason,
                model="local-edit-router-v1",
                latency_ms=latency_ms,
                server_total_ms=int((time.perf_counter() - server_started) * 1000),
                operation_count=operation_count,
                plan=local_result.plan,
                message="本地低延迟编辑成功",
            )

    try:
        result = await planner.plan(request)
        # 保持对早期测试桩/二次开发代码返回 (plan, latency_ms) 的兼容。
        if isinstance(result, tuple):
            plan, ai_latency_ms = result[:2]
            repair_attempted = False
            cache_hit = False
        else:
            plan = result.plan
            ai_latency_ms = result.latency_ms
            repair_attempted = result.repair_attempted
            cache_hit = result.cache_hit
        operation_count = len(plan.operations)
        source = "cache" if cache_hit else "ai"
        _record_usage(
            db,
            user=user,
            text=request.text,
            latency_ms=ai_latency_ms,
            success=True,
            source=source,
            operation_count=operation_count,
        )
        return PlanResponse(
            ok=True,
            source=source,
            route_reason=(
                "命中已验证方案缓存，跳过远程模型调用"
                if cache_hit
                else "复杂创作或无法确定性解析，交由 AI Drawing DSL 编译器处理"
            ),
            model="validated-plan-cache-v1" if cache_hit else settings.resolved_model,
            latency_ms=ai_latency_ms,
            server_total_ms=int((time.perf_counter() - server_started) * 1000),
            repair_attempted=repair_attempted,
            cache_hit=cache_hit,
            operation_count=operation_count,
            plan=plan,
            message="缓存方案命中" if cache_hit else "AI 规划成功",
        )
    except AIConfigurationError as exc:
        _record_usage(
            db, user=user, text=request.text, latency_ms=0, success=False, source="ai", error_message=str(exc)
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIPlanningError as exc:
        _record_usage(
            db, user=user, text=request.text, latency_ms=0, success=False, source="ai", error_message=str(exc)
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/voice-chat-v2", response_model=VoiceChatResponse)
async def voice_chat(
    payload: VoiceChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceChatResponse:
    started = time.perf_counter()
    try:
        result = await voice_chat_v2.chat(payload)
        _record_usage(
            db,
            user=user,
            text=payload.text,
            latency_ms=result.latency_ms,
            success=True,
            source="voice_v2",
            operation_count=0,
        )
        return result
    except AIConfigurationError as exc:
        _record_usage(db, user=user, text=payload.text, latency_ms=0, success=False, source="voice_v2", error_message=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIPlanningError as exc:
        _record_usage(
            db,
            user=user,
            text=payload.text,
            latency_ms=int((time.perf_counter() - started) * 1000),
            success=False,
            source="voice_v2",
            error_message=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _artwork_to_read(artwork: Artwork) -> ArtworkRead:
    try:
        scene = ArtworkScene.model_validate(json.loads(artwork.scene_json))
    except Exception:
        scene = ArtworkScene()
    return ArtworkRead(
        id=artwork.id,
        title=artwork.title,
        scene=scene,
        object_count=artwork.object_count,
        created_at=artwork.created_at,
        updated_at=artwork.updated_at,
    )


@app.post("/api/artworks", response_model=ArtworkRead)
async def save_artwork(
    payload: ArtworkCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtworkRead:
    artwork = Artwork(
        user_id=user.id,
        username=user.username,
        title=payload.title,
        scene_json=payload.scene.model_dump_json(),
        object_count=len(payload.scene.objects),
    )
    db.add(artwork)
    db.commit()
    db.refresh(artwork)
    return _artwork_to_read(artwork)


@app.get("/api/artworks", response_model=ArtworkListResponse)
async def list_artworks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> ArtworkListResponse:
    items = list(
        db.scalars(
            select(Artwork).where(Artwork.user_id == user.id).order_by(desc(Artwork.created_at)).limit(limit)
        ).all()
    )
    return ArtworkListResponse(artworks=[_artwork_to_read(item) for item in items])


@app.get("/api/artworks/latest", response_model=ArtworkRead)
async def latest_artwork(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtworkRead:
    artwork = db.scalar(
        select(Artwork).where(Artwork.user_id == user.id).order_by(desc(Artwork.created_at)).limit(1)
    )
    if not artwork:
        raise HTTPException(status_code=404, detail="还没有保存过作品")
    return _artwork_to_read(artwork)


@app.get("/api/admin/users", response_model=AdminUsersResponse)
async def admin_users(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> AdminUsersResponse:
    users = list(db.scalars(select(User).order_by(desc(User.created_at)).limit(limit)).all())
    return AdminUsersResponse(users=[UserRead.model_validate(item) for item in users])


@app.get("/api/admin/summary", response_model=AdminSummary)
async def admin_summary(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> AdminSummary:
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    banned_users = db.scalar(select(func.count()).select_from(User).where(User.is_banned.is_(True))) or 0
    admin_users = db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
    total_usage_count = db.scalar(select(func.coalesce(func.sum(User.usage_count), 0))) or 0
    total_logs = db.scalar(select(func.count()).select_from(UsageLog)) or 0
    success_logs = db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.success.is_(True))) or 0
    average_latency = db.scalar(select(func.coalesce(func.avg(UsageLog.latency_ms), 0)).where(UsageLog.success.is_(True))) or 0
    local_route_count = db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.source == "local")) or 0
    ai_route_count = db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.source == "ai")) or 0
    cache_route_count = db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.source == "cache")) or 0
    voice_chat_route_count = db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.source == "voice_v2")) or 0
    total_artworks = db.scalar(select(func.count()).select_from(Artwork)) or 0
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    today_usage_count = db.scalar(
        select(func.count()).select_from(UsageLog).where(UsageLog.created_at >= today_start)
    ) or 0
    logs = list(db.scalars(select(UsageLog).order_by(desc(UsageLog.created_at)).limit(30)).all())
    return AdminSummary(
        total_users=int(total_users),
        banned_users=int(banned_users),
        admin_users=int(admin_users),
        total_usage_count=int(total_usage_count),
        today_usage_count=int(today_usage_count),
        total_artworks=int(total_artworks),
        success_rate=round((int(success_logs) / int(total_logs) * 100) if total_logs else 0, 1),
        average_latency_ms=int(float(average_latency)),
        local_route_count=int(local_route_count),
        ai_route_count=int(ai_route_count),
        cache_route_count=int(cache_route_count),
        voice_chat_route_count=int(voice_chat_route_count),
        recent_logs=[UsageLogRead.model_validate(item) for item in logs],
    )


@app.post("/api/admin/users/{user_id}/ban", response_model=UserRead)
async def set_user_ban(
    user_id: int,
    payload: ToggleBanRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> UserRead:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and payload.banned:
        raise HTTPException(status_code=400, detail="不能封禁管理员账号")
    user.is_banned = payload.banned
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)
