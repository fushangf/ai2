# MySQL 1045 登录失败修复说明

## 错误现象

应用容器启动时出现：

```text
pymysql.err.OperationalError: (1045, "Access denied for user 'voice_draw' ...")
```

这通常不是 `3307` 端口造成的。应用容器访问 MySQL 使用的是 Docker 内部地址 `mysql:3306`；`3307` 只用于宿主机连接数据库。

根因通常是旧版使用 `./data/mysql:/var/lib/mysql` 保存数据库。MySQL 只在数据目录第一次初始化时读取 `MYSQL_USER`、`MYSQL_PASSWORD` 和 `MYSQL_ROOT_PASSWORD`。之后即使修改 `.env`，旧数据目录中的账号密码也不会自动改变。

## 4.3.1 的修复

- 改用 Docker 命名卷 `mysql_data`，不再自动复用旧的 `./data/mysql`；
- 旧目录仍留在原位置作为备份，不会自动删除；
- 应用容器和 MySQL 容器统一读取同一组 `MYSQL_*`；
- Docker 内部固定使用 `mysql:3306`；
- 宿主机仍通过 `127.0.0.1:3307` 访问；
- 密码含 `@`、`:`、`/` 等字符时会自动进行 URL 编码。

## 推荐启动方式

Windows CMD：

```bat
copy .env.example .env
scripts\docker_start.bat
```

或手动执行：

```bat
docker compose down --remove-orphans
docker compose up --build
```

## 已经创建过错误的命名卷

需要重建数据库时运行：

```bat
scripts\docker_reset_mysql.bat
```

等价命令：

```bat
docker compose down -v --remove-orphans
docker compose up --build
```

该操作会删除当前项目的 Docker MySQL 命名卷，因此会清空该卷中的账号、作品和统计数据。旧版的 `data\mysql` 目录不会被这个脚本删除。

## 需要保留旧数据库

不要删除 `data\mysql`。先备份该目录，再使用旧数据库原来的 root 密码登录，并执行：

```sql
ALTER USER 'voice_draw'@'%' IDENTIFIED BY '与当前 .env 中 MYSQL_PASSWORD 完全相同的密码';
GRANT ALL PRIVILEGES ON ai_voice_draw.* TO 'voice_draw'@'%';
FLUSH PRIVILEGES;
```

如果不知道旧 root 密码，无法安全地在原数据目录中直接重置账号。建议保留旧目录作为备份，使用新命名卷启动系统。

## CMD 注释提示

Windows CMD 不能直接执行以 `#` 开头的说明行。只复制代码块中的命令，不要复制 `# 重新启动` 一类注释。
