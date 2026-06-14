# AI 纯语音绘图工具 · 竞赛增强版 4.3.1

面向“题目二：AI 语音绘图工具”的完整参赛工程。完成首次浏览器麦克风授权后，用户可仅通过语音完成创作、编辑、中断、撤销、保存、恢复和系统自检。

## 竞赛亮点

新增：**语音交流模型 V2**。在不切出应用的情况下，用户可说“进入交流模式”切换到语音交流版本 2，保持 3 秒静默后自动得到自然语言回复；说“退出交流模式”即可返回绘图模式。


1. **自适应 3 秒静默判定**：Web Audio VAD 与语音识别结果双通道判断说话状态，并使用版本锁避免旧计时器误提交。
2. **更稳健的语音理解**：综合多个识别候选、浏览器置信度和绘图领域词进行候选排序，过滤“嗯、啊、那个”等低信息量噪声及重复片段。
3. **三路执行架构**：高频编辑走本地毫秒级路由；重复复杂任务命中已验证方案缓存；新复杂创作交给 AI。
4. **复杂指令拆解**：一句话可拆解成多个连续操作，并支持“最左边、第二个、最大的、所有”等同类对象消歧。
5. **结构化 Drawing DSL**：AI 不能输出任意代码，只能输出受 Pydantic 与 Guardrails 约束的绘图计划。
6. **AI 自动修复与连接池**：模型 JSON 校验失败会自动修复；后端复用 HTTP 连接并对 429/5xx 和网络抖动进行有限重试。
7. **事务式执行与回滚**：停止、超时、DSL 异常或网络失败都会恢复任务开始前的画面，不留下半成品。
8. **崩溃恢复**：每次成功绘制、撤销、重做和清空后自动保存本机恢复点，刷新页面后可恢复现场；恢复数据按用户隔离。
9. **赛前系统自检**：语音命令“系统自检”可检查浏览器语音能力、麦克风、后端、数据库、AI 配置和本地路由。
10. **工程完整性**：注册登录、MySQL/SQLite、管理员封禁、作品管理、使用统计、Docker、自动化测试和比赛文档齐全。

## 语音流程

```text
说“开始”
→ 自由描述画面或编辑需求
→ 连续静默 3 秒
→ 系统自动选择本地路由 / 验证缓存 / AI 复杂规划
→ Drawing DSL 校验与安全清洗
→ Canvas 逐步执行
→ 继续说“开始”进行下一轮编辑
```

复杂创作示例：

```text
开始，画一幅夜晚海边，月亮倒映在海面，远处有灯塔和三只海鸥
```

低延迟编辑示例：

```text
开始，把月亮向右移动八十像素，然后把最左边的云朵变成粉色
```

## 支持的纯语音控制

- 开始、立即绘图、停止；
- 撤销、重做、清空画布、新建画布；
- 保存图片、保存作品、打开上次作品、我的作品；
- 重复上次描述、朗读状态、语音帮助；
- 系统自检、恢复现场；
- 加快绘制、减慢绘制；
- 停止监听、继续监听。

## 快速启动

### 本地 SQLite

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

修改 `.env`：

```env
AI_API_KEY=你的七牛云APIKey
DATABASE_URL=sqlite:///./data/app.db
AUTH_SECRET_KEY=至少32位随机字符串
INIT_ADMIN_PASSWORD=管理员强密码
```

启动：

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000`。

### Docker + MySQL

```bash
cp .env.example .env
# 填写 .env 中所有 replace_ 开头的占位值
docker compose up --build
```

宿主机访问 MySQL 请连接 `127.0.0.1:3307`。


## 比赛现场模式

```bat
scripts\start_competition_kiosk.bat
```

该模式仅允许本机自动登录演示账号。公开部署必须保持：

```env
COMPETITION_KIOSK_MODE=false
```

进入工作台后可直接说：

```text
系统自检
```

确认麦克风、浏览器语音识别、后端、数据库和 AI 配置均已就绪。

## 测试与基准

```bash
pytest -q
python benchmarks/evaluate_command_router.py
```

当前自动化测试：**25 项通过**，并增加了语音交流 V2 与 MySQL 3307 宿主机端口配置。

离线本地路由基准：**19/19 样例正确分类或拆解**；本次构建中位解析耗时约 **0.102 ms**，P95 约 **0.216 ms**。该数据只衡量文本进入本地路由后的开销，不代表真实语音识别或端到端网络延迟。

## 文档

- `docs/DESIGN.md`：比赛要求的完整设计文档；
- `docs/JUDGING_MAPPING.md`：评分点与实现证据映射；
- `docs/DEMO_SCRIPT.md`：3 分钟 / 5 分钟答辩演示脚本；
- `docs/BENCHMARK_RESULTS.md`：离线路由基准；
- `docs/RELIABILITY.md`：比赛现场稳定性与故障恢复说明；
- `docs/SECURITY.md`：密钥与部署安全；
- `docs/PR_PROGRESS_TEMPLATE.md`：Pull Request 描述模板。

## 安全要求

- `.env` 已加入 `.gitignore`，不要提交真实 API Key、数据库密码或管理员密码；
- 公开仓库只提交 `.env.example` 占位模板；
- 若真实 Key 曾出现在聊天、截图、Git 历史或压缩包中，应立即在七牛云控制台重置；
- 公开部署必须关闭评委演示模式、限制 CORS，并启用 HTTPS。


## 4.3 多页面产品结构

- `/`：产品落地页
- `/login`：用户登录（可通过选项卡切换管理员登录）
- `/register`：独立注册页面
- `/workspace`：用户语音绘图工作台
- `/admin/login`：管理员独立入口，默认打开管理员选项卡
- `/admin/dashboard`：侧边栏式管理后台

用户和管理员登录使用独立的角色校验接口：`/api/login/user` 与 `/api/login/admin`。旧版 `/api/login` 保留兼容。

## MySQL 1045 错误修复

如果日志出现 `Access denied for user`，请查看 [`docs/MYSQL_1045_FIX.md`](docs/MYSQL_1045_FIX.md)。4.3.1 已改用 Docker 命名卷，并统一应用与数据库的凭据来源。宿主机端口仍为 `3307`，容器内部使用 `mysql:3306`。
