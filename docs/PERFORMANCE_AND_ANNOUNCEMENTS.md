# 性能与商家公告说明

## 1. 本轮性能审查结论

本轮主要慢点不是“2 万 SKU 必须使用更大的服务器”，而是若干请求路径做了
重复或与当前页面无关的工作：

1. 账号密码登录先访问公开 Keycloak 域名，再由前端额外请求一次
   `/auth/bootstrap`，产生两段串行网络等待。
2. 商品前台虽然只返回一页 SKU，但过去为了一个已经删除的全局标签筛选，
   仍会读取当前商家的全部公开商品标签。
3. 工作台页面使用按路由拆包，但只有点击导航后才开始下载对应分包，首次
   点击容易感觉停顿。
4. 返回刚打开过的列表时只有“并发请求去重”，没有短时间响应复用。
5. 仓库里仍有一组已经没有路由入口的旧页面与其专用 API 映射。

对应改动：

- 浏览器继续使用正式 OIDC issuer；API 通过受限 Keycloak 内网地址完成
  discovery、token、JWKS 与 userinfo 请求，避免绕行公网、Cloudflare 和
  Caddy。
- 登录和刷新响应直接携带租户列表与当前权限，正常登录不再追加一次
  bootstrap 往返；旧响应仍有兼容回退。
- 商品列表不再扫描未使用的全局标签；单个 SKU 的标签、展示标签及 AI
  搜索内容不受影响。
- 工作台导航在鼠标悬停、聚焦或手指按下时预加载目标路由分包。
- 登录后的只读 GET 使用 12 秒、最多 180 项的会话内 LRU 缓存；写请求、
  登录状态、任务进度、系统监控和访问分析不会使用该缓存。任一写请求或
  身份变化都会清空缓存。
- 公开商家资料使用 60 秒短缓存，兼顾打开速度和公告生效时效。
- 删除没有任何页面引用的旧审核、旧整库翻译、旧供应商页面及重复页面代码。

## 2. 缓存与一致性边界

- 权限、登录、刷新令牌、任务进度、CPU/内存/磁盘监控、访问分析始终实时
  请求，不允许被通用前端缓存命中。
- 商品、分类、公告等写操作成功前就会使当前会话的 GET 缓存失效，因此
  保存后重新读取不会看到 12 秒前的旧数据。
- 公告是否处于有效期由服务端按当前时间过滤；客户端只接收当前有效且已经
  发布的公告。
- 多实例或多设备之间的最终可见时间还受公开资料 60 秒短缓存影响。需要
  秒级发布时，应在后续 CDN 阶段接入按商家主动失效，而不是把所有接口改为
  `no-store`。

## 3. 商家公告

有 `announcement.manage` 权限的成员可以从
`/console/announcements` 创建、编辑、暂停和删除公告。

### 滚动字幕

- 只允许纯文本，不接受富文本或 HTML。
- 在有效期内显示于商家前台顶部。
- 适合发货安排、活动时间和简短提醒。

### 富内容弹窗

- 内容按安全结构化块保存，支持小标题、正文、项目列表、图片、视频和链接。
- 图片与视频当前填写 HTTPS/HTTP 资源地址，适合接入商家自己的图床；页面
  不执行商家输入的 HTML 或脚本。
- 商家可指定开始/结束日期，或设置从开始时间起持续若干天。
- 可设置 1–720 小时的再次显示间隔。

访客看到弹窗时，浏览器会按“商家 + 公告 ID + 公告版本”记录时间。连续
刷新不会反复弹出；达到商家设置的间隔后才会再次出现。商家修改公告会增加
版本号，因此更新后的内容可以重新向访客展示。浏览器禁用本地存储时，当前
页面仍可正常显示，但无法跨刷新保存冷却时间。

公告富内容不会使用 `dangerouslySetInnerHTML`。链接与媒体 URL 仅允许
HTTP/HTTPS，拒绝 `javascript:`、带用户名密码的 URL 和其他协议。

## 4. 数据库与权限

公告表为 `storefront_announcements`，按 `tenant_id` 隔离，并在 PostgreSQL
启用强制 RLS。迁移版本为 `20260730_0043`。

系统权限：

```text
announcement.manage
```

默认 OWNER、ADMIN 与 SALES 拥有该权限，角色授权由系统内部维护，不向商家
开放成员与角色编辑入口。没有权限的账号不会在导航栏看到公告模块，直接访问
路由也会被权限门拦截。

主要接口：

```text
GET    /api/v1/announcements
POST   /api/v1/announcements
PUT    /api/v1/announcements/{announcement_id}
DELETE /api/v1/announcements/{announcement_id}
```

公开有效公告随 `GET /api/store/{tenant_slug}` 返回，不新增逐商品查询。

## 5. 上线后观察

上线后优先观察：

- 登录接口 p50/p95 与 Keycloak token endpoint 耗时；
- `/api/store/{tenant_slug}` 和第一页 SKU 接口的 p50/p95；
- API 5xx、Caddy 502、PostgreSQL 活跃连接和慢查询；
- 首次点击工作台分包的下载耗时与静态资源 404；
- 公告创建、公告公开可见和弹窗冷却的真实浏览器行为。

如果 4C8G 升级后仍然慢，先根据这些指标区分数据库、OIDC、网络或静态资源，
不要仅凭 CPU/内存使用率继续扩容。

## 6. 验证

```bash
cd apps/api
PYTHONPATH=. ./.venv/bin/pytest -q

cd ../web
npm run build
```

生产发布后还应检查：

```bash
curl --fail https://AITradeCloud.top/api/v1/health/ready
curl --fail https://auth.AITradeCloud.top/realms/atc/.well-known/openid-configuration
```

域名大小写在 DNS 中不敏感，但文档和配置建议统一使用小写
`aitradecloud.top`。
