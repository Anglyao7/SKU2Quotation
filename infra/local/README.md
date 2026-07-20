# Local infrastructure

本目录保留本地依赖配置与兼容性契约；项目的唯一日常启动入口是仓库根目录的 `docker-compose.yml` 和 `.env.example`。

从仓库根目录运行：

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

验证关键端点：

```bash
curl --fail http://127.0.0.1:8000/api/v1/health/ready
curl --fail http://127.0.0.1:5173/
docker compose logs db-bootstrap db-migrate db-grants dependency-bootstrap
```

停止服务并保留数据：

```bash
docker compose down
```

`docker compose down --volumes` 会永久删除本地 PostgreSQL、对象、消息和缓存数据，仅在确认无需恢复后执行。示例凭据只适用于本地开发，不能用于 Staging 或 Production。
