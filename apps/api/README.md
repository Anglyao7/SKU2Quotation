# 智贸云 API

当前数据库实施状态：**Architecture Conformance Gate ACG-001 至 ACG-010 已完成；Vision/Image Embedding 与 Inquiry → Matching → Human-confirmed Quotation 闭环已实现。**

## Backend Module Boundaries

当前核心工作区读取接口：

- `GET /api/v1/dashboard`
- `GET /api/v1/supplier-profiles`
- `GET /api/v1/supplier-profiles/{supplier_id}`
- `GET /api/v1/quotations/{quotation_id}`
- `POST /api/v1/quotations/{quotation_id}/revisions`

报价 Revision 只创建不可变新版本，必须提供 `expected_version` 和修改原因；它不会覆盖已审批或已发送版本，也不会跳过人工审批。

`app/main.py` 是纯 Composition Root，只负责基础设施初始化、中间件和 Router 装配。依赖方向固定为：

```text
Router → Use Case → Domain / Repository → SQLAlchemy
```

- `app/routers/`：HTTP schema、依赖、状态码和错误映射。
- `app/use_cases/`：业务编排与事务边界。
- `app/domain/`：不依赖 FastAPI/SQLAlchemy 的领域错误与规则。
- `app/repositories/`：SQLAlchemy 持久化查询。
- `tests/test_architecture.py`：持续检查 Composition Root 行数、跨层依赖和公开路径兼容性。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

API 文档：`http://127.0.0.1:8000/docs`

Web 认证壳层使用内存 Access Token、HttpOnly Refresh Cookie 和 Session-scoped CSRF Token。刷新页面会旋转 Refresh Token 并恢复可信 Session；旧 LocalStorage Access Token 会被清除。所有环境统一通过账号密码接口登录：开发环境由仅限非生产的本地身份适配器校验，Staging/Production 的账号、邮箱或手机号与密码由 Keycloak 校验，否则启动保持 fail-closed。

工作区认证接口：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `PUT /api/v1/auth/password`
- `GET /api/v1/auth/memberships`
- `POST /api/v1/auth/tenant-context`
- `GET /api/v1/me`
- `GET /api/v1/me/permissions`

本地默认使用 `var/mercator.db`。SQLite 在启动时自动执行 Alembic migration，并创建幂等 local demo tenant、Owner/RBAC 和原有 demo suppliers。

## PostgreSQL 16+

