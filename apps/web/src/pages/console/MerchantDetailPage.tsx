import {
  Badge,
  Button,
  Card,
  Heading,
  Select,
  Switch,
  Table,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  ArrowRight,
  ChartLineUp,
  Clock,
  Eye,
  GearSix,
  Key,
  Package,
  Quotes,
  Storefront,
  UserCircle,
  UserPlus,
  UsersThree,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { ToastNotice } from "../../core/ToastContext";
import { api } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { subscriptionTierLabel } from "../../lib/subscriptionTier";
import type {
  MerchantDailyMetric,
  MerchantDetail,
  MerchantIdentityProfile,
  MerchantStatusMetric,
  Tenant,
  TenantBasicInfoPayload,
} from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";
import {
  MerchantOwnerDialog,
  MerchantOwnerPasswordResetDialog,
  TenantModuleDialog,
  TenantSubscriptionDialog,
} from "./TenantManagementPage";
import "./MerchantDetailPage.css";

type MerchantSection = "overview" | "subaccounts" | "profile";

const STATUS_LABELS: Record<MerchantStatusMetric["status"], string> = {
  PENDING_CONFIRMATION: "待确认",
  CONFIRMED: "已通过",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

const LOCALES = ["zh-CN", "en-US", "es", "pt", "tr", "ar", "ja", "ko", "fr", "fa"];
const CURRENCIES = ["CNY", "USD", "EUR", "GBP", "JPY", "KRW", "AED", "TRY"];
const TIMEZONES = [
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Tokyo",
  "Asia/Dubai",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "UTC",
];

function compactNumber(value: number) {
  return new Intl.NumberFormat(document.documentElement.lang || "zh-CN", {
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function shortDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(document.documentElement.lang || "zh-CN", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function accountStatusLabel(status: "invited" | "active" | "suspended") {
  if (status === "active") return "正常";
  if (status === "invited") return "待激活";
  return "已暂停";
}

function TrendBars({ data, label }: { data: MerchantDailyMetric[]; label: string }) {
  const max = Math.max(1, ...data.map((item) => item.count));
  const total = data.reduce((sum, item) => sum + item.count, 0);
  return (
    <div className="merchant-trend" aria-label={label}>
      <div className="merchant-trend-summary">
        <strong>{compactNumber(total)}</strong>
        <Text size="1" color="gray">{label}</Text>
      </div>
      <div className="merchant-trend-bars" role="img" aria-label={`${label}：${total}`}>
        {data.map((item) => (
          <span
            key={item.date}
            className={item.count ? "merchant-trend-bar has-value" : "merchant-trend-bar"}
            style={{ height: `${Math.max(4, (item.count / max) * 100)}%` }}
            title={`${shortDate(item.date)} · ${item.count}`}
          />
        ))}
      </div>
      <div className="merchant-trend-axis">
        <span>{data[0] ? shortDate(data[0].date) : "—"}</span>
        <span>{data.at(-1) ? shortDate(data.at(-1)!.date) : "—"}</span>
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  tone = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "attention";
}) {
  return (
    <Card className={`merchant-overview-metric ${tone === "attention" ? "is-attention" : ""}`}>
      <span className="merchant-overview-metric-icon">{icon}</span>
      <Text size="1" color="gray">{label}</Text>
      <strong>{value}</strong>
      <Text size="1" color="gray">{detail}</Text>
    </Card>
  );
}

function MerchantOverview({ detail }: { detail: MerchantDetail }) {
  const { t } = useLocale();
  const { monitoring } = detail;
  const maxStatus = Math.max(1, ...monitoring.quote_statuses.map((item) => item.count));
  return (
    <div className="merchant-detail-section">
      <div className="merchant-overview-metrics">
        <MetricCard
          icon={<Quotes />}
          label={t("累计报价")}
          value={compactNumber(monitoring.quotes_total)}
          detail={monitoring.last_quote_at ? t("最近 {time}", { time: dateTime(monitoring.last_quote_at) }) : t("暂无报价记录")}
        />
        <MetricCard
          icon={<ChartLineUp />}
          label={t("近 30 天报价")}
          value={compactNumber(monitoring.quotes_period)}
          detail={t("客户提交的报价请求")}
        />
        <MetricCard
          icon={<Clock />}
          label={t("待处理报价")}
          value={compactNumber(monitoring.quotes_pending)}
          detail={t("需要商家确认")}
          tone={monitoring.quotes_pending ? "attention" : "default"}
        />
        <MetricCard
          icon={<Package />}
          label={t("SKU 数量")}
          value={compactNumber(monitoring.skus_total)}
          detail={t("当前商品数据规模")}
        />
        <MetricCard
          icon={<Storefront />}
          label={t("前台访客")}
          value={compactNumber(monitoring.storefront_visitors_period)}
          detail={t("近 30 天去重访客")}
        />
        <MetricCard
          icon={<Eye />}
          label={t("商品浏览")}
          value={compactNumber(monitoring.product_views_period)}
          detail={t("近 30 天详情浏览")}
        />
        <MetricCard
          icon={<UsersThree />}
          label={t("运营子账号")}
          value={compactNumber(monitoring.subaccounts_total)}
          detail={t("{count} 个正常使用", { count: monitoring.subaccounts_active })}
        />
      </div>

      <div className="merchant-monitoring-grid">
        <Card className="merchant-monitoring-card merchant-monitoring-trends">
          <div className="merchant-panel-heading">
            <div>
              <Heading as="h2" size="4">{t("30 天经营趋势")}</Heading>
              <Text size="2" color="gray">{t("报价需求与商品关注度按商家时区统计。")}</Text>
            </div>
            <Badge variant="soft" color="blue">{detail.merchant.timezone || "Asia/Shanghai"}</Badge>
          </div>
          <div className="merchant-trend-grid">
            <TrendBars data={monitoring.quote_trend} label={t("报价请求")} />
            <TrendBars data={monitoring.product_view_trend} label={t("商品浏览")} />
          </div>
        </Card>

        <Card className="merchant-monitoring-card">
          <div className="merchant-panel-heading">
            <div>
              <Heading as="h2" size="4">{t("报价状态")}</Heading>
              <Text size="2" color="gray">{t("累计报价单的处理分布。")}</Text>
            </div>
          </div>
          <div className="merchant-status-list">
            {monitoring.quote_statuses.map((item) => (
              <div className="merchant-status-row" key={item.status}>
                <div>
                  <Text size="2">{t(STATUS_LABELS[item.status])}</Text>
                  <Text size="1" color="gray">{item.count.toLocaleString()}</Text>
                </div>
                <span className="merchant-status-track">
                  <span style={{ width: `${Math.max(item.count ? 8 : 0, (item.count / maxStatus) * 100)}%` }} />
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function MerchantSubaccounts({ detail }: { detail: MerchantDetail }) {
  const { t } = useLocale();
  if (!detail.subaccounts.length) {
    return (
      <EmptyState
        title={t("这个商家还没有运营子账号")}
        description={t("商家开通运营子账号后，会自动汇总到这里。")}
      />
    );
  }
  return (
    <div className="merchant-detail-section">
      <div className="merchant-section-heading">
        <div>
          <Heading as="h2" size="5">{t("运营子账号")}</Heading>
          <Text size="2" color="gray">{t("查看独立运营账号的登录活跃度与报价情况。")}</Text>
        </div>
        <Badge variant="soft" color="blue">{t("共 {count} 个", { count: detail.subaccounts.length })}</Badge>
      </div>
      <div className="desktop-table surface-panel merchant-subaccount-table">
        <Table.Root variant="surface">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>{t("子账号")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>{t("所属主账号")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>{t("近 30 天登录")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>{t("报价")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>{t("最近活动")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell justify="end">{t("详情")}</Table.ColumnHeaderCell>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {detail.subaccounts.map((account) => (
              <Table.Row key={account.id}>
                <Table.RowHeaderCell>
                  <div className="merchant-account-identity">
                    <span>{account.display_name.slice(0, 1).toUpperCase()}</span>
                    <div>
                      <Text size="2" weight="medium">{account.display_name}</Text>
                      <Text size="1" color="gray">{account.login_identifier}</Text>
                    </div>
                  </div>
                </Table.RowHeaderCell>
                <Table.Cell>{account.parent_display_name || "—"}</Table.Cell>
                <Table.Cell>{account.login_count_30d.toLocaleString()}</Table.Cell>
                <Table.Cell>{account.quote_count.toLocaleString()}</Table.Cell>
                <Table.Cell><Text size="1" color="gray">{dateTime(account.last_quote_at || account.last_login_at || undefined)}</Text></Table.Cell>
                <Table.Cell>
                  <Badge color={account.status === "active" ? "jade" : account.status === "invited" ? "blue" : "gray"} variant="soft">
                    {t(accountStatusLabel(account.status))}
                  </Badge>
                </Table.Cell>
                <Table.Cell justify="end">
                  <Button asChild size="1" variant="ghost">
                    <Link to={`/console/tenants/${detail.merchant.id}/subaccounts/${account.id}`}>
                      {t("查看")}
                      <ArrowRight />
                    </Link>
                  </Button>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      </div>
      <div className="mobile-data-list merchant-subaccount-mobile-list">
        {detail.subaccounts.map((account) => (
          <Link
            className="mobile-data-card merchant-subaccount-mobile-card"
            to={`/console/tenants/${detail.merchant.id}/subaccounts/${account.id}`}
            key={account.id}
          >
            <div className="mobile-card-heading">
              <div className="merchant-account-identity">
                <span>{account.display_name.slice(0, 1).toUpperCase()}</span>
                <div>
                  <Text size="3" weight="medium">{account.display_name}</Text>
                  <Text size="1" color="gray">{account.login_identifier}</Text>
                </div>
              </div>
              <Badge color={account.status === "active" ? "jade" : "gray"} variant="soft">
                {t(accountStatusLabel(account.status))}
              </Badge>
            </div>
            <div className="merchant-mobile-stat-row">
              <span><small>{t("30 天登录")}</small><strong>{account.login_count_30d}</strong></span>
              <span><small>{t("报价")}</small><strong>{account.quote_count}</strong></span>
              <ArrowRight />
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function MerchantProfile({
  detail,
  onSaved,
  onOwnerSetup,
  onPasswordReset,
  onModules,
  onSubscription,
}: {
  detail: MerchantDetail;
  onSaved: () => Promise<void>;
  onOwnerSetup: () => void;
  onPasswordReset: () => void;
  onModules: () => void;
  onSubscription: () => void;
}) {
  const { t } = useLocale();
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const merchant = detail.merchant;
  const [form, setForm] = useState<TenantBasicInfoPayload>({
    name: merchant.name,
    contact_email: merchant.contact_email || null,
    active: merchant.status === "active",
    default_locale: merchant.default_locale || "zh-CN",
    default_currency: merchant.default_currency || "CNY",
    timezone: merchant.timezone || "Asia/Shanghai",
  });
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    setForm({
      name: merchant.name,
      contact_email: merchant.contact_email || null,
      active: merchant.status === "active",
      default_locale: merchant.default_locale || "zh-CN",
      default_currency: merchant.default_currency || "CNY",
      timezone: merchant.timezone || "Asia/Shanghai",
    });
  }, [merchant]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setNotice(null);
    try {
      await api.updateTenantBasics(merchant.id, form);
      await Promise.all([onSaved(), reloadTenants()]);
      setNotice({ kind: "success", message: t("商家基本信息已保存。") });
    } catch (caught) {
      setNotice({
        kind: "error",
        message: caught instanceof Error ? caught.message : t("商家信息保存失败。"),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="merchant-detail-section merchant-profile-grid">
      <Card className="merchant-profile-card">
        <div className="merchant-panel-heading">
          <div>
            <Heading as="h2" size="5">{t("基本信息")}</Heading>
            <Text size="2" color="gray">{t("维护商家名称、联系方式和前台默认区域设置。")}</Text>
          </div>
        </div>
        <form className="merchant-profile-form" onSubmit={submit}>
          <label className="field-group merchant-field-span-2">
            <Text size="2" weight="medium">{t("商家名称")}</Text>
            <TextField.Root
              required
              maxLength={200}
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.currentTarget.value }))}
            />
          </label>
          <label className="field-group merchant-field-span-2">
            <Text size="2" weight="medium">{t("联系邮箱")}</Text>
            <TextField.Root
              name="contact_email"
              type="email"
              autoComplete="off"
              autoCapitalize="none"
              maxLength={320}
              value={form.contact_email || ""}
              placeholder="contact@company.com"
              onChange={(event) => setForm((current) => ({ ...current, contact_email: event.currentTarget.value || null }))}
            />
          </label>
          <label className="field-group">
            <Text size="2" weight="medium">{t("默认语言")}</Text>
            <Select.Root value={form.default_locale} onValueChange={(value) => setForm((current) => ({ ...current, default_locale: value }))}>
              <Select.Trigger />
              <Select.Content>{LOCALES.map((value) => <Select.Item value={value} key={value}>{value}</Select.Item>)}</Select.Content>
            </Select.Root>
          </label>
          <label className="field-group">
            <Text size="2" weight="medium">{t("默认货币")}</Text>
            <Select.Root value={form.default_currency} onValueChange={(value) => setForm((current) => ({ ...current, default_currency: value }))}>
              <Select.Trigger />
              <Select.Content>{CURRENCIES.map((value) => <Select.Item value={value} key={value}>{value}</Select.Item>)}</Select.Content>
            </Select.Root>
          </label>
          <label className="field-group merchant-field-span-2">
            <Text size="2" weight="medium">{t("商家时区")}</Text>
            <Select.Root value={form.timezone} onValueChange={(value) => setForm((current) => ({ ...current, timezone: value }))}>
              <Select.Trigger />
              <Select.Content>{TIMEZONES.map((value) => <Select.Item value={value} key={value}>{value}</Select.Item>)}</Select.Content>
            </Select.Root>
          </label>
          <div className="merchant-status-switch merchant-field-span-2">
            <div>
              <Text size="2" weight="medium">{t("启用商家")}</Text>
              <Text size="1" color="gray">{t("关闭后商家前台和后台账号将暂停访问，历史数据仍会保留。")}</Text>
            </div>
            <Switch checked={form.active} onCheckedChange={(checked) => setForm((current) => ({ ...current, active: checked }))} />
          </div>
          <div className="merchant-readonly-path merchant-field-span-2">
            <div>
              <Text size="2" weight="medium">{t("前台地址")}</Text>
              <Text size="1" color="gray">{t("为避免已有链接失效，地址不在这里直接修改。")}</Text>
            </div>
            <code>/{merchant.slug}</code>
          </div>
          {notice ? <div className="merchant-field-span-2"><ToastNotice kind={notice.kind} message={notice.message} /></div> : null}
          <div className="merchant-profile-actions merchant-field-span-2">
            <Button type="submit" loading={saving}>{t("保存基本信息")}</Button>
          </div>
        </form>
      </Card>

      <div className="merchant-admin-stack">
        <Card className="merchant-profile-card merchant-owner-card">
          <div className="merchant-panel-heading">
            <div>
              <Heading as="h3" size="4">{t("商家主账号")}</Heading>
              <Text size="2" color="gray">{t("该账号负责进入商家后台并开通运营子账号。")}</Text>
            </div>
            <UserCircle size={24} />
          </div>
          {merchant.owner_account ? (
            <div className="merchant-owner-summary">
              <strong>{merchant.owner_account.display_name}</strong>
              <span>{merchant.owner_account.login_identifier || merchant.owner_account.email || "—"}</span>
              <span>{t("创建于 {time}", { time: dateTime(merchant.owner_account.created_at) })}</span>
              <Button variant="soft" color="gray" onClick={onPasswordReset} disabled={merchant.status !== "active"}>
                <Key />{t("重置主账号密码")}
              </Button>
            </div>
          ) : (
            <div className="merchant-owner-summary is-empty">
              <Text size="2" color="gray">{t("尚未开通可登录的商家主账号。")}</Text>
              <Button variant="soft" onClick={onOwnerSetup} disabled={merchant.status !== "active"}>
                <UserPlus />{t("开通主账号")}
              </Button>
            </div>
          )}
        </Card>

        <Card className="merchant-profile-card merchant-access-card">
          <div className="merchant-panel-heading">
            <div>
              <Heading as="h3" size="4">{t("平台配置")}</Heading>
              <Text size="2" color="gray">{t("等级、额度与该商家可以使用的功能。")}</Text>
            </div>
            <GearSix size={23} />
          </div>
          <div className="merchant-config-list">
            <div><span>{t("商家等级")}</span><strong>{t(subscriptionTierLabel(merchant.subscription_tier))}</strong></div>
            <div><span>{t("SKU 配额")}</span><strong>{merchant.sku_limit === null ? t("不限") : merchant.sku_limit.toLocaleString()}</strong></div>
            <div><span>{t("可见模块")}</span><strong>{t("{count} 个", { count: merchant.enabled_modules?.length || 0 })}</strong></div>
            <div><span>{t("等级到期")}</span><strong>{dateTime(merchant.subscription_expires_at)}</strong></div>
          </div>
          <div className="merchant-config-actions">
            <Button variant="soft" color="gray" onClick={onSubscription}>{t("设置等级与配额")}</Button>
            <Button variant="soft" color="gray" onClick={onModules}>{t("设置可见模块")}</Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

export function MerchantDetailPage() {
  const { tenantId } = useParams();
  const { t } = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const [detail, setDetail] = useState<MerchantDetail | null>(null);
  const [identities, setIdentities] = useState<MerchantIdentityProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ownerSetup, setOwnerSetup] = useState<Tenant | null>(null);
  const [passwordReset, setPasswordReset] = useState<Tenant | null>(null);
  const [moduleEditor, setModuleEditor] = useState<Tenant | null>(null);
  const [subscriptionEditor, setSubscriptionEditor] = useState<Tenant | null>(null);

  const section = useMemo<MerchantSection>(() => {
    const requested = searchParams.get("section");
    return requested === "subaccounts" || requested === "profile" ? requested : "overview";
  }, [searchParams]);

  const load = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    setError("");
    try {
      const [nextDetail, nextIdentities] = await Promise.all([
        api.getTenantDetail(tenantId),
        api.getMerchantIdentities(),
      ]);
      setDetail(nextDetail);
      setIdentities(nextIdentities);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家详情加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [t, tenantId]);

  useEffect(() => { void load(); }, [load]);

  const refresh = useCallback(async () => {
    if (!tenantId) return;
    const nextDetail = await api.getTenantDetail(tenantId);
    setDetail(nextDetail);
  }, [tenantId]);

  if (loading) return <div className="console-page merchant-detail-page"><TableSkeleton /></div>;
  if (error || !detail) return <div className="console-page merchant-detail-page"><ErrorState message={error || t("没有找到这个商家。") } onRetry={() => void load()} /></div>;

  const merchant = detail.merchant;
  return (
    <div className="console-page merchant-detail-page">
      <div className="merchant-detail-breadcrumb">
        <Button asChild variant="ghost" color="gray" size="1"><Link to="/console/tenants"><ArrowLeft />{t("返回商家列表")}</Link></Button>
      </div>
      <header className="merchant-detail-hero">
        <div className="merchant-detail-identity">
          <span className="merchant-detail-avatar">{merchant.name.slice(0, 2).toUpperCase()}</span>
          <div>
            <div className="merchant-detail-title-row">
              <Heading size="7">{merchant.name}</Heading>
              <Badge variant="soft" color={merchant.status === "active" ? "jade" : "gray"}>{t(merchant.status === "active" ? "正常营业" : "已停用")}</Badge>
              <Badge variant="soft" color="blue">{t(subscriptionTierLabel(merchant.subscription_tier))}</Badge>
            </div>
            <Text size="2" color="gray">/{merchant.slug} · {merchant.contact_email || t("未填写联系邮箱")}</Text>
          </div>
        </div>
        <div className="merchant-detail-hero-actions">
          <Button asChild variant="soft" color="gray"><Link to={`/${merchant.slug}`} target="_blank"><Storefront />{t("查看商品前台")}</Link></Button>
          <Button variant="soft" onClick={() => setSearchParams({ section: "profile" })}><GearSix />{t("管理商家")}</Button>
        </div>
      </header>

      <Tabs.Root
        value={section}
        onValueChange={(value) => setSearchParams(value === "overview" ? {} : { section: value })}
        className="merchant-detail-tabs"
      >
        <Tabs.List>
          <Tabs.Trigger value="overview">{t("经营概览")}</Tabs.Trigger>
          <Tabs.Trigger value="subaccounts">{t("子账号")} <span>{detail.subaccounts.length}</span></Tabs.Trigger>
          <Tabs.Trigger value="profile">{t("基本信息与配置")}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="overview"><MerchantOverview detail={detail} /></Tabs.Content>
        <Tabs.Content value="subaccounts"><MerchantSubaccounts detail={detail} /></Tabs.Content>
        <Tabs.Content value="profile">
          <MerchantProfile
            detail={detail}
            onSaved={refresh}
            onOwnerSetup={() => setOwnerSetup(merchant)}
            onPasswordReset={() => setPasswordReset(merchant)}
            onModules={() => setModuleEditor(merchant)}
            onSubscription={() => setSubscriptionEditor(merchant)}
          />
        </Tabs.Content>
      </Tabs.Root>

      <MerchantOwnerDialog tenant={ownerSetup} onOpenChange={(open) => { if (!open) setOwnerSetup(null); }} onSaved={refresh} />
      <MerchantOwnerPasswordResetDialog tenant={passwordReset} onOpenChange={(open) => { if (!open) setPasswordReset(null); }} />
      <TenantModuleDialog tenant={moduleEditor} identities={identities} onOpenChange={(open) => { if (!open) setModuleEditor(null); }} onSaved={refresh} />
      <TenantSubscriptionDialog tenant={subscriptionEditor} onOpenChange={(open) => { if (!open) setSubscriptionEditor(null); }} onSaved={refresh} />
    </div>
  );
}
