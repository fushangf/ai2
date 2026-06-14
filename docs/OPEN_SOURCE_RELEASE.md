# 公开发布检查清单

发布前执行：

```bash
pytest -q
python benchmarks/evaluate_command_router.py
git status --short
git grep -nE "(sk-[A-Za-z0-9]{20,}|AI_API_KEY=.+[^_]$|MYSQL_PASSWORD=.+[^_]$)" -- . ':!docs/OPEN_SOURCE_RELEASE.md'
```

人工确认：

- [ ] `.env` 不在仓库；
- [ ] `data/*.db` 不在仓库；
- [ ] 无真实 API Key；
- [ ] 无真实账号密码；
- [ ] Docker Compose 使用环境变量，不写固定密码；
- [ ] `COMPETITION_KIOSK_MODE=false` 为公开默认值；
- [ ] README 明确首次麦克风授权限制；
- [ ] 测试、设计文档、许可证和 PR 描述齐全；
- [ ] 如历史出现过密钥，已经在服务商控制台重置并清理 Git 历史。