```powershell
$env:DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/ai_trade_cloud'
$env:AUTO_MIGRATE='false'
$env:SEED_DEMO_DATA='false'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

生产环境默认不会在 API 启动时执行 DDL；Migration 应作为独立部署 Job 运行。`scripts/seed_phase1.py` 只用于 local/test 初始化，不得在生产创建演示租户。

RLS 所需的事务上下文由 `app.database.set_request_context()` 设置：

- `app.current_organization_id`
- `app.current_tenant_id`
- `app.current_user_id`

无 context 时 PostgreSQL RLS 默认拒绝访问受保护表。业务应用和 Worker 角色不得是 superuser、表 owner 或具有 `BYPASSRLS`。身份仓储角色是明确例外：登录发生在可信租户上下文建立之前，因此它是非超级用户 + `BYPASSRLS`，但只获五张身份/Session 表的极窄权限，读取业务表必须被数据库拒绝。

## Local Compose

仓库根目录的 `infra/local/compose.yaml` 提供 PostgreSQL + pgvector、Redis、RabbitMQ、MinIO、ClamAV、API、Worker 和 Web 的可重复本地基线。它会执行角色引导、Alembic、runtime grants、bucket versioning 和 RabbitMQ quorum/DLQ 初始化；详细命令见 [`infra/local/README.md`](../../infra/local/README.md)。

## Phase 1–4A-1C Schema

- `organizations`
- `tenants`
- `users`
- `memberships`
- `roles`
- `permissions`
- `role_permissions`
- `membership_roles`
- `auth_sessions`
- `auth_refresh_tokens`
- `media_objects`
- `worker_jobs`
- `product_categories`
- `products`
- `product_images`
- `product_attributes`
- `suppliers`
- `supplier_products`
- `supplier_score`
- `ai_provider_routes`
- `ai_tasks`
- `ai_source_evidence`
- `knowledge_documents`
- `knowledge_chunks`
- `embeddings`
- `ai_runs`
- `ai_task_steps`
- `product_field_candidates`
- `product_candidate_decisions`
- `product_versions`
- `outbox_events`
- `inbox_events`
- `skus`
- `attribute_definitions`
- `supplier_prices`
- `product_audit_events`
- `vision_observations`
- `image_embeddings`
- `image_searches`
- `customers`
- `inquiries`
- `inquiry_items`
- `inquiry_match_results`
- `quotations`
- `quotation_versions`
- `quotation_items`
- `quotation_approvals`

Migration `20260718_0012` 新增可撤销服务端 Session、只保存 hash 的旋转 Refresh Token family，以及 Membership permission version。生产使用独立 `AUTH_DATABASE_URL`：业务角色必须为非 Owner、`NOBYPASSRLS`；Identity 角色必须非 superuser、仅获身份/Session 表权限，不得读取业务表。

Migration `20260718_0013` 新增 tenant-scoped `media_objects`、`worker_jobs` 以及 `source_files.security_status/media_object_id`。上传文件先写入 `tenants/{tenant_id}/quarantine/`，扫描为 CLEAN 后才提升至 `source/` 并交给解析器。生产使用 S3-compatible Adapter、ClamAV Adapter、`FILE_WORKER_INLINE=false` 和独立非 Owner、`NOBYPASSRLS` Worker 数据库角色；本地确定性扫描器在 production profile 下会拒绝启动。

Migration `20260718_0014` 为 `outbox_events` 增加 claim/lease、下一次执行、最大次数和 DEAD 状态，并创建 `inbox_events` 幂等消费回执。Relay 在业务事务之外发布，RabbitMQ 使用 durable topic exchange、persistent message、mandatory route 和 publisher confirms；发布成功后才标记 PUBLISHED。若进程在发布后、落库前崩溃，事件会重复投递，消费者以 `(tenant_id, consumer_name, event_id)` 去重。

Migration `20260718_0015` 创建 tenant-scoped `skus`、`attribute_definitions`、`supplier_prices` 与 `product_audit_events`，并为 Product Attribute 与 Supplier Product 增加类型化属性/SKU 引用。SKU 使用乐观版本；价格只追加历史；采购成本权限与普通 Product 查看权限分离；四张表均启用 PostgreSQL FORCE RLS。

Migrations `20260718_0016–0019` 创建受 APPROVED media gate 保护的 Vision Observation/Image Embedding/Image Search，以及 Customer/Inquiry/versioned Match/immutable Quotation/Approval 数据链；图片与文本匹配只产生候选，最终选品和报价决定由人工完成。所有新增业务表均为 tenant-scoped + FORCE RLS；临时查询图按 TTL 清理；Quotation 领域事件在同一事务写入通用 Outbox。

独立 Worker：

```powershell
$env:DATABASE_URL='postgresql+psycopg://worker_role@127.0.0.1:5432/ai_trade_cloud'
$env:FILE_SCANNER_PROFILE='clamav'
$env:FILE_WORKER_INLINE='false'
.\.venv\Scripts\python.exe scripts\run_file_worker.py --tenant-id <TENANT_UUID>
```

Outbox Relay 与 Product event consumer：

```powershell
$env:OUTBOX_PUBLISHER_PROFILE='rabbitmq'
$env:RABBITMQ_URL='amqp://user:password@rabbitmq:5672/%2F'
.\.venv\Scripts\python.exe scripts\run_outbox_relay.py --tenant-id <TENANT_UUID>
.\.venv\Scripts\python.exe scripts\run_product_event_consumer.py
```

认证接口：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `PUT /api/v1/auth/password`
- `POST /api/v1/auth/tenant-context`
- `GET /api/v1/me`
- `GET /api/v1/me/permissions`

生产不保存本地密码；浏览器通过同源 HTTPS 提交账号标识和密码，FastAPI 仅将凭据转交 Keycloak Direct Grant 校验，并验证返回令牌的签名、issuer、audience、subject 与已验证邮箱。自助改密还要求当前 Access Token、Session CSRF Token 和当前密码；新密码统一要求 8-128 位、至少一个英文字母和一个数字、不含空白，并且不能与当前密码或账号标识相同，符号允许但不强制。Keycloak confidential client 的 service account 仅授予 `realm-management/manage-users`，只按已验证 subject 执行用户会话注销与密码更新。成功后当前应用 Session 保留，其他应用 Session 与 Refresh Token 会被撤销。仓库中的 `local_fake` Adapter 只允许非生产 profile。Refresh Token 仅写 Secure/HttpOnly/SameSite Cookie，数据库只存 HMAC hash；Access Token 每次请求仍需回查 Session、ACTIVE Membership、Tenant 与 permission version。客户端提交的 tenant header 不作为授权根。

平台管理员先在“商家管理 → 邀请成员”登记邮箱和租户角色，再由受信任运维人员在生产服务器执行：

```bash
sudo ./infra/production/keycloak-provision-user.sh \
  owner@example.com "Merchant Owner"
