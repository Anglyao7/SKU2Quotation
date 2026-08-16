# 智能客服开发设计

> 状态：v2.4 知识库内 AI 训练工作台与安全流式对话架构已实现 + 后续路线图
> 版本：2.4
> 日期：2026-08-14
> 规范来源：[客服 AI 运行契约 v2.4](./CUSTOMER_SUPPORT_AI_RUNTIME_CONTRACT.md)

## 0. 当前交付状态

本次已完成运行契约的首个可上线闭环（知识与证据基础、店铺级 SKU/文件 RAG、
启用/关闭、多语言、引用、人工接管与版本化行为训练），
数据库版本为 `20260816_0097`。当前实现入口如下：

- 平台配置中心：`/console/system/configuration`，集中配置翻译与 Embedding API。智能客服
  模型密钥不再出现在公共配置页，统一在对应智能体详情中维护。
- 智能体列表：`/console/agents`，仅平台管理员可进入；可创建多个平台智能体。每个智能体
  自动获得不可编辑、全局唯一的 8 位数字 ID，并可绑定一个或多个店铺。
- 智能体详情：`/console/agents/{agent_id}`，集中维护名称、启停、店铺绑定、回答策略、提示词
  和该智能体的 OpenAI-compatible API 配置。
- 知识库管理：`/console/agents/knowledge`，先选择已创建智能体，再统一上传企业知识文件或
  案例 JSON；企业资料按绑定店铺隔离处理，案例 JSON 解析为该智能体的训练草稿。知识库是
  独立实体，一个知识库只绑定一个智能体和一个店铺，一个智能体可以拥有多个知识库；文件
  上传、解析、批准、撤销、重建以及后续训练都以知识库为边界，运行时仍遵守 tenant 边界。
  列表页点击知识库后进入 `/console/agents/knowledge/:knowledgeBaseId` 详情页。
- AI 训练工作台：从知识库管理进入 `/console/agents/{agent_id}/training`，仅保留“案例训练”
  和“复用规则”。可人工增删改、导出，并通过“一键审批”统一批准和立即生效；页面不提供
  模型生成案例、总结规则、训练包导入、版本发布/回滚或跨智能体复制入口。
- 商家人工工作台：`/console/support`，商家成员只查看和处理本店客服会话、AI 回答及其
  客户可见引用；可以人工接管，但不能恢复 AI、管理知识或修改任何 AI 配置。
- 客户 Widget：按客户本次消息的实际语言回答，通过带请求头令牌的 SSE 实时显示处理状态并
  增量呈现已校验回答，同时显示 AI 身份和服务端引用；SKU 引用会按服务端产品 ID 读取当前
  店铺的公开商品，并展示可横向浏览的图片、名称、公开编码、价格和详情卡片；
  商品证据充分时给出带引用的店铺答案；无命中、低分或检索降级时仍由 AI 提供通用建议、
  无匹配说明或聚焦追问。语言、数字或引用校验失败时改发安全追问，不会因此自动转人工。

已经落地的关键边界：

1. SKU 客户知识只读取已发布商品资料；供应商名称、供应商标识、供应商 SKU 与供应商
   评分在向量化前排除，MOQ 保留。
2. 企业文件支持 PDF、DOCX、TXT、Markdown 和普通 JSON；写入 Cloudflare R2/S3-compatible
   对象存储后解析、分块和向量化，处理成功的版本会直接进入检索。
   `support-ai-training/v1` 案例 JSON 会在知识库入口被识别并导入训练草稿，不作为事实知识
   向量化。
3. 客户原文永久保留。语言启发式由生成模型二次确认；跨语言时仅扩展内部检索 query，
   SKU/型号等标识不翻译，最终回答必须与客户实际语言一致。客户 query 不写入商品翻译
   记忆，受控翻译结果只随对应 Run 保存。
4. Evidence 是不可混淆的快照，保存来源类型、版本、定位、摘录、哈希和分数；客户只看到
   回答正文实际引用到的编号。
5. 开发环境默认使用请求后的后台执行；标准生产环境使用已有 tenant worker 认领持久化
   任务，进程中断后的 `RUNNING` 任务会在租约过期后重试。已批准来源重新索引失败时继续
   服务上一个成功版本。
6. v1 不开放退款、取消订单、修改资料、任意 HTTP/SQL 等写工具。实时库存、认证订单与
   其他只读动态事实属于 Phase 5，不得由静态 RAG 猜测。
7. `organization` 表示客户企业，`tenant` 表示具体店铺。文件知识、SKU、提示词、阈值、
   启停和 Run 均按 `tenant_id` 隔离；复制功能只复制选定配置，不复制知识和业务数据。
8. 智能客服管理是平台职责。历史租户角色即使仍带有 `support.ai.*` 或 `knowledge.*`
   授权记录，服务端也会过滤并拒绝管理接口；前端隐藏入口不是安全边界。
9. 平台可以创建多个智能体，但单个店铺同一时间最多绑定一个智能体。智能体可复用于多个
   店铺；绑定或修改智能体策略时，服务端会同步该店铺的运行快照，解除绑定时自动停止 AI。
10. 知识库同时记录 `tenant_id` 与必填 `agent_id`；文件来源通过 `knowledge_base_id` 归属知识库。
    店铺更换智能体后，运行时只检索当前智能体下、当前店铺的知识库，旧智能体文件不会混入新
    智能体回答。
11. 纯问候、致谢和告别由高精度规则分流，回复仍调用智能体绑定的大模型。模型只能使用
    店铺名称、管理员批准的企业对客简介和服务范围；Run 保存资料哈希且不执行向量检索。
    混合业务问题继续走 RAG，模型失败或日限额触发时使用多语言安全兜底并保持 AI 接待。
12. 检索与回答决策已经解耦。客服商品检索复用现有 `hybrid_product_search` 的商品向量与
    混合排序，只允许当前已发布、有效、可对客商品进入候选，再重新加载公开字段构造证据；
    不再扫描“最近若干 chunk”，也不会把供应商字段放进客户上下文。
13. 回答统一使用 `ANSWER / CLARIFY / NO_MATCH / HANDOFF` 与
    `EVIDENCE / GENERAL_GUIDANCE` 两个正交维度。`0` 条证据、低检索分数、Embedding 降级、
    模型失败或验证失败都不具有接管权限；只有客户明确要求人工或确需人工执行/审核的事务
    才能产生 `HANDOFF`。
14. 编排器把商品推荐识别为独立的 `PRODUCT_RECOMMENDATION` 交互目标。省略型追问会继承
    最近一条实质客户主题；模型必须输出一个带 `recommended_citation` 的主推荐，最多补充一个
    备选，不能再平铺检索结果。首轮安全草稿只因引用商品过多失败时，以它选出的主商品和
    一个备选执行一次受限模型重写；生成模型仍失败但已有公开商品证据时，会发送明确标注在
    Run 中的 `RETRIEVAL_FALLBACK` 推荐，而不是对客户声称“没有结果”。
15. 人工训练与事实知识彻底分离。案例 JSON 只能从知识库导入，人工新增和导入内容默认都是
    草稿；一键审批会统一批准、发布不可变版本并同步绑定店铺。产品不调用模型 API 生成案例
    或总结规则。训练只指导回答策略，商品事实仍必须从当前店铺证据读取；每个 Run 保存训练
    版本、训练包哈希和实际命中的案例 ID。

