# 公网生产部署

本方案面向一台 Linux 服务器上的单机正式环境：Caddy 自动申请和续期
Let's Encrypt 证书，React SPA 与 `/api` 使用同一主域，Keycloak 在
`auth.${ATC_DOMAIN}` 提供真实 OIDC。只有宿主机的 80/443 对公网开放。

生产部署有两个明确的拓扑：

- `ATC_DEPLOYMENT_PROFILE=compact`：面向公开 Beta 和 2 vCPU / 3.4 GiB
  主机，保留 Caddy、Web、API、PostgreSQL + pgvector、Redis、Keycloak
  与独立 Keycloak PostgreSQL；文件存入本地 Docker volume，文件处理与
  outbox 在请求/数据库内完成，不常驻 RabbitMQ、MinIO、ClamAV 或 Worker。
- `ATC_DEPLOYMENT_PROFILE=standard`：保留原有 RabbitMQ、MinIO、ClamAV
  与可选 Worker 的完整拓扑，适合 4 vCPU / 8 GiB 以上主机。

若云厂商交付的是已经由 Nginx 占用 80 端口、PID 1 不是 systemd 的托管
容器，使用 compact 的 `ATC_EDGE_PROXY=nginx` 拓扑。外层 Nginx 保持为
Cloudflare 回源入口，Compose 内的 Caddy 只绑定宿主回环地址；不要停止外层
Nginx，否则托管容器本身也可能退出。

## 1. 上线前提

Compact 最低要求是 2 vCPU、3 GiB RAM 和 8 GiB 构建前可用磁盘，推荐
40 GiB SSD。示例默认由部署脚本创建并持久启用一个专用 2 GiB swap 文件，
且 API、迁移镜像、Web 会严格顺序构建。Standard 推荐 Ubuntu 24.04 LTS、
4 vCPU、8 GiB RAM、80 GiB SSD；低于 6 GiB 时仍会停止。先以 SSH 运行
`free -h`、`df -h`、`docker version` 和 `docker compose version`。

服务器必须安装：

- Docker Engine 与 Docker Compose v2
- Git、curl、openssl、ca-certificates、Python 3（安全渲染 Keycloak realm）
- 可选的 restic（用于加密离机备份）

上述托管容器可先执行幂等准备脚本。它安装 Docker/Compose 及部署依赖，
实际运行一次临时容器，并在无 systemd 时让 cron 随提供商的 `/start.sh`
启动；它不会启动本站的数据库或业务容器：

```bash
sudo ./infra/production/prepare-managed-container-host.sh
```

阿里云安全组和主机防火墙只允许：

| 端口 | 来源 | 用途 |
|---|---|---|
| TCP 22 | 管理员固定 IP | SSH；完成后改成密钥登录并关闭密码登录 |
| TCP 80 | `0.0.0.0/0`、`::/0` | ACME 验证与 HTTPS 跳转 |
| TCP 443 | `0.0.0.0/0`、`::/0` | HTTPS |
| UDP 443 | `0.0.0.0/0`、`::/0` | 可选 HTTP/3 |

不要放行 5432、6379、5672、15672、8000、8080、9000、9001 或
Keycloak 管理端口。Ubuntu 可使用：

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow from <YOUR_FIXED_ADMIN_IP> to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw enable
```

## 2. 域名与 DNS

需要一个真实域名，不能用裸 IP 申请正式证书。在 DNS 控制台创建：

```text
ATC_DOMAIN                 A     <SERVER_PUBLIC_IP>
auth.ATC_DOMAIN            A     <SERVER_PUBLIC_IP>
```

例如 `ATC_DOMAIN` 是 `app.company.com` 时，第二条记录是
`auth.app.company.com`。等待两个记录在公网解析完成后再部署：

```bash
dig +short app.company.com A
dig +short auth.app.company.com A
```

OIDC 回调必须精确登记为：

```text
https://${ATC_DOMAIN}/login/callback
```

生产 Compose 会自动把 Keycloak issuer 配置为
`https://auth.${ATC_DOMAIN}/realms/atc`，不会启用本地一键登录。

## 3. 获取代码与配置密钥

