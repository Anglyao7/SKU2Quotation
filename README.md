# 智贸云

一个面向外贸团队的多租户商品、询盘与报价平台。公开端提供品牌首页和租户商品前台，企业工作台以固定 Excel 商品模版维护 SKU 商品库，并覆盖 AI 搜索、询盘匹配以及经人工确认的版本化报价。供应商资料作为独立能力保留，不再是商品导入的前置条件。

## 项目结构

```text
apps/
  api/    FastAPI、SQLAlchemy、Alembic、后台 Worker 与自动测试
  web/    React、TypeScript、Vite 与 Nginx
infra/
  images/minio/   固定版本的本地 MinIO 镜像
  production/     公网 Compose、Caddy、部署/回滚与备份恢复
docker-compose.yml
```

主要技术栈：Python 3.12、FastAPI、React 19、TypeScript、PostgreSQL 16、pgvector、Redis、RabbitMQ、S3-compatible object storage 与 ClamAV。

## 轻量本地开发

轻量模式不要求 Docker。API 默认使用 `apps/api/var/mercator.db`，启动时自动执行 Alembic 并初始化脱敏演示租户；文件存储、扫描、消息发布和图片特征使用明确的本地开发适配器。

启动 API：

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

另开终端启动 Web：

```bash
cd apps/web
npm ci
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

访问 <http://127.0.0.1:5173/>。本地与正式环境使用同一个账号密码登录界面，不再提供单独的开发演示入口。默认本地凭据为：

| 本地角色 | 账号 / 邮箱 | 密码 | 租户 |
|---|---|---|---|
| Company Owner / Platform Admin | `owner` / `owner@local.aitradecloud.invalid` | `zhimaoyun123` | `Local Demo Company`（slug：`demo`） |

可以通过 `.env` 中的 `LOCAL_LOGIN_ACCOUNT`、`LOCAL_LOGIN_EMAIL`、`LOCAL_LOGIN_PHONE` 和 `LOCAL_LOGIN_PASSWORD` 调整本地凭据。该身份和本地密钥只用于开发，不能用于 Staging 或 Production。

## 完整 Docker Compose

完整模式会启动 PostgreSQL + pgvector、Redis、RabbitMQ、MinIO、ClamAV、API、文件 Worker、Outbox Relay、产品事件消费者和 Web。启动过程会自动创建隔离数据库角色、执行 Alembic、应用运行权限、创建对象桶和消息拓扑，并初始化演示数据。

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

首次构建 MinIO 并下载 ClamAV 病毒库可能耗时较长。默认端点：

| 服务 | 地址 |
|---|---|
| Web | <http://127.0.0.1:5173/> |
| API / OpenAPI | <http://127.0.0.1:8000/docs> |
| API readiness | <http://127.0.0.1:8000/api/v1/health/ready> |
| RabbitMQ 管理端 | <http://127.0.0.1:15672/> |
| MinIO Console | <http://127.0.0.1:59001/> |

若修改 `ATC_API_PORT`，也要把 `.env` 中的 `PUBLIC_BASE_URL` 改成同一个浏览器可达端口，确保报价下载链接有效。

所有宿主机端口只绑定 `127.0.0.1`。PostgreSQL、Redis、RabbitMQ、MinIO 与 ClamAV 位于内部数据网络；本配置仅用于 Local/CI，不是生产部署方案。

公网正式环境不要直接修改本地 Compose。域名、HTTPS、自托管 OIDC、
最小暴露面、不可变提交部署、回滚和灾备步骤见
[DEPLOYMENT.md](./DEPLOYMENT.md)。

停止并保留数据：

```bash
docker compose down
```

只有确认可以永久删除全部本地数据库、对象、队列和缓存后，才执行：

```bash
docker compose down --volumes
```

## 页面与接口

主要 Web 路由：

- `/`：品牌首页
- `/login`：统一账号密码登录入口
- `/:tenantSlug`：租户商品前台，例如 `/demo`
- `/console/tenants`：平台管理员的商家创建、查看与启停
- `/console/dashboard`：企业仪表盘
- `/console/products`：SKU 商品库与固定 Excel 模版导入
- `/console/products/categories`：一级、二级商品分类管理
- `/console/ai-search`：AI 产品搜索
- `/console/inquiries`：询盘匹配工作台
- `/console/quotes`：报价列表、详情、修订与审批
- `/console/system/permissions`：权限查看

当前 Demo 的商品闭环为：下载固定商品模版 → 填写全部 SKU → 在商品库上传 XLSX → 系统按商品型号更新 SKU、公开价、描述、图片及可选供应商 → 商品发布到商家前台 → 选购后生成报价草稿。供应商列可以留空；填写时会按名称复用或创建供应商，并将 SKU 关联到进销存。商品价格可以留空，系统会按 `0.00` 保存并正常发布。供应商及采购成本不会暴露到客户目录。

平台管理员创建的新商家会立即获得独立租户和空商品前台，但不会自动伪造商家成员。商家成员邀请与首次 Owner 分配属于后续账号开通流程；在完成该流程前，平台管理员仍可从 `/console/tenants` 管理商家状态。

核心 API 使用 `/api/v1`。为现有商品前台和报价下载保留以下兼容接口：

- `GET /api/store/{tenant_slug}`
- `GET /api/store/{tenant_slug}/skus`
- `GET /api/store/{tenant_slug}/skus/{sku_id}`
- `POST /api/store/{tenant_slug}/quotes`
- `GET /api/quotes/{quote_id}/pdf`（下载凭证放在 `X-Quote-Download-Token` 请求头）
- `GET /api/quotes/{quote_id}/xlsx`（下载凭证放在 `X-Quote-Download-Token` 请求头）

报价、价格、产品发布和对客图片均保留人工确认点；兼容商品前台创建的是待确认报价草稿，不会绕过审批。

## 验证

API 与架构测试：

```bash
cd apps/api
.venv/bin/python -m pytest -q
```

Web 构建：

```bash
cd apps/web
npm ci
npm run lint --if-present
npm run build
```

安装 Docker 的环境还应验证完整模型：

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

真实供应商、客户、产品、询盘、价格和上传原件不得提交到代码仓库，也不得复制到 Local/CI 的公开产物中。
