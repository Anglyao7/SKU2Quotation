import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Checkbox,
  Dialog,
  Heading,
  IconButton,
  Select,
  Table,
  Text,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import {
  CheckCircle,
  Eye,
  EyeSlash,
  NotePencil,
  Plus,
  SlidersHorizontal,
  Trash,
  UserPlus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { dateTime } from "../../lib/format";
import type {
  MerchantOwnerAccount,
  MerchantOwnerAccountPayload,
  Tenant,
  TenantModuleCode,
  TenantPayload,
  TenantSubscriptionStatus,
  TenantSubscriptionTier,
} from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

const LOGIN_EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const SUBSCRIPTION_TIERS: Array<{
  value: TenantSubscriptionTier;
  label: string;
  description: string;
}> = [
  { value: "TRIAL", label: "试用", description: "默认 1 个月 · 500 SKU" },
  { value: "STANDARD", label: "Standard", description: "基础版 · 5000 SKU" },
  { value: "SILVER", label: "Silver", description: "进阶版 · 5000 SKU" },
  { value: "ELITE", label: "Elite", description: "高级版 · SKU 不限" },
];

const SUBSCRIPTION_TIER_COLORS: Record<
  TenantSubscriptionTier,
  "gray" | "blue" | "violet" | "amber"
> = {
  TRIAL: "gray",
  STANDARD: "blue",
  SILVER: "violet",
  ELITE: "amber",
};

function subscriptionTierLabel(tier: TenantSubscriptionTier): string {
  return SUBSCRIPTION_TIERS.find((item) => item.value === tier)?.label ?? tier;
}

function subscriptionStatusLabel(status: TenantSubscriptionStatus): string {
  if (status === "expired") return "已过期";
  if (status === "expiring_soon") return "即将到期";
  return "有效";
}

function toDateTimeLocal(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function addCalendarMonths(value: Date, months: number): Date {
  const result = new Date(value);
  const day = result.getDate();
  result.setDate(1);
  result.setMonth(result.getMonth() + months);
  const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
  result.setDate(Math.min(day, lastDay));
  return result;
}

function defaultExpiryForTier(tier: TenantSubscriptionTier): Date {
  return addCalendarMonths(new Date(), tier === "TRIAL" ? 1 : 12);
}

function defaultSkuLimitForTier(tier: TenantSubscriptionTier): number | null {
  if (tier === "TRIAL") return 500;
  if (tier === "STANDARD" || tier === "SILVER") return 5_000;
  return null;
}

function skuLimitLabel(limit: number | null): string {
  return limit === null ? "不限" : limit.toLocaleString();
}

const TENANT_MODULES: Array<{
  code: TenantModuleCode;
  label: string;
  description: string;
}> = [
  { code: "products", label: "商品中心", description: "SKU、分类、标签、多语言与 AI 搜索" },
  { code: "analytics", label: "网站监测", description: "访问、国家与商品热度数据" },
  { code: "inventory", label: "进销存", description: "库存、采购、销售与调拨" },
  { code: "announcements", label: "公告管理", description: "顶部字幕与富内容公告" },
  { code: "support", label: "客服管理", description: "客户会话、回复与前台悬浮入口" },
  { code: "support_ai", label: "AI 智能客服", description: "知识库、自动回复与运行记录" },
  { code: "inquiries", label: "询盘", description: "客户与询盘工作流" },
  { code: "quotations", label: "报价", description: "报价单、模板与订单" },
  { code: "subaccounts", label: "子账号", description: "客户子账号与订货入口" },
];

const DEFAULT_TENANT_MODULES = TENANT_MODULES.map((module) => module.code);

function enabledTenantModules(tenant: Tenant): TenantModuleCode[] {
  const enabled = new Set(tenant.enabled_modules ?? DEFAULT_TENANT_MODULES);
  return DEFAULT_TENANT_MODULES.filter((code) => enabled.has(code));
}

function apiErrorCode(caught: unknown): string | undefined {
  if (!(caught instanceof ApiError) || !caught.details || typeof caught.details !== "object") return undefined;
  const detail = (caught.details as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return undefined;
  const code = (detail as { code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

function tenantLoginEmail(tenant: Tenant): string {
  return (
    tenant.owner_account?.email
    || tenant.contact_email
    || tenant.owner_account?.login_identifier
    || ""
  );
}

function InitialPasswordField() {
  const { t } = useLocale();
  const [visible, setVisible] = useState(false);

  return (
    <TextField.Root
      name="password"
      type={visible ? "text" : "password"}
      required
      minLength={8}
      maxLength={128}
      autoComplete="new-password"
      placeholder={t("至少 8 位，包含字母和数字")}
    >
      <TextField.Slot side="right">
        <button
          type="button"
          className="login-password-toggle"
          aria-label={t(visible ? "隐藏密码" : "显示密码")}
          aria-pressed={visible}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeSlash size={18} /> : <Eye size={18} />}
        </button>
      </TextField.Slot>
    </TextField.Root>
  );
}

export function TenantManagementPage() {
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const { t } = useLocale();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [ownerSetup, setOwnerSetup] = useState<Tenant | null>(null);
  const [moduleEditor, setModuleEditor] = useState<Tenant | null>(null);
  const [subscriptionEditor, setSubscriptionEditor] = useState<Tenant | null>(null);
  const [deleting, setDeleting] = useState<Tenant | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTenants(await api.getTenants());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家列表加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deactivateTenant(deleting.id);
      setDeleting(null);
      await Promise.all([load(), reloadTenants()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家停用失败。"));
      setDeleting(null);
    }
  };

  const refreshAll = async () => {
    await Promise.all([load(), reloadTenants()]);
  };

  return (
    <div className="console-page">
      <div className="page-heading-row">
        <div>
          <Text size="2" color="gray">{t("商家、登录账号与商品前台")}</Text>
          <Heading size="7">{t("商家管理")}</Heading>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={18} />
          {t("新增商家")}
        </Button>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : loading ? (
        <TableSkeleton />
      ) : tenants.length === 0 ? (
        <EmptyState
          title={t("平台还没有商家")}
          description={t("创建首个商家后，即可上传 SKU 并开放商品前台。")}
          action={(
            <Button onClick={() => setEditing("new")}>
              <Plus size={17} />
              {t("新增商家")}
            </Button>
          )}
        />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>{t("商家")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("登录邮箱")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("前台地址")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("报价")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("等级")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("SKU 配额")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("过期时间")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("可见模块")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("创建时间")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell justify="end">{t("操作")}</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {tenants.map((tenant) => {
                  const loginEmail = tenantLoginEmail(tenant);
                  return (
                    <Table.Row key={tenant.id}>
                      <Table.RowHeaderCell>
                        <Text size="2" weight="medium">{tenant.name}</Text>
                      </Table.RowHeaderCell>
                      <Table.Cell>
                        {loginEmail ? (
                          <Text size="1">{loginEmail}</Text>
                        ) : (
                          <Text size="1" color="amber">{t("尚未开通")}</Text>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <Text className="mono-text" size="1">/{tenant.slug}</Text>
                      </Table.Cell>
                      <Table.Cell>{tenant.sku_count ?? 0}</Table.Cell>
                      <Table.Cell>{tenant.quote_count ?? 0}</Table.Cell>
                      <Table.Cell>
                        <Button
                          size="1"
                          variant="soft"
                          color={SUBSCRIPTION_TIER_COLORS[tenant.subscription_tier]}
                          onClick={() => setSubscriptionEditor(tenant)}
                        >
                          {t(subscriptionTierLabel(tenant.subscription_tier))}
                          <NotePencil size={14} />
                        </Button>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="merchant-sku-quota">
                          <Text size="1" weight="medium">
                            {(tenant.sku_count ?? 0).toLocaleString()} / {t(skuLimitLabel(tenant.sku_limit))}
                          </Text>
                          {tenant.sku_limit !== null && (tenant.sku_count ?? 0) >= tenant.sku_limit ? (
                            <Badge size="1" color="red" variant="soft">{t("已达上限")}</Badge>
                          ) : null}
                        </div>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="merchant-subscription-expiry">
                          <Text
                            size="1"
                            color={tenant.subscription_status === "expired" ? "red" : "gray"}
                          >
                            {dateTime(tenant.subscription_expires_at)}
                          </Text>
                          {tenant.subscription_status === "active" ? null : (
                            <Badge
                              size="1"
                              variant="soft"
                              color={tenant.subscription_status === "expired" ? "red" : "amber"}
                            >
                              {t(subscriptionStatusLabel(tenant.subscription_status))}
                            </Badge>
                          )}
                        </div>
                      </Table.Cell>
                      <Table.Cell>
                        <Button
                          size="1"
                          variant="soft"
                          color="gray"
                          onClick={() => setModuleEditor(tenant)}
                        >
                          <SlidersHorizontal size={15} />
                          {t("{count} / {total} 个", {
                            count: enabledTenantModules(tenant).length,
                            total: TENANT_MODULES.length,
                          })}
                        </Button>
                      </Table.Cell>
                      <Table.Cell>
                        <Badge
                          variant="soft"
                          color={tenant.status === "active" ? "jade" : "gray"}
                        >
                          {t(tenant.status === "active" ? "启用" : "停用")}
                        </Badge>
                      </Table.Cell>
                      <Table.Cell>
                        <Text size="1" color="gray">{dateTime(tenant.created_at)}</Text>
                      </Table.Cell>
                      <Table.Cell justify="end">
                        <div className="table-actions">
                          {tenant.owner_account?.status === "active" ? null : (
                            <Tooltip content={t("开通登录账号")}>
                              <IconButton
                                size="1"
                                variant="ghost"
                                color="jade"
                                disabled={tenant.status !== "active"}
                                aria-label={t("为 {name} 开通登录账号", { name: tenant.name })}
                                onClick={() => setOwnerSetup(tenant)}
                              >
                                <UserPlus size={17} />
                              </IconButton>
                            </Tooltip>
                          )}
                          <Tooltip content={t("查看前台")}>
                            <IconButton asChild size="1" variant="ghost" color="gray">
                              <Link
                                to={`/${tenant.slug}`}
                                target="_blank"
                                aria-label={t("查看 {name} 商品前台", { name: tenant.name })}
                              >
                                <Eye size={17} />
                              </Link>
                            </IconButton>
                          </Tooltip>
                          <Tooltip content={t("编辑")}>
                            <IconButton
                              size="1"
                              variant="ghost"
                              color="gray"
                              aria-label={t("编辑 {name}", { name: tenant.name })}
                              onClick={() => setEditing(tenant)}
                            >
                              <NotePencil size={17} />
                            </IconButton>
                          </Tooltip>
                          {tenant.status === "active" ? (
                            <Tooltip content={t("停用")}>
                              <IconButton
                                size="1"
                                variant="ghost"
                                color="red"
                                aria-label={t("停用 {name}", { name: tenant.name })}
                                onClick={() => setDeleting(tenant)}
                              >
                                <Trash size={17} />
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table.Root>
          </div>

          <div className="mobile-data-list">
            {tenants.map((tenant) => {
              const loginEmail = tenantLoginEmail(tenant);
              return (
                <div className="mobile-data-card" key={tenant.id}>
                  <div className="mobile-card-heading">
                    <div>
                      <Text as="div" size="3" weight="medium">{tenant.name}</Text>
                      <Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text>
                    </div>
                    <div className="mobile-card-badges">
                      <Badge color={SUBSCRIPTION_TIER_COLORS[tenant.subscription_tier]}>
                        {t(subscriptionTierLabel(tenant.subscription_tier))}
                      </Badge>
                      <Badge color={tenant.status === "active" ? "jade" : "gray"}>
                        {t(tenant.status === "active" ? "启用" : "停用")}
                      </Badge>
                    </div>
                  </div>
                  <Text size="2" color={loginEmail ? "gray" : "amber"}>
                    {loginEmail || t("尚未开通登录账号")}
                  </Text>
                  <Text size="2" color="gray">
                    {t("{skus} 个 SKU / {quotes} 份报价", {
                      skus: tenant.sku_count || 0,
                      quotes: tenant.quote_count || 0,
                    })}
                  </Text>
                  <Text size="2" color="gray">
                    {t("SKU 配额：{used} / {limit}", {
                      used: (tenant.sku_count ?? 0).toLocaleString(),
                      limit: t(skuLimitLabel(tenant.sku_limit)),
                    })}
                  </Text>
                  <Text
                    size="2"
                    color={tenant.subscription_status === "expired" ? "red" : "gray"}
                  >
                    {t("到期：{date}", { date: dateTime(tenant.subscription_expires_at) })}
                    {tenant.subscription_status === "active"
                      ? ""
                      : ` · ${t(subscriptionStatusLabel(tenant.subscription_status))}`}
                  </Text>
                  <div className="mobile-card-footer">
                    <div className="page-actions">
                      <Button
                        size="1"
                        variant="soft"
                        color={SUBSCRIPTION_TIER_COLORS[tenant.subscription_tier]}
                        onClick={() => setSubscriptionEditor(tenant)}
                      >
                        {t("等级设置")}
                      </Button>
                      <Button
                        size="1"
                        variant="soft"
                        color="gray"
                        onClick={() => setModuleEditor(tenant)}
                      >
                        <SlidersHorizontal />
                        {t("可见模块 {count}", { count: enabledTenantModules(tenant).length })}
                      </Button>
                      <Button asChild size="1" variant="soft">
                        <Link to={`/${tenant.slug}`}>{t("查看前台")}</Link>
                      </Button>
                      {tenant.owner_account?.status === "active" ? null : (
                        <Button
                          size="1"
                          variant="soft"
                          color="jade"
                          disabled={tenant.status !== "active"}
                          onClick={() => setOwnerSetup(tenant)}
                        >
                          <UserPlus />
                          {t("开通登录账号")}
                        </Button>
                      )}
                    </div>
                    <div>
                      <IconButton
                        variant="ghost"
                        aria-label={t("编辑 {name}", { name: tenant.name })}
                        onClick={() => setEditing(tenant)}
                      >
                        <NotePencil />
                      </IconButton>
                      {tenant.status === "active" ? (
                        <IconButton
                          variant="ghost"
                          color="red"
                          aria-label={t("停用 {name}", { name: tenant.name })}
                          onClick={() => setDeleting(tenant)}
                        >
                          <Trash />
                        </IconButton>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <TenantFormDialog
        tenant={editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        onChanged={refreshAll}
      />
      <MerchantOwnerDialog
        tenant={ownerSetup}
        onOpenChange={(open) => {
          if (!open) setOwnerSetup(null);
        }}
        onSaved={refreshAll}
      />
      <TenantModuleDialog
        tenant={moduleEditor}
        onOpenChange={(open) => {
          if (!open) setModuleEditor(null);
        }}
        onSaved={refreshAll}
      />
      <TenantSubscriptionDialog
        tenant={subscriptionEditor}
        onOpenChange={(open) => {
          if (!open) setSubscriptionEditor(null);
        }}
        onSaved={refreshAll}
      />
      <AlertDialog.Root
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      >
        <AlertDialog.Content>
          <AlertDialog.Title>{t("停用这个商家？")}</AlertDialog.Title>
          <AlertDialog.Description>
            {t("“{name}”的商品前台将停止访问，历史数据会保留，可在编辑商家时重新启用。", {
              name: deleting?.name ?? "",
            })}
          </AlertDialog.Description>
          <div className="dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">{t("取消")}</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button color="red" onClick={() => void remove()}>{t("确认停用")}</Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}

function TenantSubscriptionDialog({
  tenant,
  onOpenChange,
  onSaved,
}: {
  tenant: Tenant | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [tier, setTier] = useState<TenantSubscriptionTier>("TRIAL");
  const [expiresAt, setExpiresAt] = useState("");
  const [skuLimit, setSkuLimit] = useState("500");
  const [unlimitedSkus, setUnlimitedSkus] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!tenant) return;
    setTier(tenant.subscription_tier);
    setExpiresAt(toDateTimeLocal(tenant.subscription_expires_at));
    setUnlimitedSkus(tenant.sku_limit === null);
    setSkuLimit(tenant.sku_limit === null ? "" : String(tenant.sku_limit));
    setError("");
  }, [tenant]);

  const chooseTier = (nextTier: TenantSubscriptionTier) => {
    setTier(nextTier);
    setExpiresAt(toDateTimeLocal(defaultExpiryForTier(nextTier)));
    const nextLimit = defaultSkuLimitForTier(nextTier);
    setUnlimitedSkus(nextLimit === null);
    setSkuLimit(nextLimit === null ? "" : String(nextLimit));
    setError("");
  };

  const applyTerm = (months: number) => {
    setExpiresAt(toDateTimeLocal(addCalendarMonths(new Date(), months)));
    setError("");
  };

  const save = async () => {
    if (!tenant || saving) return;
    const parsedExpiry = new Date(expiresAt);
    if (!expiresAt || Number.isNaN(parsedExpiry.getTime())) {
      setError(t("请选择有效的到期时间。"));
      return;
    }
    if (parsedExpiry.getTime() <= Date.now()) {
      setError(t("到期时间必须晚于当前时间。"));
      return;
    }
    const numericSkuLimit = Number(skuLimit);
    const parsedSkuLimit = unlimitedSkus ? null : numericSkuLimit;
    if (
      !unlimitedSkus
      && (!skuLimit.trim() || !Number.isInteger(numericSkuLimit) || numericSkuLimit < 0)
    ) {
      setError(t("SKU 上限必须是大于或等于 0 的整数。"));
      return;
    }

    setSaving(true);
    setError("");
    try {
      await api.updateTenantSubscription(tenant.id, {
        subscription_tier: tier,
        subscription_expires_at: parsedExpiry.toISOString(),
        sku_limit: parsedSkuLimit,
      });
      await onSaved();
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("等级保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={onOpenChange}>
      <Dialog.Content className="merchant-subscription-dialog">
        <Dialog.Title>{t("设置商家等级")}</Dialog.Title>
        <Dialog.Description>
          {t("为“{name}”设置等级与有效期。到期后会在商家列表中提醒。", {
            name: tenant?.name ?? "",
          })}
        </Dialog.Description>

        <div className="subscription-tier-grid">
          {SUBSCRIPTION_TIERS.map((item) => (
            <button
              key={item.value}
              type="button"
              className={tier === item.value ? "subscription-tier-card is-selected" : "subscription-tier-card"}
              onClick={() => chooseTier(item.value)}
            >
              <Badge size="1" color={SUBSCRIPTION_TIER_COLORS[item.value]} variant="soft">
                {t(item.label)}
              </Badge>
              <Text as="span" size="1" color="gray">{t(item.description)}</Text>
            </button>
          ))}
        </div>

        <div className="subscription-expiry-panel">
          <div className="subscription-expiry-heading">
            <div>
              <Text as="div" size="2" weight="medium">{t("过期时间")}</Text>
              <Text as="div" size="1" color="gray">
                {t("试用默认 1 个月，正式等级默认 1 年；也可以直接修改日期。")}
              </Text>
            </div>
            {tenant ? (
              <Badge
                color={tenant.subscription_status === "expired" ? "red" : tenant.subscription_status === "expiring_soon" ? "amber" : "jade"}
                variant="soft"
              >
                {t(subscriptionStatusLabel(tenant.subscription_status))}
              </Badge>
            ) : null}
          </div>

          <TextField.Root
            type="datetime-local"
            value={expiresAt}
            min={toDateTimeLocal(new Date(Date.now() + 60_000))}
            onChange={(event) => {
              setExpiresAt(event.currentTarget.value);
              setError("");
            }}
          />

          <div className="subscription-term-actions" aria-label={t("快速设置期限")}>
            <Text size="1" color="gray">{t("从今天起")}</Text>
            <Button type="button" size="1" variant="soft" color="gray" onClick={() => applyTerm(1)}>
              {t("1 个月")}
            </Button>
            <Button type="button" size="1" variant="soft" color="gray" onClick={() => applyTerm(3)}>
              {t("3 个月")}
            </Button>
            <Button type="button" size="1" variant="soft" color="gray" onClick={() => applyTerm(12)}>
              {t("1 年")}
            </Button>
            <Button type="button" size="1" variant="soft" color="gray" onClick={() => applyTerm(24)}>
              {t("2 年")}
            </Button>
          </div>

          {tenant ? (
            <Text size="1" color="gray">
              {t("本期开始：{date}", { date: dateTime(tenant.subscription_started_at) })}
            </Text>
          ) : null}
        </div>

        <div className="subscription-quota-panel">
          <div className="subscription-expiry-heading">
            <div>
              <Text as="div" size="2" weight="medium">{t("SKU 数量上限")}</Text>
              <Text as="div" size="1" color="gray">
                {t("按 SKU 记录计数，商品数量不参与配额计算。")}
              </Text>
            </div>
            <Badge color="blue" variant="soft">
              {t("已使用 {count}", { count: (tenant?.sku_count ?? 0).toLocaleString() })}
            </Badge>
          </div>

          <div className="subscription-quota-controls">
            <TextField.Root
              type="number"
              min="0"
              step="1"
              value={skuLimit}
              disabled={unlimitedSkus}
              placeholder={t("输入 SKU 上限")}
              onChange={(event) => {
                setSkuLimit(event.currentTarget.value);
                setError("");
              }}
            />
            <label className="subscription-unlimited-option">
              <Checkbox
                checked={unlimitedSkus}
                onCheckedChange={(checked) => {
                  const nextUnlimited = checked === true;
                  setUnlimitedSkus(nextUnlimited);
                  if (!nextUnlimited && !skuLimit) {
                    const fallback = defaultSkuLimitForTier(tier) ?? 5_000;
                    setSkuLimit(String(fallback));
                  }
                  setError("");
                }}
              />
              <Text size="2">{t("不限制 SKU 数量")}</Text>
            </label>
          </div>

          <div className="subscription-term-actions">
            <Button
              type="button"
              size="1"
              variant="soft"
              color="gray"
              onClick={() => {
                const nextLimit = defaultSkuLimitForTier(tier);
                setUnlimitedSkus(nextLimit === null);
                setSkuLimit(nextLimit === null ? "" : String(nextLimit));
                setError("");
              }}
            >
              {t("恢复当前档位默认值")}
            </Button>
            <Text size="1" color="gray">
              {t("当前档位默认：{limit}", {
                limit: t(skuLimitLabel(defaultSkuLimitForTier(tier))),
              })}
            </Text>
          </div>

          {!unlimitedSkus
          && Number.isFinite(Number(skuLimit))
          && Number(skuLimit) < (tenant?.sku_count ?? 0) ? (
            <Callout.Root color="amber" size="1">
              <Callout.Icon><WarningCircle /></Callout.Icon>
              <Callout.Text>
                {t("新的上限低于当前 SKU 数量；现有 SKU 不会被删除，但将无法继续新增。")}
              </Callout.Text>
            </Callout.Root>
          ) : null}
        </div>

        {error ? (
          <Callout.Root color="red">
            <Callout.Icon><WarningCircle /></Callout.Icon>
            <Callout.Text>{error}</Callout.Text>
          </Callout.Root>
        ) : null}

        <div className="dialog-actions">
          <Dialog.Close>
            <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
          </Dialog.Close>
          <Button type="button" loading={saving} onClick={() => void save()}>
            {t("保存等级")}
          </Button>
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function TenantModuleDialog({
  tenant,
  onOpenChange,
  onSaved,
}: {
  tenant: Tenant | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [selected, setSelected] = useState<Set<TenantModuleCode>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!tenant) return;
    setSelected(new Set(enabledTenantModules(tenant)));
    setError("");
  }, [tenant]);

  const toggle = (code: TenantModuleCode, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(code);
      else next.delete(code);
      return next;
    });
  };

  const save = async () => {
    if (!tenant || saving) return;
    setSaving(true);
    setError("");
    try {
      const modules = TENANT_MODULES
        .map((module) => module.code)
        .filter((code) => selected.has(code));
      await api.updateTenantModules(tenant.id, modules);
      await onSaved();
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("模块权限保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={onOpenChange}>
      <Dialog.Content className="merchant-module-dialog">
        <Dialog.Title>{t("{name} 的可见模块", { name: tenant?.name ?? "" })}</Dialog.Title>
        <Dialog.Description>
          {t("勾选商家后台可以使用的模块。概览、账户安全和商品前台始终保留。")}
        </Dialog.Description>

        <div className="merchant-module-toolbar">
          <Text size="2" color="gray">
            {t("已选择 {count} 个模块", { count: selected.size })}
          </Text>
          <div>
            <Button
              type="button"
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => setSelected(new Set(DEFAULT_TENANT_MODULES))}
            >
              {t("全选")}
            </Button>
            <Button
              type="button"
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => setSelected(new Set())}
            >
              {t("清空")}
            </Button>
          </div>
        </div>

        <div className="merchant-module-grid">
          {TENANT_MODULES.map((module) => {
            const checked = selected.has(module.code);
            return (
              <label
                className={checked ? "merchant-module-option is-selected" : "merchant-module-option"}
                key={module.code}
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={(value) => toggle(module.code, value === true)}
                />
                <span>
                  <Text as="div" size="2" weight="medium">{t(module.label)}</Text>
                  <Text as="div" size="1" color="gray">{t(module.description)}</Text>
                </span>
              </label>
            );
          })}
        </div>

        {error ? (
          <Callout.Root color="red">
            <Callout.Icon><WarningCircle /></Callout.Icon>
            <Callout.Text>{error}</Callout.Text>
          </Callout.Root>
        ) : null}

        <div className="dialog-actions">
          <Dialog.Close>
            <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
          </Dialog.Close>
          <Button type="button" loading={saving} onClick={() => void save()}>
            {t("保存可见模块")}
          </Button>
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function MerchantOwnerDialog({
  tenant,
  onOpenChange,
  onSaved,
}: {
  tenant: Tenant | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenant) return;
    const data = new FormData(event.currentTarget);
    const email = String(data.get("login_email") || "").trim().toLowerCase();
    const payload: MerchantOwnerAccountPayload = {
      display_name: tenant.name,
      login_identifier: email,
      email,
      password: String(data.get("password") || ""),
    };
    setSaving(true);
    setError("");
    try {
      await api.updateTenant(tenant.id, {
        name: tenant.name,
        contact_email: email,
        active: true,
      });
      const owner = await api.provisionMerchantOwner(tenant.id, payload);
      setResult(owner);
      await onSaved().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("登录账号开通失败。"));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setResult(null);
      setError("");
    }
    onOpenChange(open);
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
      <Dialog.Content className="merchant-dialog">
        <Dialog.Title>{t("开通商家登录账号")}</Dialog.Title>
        <Dialog.Description>
          {t("为“{name}”设置登录邮箱和初始密码。", { name: tenant?.name ?? "" })}
        </Dialog.Description>
        {result ? (
          <div className="dialog-form">
            <Callout.Root color="green">
              <Callout.Icon><CheckCircle /></Callout.Icon>
              <Callout.Text>{t("登录账号已开通，可以立即使用。")}</Callout.Text>
            </Callout.Root>
            <Text size="2" color="gray">
              {t("登录邮箱：{email}", { email: result.email || result.login_identifier || "—" })}
            </Text>
            <div className="dialog-actions">
              <Dialog.Close><Button>{t("完成")}</Button></Dialog.Close>
            </div>
          </div>
        ) : (
          <form className="dialog-form" onSubmit={submit} key={tenant?.id}>
            <label className="field-group">
              <Text size="2" weight="medium">{t("登录邮箱")} *</Text>
              <TextField.Root
                name="login_email"
                type="email"
                required
                maxLength={320}
                autoComplete="email"
                autoCapitalize="none"
                placeholder="name@company.com"
              />
            </label>
            <label className="field-group">
              <Text size="2" weight="medium">{t("初始密码")} *</Text>
              <InitialPasswordField />
            </label>
            {error ? (
              <Callout.Root color="red">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
              </Dialog.Close>
              <Button type="submit" loading={saving}>
                <UserPlus />
                {t("确认开通")}
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}

function TenantFormDialog({
  tenant,
  onOpenChange,
  onChanged,
}: {
  tenant: Tenant | "new" | null;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const { t } = useLocale();
  const current = tenant && tenant !== "new" ? tenant : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [createdTenant, setCreatedTenant] = useState<Tenant | null>(null);
  const [createdOwner, setCreatedOwner] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get("name") || "").trim();
    const loginEmail = current
      ? ""
      : String(data.get("login_email") || "").trim().toLowerCase();
    if (!current && !LOGIN_EMAIL_PATTERN.test(loginEmail)) {
      setError(t("请输入有效的登录邮箱，例如 name@company.com。"));
      return;
    }
    setSaving(true);
    setError("");

    try {
      if (current) {
        await api.updateTenant(current.id, {
          name,
          contact_email: current.owner_account?.email || current.contact_email || "",
          active: String(data.get("status") || "active") === "active",
        });
        await onChanged();
        onOpenChange(false);
        return;
      }

      const password = String(data.get("password") || "");
      const tenantPayload: TenantPayload = {
        name,
        contact_email: loginEmail,
        active: true,
      };

      let merchant = createdTenant;
      let merchantWasCreated = false;
      if (merchant) {
        merchant = await api.updateTenant(merchant.id, tenantPayload);
      } else {
        merchant = await api.createTenant(tenantPayload);
        merchantWasCreated = true;
        setCreatedTenant(merchant);
      }

      let owner: MerchantOwnerAccount;
      try {
        owner = await api.provisionMerchantOwner(merchant.id, {
          display_name: name,
          login_identifier: loginEmail,
          email: loginEmail,
          password,
        });
      } catch (caught) {
        if (merchantWasCreated) {
          await onChanged().catch(() => undefined);
        }
        const reason = caught instanceof Error ? caught.message : t("登录账号开通失败。");
        setError(t("商家已创建，但登录账号开通失败：{reason}", { reason }));
        return;
      }
      setCreatedOwner(owner);
      await onChanged().catch(() => undefined);
    } catch (caught) {
      setError(
        apiErrorCode(caught) === "TENANT_SLUG_EXISTS"
          ? t("商家前台地址暂时发生冲突，请再次提交，系统会自动分配新地址。")
          : caught instanceof Error ? caught.message : t("商家保存失败。"),
      );
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setError("");
      setCreatedTenant(null);
      setCreatedOwner(null);
    }
    onOpenChange(open);
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
      <Dialog.Content className="merchant-dialog">
        <Dialog.Title>{t(current ? "编辑商家" : "新增商家")}</Dialog.Title>
        <Dialog.Description>
          {t(current ? "修改商家名称或状态。" : "填写三项信息即可创建商家并开通登录账号。")}
        </Dialog.Description>

        {createdOwner ? (
          <div className="dialog-form">
            <Callout.Root color="green">
              <Callout.Icon><CheckCircle /></Callout.Icon>
              <Callout.Text>{t("商家已创建，可以立即登录。")}</Callout.Text>
            </Callout.Root>
            <Text size="2" color="gray">
              {t("登录邮箱：{email}", {
                email: createdOwner.email || createdOwner.login_identifier || "—",
              })}
            </Text>
            {createdTenant ? (
              <Text size="2" color="gray" className="mono-text">
                {t("前台地址：/{slug}", { slug: createdTenant.slug })}
              </Text>
            ) : null}
            <div className="dialog-actions">
              <Dialog.Close><Button>{t("完成")}</Button></Dialog.Close>
            </div>
          </div>
        ) : (
          <form className="dialog-form" onSubmit={submit} key={current?.id || "new"}>
            <label className="field-group">
              <Text size="2" weight="medium">{t("商家名称")} *</Text>
              <TextField.Root
                name="name"
                required
                maxLength={200}
                defaultValue={current?.name}
                placeholder={t("例如 海岸家居")}
              />
            </label>

            {current ? (
              <label className="field-group">
                <Text size="2" weight="medium">{t("状态")}</Text>
                <Select.Root name="status" defaultValue={current.status}>
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="active">{t("启用")}</Select.Item>
                    <Select.Item value="inactive">{t("停用")}</Select.Item>
                  </Select.Content>
                </Select.Root>
              </label>
            ) : (
              <>
                <label className="field-group">
                  <Text size="2" weight="medium">{t("登录邮箱")} *</Text>
                  <TextField.Root
                    name="login_email"
                    type="email"
                    required
                    pattern={LOGIN_EMAIL_PATTERN.source}
                    maxLength={320}
                    autoComplete="email"
                    autoCapitalize="none"
                    placeholder="name@company.com"
                    title={t("请输入有效的登录邮箱，例如 name@company.com。")}
                  />
                </label>
                <label className="field-group">
                  <Text size="2" weight="medium">{t("初始密码")} *</Text>
                  <InitialPasswordField />
                </label>
              </>
            )}

            {error ? (
              <Callout.Root color="red">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
              </Dialog.Close>
              <Button type="submit" loading={saving}>
                {t(current ? "保存商家" : createdTenant ? "继续开通账号" : "创建商家")}
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