```bash
install -d -m 0750 /opt/ai-trade-cloud
git clone https://github.com/Anglyao7/SKU2Quotation.git /opt/ai-trade-cloud/app
cd /opt/ai-trade-cloud/app
install -m 0600 .env.production.example .env.production
```

编辑 `.env.production`，替换所有占位值。每个服务密码和密钥应独立生成，
不要重复使用：

```bash
openssl rand -hex 32
```

普通 VM 保持 `ATC_EDGE_PROXY=caddy`。若使用前述托管容器，改为：

```text
ATC_DEPLOYMENT_PROFILE=compact
ATC_EDGE_PROXY=nginx
ATC_NGINX_EDGE_PORT=18080
```

该端口只绑定 `127.0.0.1`，不得在安全组或容器端口映射中公开。

`KEYCLOAK_INITIAL_USER_PASSWORD` 不能使用纯 hex：它必须至少 16 位并同时
包含大写字母、小写字母、数字和特殊字符。可用下列命令生成后，以单引号
包裹写入环境文件：

```bash
printf 'Aa1!%s\n' "$(openssl rand -hex 24)"
```

`OIDC_BOOTSTRAP_ADMIN_EMAIL` 必须是真实、唯一且由运营者控制的邮箱。
`BOOTSTRAP_*` 定义首次组织、租户和 OWNER；初始化命令是幂等的。
Keycloak 首位用户使用上述初始密码直接登录；上线后应通过受信任运维流程
轮换为仅运营者知晓的强密码。
部署脚本通过 JSON 解析器渲染 Keycloak realm；邮箱或显示值中合法的
`/`、`&` 等字符不会被 shell 文本替换破坏。

`LEGAL_OPERATOR_NAME` 和 `PRIVACY_CONTACT_EMAIL` 必须填写真实的运营主体
及可联系邮箱，构建时会写入公开隐私政策页；缺少或仍为示例值时部署会立即
失败。`PRIVACY_EFFECTIVE_DATE` 使用 `YYYY-MM-DD`，未填时默认为
`2026-07-23`。上线前应由实际运营主体复核隐私政策内容与生效日期。

Compact 公开 Beta 用 `ATC_ENABLE_SMTP` 明确决定是否接入真实 SMTP。
设为 `false` 时不要填写假 SMTP 参数；首次 bootstrap 管理员仍是已验证
邮箱并可直接使用账号密码登录，Keycloak 对账会跳过 SMTP 投递测试。
此模式不能发送忘记密码或成员验证邮件。设为 `true` 时必须填写
全部真实 `KEYCLOAK_SMTP_*` 参数，对账会实际测试投递。Standard 仍强制
启用 SMTP。

本地备份始终必需。Compact 用 `ATC_ENABLE_REMOTE_BACKUP` 明确决定是否
再同步到离机 restic；设为 `false` 时不要填写假仓库。启用时先安装 restic，
配置目标存储所需的云/SFTP 凭据，然后初始化并确认可读：

```bash
sudo ./infra/production/restic-init.sh
```

`RESTIC_REPOSITORY` 只接受 `s3:`、`rest:`、`sftp:`、`azure:`、`gs:` 或
`rclone:` 远端仓库；本地路径不能通过生产校验。Standard 仍强制启用该
远端备份。

若同机已有旧 `www` 容器，可让 compact Caddy 成为唯一公网入口：先把旧
容器加入一个共享 external Docker network，再设置
`ATC_ENABLE_LEGACY_WWW=true`、`ATC_LEGACY_WWW_UPSTREAM=容器名:端口` 和
`ATC_LEGACY_WWW_NETWORK=网络名`。关闭时不会加载 override，也不要求该
external network 存在。

完成后验证：

```bash
chmod 600 .env.production
sudo ./infra/production/scripts/validate_env.sh
```

`.env.production`、`.runtime/` 和 `.deployments/` 都已被 Git 忽略。
不要将文件内容粘贴到 Issue、CI 日志或聊天中。

## 4. 按不可变提交部署

从可信工作站确认准备发布的完整提交 SHA：

```bash
git ls-remote https://github.com/Anglyao7/SKU2Quotation.git refs/heads/main
```