主要实现文件为 `support_ai_models.py`、`support_ai_schemas.py`、
`services/support_ai_*`、`routers/support_ai.py`、`use_cases/support_ai.py` 和迁移
`20260809_0060_support_ai_configuration.py`、
`20260809_0061_tenant_module_entitlements.py`、
`20260809_0062_support_ai_store_profiles.py`、
`20260809_0063_support_ai_agents.py`、
`20260810_0070_support_ai_social_profiles.py` 与
`20260810_0072_knowledge_index_checkpoints.py` 与
`20260813_0083_support_ai_training.py`。后续章节同时保留长期目标；标为 Phase 5/6
的能力不属于本次 v1 自动回答范围。

## 1. 文档目的

本文把运行契约映射为当前 SKU2Quotation 项目的可实施架构、数据模型、模块边界、接口、
页面、测试和迭代顺序。后续智能客服开发以本文为主计划，以运行契约为强制验收标准。

运行契约回答“系统必须如何表现”；本文回答“在当前代码库中如何实现”。发生冲突时，
运行契约优先，修改设计不能隐式降低安全边界。

## 2. 已确定的设计决策

1. 第一版使用**单一客服编排器**执行每次回答，但平台可管理多个独立智能体；不提前建设
   智能体之间互相委派的多 Agent 网络。
2. SKU 和企业文件使用统一知识来源模型，但通过两条独立 ingestion pipeline 进入。
3. 继续使用 PostgreSQL、pgvector、现有 Embedding Provider 和混合检索基础。
4. 客户客服使用独立的字段白名单投影，不直接复用内部商品搜索结果。
5. 知识边界在 chunk/Embedding 之前执行，回答后脱敏不是主要防线。
6. 引用和 Evidence 是持久化业务数据，不由模型临时拼接。
7. 动态事实通过只读工具查询，不写入共享向量。
8. 生成模型通过 provider-neutral port 接入，不把 OpenAI、Azure 或其他厂商 SDK 写进
   `use_cases`。
9. 模型调用在后台任务中执行，访客发消息的 HTTP 请求不等待完整 AI 推理。
10. 店铺状态只允许启用/关闭；草稿评估和不发送验证属于平台发布流程，不是店铺状态。
11. 智能体配置与店铺运行快照分层：智能体详情是模型、提示词、阈值和店铺绑定的唯一管理
    入口；店铺只保存执行所需快照。知识库、启停、试跑和运行审计均只对平台管理员开放。
12. 安全社交意图使用确定性高精度路由，生成内容仍走店铺模型。企业对客简介与服务范围
    是独立、可审计的公开字段，不能用内部说明或自由提示词替代。
13. 检索层只返回证据与诊断信息，不决定是否接管；回答层即使收到空证据也必须调用生成
    模型。企业事实必须引用，通用建议必须显式使用 `GENERAL_GUIDANCE`。
14. 人工接管是窄授权动作，不是错误兜底。低置信度、无命中、Embedding/模型/引用故障
    默认发送多语言安全追问并保持 `AI_ACTIVE`。
15. 商品推荐是回答层决策，不是 Retriever 的另一种展示样式。有商品证据时回答层必须先选
    一个主商品并说明取舍；没有商品证据时才使用通用选择框架或聚焦追问。

## 3. 当前系统基线

### 3.1 可以直接复用

- [`services/knowledge.py`](../apps/api/app/services/knowledge.py)：商品 canonical payload、
  deterministic chunk、内容哈希、版本切换和批量预计算基础。
- [`knowledge_embedding_models.py`](../apps/api/app/knowledge_embedding_models.py)：
  `KnowledgeDocumentRow`、`KnowledgeChunkRow`、`EmbeddingRow` 和 pgvector 数据结构。
- [`services/embedding.py`](../apps/api/app/services/embedding.py)：本地确定性 Embedding 和
  OpenAI-compatible Embedding port/adapter。
- [`services/hybrid_search.py`](../apps/api/app/services/hybrid_search.py)：lexical/vector 候选、
  PostgreSQL 有界预选和现有排序基础。
- [`embedding_management_models.py`](../apps/api/app/embedding_management_models.py)：可观测
  索引任务和模型版本记录。商品向量化按批次原子提交向量与剩余商品断点，支持暂停、继续、
  临时失败续跑以及 API 服务重启后的断点恢复；继续任务不得重复处理已提交商品。
- [`support_models.py`](../apps/api/app/support_models.py)：前台会话、消息、翻译，以及已支持的
  `AI` sender type。
- [`use_cases/support.py`](../apps/api/app/use_cases/support.py)：访客/商家消息、租户解析和客服
  翻译流程。
- [`ai_data_models.py`](../apps/api/app/ai_data_models.py)：通用 `AITaskRow`、provider route 和
  source evidence 基础。
- [`file_security_models.py`](../apps/api/app/file_security_models.py) 与对象存储：
  私有文件、哈希、历史兼容状态及 Cloudflare R2/S3-compatible 存储能力。后台知识文件不再
  经过恶意内容扫描，完成格式解析与向量化后直接可用。
- 前端客服窗口和 [`SupportCenterPage.tsx`](../apps/web/src/core/pages/SupportCenterPage.tsx)：
  客户消息与人工客服工作台。

### 3.2 当前阻塞点

1. `KnowledgeDocumentRow` 被 check constraint 和 tenant FK 写死为 `PRODUCT`。
2. `KnowledgeChunkRow.chunk_type` 只允许五种商品 chunk，不能表达页、段落、表格和幻灯片。
3. 当前商品知识 document 固定为 `classification=INTERNAL`，没有客户 Agent 启用状态、审核
   状态和引用展示策略。
4. 当前 `hybrid_product_search` 直接关联 Product，并包含 supplier ranking signal；客服不能
   原样调用它。
5. 当前字段策略已移除供应商名称/编码/SKU/评分，但仍需按运行契约处理客户公开字段、原始
   供应商交期和多 MOQ 聚合。
6. `WorkerJobRow` 被约束为商品导入的 `FILE_SCAN_AND_PARSE`，且强依赖 source file/import job，
   不适合作为通用知识文件任务。
7. 客服消息没有 AI Run、claims、citations、evidence、模型版本和 validation 结果。
8. 会话只有 `OPEN/CLOSED`，没有 AI active、human active、suspended 等接管状态。
9. `PublicSupportWidgetResponse.ai_enabled` 当前固定为 `False`。
10. 只有 Embedding/翻译模型适配器，没有客服生成模型的结构化输出适配器。

## 4. 目标架构

```text
                         ┌──────────────────────────┐
Product/SKU change ─────>│ Customer Product Projector│
                         └────────────┬─────────────┘
                                      │
File upload -> R2 -> validate -> parse ┤
                                      ▼
                         Knowledge Source + Versions
                                      │
                             chunks + locators
                                      │
                         lexical index + pgvector
                                      │
Visitor message                        │
      │                                │
      ▼                                │
Support AI Task -> Query Planner -> Policy-filtered Hybrid Retriever
      │                                      │
      │                     evidence[] + retrieval diagnostics
      │                                      │
      └──────────────> Context/Evidence Builder
                                      │
                      Structured LLM decision (always called)
                                      │
                       Citation/Grounding/Safety Validator
                                      │
       ┌──────────────────┬───────────┴──────────┬──────────────────┐
       ▼                  ▼                      ▼                  ▼
 ANSWER + citation     CLARIFY             NO_MATCH          authorized HANDOFF
 or general advice   focused question   + next suggestion   human-only action
       │                  │                      │                  │
       └──────────────────┴────── Trace/Evaluation ────────────────┘
```