```

包装脚本启动一个只加入 Keycloak 私有 `identity` 网络的一次性容器；
公网 `/admin*` 仍然保持关闭。Keycloak 管理员密码和初始用户密码只通过
无回显终端提示输入；脚本没有密码命令行参数，也不会把凭据交给业务 API、
环境变量或容器配置。初始密码直接保存为永久凭据；默认仍以
`emailVerified=false` 创建身份，并由 Keycloak SMTP 发送邮箱验证邮件。
SMTP 发信失败时身份保持未验证并允许安全重试。只有运维人员已完成线下
邮箱核验并留存证据时，才可显式使用 `--email-verified`。

生产启动导入只创建不存在的 Realm。后续发布由
`infra/production/keycloak-reconcile.sh` 通过私有 Admin API 对账受管 Realm
与 confidential client 字段，并验证 client secret；管理员凭据只经 stdin
传入一次性容器。对账还会绑定受控运营邮箱并调用 Keycloak SMTP 测试接口，
让错误的邮件连接或认证配置在应用切换前失败。这样域名、精确回调地址和
OIDC secret 的受控轮换不会依赖 Keycloak 对已存在 Realm 明确跳过的启动
导入行为。

`users` 是全局身份；一个 User 通过 Membership 加入多个 Tenant。Role 属于 Tenant，Permission 是平台级稳定键。关联表使用复合租户外键，防止跨租户 UUID 引用。

Phase 2 已把原有 `suppliers`、`source_files`、`import_jobs`、`review_items` 回填到固定 local Tenant，并增加 tenant-aware FK 和 RLS。旧 `SUP-*` ID 继续作为兼容主键，现有上传、解析、复核与报价接口不变。

Phase 3A 只创建 AI Task intent、Provider Route metadata 和 Source Evidence lineage；该阶段当时没有创建 `ai_runs`、`embeddings`、`knowledge_bases` 或任何 vector index，也没有 Agent、LLM/OCR Provider 调用。

Phase 3B 创建 `knowledge_documents`、`knowledge_chunks`、`embeddings`，使用 PostgreSQL pgvector、模型特定 partial HNSW index、租户复合 FK 和 RLS。产品投影只读取 ACTIVE 产品和 `CONFIRMED` 属性；默认 `atc-feature-hash` 是无网络、确定性的开发/测试适配器，不是生产语义模型。

Phase 4A-1A 创建 `ai_runs`、`ai_task_steps`、`product_field_candidates`。工作流只接受本地原生 XLSX 和 `FAKE` Provider，通过 `ai_source_evidence` 生成 `AI_SUGGESTED` Candidate Draft；候选表没有 `product_id`，流程不调用 Product、Embedding、OCR、Vision、LLM 或 Agent 写入路径。失败任务进入 `PARTIAL`，重试创建新 Run 并复用 Step checkpoint；相同输入重复执行直接返回已有结果。

Phase 4A-1B 将现有 `POST /api/v1/imports` 接入 `NATIVE` Product Intelligence Provider，支持 XLSX 与 CSV。CSV 支持 UTF-8、UTF-8 BOM、GB18030 和常见分隔符；候选 Evidence 精确到 Sheet/Cell。相同租户、供应商上下文、文件 hash 和 Parser Version 的重复上传复用 Task；临时文件不可用时进入 `PARTIAL`，文件恢复后创建新 Run 继续。Product 与 Embedding 不发生写入。

Phase 4A-1C 对 Candidate 执行版本化确定性标准化，并通过 `product.review` + `product.create/edit` 权限的显式人工决策才写入 Product、`CONFIRMED` Attribute 和 SupplierProduct。Candidate 本体保持 `AI_SUGGESTED`，查询 API 通过 `latest_decision` 返回当前审核结果。每次采用创建不可变 `product_versions` 快照和同事务 `product.committed` Outbox；Phase 3B Knowledge 投影在独立事务中幂等执行，失败不回滚已批准 Product。本阶段没有新增 Embedding 表/模型，也没有 OCR、Vision、LLM、自动分类或 Agent。

Phase 3B 新接口：

- `POST /api/v1/ai/knowledge/products/{product_id}/project`
- `POST /api/v1/ai/search/products`
- `GET /api/v1/ai/product-intelligence/tasks/{task_id}/candidates`
- `POST /api/v1/ai/product-intelligence/tasks/{task_id}/groups/{group_key}/approve`
- `POST /api/v1/ai/product-intelligence/tasks/{task_id}/groups/{group_key}/reject`

Hybrid Search V1 固定使用 `0.35 Keyword + 0.35 Semantic + 0.20 Attribute + 0.10 Supplier`，响应包含 score breakdown、证据引用、ranking version 和 degraded channels。

## Migration 与 Seed

```powershell
# 升级到当前 Phase head
.\.venv\Scripts\python.exe -m alembic upgrade head

