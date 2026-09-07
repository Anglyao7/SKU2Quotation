# 待确认报价改价后通过报 500

## 原因与修复

工作台先保存商品明细，再调用确认接口。旧迁移 `20260720_0020` 中的
`trg_immutable_public_quote_draft_items` 会拒绝所有 UPDATE/DELETE，连待确认报价的
合法改价也不例外。这个触发器只存在于 PostgreSQL，因此 SQLite API 测试无法发现。

新增迁移 `20260907_0135`，原子替换原触发器函数，不移除触发器、不修改已有报价数据：

- 仅允许未删除、状态为 `PENDING_CONFIRMATION` 的报价修改现有编辑接口支持的字段：
  单价、数量、行金额、名称、描述、规格、分类、单位、币种和更新时间。
- 明细归属、SKU/商品标识与版本、装箱规则、来源图片、客户备注等字段继续不可修改。
  DELETE 仍被禁止；已确认、完成、取消或过期状态的明细继续不可修改。
- 检查状态时锁定父报价，与确认操作串行，等待后重新检查最新状态。
- 保持 `SECURITY INVOKER` 和租户 RLS，不增加运行账号权限。
- SQLite 不需要此触发器，升级/降级为空操作；PostgreSQL 降级恢复旧的全量拒绝行为。

Dockerfile 和所有 Compose 文件的 migration head 同步为 `20260907_0135`。

## 验证

2026-09-07 本地独立 PostgreSQL 16 测试库：28 项通过（包含 1 项 SQLite 空操作测试）。
覆盖旧错误复现、迁移恢复、主账号和子账号改价后确认、订单新金额/明细快照、重复确认
不产生重复订单、确认后的编辑拦截、来源字段保护、租户隔离、并发确认与编辑竞争。

```sh
cd apps/api
# 连接必须是独立测试库，库名必须以 atc_quote_test_ 开头。
# 测试会创建三张报价表、触发器和受 RLS 限制的测试角色；不要使用业务数据库。
ATC_QUOTE_TEST_DATABASE_URL='postgresql+psycopg://TEST_OWNER@127.0.0.1:TEST_PORT/atc_quote_test_0135' \
  .venv/bin/python -m pytest tests/test_pending_quote_item_edits_postgres.py -q
```

另外 35 项既有 API/迁移/部署配置检查通过：

```sh
cd apps/api
.venv/bin/python -m pytest -q \
  tests/test_api.py::test_anonymous_storefront_visitor_can_follow_merchant_quote_updates \
  tests/test_api.py::test_public_carton_orders_validate_source_and_freeze_quote_rule \
  tests/test_api.py::test_customer_subaccount_is_restricted_and_orders_remain_owner_read_only \
  tests/test_api.py::test_public_catalog_migration_is_reversible_on_sqlite \
  tests/test_carton_ordering.py tests/test_production_infrastructure.py
```

## 发布要求

本次仅完成代码和本地验证，未部署、未改线上订单。
下次发布必须按现有迁移流程将数据库升级到 `20260907_0135`，只换应用包不能解除旧触发器。
这是函数替换，不回填/重写历史明细，也不需要重新生成订单。之前保存失败的改价未提交，
上线后应由用户重新保存并确认，不自动替用户批准订单。

触发器及锁的实现参考 PostgreSQL 官方文档：
[触发器函数](https://www.postgresql.org/docs/16/plpgsql-trigger.html)、
[行锁](https://www.postgresql.org/docs/16/explicit-locking.html)。