### 4.1 请求链路与索引链路分离

- 知识解析、chunk、Embedding 和版本激活走异步 ingestion job。
- 访客发消息先可靠保存，再创建幂等 AI Task。
- AI worker 只读取已经 `ACTIVE + APPROVED` 的知识版本。
- 新索引未完成时继续使用旧活动版本，不能让部分 chunk 对客户可见。

## 5. 后端模块设计

建议增加以下模块，保持 router -> use case -> service/port -> adapter 的现有方向：

```text
apps/api/app/
  knowledge_source_models.py
  support_ai_models.py
  support_ai_schemas.py
  routers/
    support_ai.py
    knowledge_sources.py
  use_cases/
    support_ai.py
    knowledge_sources.py
  services/
    support_ai/
      orchestrator.py
      policy.py
      query_planner.py
      retriever.py
      context_builder.py
      evidence.py
      answer_generator.py
      validators.py
      handoff.py
      tool_registry.py
    knowledge_ingestion/
      product_projector.py
      document_parser.py
      chunker.py
      projector.py
      lifecycle.py
  ports/
    chat_model.py
    knowledge_parser.py
    support_tool.py
  adapters/
    chat_model.py
    knowledge_parsers/
  workers/
    support_ai.py
    knowledge_ingestion.py
```

首轮不要求一次创建所有文件。模块应在对应阶段出现，禁止先生成空壳和未使用抽象。

### 5.1 `SupportAIOrchestrator`

编排器负责运行状态，不负责直接访问 ORM：

1. 加载租户 AI 设置、会话状态和触发消息。
2. 运行输入安全及是否允许 AI 接管的检查。
3. 构建去重后的受控最近上下文，生成原始/改写查询和 `interaction_goal`；省略型推荐继承
   最近实质客户主题，具体的新需求不继承旧主题。
4. 执行知识检索或只读工具并记录诊断；空结果仍继续进入回答决策。
5. 构建带 opaque evidence ID 的模型上下文。
6. 请求结构化回答动作和 grounding mode；推荐目标额外要求 `recommended_citation`、一个
   主推荐及最多一个备选。
7. 执行 citation、推荐决策契约、grounding、边界、PII、语言和重复校验。
8. 在同一事务中保存 Run 结果、evidence use、AI message 和引用。
9. 失败时执行有限重试或多语言安全追问；推荐目标已有 SKU 证据时使用可审计的检索兜底
   推荐；只有授权原因可以人工接管。

每一步产生可记录的 step result。不得把整个流程写成一个难以定位失败原因的函数。

### 5.2 `ChatModelPort`

首版 port 至少支持：

```python
class ChatModelPort(Protocol):
    identity: ChatModelIdentity

    def generate_structured(
        self,
        *,
        messages: list[ChatMessage],
        output_schema: dict[str, object],
        tools: list[ToolDefinition],
        timeout_seconds: float,
    ) -> ChatModelResult: ...
```

要求：

- Provider identity 至少记录 provider/name/version。
- 优先使用严格 Structured Output/JSON Schema；仍要在本地再次验证。
- OpenAI-compatible 网关可能忽略 `response_format`。适配器应在末尾追加明确 JSON-only
  契约；收到普通文本时只允许一次受限结构修复，修复结果仍须通过同一 Validator 链。
- Provider 错误只能返回安全错误码，不能写入密钥和完整第三方响应。
- Use case 不得知道 `/v1/responses`、Anthropic Messages 或厂商 SDK 类型。
- Provider route 使用现有 `AIProviderRouteRow`，新增 capability
  `CUSTOMER_SUPPORT_RESPONSE`，凭证继续使用 secret reference/加密配置，不进 Prompt。
- `AIProviderRouteRow.max_data_classification` 的约束需要加入 `CUSTOMER_APPROVED`，并按
  `PUBLIC < CUSTOMER_APPROVED < INTERNAL < CONFIDENTIAL < RESTRICTED` 执行发送上限校验。
- 测试提供 network-free fake adapter，可以精确模拟无效 JSON、伪造引用、超时和工具调用。

### 5.3 客服专用 Retriever

当前 `support_ai_retrieval.py` 提供独立客服 Retriever。它复用
`hybrid_product_search()` 的既有商品向量与混合排名，但绝不把搜索结果对象直接交给模型；
只使用排名后的商品 ID，从公共目录白名单重新加载客户安全事实并生成 Evidence：

- 强制 tenant、classification、approval、audience、status 和有效期过滤。
- 客服调用明确关闭共享检索的 supplier scoring，不查询或返回 supplier identity、supplier
  SKU、supplier score 或其他 supplier signal；客户上下文完全由公共目录重新投影。
- 分别获取 Product 与 File 候选，按配置控制每类配额。
- 先处理 SKU/商品编码、条码和精确名称，再进行语义召回。
- 关键词与属性均不命中时，使用独立的语义相似度门槛保留高相关候选，不能把乘过语义权重的
  混合总分再次当成语义阈值；客服侧使用语义支持度重新执行店铺配置阈值。
- 统一 rerank，并返回 `RetrievedEvidence`，而不是 UI Product result。
- 保留 document/chunk/source version/locator 和所有分数。
- 对冲突、低支持度、无结果和语义检索降级返回明确 diagnostics；允许 Evidence 为空，但
  编排器仍必须调用模型进入 `CLARIFY / NO_MATCH / GENERAL_GUIDANCE`。

建议把现有通用向量候选和 tokenization 下沉为私有公共函数，内部商品搜索与客服检索分别
维护自己的 field policy 和 ranking policy。

### 5.4 Validator 链

初始 Validator 顺序：

```text
SchemaValidator
  -> ConversationOwnershipValidator
  -> EvidenceReferenceValidator
  -> GroundingValidator
  -> SensitiveFieldValidator
  -> LinkValidator
  -> LocaleValidator
  -> DuplicationAndLoopValidator
```

Validator 返回稳定 code、可重试性和安全原因。模型不得决定是否跳过 Validator。

## 6. 数据模型

### 6.1 `knowledge_sources`：稳定来源身份

新增 `KnowledgeSourceRow`：

| 字段 | 说明 |
|---|---|
| `id`, `tenant_id` | 复合租户身份与 RLS 边界 |
| `source_kind` | `PRODUCT`、`FILE`、`MANUAL`、`FAQ` |
| `product_id` | PRODUCT 来源使用的 tenant-scoped FK，可空 |
| `source_key` | FILE/MANUAL 的稳定业务键 |
| `internal_title` | 后台真实标题 |
| `customer_citation_title` | 客户安全标题 |
| `locale` | 来源主要语言 |
| `classification` | 运行契约中的五级分类 |
| `customer_agent_enabled` | 客户 AI 是否可检索 |
| `staff_copilot_enabled` | 后台 Copilot 是否可检索 |
| `citation_mode` | `LINK/EXCERPT/LABEL/NONE` |
| `approval_status` | `DRAFT/APPROVED/REVOKED` |
| `effective_from/until` | 生效窗口 |
| `status` | `ACTIVE/ARCHIVED/DELETED` |
| `approved_by/approved_at` | 审核记录 |
| `record_version` | 乐观并发和审计版本 |

约束：

