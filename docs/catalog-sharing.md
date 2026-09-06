# 商品 / 分类分享与社交卡片

- 商品列表每行可分享商品；勾选商品可生成精选分享（最多 500 个商品）。以商品 ID 为单位，不再要求前端先加载 SKU。旧的 `sku_ids` API 仍兼容。
- 分类树一级、二级分类行均有分享入口。子账号商品目录也可分享商品或选择分类分享。
- 复制链接、二维码沿用 `/{店铺自己的 slug}/share/{分享 ID}?lang=...`。旧链接不变。
- Nginx 和 Vite 开发代理将该路径交给 `/api/store/{slug}/shares/{token}/preview`。服务端返回带 OG / Twitter 大图卡片标签的 HTML，爬虫无需运行 JavaScript，也无需登录。
- 普通浏览器通过同源外部脚本进入 `/{slug}?share=...&lang=...`，仍按分享范围显示商品，保留子账号身份。无脚本时保留图片、名称和可点击入口。兼容生产 `script-src 'self'`，无需放宽 CSP。
- 卡片仅从公开商品数据中提取标题、描述和代表商品图片；没有图片时依次使用商家 Logo、通用商品图。不输出供应商、内部成本、主账号身份或登录信息。分类停用、内容下架或全部对该子账号隐藏时返回 404。
- 生产 canonical / 图片绝对地址优先使用已有 `PUBLIC_BASE_URL`。图片仍使用现有 R2 / 公开媒体 URL，不复制或备份图片。
- 不新增数据表、不迁移商品数据。前后端需一同发布，因为新入口使用 `product_ids`，Nginx 也新增了分享页路由。

## 验证

2026-09-07：分享相关后端 31 项回归及真实 Vite 代理检查通过。发布预检已补齐热门商品两句缺失译文及分享入口中的英文占位，8 种扩展语言各 3754 项全部通过校验，完整 `npm run build`（翻译检查、TypeScript、Vite）通过。15 组前端回归脚本通过。浏览器连接连续超时，尚未完成视觉验收。

`apps/api`: `python -m pytest tests/test_catalog_share_metadata.py tests/test_api.py -k 'catalog_share or merchant_controls_optional_share_card_subtitle or customer_subaccount_is_restricted'`

`apps/web`: `node scripts/test-catalog-sharing.mjs`

上线后对实际分享链接执行 GET（不带登录凭证，User-Agent 可设为 `facebookexternalhit/1.1`），应直接得到 HTML，包含 `og:title`、`og:image`、`og:description`、`og:url`、`twitter:card`。不是仅前端动态修改 head。

OG 是供社交平台读取的元数据标准：https://ogp.me/ 。它不保证每款应用都会显示卡片，也无法主动清理社交平台已经缓存的预览；应用可能延迟更新、裁切图片，或需要额外的平台分享 SDK。此实现未配置微信 JS-SDK，不宣称保证微信会话内自定义分享卡片。
