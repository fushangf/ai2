# 4.3.1 修复说明

- 修复旧 `data/mysql` 数据目录导致 `.env` 新密码不生效的问题；
- Docker MySQL 改用命名卷，旧目录原样保留；
- 应用容器与 MySQL 容器统一使用 `MYSQL_*` 配置；
- Docker 内部固定连接 `mysql:3306`，宿主机端口保持 `3307`；
- 数据库用户名、密码和库名自动 URL 编码；
- 新增 Windows/Linux Docker 启动与数据库重置脚本；
- 新增 MySQL 1045 专项排障文档。