- PRODUCT 必须有 `product_id`；其他类型不得伪造 product FK。
- `customer_agent_enabled=true` 时只允许 `PUBLIC/CUSTOMER_APPROVED + APPROVED +
  citation_mode!=NONE`。
- 同一租户/商品只有一个稳定 PRODUCT source。
- 所有写操作必须带 tenant 条件；PostgreSQL 开启并强制 RLS。

### 6.2 `knowledge_documents`：不可变来源版本

保留现有表并迁移为通用版本表：

1. 新增 tenant-scoped `knowledge_source_id` FK。
2. 为当前商品 documents 回填一条 PRODUCT `knowledge_source`。
3. 增加可空 `media_object_id`、`parser_identifier/version`、`chunker_version`。
4. 删除 `source_entity_type='PRODUCT'` check 和直接 product composite FK。
5. classification check 增加 `CUSTOMER_APPROVED`。
6. 兼容期保留 `source_entity_type/id` 只读字段；完成迁移后再删除。
7. classification、citation 和权限在 document 中保存来源激活时的快照。
8. 继续使用“同一 source/locale 仅一个 ACTIVE version”的 partial unique index。

Document 仍保存 canonical normalized payload 和 content hash；原始文件二进制留在对象存储，
不得写入 PostgreSQL JSON。

### 6.3 `knowledge_chunks`

新增 `locator JSONB`，并扩展 chunk type：

```text
OVERVIEW, SPECIFICATIONS, FEATURES, MARKETS, SUPPLY,
SECTION, PARAGRAPH, FAQ, TABLE, SLIDE, SHEET_RANGE
```

`locator` 结构按来源类型由 schema 校验；`chunk_metadata` 只保存检索辅助信息，不能替代
locator。Embedding 表继续引用 chunk，不需要为文件另建一套向量表。

### 6.4 通用 AI Task 与客服 Run

复用 `AITaskRow` 保存幂等、风险、provider route、policy snapshot 和总体状态；新增一对一
`SupportAIRunRow` 保存客服领域信息：

| 字段组 | 内容 |
|---|---|
| 关联 | `tenant_id`、`ai_task_id`、conversation、trigger message、response message |
| 输入 | 原始 query、改写 query、locale、intent、上下文摘要哈希 |
| 店铺状态 | 当时的 `enabled_snapshot` 与单会话人工接管状态 |
| 版本 | runtime contract、field policy、retrieval、reranker、prompt、orchestrator |
| 模型 | 内部 provider/name/profile route snapshot；店铺接口仅返回 display model name |
| 输出 | decision、answer payload、validation result、handoff reason |
| 性能 | 各阶段延迟、input/output token、估算成本 |
| 交付结果 | `NONE/TEST_ONLY/MESSAGE_SENT/HANDED_OFF/DECLINED` |

`(tenant_id, trigger_message_id)` 必须唯一，保证一次访客消息最多生成一个 Run。

`AITaskRow.status` 是排队、运行、验证、成功/失败等任务生命周期的唯一状态源；
`SupportAIRunRow.delivery_result` 只表达客服领域的最终交付结果，避免维护两套会漂移的运行
状态。运行契约状态机由这两个字段确定性映射，不允许业务代码自由组合非法状态。

### 6.5 Evidence catalog 与 Run evidence use

现有 `AISourceEvidenceRow` 适合作为不可变来源证据目录，但需要：

- classification 增加 `CUSTOMER_APPROVED`。
- locator 增加 `CHUNK_SECTION`、`DOCUMENT_PARAGRAPH`、`TOOL_RESULT` 等类型。
- 不再依赖单一 `ai_task_id` 表示使用关系。

新增 `SupportAIEvidenceUseRow` 关联 Run 与 evidence catalog，并保存本次检索状态：

- query、candidate rank、lexical/vector/rerank/final score。
- selected、cited、citation order、claim IDs。
- safe excerpt、excerpt hash、customer title/citation mode/locator 快照。
- source/document/chunk version 快照。

同一来源证据可以被多个 Run 使用；每次 Run 的排序和客户显示快照彼此独立。

### 6.6 Tool calls

新增 `SupportAIToolCallRow`：

- `run_id`、tool name/version、status。
- 安全输入、input hash、幂等键。
- 安全输出、output hash、observed_at、数据记录版本。
- latency、attempts、safe error code/message。
- 是否需要确认、确认消息和确认时间（为未来写工具预留，v1 恒为 false）。

工具原始第三方响应不得直接持久化；只有满足审计需要的受控字段和哈希进入数据库。

### 6.7 会话和消息扩展

`StorefrontChatConversationRow` 增加：

- `automation_state`：`AI_ACTIVE`、`AI_SUSPENDED`、`HUMAN_ACTIVE`、`DISABLED`。
- `automation_suspended_at`、`automation_suspend_reason`。
- 可选 `last_ai_run_at`。

`StorefrontChatMessageRow` 增加可空 tenant-scoped `ai_run_id`，AI 消息必须唯一关联 Run。
公共与后台消息 response 增加结构化 `citations`，但普通访客/商家消息返回空数组。

### 6.8 租户 AI 设置

新增 `SupportAISettingsRow`：

- mode，是否启用。
- 自动回答主题 allowlist 和强制人工主题 denylist。
- 最大模型回合、最大重试、超时和日用量上限。
- Retriever 候选配额、支持度阈值和引用展示选项。
- 默认回答语言策略、品牌语气和安全失败文案。
- 当前已批准 Prompt/policy/provider route 版本。
- updated_by、record_version 和审计时间。

设置保存时执行 schema 校验；不能允许商家通过自由文本覆盖系统安全指令。

### 6.9 智能体训练案例、规则与版本

- `SupportAITrainingCaseRow` 保存人工或案例 JSON 导入的问答案例、期望动作、grounding 模式、
  行为说明、所需证据类型、禁用模式、来源店铺和审核状态。
- `SupportAITrainingRuleRow` 保存从多个案例归纳的可复用行为规则、适用意图、优先级、来源
  案例 ID 和审核状态；规则内容不得定义企业事实。
- `SupportAITrainingVersionRow` 保存一次发布的不可变案例/规则快照、编译 Prompt、内容哈希、
  发布说明和激活状态。发布或回滚会把快照同步至该智能体当前绑定店铺的 AI settings。
- `SupportAISettingsRow` 保存当前训练版本、编译 Prompt、训练包哈希与示例快照；
  `SupportAIRunRow` 再保存本次使用的版本与命中案例 ID，避免发布新版本改写在途或历史 Run。

案例检索只做轻量相关性选择，不把案例写入知识向量库。运行时明确标记案例为行为示例，
Validator 仍只承认当前 SKU/文件 Evidence 和受控 Tool result 为企业事实来源。

## 7. SKU 知识实现

### 7.1 投影器拆分

当前 `build_product_payload()` 应逐步拆为：

```text
load_product_projection_source()     # 读取租户内权威数据
apply_customer_product_policy()      # 显式字段 allowlist
build_customer_product_chunks()      # 只接收安全 DTO
project_knowledge_version()          # 通用版本/Embedding 生命周期
```

禁止把 ORM 对象或完整 supplier record 传给 chunk builder。安全 DTO 使用冻结 dataclass/
Pydantic schema，使新增 ORM 字段不会自动进入投影。

### 7.2 v1 字段

按照运行契约先实现：

