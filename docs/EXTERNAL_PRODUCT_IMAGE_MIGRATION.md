# 外链商品图片迁移

`apps/api/scripts/migrate_external_product_images.py` 用于把某个商家已经导入的
外链商品图下载到平台自己的 S3 兼容对象存储，并在每张图上传成功后更新
`product_images`。商品、SKU、分类、价格和报价数据都不会被重建。

脚本支持 AWS S3、Cloudflare R2、Backblaze B2、MinIO 等 S3 兼容服务，沿用
应用已有的 `OBJECT_STORAGE_*` 和 AWS 凭据环境变量。凭据不要写进命令、
仓库或迁移日志。

## 安全机制

- 默认仅做预演，不下载、不上传、不修改数据库。
- 正式执行必须同时提供 `--apply` 和准确的商家确认值。
- 来源域名默认全部拒绝；必须用 `--source-host` 明确放行，或者主动使用
  `--allow-all-public-hosts`。
- 默认拒绝回环、私网、链路本地和保留地址，且每一次 HTTP 跳转都会重新校验。
- 只接受通过文件特征识别的 JPEG、PNG、WebP、GIF、BMP、AVIF；不接收 HTML
  或 SVG。
- 默认单图上限 25 MiB、像素上限一亿、并发数 4。
- 先上传对象，再以单行事务更新数据库；失败的图片继续使用原链接。
- 目标对象键由商家、商品、图片 ID 和内容哈希确定。中断后重跑不会重复上传。
- `.runtime/image-migrations/` 中保存不含 URL 查询参数的 0600 权限 JSONL
  结果，可精确查看失败原因。

## 第一步：配置目标图床

下面只是变量名示例，实际值由密钥管理或服务器环境注入：

```bash
export OBJECT_STORAGE_BACKEND=s3
export OBJECT_STORAGE_BUCKET=your-private-bucket
export OBJECT_STORAGE_ENDPOINT_URL=https://your-s3-compatible-endpoint
export OBJECT_STORAGE_REGION=auto
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

应用运行时也必须使用同一个存储桶。若希望浏览器直接从图片域名读取对象，
同时给 API 配置：

```bash
export PUBLIC_MEDIA_BASE_URL=https://images.example.com
```

未配置 `PUBLIC_MEDIA_BASE_URL` 时，前台仍可通过平台媒体接口读取对象，但会
占用 API 服务器带宽。

## 第二步：只读盘点

在 `apps/api` 目录执行：

```bash
.venv/bin/python -m scripts.migrate_external_product_images \
  --tenant-slug your-tenant
```

输出会列出外链图片总数和旧图片域名。预演不会发起图片请求。

## 第三步：小批量验证

先迁移 20 张。`--source-host` 可以重复传入；若旧图会跳转到 CDN，源站和
跳转后的 CDN 域名都要放行。

```bash
.venv/bin/python -m scripts.migrate_external_product_images \
  --tenant-slug your-tenant \
  --source-host old-images.example.com \
  --source-host cdn.example.com \
  --limit 20 \
  --apply \
  --confirm-tenant your-tenant
```

确认商家前台的图片正常后，去掉 `--limit` 执行全量迁移。脚本退出码为 0
表示所选图片全部成功；存在失败时退出码为 1，修正网络或来源域名后直接重跑。

未发布的商家前台可能无法用 slug 在受限的生产数据库角色下解析，此时使用
后台显示的 UUID：

```bash
.venv/bin/python -m scripts.migrate_external_product_images \
  --tenant-id 00000000-0000-0000-0000-000000000000
```

## 注意

迁移更新的是线上数据库，而原始 Excel 里的旧图片链接不会自动变化。如果以后
重新导入同一份旧文件，旧链接可能被再次带入。正式迁移后应保留原文件备份，并
把后续商品维护切换到新图床链接；若需要频繁重复导入旧表，应再增加“原始图片
URL 映射”字段或先批量改写源 Excel。
