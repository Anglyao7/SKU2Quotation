import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Heading,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  CheckCircle,
  CaretLeft,
  CaretRight,
  Eye,
  EyeSlash,
  FileText,
  CurrencyDollar,
  Plus,
  Power,
  SlidersHorizontal,
  UserPlus,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  createCustomerSubaccount,
  CoreApiError,
  getCustomerSubaccountDashboard,
  listCustomerSubaccountOrders,
  updateCustomerSubaccountStatus,
  updateCustomerSubaccountAccess,
  getCustomerSubaccountPricing,
  updateCustomerSubaccountPricing,
  updateCustomerSubaccountProductPricing,
  clearCustomerSubaccountProductPricing,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { money } from "../../lib/format";
import type {
  CustomerSubaccount,
  CustomerSubaccountDashboard,
  CustomerSubaccountCapability,
  CustomerSubaccountOrderPage,
  SubaccountPricingMode,
  SubaccountPricingPage,
} from "../types";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

const ORDER_PAGE_SIZE = 20;
const SUBACCOUNT_CAPABILITIES: Array<{ code: CustomerSubaccountCapability; label: string }> = [
  { code: "catalog", label: "浏览商品" },
  { code: "submit_orders", label: "提交报价" },
  { code: "view_orders", label: "查看本人订单" },
];

function isPasswordPolicyError(reason: unknown): boolean {
  if (!(reason instanceof CoreApiError) || !reason.details || typeof reason.details !== "object") return false;
  const detail = (reason.details as { detail?: unknown }).detail;
  return Boolean(detail && typeof detail === "object" && (detail as { code?: unknown }).code === "PASSWORD_POLICY_VIOLATION");
}