- 商品/SKU 公开基本信息。
- 已确认并客户可见的属性。
- 标签、用途、认证和包装信息。
- 公开 MOQ；商品概览 chunk 汇总 MOQ，规格 chunk 保留 SKU 与 MOQ 的精确对应。多个值只能
  作为匿名化选项展示或要求客户明确 SKU，不能由模型猜测默认值。

明确排除 supplier identity/SKU/score、采购成本、内部备注和未确认字段。原始供应商
`lead_time_days` 从客户 RAG 移出；以后由“公开承诺交期”字段或实时工具提供。

### 7.3 更新事件

- 商品/SKU/属性/标签/公开 MOQ 变化触发对应 PRODUCT source 增量投影。
- 与客户字段无关的供应商评分变化不得触发客服 Embedding。
- 字段策略、chunker 或 Embedding 模型变化触发受控全量重建。
- Outbox consumer 失败可重试；新版本失败不切换活动 document。

## 8. 文件知识实现

### 8.1 上传

复用 `ObjectStoragePort` 和 `MediaObjectRow`，对象初始进入 `QUARANTINE`。建议对象键：

```text
tenants/{tenant_id}/knowledge/{source_id}/{sha256}/source/{safe_filename}
```

数据库和前端只使用 media ID/source ID；不保存可长期访问的签名 URL。

### 8.2 Ingestion job

新增专用 `KnowledgeIngestionJobRow`，不强行复用 import-only `WorkerJobRow`。字段至少包括：

- tenant/source/media/document IDs。
- mode：`NEW_VERSION/REINDEX/REPARSE`。
- stage：`SCANNING/PARSING/NORMALIZING/CHUNKING/EMBEDDING/VALIDATING/ACTIVATING`。
- status、attempt、lease、checkpoint、safe error。
- parser/chunker/Embedding 版本和进度计数。

同一 source 只允许一个活动 ingestion job；job 使用 DB lease，进程重启后可以安全接管。

### 8.3 Parser 路由

首批建议支持：

| 类型 | Parser 输出 |
|---|---|
| PDF | 页、标题、段落、表格；扫描页可选 OCR |
| DOCX | 标题层级、段落、列表和表格 |
| PPTX | 幻灯片、标题、文本块和表格 |
| XLSX | 工作表、命名表格和单元格范围 |
| TXT/Markdown | 标题、段落、列表和代码块 |
| JSON | 对象/数组内容和 JSONPath；案例 JSON 自动转入对应智能体训练草稿 |

每个 parser 返回统一 `ParsedDocument`，包括 blocks、locator、语言和 warnings。Parser 不直接
写数据库；projector 统一完成 canonical payload、chunk 和版本激活。

### 8.4 审核与激活

- 首次上传及新版本默认 `REVIEW_REQUIRED/DRAFT`。
- 后台预览解析结果、客户可见标题、分类、引用模式和抽样 chunk。
- 审核人点击发布后才可变为 `APPROVED + ACTIVE`。
- `CUSTOMER_APPROVED` 文件不能提供原文件下载，只能根据 citation mode 展示安全摘录/标签。

## 9. 回答运行流程

### 9.1 触发

`send_public_message()` 成功持久化访客消息后：

1. 读取租户 mode 和会话 automation state。
2. mode 不是 `OFF` 时，以 `support:{tenant}:{conversation}:{message}` 创建幂等 AITask。
3. 提交事务后通知 worker；接口立即返回访客消息。
4. Widget 建立带 `X-Support-Token` 的 fetch/SSE 通道；状态变化实时推送，断线时自动重连并
   用普通会话读取兜底，不再依赖 4 秒轮询。

模型调用不得发生在数据库事务或访客 HTTP 请求等待路径中。

### 9.2 Worker

```text
claim task
  -> verify conversation ownership
  -> build bounded context
  -> rewrite/classify
  -> retrieve and/or call read tool
  -> freeze evidence uses
  -> generate structured result
  -> validate
  -> recheck conversation/human ownership
  -> persist AI message + citations or handoff
```

最后一次 ownership check 防止模型运行期间人工已经回复，但 AI 仍追加一条自动回答。

### 9.3 安全流式链路

```text
模型 SSE -> 服务端累积结构化 JSON -> Validator 链 -> 原子落库
                                                    -> 客户 SSE 增量呈现
```

- `OpenAICompatibleChatGeneration.generate_json_stream()` 解析上游 `data:` 事件，记录
  `transport_mode=STREAM` 和 `first_delta_ms`；不支持流式的兼容网关显式降级到缓冲请求。
- 每次生成末尾追加 JSON-only 提醒；忽略 `response_format` 的普通文本响应进入一次
  `STREAM_REPAIR / BUFFERED_REPAIR`，而不是直接成为客户回答或通用固定兜底。
- 编排器只消费累积后的结构化结果。未经引用、数字、语言、MOQ 和敏感字段校验的原始模型
  token 不进入客户通道。
- `GET /api/store/{slug}/support/conversations/current/events` 使用请求头会话令牌，发送
  `conversation / message_start / message_delta / message_end`，设置 `X-Accel-Buffering: no`、
  `Cache-Control: no-transform` 和 `Content-Encoding: identity`，并每 12 秒发送心跳。
- AI 处理中以 250ms 读取会话快照，空闲时为 500ms；连接约 50 秒主动轮换，前端 750ms 后
  重连。消息 ID 用于去重，断线后以数据库中的完整消息恢复。
- 客户流只对已经落库的最终回答做快速分片：短回答每 8 个字符一段，长回答动态增大分片并
  最多发送 80 段，每段约 12ms，客户端呈现额外耗时上限约 1 秒。

### 9.4 店铺启停行为

- `关闭`：新客户消息不进入 AI 队列，知识和历史 Run 保留，人工客服不受影响。
- `启用`：有证据且通过阈值时发送带引用的企业事实；无证据或低置信度时发送通用建议、
  无匹配说明或聚焦追问并保持 AI 接待。启用不表示可以无依据断言企业事实。
- 测试实验室：无论店铺是否启用都可执行 `TEST_ONLY` Run，但绝不写入客户会话。
- 平台离线评估和不发送验证使用独立测试任务，不增加店铺状态枚举。

## 10. Tool 设计

### 10.1 第一批只读工具

```text
get_public_product_state(product_or_sku_code)
get_current_public_price(sku_id, optional_quantity, optional_currency)
get_current_availability(sku_id, optional_quantity)
get_customer_order_status(order_reference)  # 需要身份验证
handoff_to_human(reason, priority, summary)
```

MOQ 首版优先来自客户知识投影；若以后 MOQ 具有客户、数量梯度或时效性，再提升为工具。

### 10.2 Tool 注册表

每个 Tool 定义：

- 名称、版本、用途说明和适用 intent。
- strict input/output schema。
- required authentication/permission/risk level。
- timeout、retry、rate limit 和结果分类。
- 是否可以向客户展示输出字段。
- evidence renderer 和 failure/handoff policy。

模型只看到经过当前租户设置筛选后的少量工具。工具描述应清晰且互不重叠，避免 planner
因工具过多或语义相近而误选。

## 11. API 设计

以下为 v1 已落地接口；response schema 以 OpenAPI、Pydantic schema 和集成测试固化。

### 11.1 AI 设置与运行