# 检查 ORM 与 migration 是否漂移
.\.venv\Scripts\python.exe -m alembic check

# 仅 local/test：幂等初始化 Tenant、Owner、Role 和 Permission
.\.venv\Scripts\python.exe -m scripts.seed_phase1
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

自动测试覆盖 Phase 1.5 生命周期/软删除、自定义角色、Phase 2 schema scope、Phase 3A/3B、Phase 4A-1A/1B/1C、认证、文件安全 Worker、Outbox Relay、Product Center、Image Intelligence、Inquiry Matching、human-gated Quotation 和 R1-02 基础设施契约。默认完整套件为 `63 passed, 2 skipped, 1 known warning`；注入真实 PostgreSQL URL 后两项非 Owner app/worker RLS Gate 额外执行并通过。真实 PostgreSQL 清单为 44 张 tenant RLS 表，应用仓库的 384 维 pgvector `<=>` 查询亦已执行通过。

## 已有接口（保持兼容）

- `POST /api/v1/imports`
- `GET /api/v1/imports`
- `GET /api/v1/review-items`
- `PATCH /api/v1/review-items/{id}`
- `POST /api/v1/review-items/{id}/approve`
- `POST /api/v1/pricing/calculate`
- `POST /api/v1/ai/knowledge/products/{product_id}/project`
- `POST /api/v1/ai/search/products`
- `GET /api/v1/ai/product-intelligence/tasks/{task_id}/candidates`
- `POST /api/v1/ai/product-intelligence/tasks/{task_id}/groups/{group_key}/approve`
- `POST /api/v1/ai/product-intelligence/tasks/{task_id}/groups/{group_key}/reject`
- `POST /api/v1/product-images/{image_id}/intelligence`
- `POST /api/v1/image-searches`
- `POST /api/v1/customers`
- `POST /api/v1/inquiries`
- `GET /api/v1/inquiries/{inquiry_id}`
- `PATCH /api/v1/inquiry-items/{item_id}/confirm`
- `POST /api/v1/inquiries/{inquiry_id}/match`
- `POST /api/v1/inquiry-items/{item_id}/selection`
- `POST /api/v1/inquiries/{inquiry_id}/quotation`
- `GET /api/v1/quotations`
- `GET /api/v1/quotations/{quotation_id}`
- `POST /api/v1/quotations/{quotation_id}/decision`