export function CustomerAccountsPage() {
  const { t } = useLocale();
  const [data, setData] = useState<CustomerSubaccountDashboard>();
  const [orders, setOrders] = useState<CustomerSubaccountOrderPage>();
  const [loading, setLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [accessEditor, setAccessEditor] = useState<CustomerSubaccount>();
  const [pricingEditor, setPricingEditor] = useState<CustomerSubaccount>();
  const [updatingId, setUpdatingId] = useState<string>();

  const load = useCallback(async (page = 1) => {
    setLoading(true);
    setError("");
    try {
      const [dashboard, orderPage] = await Promise.all([
        getCustomerSubaccountDashboard(),
        listCustomerSubaccountOrders(page, ORDER_PAGE_SIZE),
      ]);
      setData(dashboard);
      setOrders(orderPage);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("客户账号数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const updateStatus = async (account: CustomerSubaccount) => {
    if (updatingId) return;
    setUpdatingId(account.id);
    setError("");
    try {
      const updated = await updateCustomerSubaccountStatus(
        account.id,
        account.status === "active" ? "suspended" : "active",
      );
      setData((current) => current ? {
        ...current,
        activeCount: current.activeCount
          + (updated.status === "active" ? 1 : -1),
        suspendedCount: current.suspendedCount
          + (updated.status === "suspended" ? 1 : -1),
        accounts: current.accounts.map((row) => row.id === updated.id ? updated : row),
      } : current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("账号状态更新失败"));
    } finally {
      setUpdatingId(undefined);
    }
  };

  const changeOrderPage = async (page: number) => {
    if (!orders || ordersLoading || page < 1 || page === orders.page) return;
    setOrdersLoading(true);
    setError("");
    try {
      setOrders(await listCustomerSubaccountOrders(page, ORDER_PAGE_SIZE));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("订单数据加载失败"));
    } finally {
      setOrdersLoading(false);
    }
  };

  if (loading && !data) return <div className="core-workspace"><CoreLoading label={t("正在读取客户账号")} /></div>;

  return <div className="core-workspace customer-accounts-page">
    <CorePageHeading
      eyebrow={t("账户管理")}
      title={t("子账号管理")}
      description={t("管理子账号、价格规则和成交数据。")}
      actions={<Button onClick={() => setEditorOpen(true)}><UserPlus />{t("开通子账号")}</Button>}
    />
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

    <section className="customer-account-metrics" aria-label={t("子账号概览")}>
      <Metric icon={<UsersThree />} label={t("全部子账号")} value={(data?.accounts.length ?? 0).toString()} />
      <Metric icon={<CheckCircle />} label={t("当前已开通")} value={(data?.activeCount ?? 0).toString()} tone="jade" />
      <Metric icon={<Eye />} label={t("近期开单申请")} value={(data?.orderCount ?? 0).toString()} />
      <Metric icon={<CurrencyDollar />} label={t("累计询价金额")} value={money(data?.orderAmount ?? 0, data?.currency || "CNY")} tone="jade" />
      <Metric icon={<CurrencyDollar />} label={t("今日成交额")} value={money(data?.todayOrderAmount ?? 0, data?.currency || "CNY")} tone="jade" />
      <Metric icon={<CheckCircle />} label={t("本月成交额")} value={money(data?.monthOrderAmount ?? 0, data?.currency || "CNY")} />
    </section>

    <section className="customer-account-grid">
      <Card className="customer-account-panel">
        <div className="customer-account-panel-heading">
          <div><Text size="1" color="gray">{t("账号列表")}</Text><Heading size="5">{t("已开通的子账号")}</Heading></div>
          <Text size="2" color="gray">{t("主账号可管理价格、启停和订单数据")}</Text>
        </div>
        {data?.accounts.length ? <div className="customer-account-list">
          {data.accounts.map((account) => <article className="customer-account-row" key={account.id}>
            <div className="customer-account-identity">
              <span className="customer-account-avatar">{account.displayName.slice(0, 2).toUpperCase()}</span>
              <span><strong>{account.displayName}</strong><small>{account.loginIdentifier}{account.email ? ` · ${account.email}` : ""}</small><small className="customer-account-pricing-summary">+{Number(account.markupPercent || 0).toLocaleString()}% · {t("{count} 个单品规则", { count: account.overrideCount })}</small></span>
            </div>
            <div className="customer-account-signal">
              <small>{t("最近访问")}</small><strong>{account.lastLoginAt ? coreDate(account.lastLoginAt) : t("尚未登录")}</strong>
              <span>{t("近 30 天 {count} 次", { count: account.loginCount30d })}</span>
            </div>
            <div className="customer-account-signal">
              <small>{t("订单申请")}</small><strong>{t("{count} 笔", { count: account.orderCount })}</strong>
              <span>{money(account.orderAmount, data?.currency || "CNY")}{account.lastOrderAt ? ` · ${t("最近 {date}", { date: coreDate(account.lastOrderAt) })}` : ""}</span>
            </div>
            <div className="customer-account-signal">
              <small>{t("今日成交")}</small><strong>{money(account.todayOrderAmount, data?.currency || "CNY")}</strong>
              <span>{t("{count} 笔", { count: account.todayOrderCount })} · {t("本月 {amount}", { amount: money(account.monthOrderAmount, data?.currency || "CNY") })}</span>
            </div>
            <Badge color={account.status === "active" ? "jade" : "gray"}>{t(account.status === "active" ? "已开通" : "已停用")}</Badge>
            <div className="customer-account-actions">
              <Button size="1" variant="soft" color="gray" onClick={() => setAccessEditor(account)}><SlidersHorizontal />{t("权限")}</Button>
              <Button size="1" variant="soft" color="gray" onClick={() => setPricingEditor(account)}><CurrencyDollar />{t("价格")}</Button>
              <Button
                size="1"
                variant="soft"
                color={account.status === "active" ? "gray" : "jade"}
                loading={updatingId === account.id}
                onClick={() => void updateStatus(account)}
              ><Power />{t(account.status === "active" ? "停用" : "重新开通")}</Button>
            </div>
          </article>)}
        </div> : <CoreEmpty
          title={t("还没有子账号")}
          description={t("为团队成员开通独立登录账号，并在这里管理可见范围。")}
          action={<Button variant="soft" onClick={() => setEditorOpen(true)}><Plus />{t("开通第一个子账号")}</Button>}
        />}
      </Card>

      <Card className="customer-account-side-note">
        <span className="customer-account-side-icon"><Eye size={24} /></span>
        <Text size="1" color="gray">{t("主账号管理范围")}</Text>
        <Heading size="4">{t("价格、商品和订单一处管理")}</Heading>
        <Text size="2" color="gray">{t("主账号可以设置统一加价、单品价格，并查看每个子账号的访问与成交数据。")}</Text>
        <ul>
          <li>{t("子账号使用受限后台，不显示原价格、供应商与供应链")}</li>
          <li>{t("订单和金额按照提交账号自动归属")}</li>
          <li>{t("停用后立即失去门户访问")}</li>
        </ul>
      </Card>
    </section>

    <Card className="customer-order-panel">
      <div className="customer-account-panel-heading">
        <div><Text size="1" color="gray">{t("只读订单数据")}</Text><Heading size="5">{t("全部子账号订单")}</Heading></div>
        <Badge color="gray"><FileText />{t("共 {count} 笔 · 不支持修改", { count: orders?.total ?? 0 })}</Badge>
      </div>
      {orders?.items.length ? <div className={`customer-order-table${ordersLoading ? " is-loading" : ""}`} aria-busy={ordersLoading}>
        <div className="customer-order-table-head"><span>{t("订单")}</span><span>{t("提交账号")}</span><span>{t("客户信息")}</span><span>{t("金额")}</span><span>{t("状态")}</span><span>{t("提交时间")}</span></div>
        {orders.items.map((order) => <div className="customer-order-table-row" key={order.id}>
          <span className="mono-text">{order.quoteNumber}</span>
          <span>{order.submittedByName}</span>
          <span>{order.customerCompany || order.customerName}</span>
          <strong>{money(order.totalAmount, order.currency)}</strong>
          <Badge color={order.status === "PENDING_CONFIRMATION" ? "amber" : order.status === "CONFIRMED" ? "jade" : "gray"}>{t(orderStatusLabel[order.status] ?? order.status)}</Badge>
          <span>{coreDate(order.createdAt)}</span>
        </div>)}
      </div> : <CoreEmpty title={t("子账号尚未提交订单")} description={t("订单会在子账号从商品前台提交报价申请后自动显示在这里。")} />}
      {orders && orders.total > orders.pageSize ? <div className="customer-order-pagination">
        <Text size="2" color="gray">{t("第 {page} / {pages} 页", { page: orders.page, pages: Math.ceil(orders.total / orders.pageSize) })}</Text>
        <div>
          <Button size="1" variant="soft" color="gray" disabled={ordersLoading || orders.page <= 1} onClick={() => void changeOrderPage(orders.page - 1)}><CaretLeft />{t("上一页")}</Button>
          <Button size="1" variant="soft" color="gray" disabled={ordersLoading || orders.page >= Math.ceil(orders.total / orders.pageSize)} onClick={() => void changeOrderPage(orders.page + 1)}>{t("下一页")}<CaretRight /></Button>
        </div>
      </div> : null}
    </Card>

    {editorOpen ? <CustomerAccountCreateDialog
      onClose={() => setEditorOpen(false)}
      onCreated={async () => { setEditorOpen(false); await load(1); }}
    /> : null}
    {accessEditor ? <CustomerAccountAccessDialog
      account={accessEditor}
      onClose={() => setAccessEditor(undefined)}
      onSaved={(updated) => {
        setData((current) => current ? {
          ...current,
          accounts: current.accounts.map((row) => row.id === updated.id ? updated : row),
        } : current);
        setAccessEditor(undefined);
      }}
    /> : null}
    {pricingEditor ? <SubaccountPricingDialog
      account={pricingEditor}
      onClose={() => setPricingEditor(undefined)}
      onSaved={(policy) => {
        setData((current) => current ? {
          ...current,
          accounts: current.accounts.map((row) => row.id === pricingEditor.id ? {
            ...row,
            markupPercent: policy.markupPercent,
            overrideCount: policy.overrideCount,
          } : row),
        } : current);
      }}
    /> : null}
  </div>;
}

function Metric({ icon, label, value, tone = "" }: { icon: ReactNode; label: string; value: string; tone?: string }) {
  return <Card className={`customer-account-metric ${tone}`}><span>{icon}</span><div><Text size="2" color="gray">{label}</Text><strong>{value}</strong></div></Card>;
}

function CustomerAccountCreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const { t } = useLocale();
  const [displayName, setDisplayName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [capabilities, setCapabilities] = useState<Set<CustomerSubaccountCapability>>(
    new Set(SUBACCOUNT_CAPABILITIES.map((item) => item.code)),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createCustomerSubaccount({
        displayName: displayName.trim(),
        loginIdentifier: identifier.trim(),
        password,
        email: email.trim() || undefined,
        capabilities: SUBACCOUNT_CAPABILITIES.map((item) => item.code).filter((code) => capabilities.has(code)),
      });
      await onCreated();
    } catch (caught) {
      setError(isPasswordPolicyError(caught) ? t("密码必须是 6 位数字。") : caught instanceof Error ? caught.message : t("子账号创建失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <Dialog.Title>{t("开通子账号")}</Dialog.Title>
        <Dialog.Description>{t("创建后，对方使用账号密码登录商品后台，并按你配置的范围使用功能。")}</Dialog.Description>
        <div className="customer-account-form-grid">
          <label><Text size="2" weight="medium">{t("子账号名称")}</Text><TextField.Root value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder={t("例如 上海澄明贸易") } required maxLength={120} /></label>
          <label><Text size="2" weight="medium">{t("登录账号")}</Text><TextField.Root value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={t("账号、邮箱或手机号") } required maxLength={320} autoCapitalize="none" /></label>
          <label><Text size="2" weight="medium">{t("联系邮箱（可选）")}</Text><TextField.Root value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t("name@example.com") } type="email" maxLength={320} /></label>
          <label>
            <Text size="2" weight="medium">{t("初始密码")}</Text>
            <TextField.Root
              value={password}
              onChange={(event) => setPassword(event.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder={t("请输入 6 位数字")}
              type={passwordVisible ? "text" : "password"}
              inputMode="numeric"
              pattern="[0-9]{6}"
              required
              minLength={6}
              maxLength={6}
              autoComplete="new-password"
            >
              <TextField.Slot side="right">
                <button
                  type="button"
                  className="login-password-toggle"
                  aria-label={t(passwordVisible ? "隐藏密码" : "显示密码")}
                  aria-pressed={passwordVisible}
                  onClick={() => setPasswordVisible((current) => !current)}
                >
                  {passwordVisible ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </TextField.Slot>
            </TextField.Root>
          </label>
        </div>
        <div className="subaccount-access-options">
          {SUBACCOUNT_CAPABILITIES.map((item) => <label key={item.code}>
            <Checkbox
              checked={capabilities.has(item.code)}
              disabled={item.code === "catalog"}
              onCheckedChange={(checked) => setCapabilities((current) => {
                const next = new Set(current);
                if (checked === true) next.add(item.code); else next.delete(item.code);
                return next;
              })}
            />
            <Text size="2">{t(item.label)}</Text>
          </label>)}
        </div>
        <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("请将初始账号密码通过可靠渠道交给客户；密码不会在创建后再次显示。")}</div>
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button type="submit" loading={saving}><UserPlus />{t(saving ? "正在开通" : "确认开通")}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

function CustomerAccountAccessDialog({
  account,
  onClose,
  onSaved,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
  onSaved: (updated: CustomerSubaccount) => void;
}) {
  const { t } = useLocale();
  const [selected, setSelected] = useState<Set<CustomerSubaccountCapability>>(
    new Set(account.capabilities),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const capabilities = SUBACCOUNT_CAPABILITIES
        .map((item) => item.code)
        .filter((code) => selected.has(code));
      onSaved(await updateCustomerSubaccountAccess(account.id, capabilities));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号权限保存失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-access-dialog">
      <Dialog.Title>{t("{name} 的可见范围", { name: account.displayName })}</Dialog.Title>
      <div className="subaccount-access-options">
        {SUBACCOUNT_CAPABILITIES.map((item) => <label key={item.code}>
          <Checkbox
            checked={selected.has(item.code)}
            disabled={item.code === "catalog"}
            onCheckedChange={(checked) => setSelected((current) => {
              const next = new Set(current);
              if (checked === true) next.add(item.code); else next.delete(item.code);
              return next;
            })}
          />
          <Text size="2">{t(item.label)}</Text>
        </label>)}
      </div>
      {error ? <Text color="red" size="2">{error}</Text> : null}
      <div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button loading={saving} onClick={() => void save()}>{t("保存权限")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}

function SubaccountPricingDialog({
  account,
  onClose,
  onSaved,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
  onSaved: (policy: { markupPercent: number; overrideCount: number }) => void;
}) {
  const { t } = useLocale();
  const [data, setData] = useState<SubaccountPricingPage>();
  const [markup, setMarkup] = useState(String(account.markupPercent || 0));
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingProduct, setEditingProduct] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await getCustomerSubaccountPricing(account.id, query, page, 30);
      setData(next);
      setMarkup(String(next.policy.markupPercent));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("价格规则加载失败"));
    } finally {
      setLoading(false);
    }
  }, [account.id, page, query, t]);

  useEffect(() => { void load(); }, [load]);

  const saveMarkup = async () => {
    const value = Number(markup);
    if (!Number.isFinite(value) || value < 0 || value > 100000) {
      setError(t("统一加价必须是 0 到 100000 之间的数字"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const policy = await updateCustomerSubaccountPricing(account.id, value);
      setData((current) => current ? { ...current, policy } : current);
      onSaved(policy);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("价格规则保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const saveProductRule = async (
    productId: string,
    mode: SubaccountPricingMode,
    rawValue: string,
  ) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    setEditingProduct(productId);
    setError("");
    try {
      const item = await updateCustomerSubaccountProductPricing(account.id, productId, mode, value);
      setData((current) => current ? {
        ...current,
        items: current.items.map((row) => row.productId === item.productId ? item : row),
        policy: { ...current.policy, overrideCount: current.items.some((row) => row.productId === item.productId && row.overrideMode) ? current.policy.overrideCount : current.policy.overrideCount + 1 },
      } : current);
      onSaved({ markupPercent: Number(markup) || 0, overrideCount: (data?.policy.overrideCount || 0) + (data?.items.find((row) => row.productId === productId)?.overrideMode ? 0 : 1) });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("单品价格保存失败"));
    } finally {
      setEditingProduct(undefined);
    }
  };

  const clearProductRule = async (productId: string) => {
    setEditingProduct(productId);
    try {
      await clearCustomerSubaccountProductPricing(account.id, productId);
      setData((current) => current ? {
        ...current,
        items: current.items.map((row) => row.productId === productId
          ? { ...row, overrideMode: undefined, overrideValue: undefined, effectivePriceFrom: Number((row.basePriceFrom * (1 + (current.policy.markupPercent / 100))).toFixed(2)), effectivePriceTo: Number((row.basePriceTo * (1 + (current.policy.markupPercent / 100))).toFixed(2)) }
          : row),
        policy: { ...current.policy, overrideCount: Math.max(0, current.policy.overrideCount - 1) },
      } : current);
      onSaved({ markupPercent: Number(markup) || 0, overrideCount: Math.max(0, (data?.policy.overrideCount || 1) - 1) });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("单品价格清除失败"));
    } finally {
      setEditingProduct(undefined);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-pricing-dialog">
      <Dialog.Title>{t("{name} 的价格设置", { name: account.displayName })}</Dialog.Title>
      <Dialog.Description>{t("统一加价作用于全部商品；单品规则优先。子账号只会看到最终价格。")}</Dialog.Description>
      <section className="subaccount-pricing-policy">
        <label><Text size="2" weight="medium">{t("统一加价（%）")}</Text><TextField.Root type="number" min="0" max="100000" step="0.1" value={markup} onChange={(event) => setMarkup(event.target.value)} /></label>
        <Button loading={saving} onClick={() => void saveMarkup()}><CurrencyDollar />{t("应用到所有商品")}</Button>
        <Text size="1" color="gray">{t("当前已有 {count} 个单品规则", { count: data?.policy.overrideCount ?? account.overrideCount })}</Text>
      </section>
      <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索商品名称或编码") } />
      {error ? <Text color="red" size="2">{error}</Text> : null}
      {loading ? <CoreLoading label={t("正在读取商品价格")} /> : data?.items.length ? <div className="subaccount-pricing-table">
        <div className="subaccount-pricing-table-head"><span>{t("商品")}</span><span>{t("主账号价格")}</span><span>{t("子账号价格")}</span><span>{t("单品规则")}</span></div>
        {data.items.map((item) => <SubaccountPricingRow key={item.productId} item={item} busy={editingProduct === item.productId} onSave={saveProductRule} onClear={clearProductRule} />)}
      </div> : <CoreEmpty title={t("没有匹配商品")} description={t("先确认商品已经发布到前台。")} />}
      {data && data.total > data.pageSize ? <div className="subaccount-pricing-pagination">
        <Text size="1" color="gray">{t("第 {page} / {pages} 页", { page: data.page, pages: Math.ceil(data.total / data.pageSize) })}</Text>
        <div>
          <Button size="1" variant="soft" color="gray" disabled={loading || data.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><CaretLeft />{t("上一页")}</Button>
          <Button size="1" variant="soft" color="gray" disabled={loading || data.page >= Math.ceil(data.total / data.pageSize)} onClick={() => setPage((current) => Math.min(Math.ceil(data.total / data.pageSize), current + 1))}>{t("下一页")}<CaretRight /></Button>
        </div>
      </div> : null}
      <div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={onClose}>{t("关闭")}</Button><Button onClick={() => { if (data) onSaved(data.policy); onClose(); }}>{t("完成")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}

function SubaccountPricingRow({
  item,
  busy,
  onSave,
  onClear,
}: {
  item: SubaccountPricingPage["items"][number];
  busy: boolean;
  onSave: (productId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClear: (productId: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [mode, setMode] = useState<SubaccountPricingMode>(item.overrideMode || "MARKUP_PERCENT");
  const [value, setValue] = useState(item.overrideValue == null ? "" : String(item.overrideValue));
  useEffect(() => {
    setMode(item.overrideMode || "MARKUP_PERCENT");
    setValue(item.overrideValue == null ? "" : String(item.overrideValue));
  }, [item.overrideMode, item.overrideValue]);
  return <div className="subaccount-pricing-table-row">
    <div><strong>{item.productName}</strong><small>{item.productCode || "—"} · {t("{count} 个 SKU", { count: item.skuCount })}</small></div>
    <span>{item.basePriceFrom === item.basePriceTo ? `${item.currency} ${item.basePriceFrom}` : `${item.currency} ${item.basePriceFrom}–${item.basePriceTo}`}</span>
    <strong>{item.effectivePriceFrom === item.effectivePriceTo ? `${item.currency} ${item.effectivePriceFrom}` : `${item.currency} ${item.effectivePriceFrom}–${item.effectivePriceTo}`}</strong>
    <div className="subaccount-pricing-rule-editor">
      <select value={mode} onChange={(event) => setMode(event.target.value as SubaccountPricingMode)} aria-label={t("单品价格方式")}><option value="MARKUP_PERCENT">{t("加价百分比")}</option><option value="FIXED_PRICE">{t("固定价格")}</option></select>
      <TextField.Root size="1" type="number" min="0" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} placeholder="—" aria-label={t("单品价格数值")} />
      <Button size="1" loading={busy} onClick={() => void onSave(item.productId, mode, value)}>{t("应用")}</Button>
      {item.overrideMode ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void onClear(item.productId)}>{t("恢复")}</Button> : null}
    </div>
  </div>;
}