```text
GET   /api/v1/system/ai-generation/settings
PUT   /api/v1/system/ai-generation/settings
GET   /api/v1/system/ai-generation/profiles
POST  /api/v1/system/ai-generation/profiles
PUT   /api/v1/system/ai-generation/profiles/{profile_id}
POST  /api/v1/system/ai-generation/profiles/{profile_id}/copy
GET   /api/v1/system/ai-generation/store-configurations
PUT   /api/v1/system/ai-generation/store-configurations/{tenant_id}/provider
POST  /api/v1/system/ai-generation/store-configurations/bulk-provider-bindings
POST  /api/v1/system/ai-generation/store-configurations/copy
GET   /api/v1/support/ai/settings?tenant_id={tenant_id}
PATCH /api/v1/support/ai/settings?tenant_id={tenant_id}
POST  /api/v1/support/ai/test-runs?tenant_id={tenant_id}
GET   /api/v1/support/ai/runs?tenant_id={tenant_id}
GET   /api/v1/support/ai/runs/{run_id}?tenant_id={tenant_id}
PATCH /api/v1/support/conversations/{conversation_id}/automation
```

以上生成模型、店铺 AI 设置、试跑与运行审计接口均只有平台管理员可以调用。API Key 使用
`SUPPORT_AI_SETTINGS_MASTER_KEY` 加密，平台读取接口只返回是否已配置和末四位提示，旧 Key
留空表示保持不变。配置保存不发起模型请求；可在“问答试跑”中验证完整业务链路。

店铺复制接口只复制明确勾选的模型绑定、策略和可选启停状态；不会复制文件知识、SKU、
会话或 Run。默认不复制启停状态，避免未验收店铺被批量开启。

### 11.2 知识来源

```text
GET    /api/v1/support/ai/knowledge/sources?tenant_id={tenant_id}
POST   /api/v1/support/ai/knowledge/sources/upload?tenant_id={tenant_id}
PATCH  /api/v1/support/ai/knowledge/sources/{source_id}?tenant_id={tenant_id}
POST   /api/v1/support/ai/knowledge/sources/{source_id}/approve?tenant_id={tenant_id}
POST   /api/v1/support/ai/knowledge/sources/{source_id}/reindex?tenant_id={tenant_id}
DELETE /api/v1/support/ai/knowledge/sources/{source_id}?tenant_id={tenant_id}

# Knowledge-base scoped management (the preferred contract)
GET    /api/v1/system/support-ai/agents/{agent_id}/knowledge-bases
POST   /api/v1/system/support-ai/agents/{agent_id}/knowledge-bases
PATCH  /api/v1/system/support-ai/knowledge-bases/{knowledge_base_id}?tenant_id={tenant_id}
GET    /api/v1/system/support-ai/knowledge-bases/{knowledge_base_id}/sources?tenant_id={tenant_id}
POST   /api/v1/system/support-ai/knowledge-bases/{knowledge_base_id}/sources/upload?tenant_id={tenant_id}
GET    /api/v1/support/ai/knowledge/jobs/{job_id}?tenant_id={tenant_id}
```

`DELETE` 在 v1 表示撤销，不物理删除历史来源；既有 Run/Evidence 仍可审计。文件上传沿用对象
存储和 media ID；大文件后续可增加预签名直传，不改变 source API。全部接口先验证平台
管理员身份，再切换到目标店铺 RLS 上下文。

### 11.3 AI 训练工作台

```text
GET    /api/v1/system/support-ai/agents/{agent_id}/training
POST   /api/v1/system/support-ai/agents/{agent_id}/training/cases
PUT    /api/v1/system/support-ai/agents/{agent_id}/training/cases/{case_id}
DELETE /api/v1/system/support-ai/agents/{agent_id}/training/cases/{case_id}
POST   /api/v1/system/support-ai/agents/{agent_id}/training/rules
PUT    /api/v1/system/support-ai/agents/{agent_id}/training/rules/{rule_id}
DELETE /api/v1/system/support-ai/agents/{agent_id}/training/rules/{rule_id}
POST   /api/v1/system/support-ai/agents/{agent_id}/training/approve-all
GET    /api/v1/system/support-ai/agents/{agent_id}/training/preview
POST   /api/v1/system/support-ai/agents/{agent_id}/training/publish
POST   /api/v1/system/support-ai/agents/{agent_id}/training/versions/{version_id}/activate
GET    /api/v1/system/support-ai/agents/{agent_id}/training/export
POST   /api/v1/system/support-ai/agents/{agent_id}/training/import
POST   /api/v1/system/support-ai/agents/{agent_id}/training/copy
```

所有训练接口仅限平台管理员。前端只从知识库开放训练入口，训练 JSON 的导入由知识库上传
流程调用 `training/import`；训练工作台不再显示单独导入、复制、预览、发布或版本回滚。
`approve-all` 会批准全部草稿，并在一次服务端流程中创建不可变版本、切换当前版本和同步
绑定店铺快照。`preview/publish/activate/copy` 继续作为兼容及运维接口，不属于日常页面流程。
产品不提供在线模型生成案例或总结规则的接口。

### 11.4 部署配置

店铺显式绑定的配置档案优先，其次是数据库中的平台默认档案；环境变量只作为未绑定店铺的
冷启动/灾备回退：

```text
SUPPORT_AI_SETTINGS_MASTER_KEY
SUPPORT_AI_ENABLED
SUPPORT_AI_BASE_URL
SUPPORT_AI_API_KEY
SUPPORT_AI_MODEL
SUPPORT_AI_MODEL_DISPLAY_NAME
SUPPORT_AI_TIMEOUT_SECONDS
SUPPORT_AI_MAX_OUTPUT_TOKENS
SUPPORT_AI_TEMPERATURE
SUPPORT_AI_WORKER_INLINE
SUPPORT_AI_STALE_JOB_SECONDS
```

标准生产 compose 将 `SUPPORT_AI_WORKER_INLINE=false`，由 `scripts.run_tenant_workers`
处理队列；compact 和开发环境默认为 `true`。文件对象沿用现有 `OBJECT_STORAGE_*` R2/S3
变量，向量模型沿用配置中心或 `TEXT_EMBEDDING_*`。

### 11.5 公共消息引用

现有公共 conversation/message 接口保持兼容，为消息增加：

```json
{
  "id": "message-id",
  "sender_type": "AI",
  "body": "这款产品的公开起订量为 100 件。[1]",
  "citations": [
    {
      "number": 1,
      "title": "6L 智能宠物喂食器 · 产品规格",
      "mode": "LINK",
      "url": "/store/.../products/...",
      "locator_label": "MOQ",
      "updated_at": "2026-08-09T00:00:00Z"
    }
  ]
}
```

URL 必须由服务端 allowlisted renderer 生成，不能直接使用模型输出或对象存储键。
回答中的 `[1]` 等显示编号也由服务端根据已验证的 claim/evidence 映射插入；模型返回的
编号文本不具有引用效力。

公共客户实时通道：

```text
GET /api/store/{tenant_slug}/support/conversations/current/events
X-Support-Token: <opaque session token>
Accept: text/event-stream
```

令牌不得作为 query parameter。SSE 只是已持久化会话的增量视图，不是第二份回答状态；重连
和普通 GET 返回的最终消息必须完全一致。

## 12. 权限与 RLS

数据库中保留以下历史权限码用于兼容既有审计记录，但它们不再向租户角色生效或开放委派：

```text
support.ai.manage
support.ai.inspect
support.ai.test
knowledge.manage
knowledge.approve
```

