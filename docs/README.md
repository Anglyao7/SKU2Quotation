# 智贸云文档索引

本目录只保留仍与当前系统有关的专题说明；本地启动、项目结构和测试命令以
根目录 [README](../README.md) 为准，正式服务器发布、回滚和备份以
[DEPLOYMENT](../DEPLOYMENT.md) 为准。

| 文档 | 用途 | 状态 |
|---|---|---|
| [性能与商家公告](./PERFORMANCE_AND_ANNOUNCEMENTS.md) | 登录、商品加载、页面切换优化；公告发布与排障 | 当前 |
| [外部商品图片迁移](./EXTERNAL_PRODUCT_IMAGE_MIGRATION.md) | 把历史第三方图片迁入自己的对象存储 | 当前 |
| [图床、CDN 与独立域名](./FUTURE_INFRASTRUCTURE_ROADMAP.md) | TB 级图片、静态加速和商家自有域名 | 后续规划 |
| [商品多语言包架构](./CATALOG_LANGUAGE_PACKS.md) | 全量/增量翻译、Cloudflare R2、IndexedDB 缓存与故障降级 | 当前 |
| [客服 AI 运行契约 v2](./CUSTOMER_SUPPORT_AI_RUNTIME_CONTRACT.md) | 客服知识边界、无命中回答、证据引用、窄授权人工接管与上线门槛 | 实施基线 |
| [智能客服开发设计](./CUSTOMER_SUPPORT_AI_DEVELOPMENT.md) | 当前代码映射、目标架构、数据模型、接口、测试与分阶段计划 | 实施蓝图 |

已从前端删除且不再维护的旧页面包括待审核商品、旧版供应商工作台、旧版
整库翻译任务页和重复的旧仪表盘/报价/SKU 页面。兼容 API 暂不因页面删除
而直接下线；只有确认没有导入任务、脚本或历史客户端调用后，才通过独立的
弃用版本移除服务端路由。