在服务器传入该 40 位 SHA：

```bash
cd /opt/ai-trade-cloud/app
sudo ./infra/production/deploy.sh <40_CHARACTER_COMMIT_SHA>
```

托管容器改用包装脚本；它先以可回滚方式渲染并校验外层 Nginx，再调用同一
套不可变部署、迁移、备份和健康检查流程：

```bash
sudo ./infra/production/deploy-managed-container.sh <40_CHARACTER_COMMIT_SHA>
```

除第一次空库部署外，每次升级前必须审核 Alembic 变更符合
expand/contract：本次发布只做向后兼容的新增，旧字段/旧行为至少保留到
下一次独立发布。确认后临时把 `.env.production` 中
`ATC_CONFIRMED_EXPAND_CONTRACT=true`；部署完成后改回 false。部署脚本会
持有全局运维锁，并在迁移前生成一次成功且校验通过的停写备份，否则拒绝
执行迁移。定时备份、恢复、回滚和人工发布不会并发修改容器或数据库。

脚本会依次执行：

1. 检查环境文件权限、DNS、内存、磁盘、Git 工作区和 Docker；
2. fetch 并 detached checkout 指定提交；
3. 在不触碰现有业务容器前拉取依赖并构建不可变镜像；compact 严格按
   API → migration/bootstrap → Web 顺序构建；
4. 启动或保留持久依赖；
5. 幂等创建隔离数据库角色；
6. 执行 Alembic、运行权限授权、首次 OWNER/租户初始化；
7. Standard 创建版本化对象桶与 RabbitMQ 拓扑；compact 使用本地对象卷；
8. 通过 Keycloak 私有 Admin API 对账受管 Realm/OIDC 配置并验证 client
   secret；
9. 更新 API/Web/Worker/Caddy 并验证公网 API 与 OIDC discovery。

浏览器仍使用 `https://auth.${ATC_DOMAIN}`，OIDC issuer 及令牌中的签发者
也保持正式公网地址；API 容器则通过受限的
`OIDC_BACKCHANNEL_BASE_URL=http://keycloak:8080` 在服务网络内完成
discovery、token、JWKS 和 userinfo 请求，避免登录请求绕行 Cloudflare、
Caddy 和云主机公网回环。应用仍严格校验 discovery 返回的正式 issuer，
生产环境也只接受这一固定内部服务地址。部署验收会向内网 token endpoint
发送一个必然失败的假授权码，以确认内部回源链路真实可用。

脚本不会运行 `docker compose down`、不会删除卷，也不会自动执行数据库
downgrade。升级失败时会用 `.deployments/previous.env` 恢复上一组应用镜像；
数据库迁移必须保持向后兼容。手工回滚：

```bash
sudo ./infra/production/rollback.sh .deployments/previous.env
```

## 5. 验收与日常运维

```bash
sudo ./infra/production/compose.sh ps
sudo ./infra/production/compose.sh logs --tail=200 api web caddy keycloak
curl --fail "https://${ATC_DOMAIN}/api/v1/health/ready"
curl --fail "https://auth.${ATC_DOMAIN}/realms/atc/.well-known/openid-configuration"
```

确认响应头包含 HSTS、CSP（主站）、`nosniff` 和禁止 iframe。生产 API
关闭 Uvicorn access log；Caddy 不启用请求访问日志；Nginx 使用专用
`atc_safe` 格式，只记录客户端 IP、方法和无 query 的规范化 `$uri`，
绝不记录 `$request`、`$request_uri`、Referer 或任意请求头，
并对报价下载等敏感路径关闭访问日志。报价下载凭证只能放在
`X-Quote-Download-Token` 请求头，禁止恢复成 URL query；代理和应用日志
都不得记录该请求头。其余 API 请求按 Caddy 验证后的真实客户端 IP 限速，
并将代理请求体限制为 260 MiB、应用文件安全上限设为 250 MiB；应用还通过
启用 Redis 的限流层做第二道保护。
Redis 使用 `noeviction`：内存耗尽时限流存储会显式失败，应用返回 503，
不会因静默逐出限流桶而放松防护。