- `support.view/reply` 继续控制商家查看和回复本店会话；成功发送第一条人工回复时自动完成
  接管。
- `support.ai.*` 与 `knowledge.*` 不再是可委派的租户权限；只有平台管理员身份可以调用。
- 商家成员不能恢复单会话 AI 接待；人工接管优先且保持有效。
- 新表均启用 tenant RLS；平台管理员管理指定店铺时由服务端切换目标 RLS 上下文。

## 13. 前端设计

### 13.1 平台“智能客服管理”模块

`/console/support/ai` 由 `PlatformAdminGate` 保护，并提供目标店铺选择器，包含：

1. **概览**：当前店铺启停、模型展示名、索引健康、近期 Run、自动回答/转人工/失败趋势。
2. **知识来源**：SKU 索引、文件列表、分类、审核、版本、状态和错误。
3. **回答策略**：允许主题、强制人工主题、语言、品牌语气和安全失败文案。
4. **测试实验室**：输入真实问题，查看改写、候选证据、回答、引用和 Validator。
5. **回答检查**：按 Run 查看完整 evidence、工具、模型版本和人工修改。
6. **AI 训练工作台**：在知识库选择智能体后进入，只包含案例训练和复用规则；案例 JSON 在
   知识库导入，工作台支持人工增删改、导出和一键审批生效。

商家导航不显示该模块，直接访问也会被前后端同时拒绝。悬浮球展示设置继续属于个人中心；
人工会话继续属于客服管理，不与知识配置混在一起。

### 13.2 客户 Widget

- AI 消息显示清晰身份，不伪装成人工客服。
- 引用显示在对应回答下方，支持标题、定位、更新时间和安全预览。
- `LABEL` 引用不可点击到内部文件。
- 客户始终有“转人工”入口。
- AI 正在处理、需要补充信息、已转人工和暂时失败有不同状态。
- 不在客户端计算权限、证据有效性或构造来源 URL。

### 13.3 客服工作台

- 商家成员只能读取本店会话、客户可见 AI 回答与对应引用，并按客服权限人工回复。
- 商家发送第一条回复时接管正在自动处理的会话；仅查看、打开、领取会话或点击状态按钮
  都不能触发接管。只有平台管理员可以恢复 AI 接待。
- 不展示知识库清单、Prompt、阈值、模型/API 状态、试跑或内部 Run 决策细节。
- 人工消息不会自动进入知识库。
- AI 判断需要人工时，访客端显示“联系人工客服”确认操作；确认后才进入待处理队列。
- 后台全局顶栏铃铛展示当前店铺的待处理数量，新请求以气泡通知；点击通知
  直接打开目标会话。阅读不清零，人工回复、结束会话或恢复 AI 后才解决提醒。

## 14. 多语言策略

- 会话继续使用现有客服翻译基础；AI 生成前保留访客原文和 normalized query。
- 每次生成都根据最新访客消息计算 `required_response_language`，同时写入 system prompt 和
  结构化输入；回答正文和 `detected_language` 必须使用该语言，店铺 locale、历史消息、证据
  语言及企业语气提示均不得覆盖它。
- 短外语寒暄和短商品问句不得回退为店铺默认语言；服务端先识别常见词汇，生成模型
  再以最新访客原文为唯一权威进行复核。从寒暄、商品说明到追问和无匹配引导，所有
  对客句子都必须使用该语言，不得跟随中文知识库切换语言。
- Retriever 使用多语言 Embedding，或对检索 query 生成受控翻译；不得翻译 SKU/订单号。
- 首选与访客语言匹配的知识；缺失时可以跨语言检索并在回答阶段翻译。
- customer citation title 可以按 locale 提供翻译；没有翻译时回退企业默认语言。
- Evidence 始终指向原始来源版本，翻译后的摘录另存 hash 和 translator version。
- 商品语言包是前台展示缓存，不直接作为客服事实源；事实仍来自商品知识版本。

## 15. 安全实现

### 15.1 输入和来源

- 对用户输入、文件文本和工具输出使用明确的数据分隔，绝不拼进 system instruction。
- 文件 parser 删除脚本/宏执行能力，只读取静态内容。
- 只有对象存储中状态可用、格式受支持的 media object 才进入 parser。
- 来源审批与客户 Agent 启用是服务端写操作，需权限和审计。

### 15.2 工具

- tenant/auth context 由 server-side context 注入。
- 禁止 generic HTTP、generic SQL、filesystem 和 object-storage browser tool。
- 输出 DTO 只包含公开字段；完整 ORM 不进入模型。
- 未来写工具默认 require confirmation，并单独经过 tool input/output guardrail。

### 15.3 输出

- 拦截供应商、成本、内部备注、密钥形态和非 allowlisted URL。
- 数字和单位从 claim/evidence 进行一致性检查。
- 引用 renderer 不信任模型生成的 label/URL。
- Validator 结果和拒绝原因使用安全错误码，不把内部实现暴露给客户。

## 16. 测试策略

### 16.1 单元测试

- Customer product allowlist 和所有禁止字段哨兵测试。
- 每种文件 parser/chunker/locator fixture。
- query rewrite 对 SKU、数字、语言的保真。
- retrieval filter、source quotas、authority 和 conflict policy。
- structured output、citation 和 sensitive field validators。
- tool strict schema、tenant injection 和 safe output DTO。

### 16.2 数据库与集成测试

- 所有新表的 tenant composite FK、RLS 和跨租户失败测试。
- source 新版本原子激活、旧版本 stale、失败回滚。
- 一个 evidence catalog 被多个 Run 使用且快照互不污染。
- 一次 visitor message 只能创建一个 AITask/AI message。
- 人工在模型运行期间回复会取消自动发送。
- 文件撤销后退出新检索，但历史 Run 仍可审计。
- 商品推荐复用现有混合检索，只把当前公开商品事实写入 Evidence，供应商字段永不出现。
- “我不知道，你给我推荐一款”等追问继承上一轮实质客户主题；已经写明“大型犬玩具”等
  具体新主题时不得混入旧商品。
- “有什么适合骑行的装备”等场景选择问法必须识别为推荐；“主要用于骑行”等下一轮约束应
  继承推荐目标，并同时保留原主题和新增用途参与检索。
- 推荐模型输出必须包含正文实际使用的主商品引用且最多引用两个商品；只列候选、缺少主
  推荐或引用非 SKU 证据时触发推荐契约失败。
- Evidence 未出现 MOQ 时模型不得推断为“无起订量限制”；该断言由服务端按正文引用关联到
  具体商品证据校验，只有来源明确写明无最低订购量时才允许发送。
- 首轮已选出有效主商品但引用过多时，只允许一次双商品受限重写；Run 同时保存首轮与重写
  的 Prompt 哈希、验证结果和用量。
- 生成模型超时但已有 SKU 证据时返回带引用的检索兜底推荐，并在 Run 中保留失败原因；
  不能退化成“资料不足”或人工接管。
- 商品无命中、Embedding 降级、低分和模型验证失败均保持 `AI_ACTIVE` 并返回安全追问。
- 客户明确要求人工以及人工专属事务才会写入授权 `handoff_reason`。

### 16.3 Agent 合约测试

使用 FakeChatModel 固定返回：

- 正确回答和引用。
- 不存在/跨租户 evidence ID。
- 引用存在但 claim 不受支持。
- 内部字段泄漏。
- 无效 JSON、超长文本、错误语言和循环工具调用。
- 超时、限流和部分工具失败。
- 空 Evidence 下的 `CLARIFY / NO_MATCH / GENERAL_GUIDANCE`。
- 模型试图以 `NO_CUSTOMER_SAFE_EVIDENCE` 等未授权原因为由转人工。

### 16.4 离线评估

建立 `support_ai_eval_cases` fixture 或独立数据集，保存问题、用户画像、期望 decision、
必需/禁止 evidence、期望工具和关键事实。每次以下变化自动运行同一测试集：

- 模型或 Prompt。
- Embedding 或 chunker。
- Retriever 权重/阈值。
- 字段策略和知识 schema。
- Tool 描述/schema。

## 17. 可观测性与运营

### 17.1 指标

- 任务 queue wait、各 stage p50/p95、模型和工具错误率。
- 模型 `first_delta_ms`、生成完成耗时、回答落库到客户首分片耗时、SSE 重连率和缓冲降级率。
- retrieval no-result、low-support、conflict、citation validation failure。
- `ANSWER / CLARIFY / NO_MATCH / HANDOFF` 分布、grounding mode、无结果后继续解决率。
- 测试集 correctness、线上 resolution/handoff/repeat contact、误接管率和人工接管率。
- 每租户 Token、成本、日限额和 provider 限流。
- 每来源命中、解决、失败和内容缺口。

### 17.2 告警与开关

- 跨租户或敏感字段 guardrail 命中立即产生安全告警。
- 引用验证失败、模型失败和 tool failure 持续升高时告警并按店铺策略关闭智能客服；不得
  把系统性故障逐个自动转成人工会话，避免人工队列雪崩。
- 支持平台 API 档案停用、店铺启停和单会话 suspend 三层停止方式。
- Provider route、Prompt、策略和 Agent 版本可快速回退到上一个已批准版本。

## 18. 实施阶段

阶段按依赖顺序推进，不以日期绑定。每一阶段完成验收后才进入下一阶段。

### Phase 0：契约与基线（已完成）

- 运行契约和开发设计进入文档索引。
- 当前商品知识禁止字段测试通过。
- 建立首批真实客服评估问题和敏感字段哨兵集合。

### Phase 1：知识与证据基础（v1 已完成）

- 新增 knowledge source、通用 document/chunk migration 和 RLS。
- 新增 AI settings、SupportAIRun、EvidenceUse、会话 automation state。
- 建立客户商品安全 DTO/投影器，移出供应商交期和内部字段。
- 建立 source approval、version 和 citation renderer。
- 暂不接入真实生成模型。

验收：边界、版本、跨租户、引用 renderer 和 migration 测试全部通过。

### Phase 2：SKU 受控回答与平台验证（v2 已完成）

- 实现 ChatModelPort/adapter、Provider route 和 FakeChatModel。
- 实现客服 Retriever、编排器、结构化回答和 Validator 链。
- 商品 Retriever 复用现有 AI 搜索索引与混合排名，并用公共目录二次投影 Evidence。
- 实现无命中仍回答、检索诊断和窄授权人工接管决策。
- 后台测试实验室、Run inspection 和人工草稿。
- 建立离线评估与回归命令。

验收：真实 SKU 测试集达到批准基线；不产生客户自动消息。

### Phase 3：企业文件知识（v1 已完成）

- 实现知识文件上传、parser、chunker、ingestion job 和处理预览。
- 支持 PDF/DOCX/TXT/Markdown；PPTX/XLSX 按真实需求接续。
- 实现页/章节/段落/表格引用及历史版本审计。
- SKU 与文件候选统一 rerank。

验收：客户安全标题、引用定位、撤销、版本和 Prompt injection 测试通过。

### Phase 4：店铺级安全自动回答（功能已完成，生产启用由运营控制）

- 仅开放批准的商品/品牌知识主题。
- Widget 展示 AI、引用、实时处理状态、安全流式回答和转人工。
- 人工接管、并发 ownership 和失败降级完整上线。
- 先小店铺/小流量灰度，持续对比平台验证集与人工结果。

验收：运行契约第 16、20 节全部满足，紧急停用和回退演练通过。

### Phase 4.5：人工训练与版本治理（已完成）

- 建立案例、规则、不可变训练版本和 Run 快照。
- 知识库统一导入案例 JSON，工作台支持人工增删改、导出与一键审批生效。
- 商品案例与规则由人工或开发协作过程离线准备；产品不调用模型 API 在线生成或总结。
- 训练内容只改变回答行为，不成为企业事实或引用来源。

验收：草稿隔离、知识库导入强制草稿、一键审批原子发布、运行时版本快照和“案例不是证据”
回归测试通过。

### Phase 5：实时只读工具

- 逐个接入公开价格、可售状态、库存和已认证订单查询。
- 每个工具单独评估选择、参数、权限、证据和失败行为。
- 仍不开放退款、取消或资料修改。

验收：动态事实不从 RAG 回答，工具证据带 observed_at；工具失败先安全说明或追问，只有
需要人工专属动作时正确转人工。

### Phase 6：持续优化

- 内容缺口、低质量来源和人工修改分析。
- Retriever/reranker、缓存和多语言优化；持续监控流式链路首分片与重连指标。
- 只有在单编排器持续出现复杂 Prompt 或工具选择问题时，才评估专用 Agent；新增 Agent
  不能改变运行契约。

## 19. 完成定义

一个智能客服阶段只有同时满足以下条件才算完成：

- 功能代码、迁移、RLS、权限、API schema 和前端状态完整。
- 单元、集成、跨租户、边界、Agent 合约和离线评估通过。
- Run、Evidence、版本、工具和错误均可观测。
- 故障降级、人工接管、kill switch 和回滚经过演练。
- 文档中的当前状态、接口和验收结果同步更新。
- 不存在只靠 Prompt 执行的关键安全边界。

## 20. 行业实现参考

本设计参考的官方资料（检索于 2026-08-09）：

- [Intercom：Fin AI Engine 的 query refinement、RAG 和 answer validation](https://www.intercom.com/help/en/articles/9929230-the-fin-ai-engine)
- [Intercom：知识来源与 AI Agent/Copilot 的可用范围](https://www.intercom.com/help/en/articles/9440354-knowledge-sources-to-power-ai-agents-and-self-serve-support)
- [Zendesk：知识 chunk 与向量检索](https://support.zendesk.com/hc/en-us/articles/4408845739162-Optimizing-your-knowledge-content-for-generative-AI)
- [Zendesk：Generative Procedures、API integration 与人工接管](https://support.zendesk.com/hc/en-us/articles/10473649691418-About-generative-procedures-for-AI-agents)
- [Microsoft：知识、工具和 Topic 的生成式编排](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/generative-orchestration)
- [Microsoft：Grounding、provenance、citation 和输入输出安全检查](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/generative-ai-public-websites)
- [Microsoft：可重复 Agent test set 与 activity map](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-intro)
- [Amazon Connect：query reformulation、hybrid retrieval、content filter 与 Agent version](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-agents.html)
- [Salesforce：确定性 action、LLM tool 和用户确认](https://developer.salesforce.com/docs/ai/agentforce/guide/ascript-ref-actions.html)
- [OpenAI：从单 Agent、分层 guardrail 到 human intervention](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)
- [OpenAI Agents SDK：generation、tool、guardrail 与 handoff tracing](https://openai.github.io/openai-agents-python/tracing/)