Keycloak 的 `/admin*`、`/realms/master*`、`/health*`、`/metrics*`
在公网域名上返回 404。

`start --import-realm` 只负责首次创建 Realm；Keycloak 对已经存在的 Realm
会跳过启动导入。为避免域名、回调地址、安全策略或 `OIDC_CLIENT_SECRET`
在模板与数据库之间漂移，每次部署都会在应用切换前运行
`keycloak-reconcile.sh`：它只连接私有 `identity` 网络，更新代码声明的
Realm/OIDC client 字段，保留用户和未受管扩展，并重新读取 client secret
做常量时间比对。它还把受控运营邮箱绑定到 master 管理员，并通过 Keycloak
官方 SMTP 测试接口实际发送测试邮件；SMTP 连接、认证或投递请求失败都会
阻止上线。管理员凭据经 stdin 传入一次性容器，不进入参数、容器环境或
日志。任何对账/验证失败都会在新应用上线前终止部署。

修改 `.env.production` 中的 `OIDC_CLIENT_SECRET` 会在下一次受控部署中同步
轮换 Keycloak client；不要单独手工修改其中一侧。`KEYCLOAK_ADMIN_PASSWORD`
必须始终与 Keycloak master 管理员的真实凭据一致，单独修改环境文件不会
替 Keycloak 管理员改密，只会让后续部署安全失败。Realm 启动导入的跳过
语义见 [Keycloak 官方导入说明](https://www.keycloak.org/server/importExport)。

管理时只通过容器内部执行 `kcadm`：

```bash
sudo ./infra/production/keycloak-admin-login.sh
```

包装脚本会从权限为 600 的生产环境文件读取管理员用户名，并在终端提示
密码；不要把密码写在命令行。首次登录后立即轮换 bootstrap admin 密码。
Realm 用户默认强制强密码和 TOTP，SMTP 与“忘记密码”在生产中强制启用。
管理员确需人工重置用户密码时，先用上述方式登录 `kcadm`，再运行仓库
提供的交互脚本：

```bash
sudo ./infra/production/keycloak-reset-user-password.sh owner@example.com
```

脚本从终端读取两次密码，通过 stdin 写入容器内的 mode-600 临时 JSON，
完成后立即删除；密码不会进入 shell history、进程参数、Docker inspect
或日志。详细管理语义以
[Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
为准。

新增商家成员时，必须先由平台管理员在“商家管理 → 邀请成员”登记准确的
邮箱、目标租户和角色。随后在服务器上执行：

```bash
sudo ./infra/production/keycloak-provision-user.sh \
  owner@merchant.example "Merchant Owner"
```

该命令启动的一次性容器只加入私有 `identity` 网络，直接访问
`http://keycloak:8080`；Keycloak 管理 API 仍不会暴露到公网。管理员密码与
初始用户密码均只从当前终端无回显读取，不进入参数、环境变量或业务 API。
第三个参数可指定与该邮箱绑定的 E.164 手机号作为用户名；Keycloak 的邮箱
登录能力使邮箱和手机号都可用于登录。默认新身份以
`emailVerified=false` 创建，并要求完成邮箱验证；发信失败时身份保持未验证，
可以在 SMTP 恢复后安全重试。只有完成线下核验并留存证据时，运维人员才可
显式传入 `--email-verified`。

镜像搜索在 `IMAGE_INTELLIGENCE_PROFILE=disabled` 时明确关闭；只有接入并
审核远程 provider 后才能启用，生产环境绝不能使用 deterministic 适配器。

## 6. 备份

Compact 每次备份至少在本机包含应用 PostgreSQL 和 Keycloak PostgreSQL
两份自定义格式 dump，并额外归档本地对象卷。Standard 每次备份包含：

- 应用 PostgreSQL 自定义格式 dump；
- Keycloak PostgreSQL 自定义格式 dump；
- MinIO 当前对象、对象元数据、逐对象 SHA-256；
- RabbitMQ durable volume（队列定义、未消费的持久消息与投递状态）；
- 发布提交、迁移版本以及整包 `SHA256SUMS`。

为了让数据库引用与对象快照处于同一个受控时间窗口，首发备份会短暂停止
Caddy、API、Worker 和 Keycloak 的写入，完成本地 dump/对象复制后立即
恢复并执行健康检查，再进行较慢的离机同步。因此每日定时器应安排在业务
低峰；随着对象规模增长，应迁移到云盘/数据库 PITR 与对象存储原生快照，
避免全量复制扩大维护窗口。

安装每天 03:20 执行的备份任务：

```bash
sudo ./infra/production/install-backup-timer.sh
sudo systemctl start atc-backup.service
sudo journalctl -u atc-backup.service -n 200 --no-pager
sudo systemctl list-timers atc-backup.timer --no-pager
```

常规 VM 使用 systemd timer；PID 1 不是 systemd 的托管容器会自动写入
`/etc/cron.d/atc-backup`，准备脚本负责保证 cron 当前运行并可随容器重启。

本地保留天数由 `ATC_BACKUP_RETENTION_DAYS` 控制，默认示例为 14 天。
首次部署会在发布完成前强制生成一份本地基线备份并自动启用对应平台的
定时任务。`ATC_ENABLE_REMOTE_BACKUP=true` 时，环境校验会实际读取远端
restic 仓库，备份脚本执行加密离机复制和保留策略，失败即整次备份失败。
远端仓库凭据只能放在权限为 600 的环境文件或云密钥服务中。

每月至少进行一次恢复演练，并记录 RPO、RTO、备份时间和校验结果。

灾备包故意不包含 `.env.production`、restic 仓库密码、DNS/域名账号、
SSH 私钥或云平台凭据。必须把这些内容另存到团队密码管理器或云密钥服务，
并确认至少两名授权管理员能够在服务器完全丢失时取得它们；否则拥有远端
备份文件也无法完成恢复。

## 7. 恢复手册

列出并选择一个时间戳目录：

```bash
ls -1 /var/backups/ai-trade-cloud
cd /opt/ai-trade-cloud/app
sudo env ATC_RESTORE_CONFIRM=RESTORE-20260723T032000Z \
  ./infra/production/restore.sh 20260723T032000Z
```

恢复脚本先校验全部 checksum，再创建一次当前状态安全备份，然后：

1. 停止 Caddy、Web、API、Worker 和 Keycloak 写入；
2. 把应用与 Keycloak dump 分别恢复到隔离的新数据库；
3. 验证后原子交换数据库名称，并保留原数据库；
4. 恢复 MinIO 对象；对象版本控制会保留更晚版本，脚本不会清空桶；
5. 恢复同一停写窗口的 RabbitMQ durable state，保证已标记 PUBLISHED
   但尚未写入 inbox 的消息不会丢失；
6. 将恢复库迁移到当前 head、重新授权和初始化依赖；
7. 启动 Keycloak 后用当前 `.env.production` 对账 Realm、域名与 OIDC
   secret，成功后才启动 API；
8. 启动其余服务并执行公网 API/OIDC 健康检查。

Redis 只承载可重建的缓存/短期协调状态，故意不进入灾备包；应用
PostgreSQL 的 outbox/inbox 与 RabbitMQ 持久队列则必须成对恢复。

如果恢复后的业务验证失败，停止写入后把保留的
`ai_trade_cloud_pre_*`、`keycloak_pre_*` 数据库名称交换回来。确认恢复
成功并完成另一份备份之前，不要删除这些数据库或任何 Docker volume。

## 8. 更新、监控与应急

- 每次部署前检查磁盘、备份和数据库迁移说明。
- 通过 `./infra/production/compose.sh logs` 查看轮转后的 JSON 容器日志。
- 监控 `/api/v1/health/ready`、证书到期时间、磁盘、内存、PostgreSQL、
  RabbitMQ 队列积压、ClamAV 更新时间以及最近一次 timer 成功时间。
- 禁止使用 `docker compose down --volumes`、`docker volume rm` 或手工
  清理 `.deployments` 中仍可能需要的镜像元数据。
- SSH 上线后改用 ed25519 密钥，禁用 root 密码登录，并立即轮换任何曾经
  在聊天或工单里发送过的服务器密码。
