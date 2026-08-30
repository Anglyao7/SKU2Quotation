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
  CaretDown,
  CaretLeft,
  CaretRight,
  Eye,
  EyeSlash,
  FileText,
  CurrencyDollar,
  Key,
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
  getCustomerSubaccountOrder,
  listCategories,
  resetCustomerSubaccountPassword,
  updateCustomerSubaccountPricing,
  updateCustomerSubaccountProductPricing,
  updateCustomerSubaccountCategoryPricing,
  clearCustomerSubaccountCategoryPricing,
  clearCustomerSubaccountProductPricing,
  updateCustomerSubaccountSkuPricing,
  clearCustomerSubaccountSkuPricing,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { money } from "../../lib/format";
import type {
  CustomerSubaccount,
  CustomerSubaccountDashboard,
  CustomerSubaccountModule,
  CustomerSubaccountOrderPage,
  CustomerSubaccountOrderDetail,
  ProductCategory,
  SubaccountPricingMode,
  SubaccountPricingPage,
  SubaccountProductPricingItem,
} from "../types";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

const ORDER_PAGE_SIZE = 20;
const SUBACCOUNT_MODULES: Array<{
  code: CustomerSubaccountModule;
  label: string;
  description: string;
}> = [
  { code: "products", label: "商品与目录", description: "只读查看商品、SKU 与前台目录" },
  { code: "inquiries", label: "询盘", description: "客户需求与询盘处理" },
  { code: "quotations", label: "报价", description: "报价制作与订单跟进" },
  { code: "announcements", label: "公告", description: "发布前台公告" },
  { code: "support", label: "客户沟通", description: "查看并回复客户消息" },
];
const ALL_SUBACCOUNT_MODULES = SUBACCOUNT_MODULES.map((item) => item.code);

function isPasswordPolicyError(reason: unknown): boolean {
  if (!(reason instanceof CoreApiError) || !reason.details || typeof reason.details !== "object") return false;
  const detail = (reason.details as { detail?: unknown }).detail;
  return Boolean(detail && typeof detail === "object" && (detail as { code?: unknown }).code === "PASSWORD_POLICY_VIOLATION");
}

function countryFlag(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(normalized)) return "🌐";
  return String.fromCodePoint(
    ...[...normalized].map((character) => 127397 + character.charCodeAt(0)),
  );
}

function countryLabel(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  return normalized ? `${countryFlag(normalized)} ${normalized}` : "—";
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
  const [passwordEditor, setPasswordEditor] = useState<CustomerSubaccount>();
  const [orderDetail, setOrderDetail] = useState<CustomerSubaccountOrderDetail>();
  const [orderDetailLoading, setOrderDetailLoading] = useState(false);
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

  const openOrder = async (orderId: string) => {
    setOrderDetailLoading(true);
    setError("");
    try {
      setOrderDetail(await getCustomerSubaccountOrder(orderId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("订单详情加载失败"));
    } finally {
      setOrderDetailLoading(false);
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
              <span><strong>{account.displayName}</strong><small>{account.loginIdentifier}{account.email ? ` · ${account.email}` : ""}</small><small className="customer-account-pricing-summary">+{Number(account.markupPercent || 0).toLocaleString()}% · {t("{count} 个单品规则", { count: account.overrideCount })} · {t("{count} 个分类规则", { count: account.categoryOverrideCount ?? 0 })} · {t("{count} 个 SKU 特价", { count: account.skuOverrideCount ?? 0 })}</small></span>
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
              <Button size="1" variant="soft" color="gray" onClick={() => setPasswordEditor(account)}><Key />{t("改密码")}</Button>
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
          <li>{t("子账号使用独立工作台，可处理自己的询价；原价格、供应商与供应链不显示")}</li>
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
        <div className="customer-order-table-head"><span>{t("订单")}</span><span>{t("提交账号")}</span><span>{t("客户信息")}</span><span>{t("国家")}</span><span>{t("金额")}</span><span>{t("状态")}</span><span>{t("提交时间")}</span></div>
        {orders.items.map((order) => <div className="customer-order-table-row" key={order.id} role="button" tabIndex={0} onClick={() => void openOrder(order.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openOrder(order.id); } }}>
          <span className="mono-text">{order.quoteNumber}</span>
          <span>{order.submittedByName}</span>
          <span>{order.customerCompany || order.customerName}</span>
          <span title={order.visitorCountryCode || undefined}>{countryLabel(order.visitorCountryCode)}</span>
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
    {passwordEditor ? <CustomerSubaccountPasswordDialog
      account={passwordEditor}
      onClose={() => setPasswordEditor(undefined)}
    /> : null}
    {orderDetail || orderDetailLoading ? <CustomerSubaccountOrderDetailDialog
      detail={orderDetail}
      loading={orderDetailLoading}
      onClose={() => { setOrderDetail(undefined); setOrderDetailLoading(false); }}
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
            categoryOverrideCount: policy.categoryOverrideCount,
            skuOverrideCount: policy.skuOverrideCount,
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
        modules: ALL_SUBACCOUNT_MODULES,
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
        <Dialog.Description>{t("对方使用账号密码登录同一套商品工作台；密码可在输入时显示，后续也可以由主账号重新设置。")}</Dialog.Description>
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
        <div className="customer-account-dialog-note"><SlidersHorizontal size={18} />{t("默认开放全部运营模块；创建后可在“权限”中逐项收窄。")}</div>
        <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("请将初始账号密码通过可靠渠道交给客户；密码不会在创建后再次显示。")}</div>
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button type="submit" loading={saving}><UserPlus />{t(saving ? "正在开通" : "确认开通")}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

function CustomerSubaccountPasswordDialog({
  account,
  onClose,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(password)) {
      setError(t("密码必须是 6 位数字。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await resetCustomerSubaccountPassword(account.id, password);
      setSaved(true);
    } catch (caught) {
      setError(isPasswordPolicyError(caught) ? t("密码必须是 6 位数字。") : caught instanceof Error ? caught.message : t("密码更新失败"));
    } finally {
      setSaving(false);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog customer-password-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <Dialog.Title>{t("修改子账号密码")}</Dialog.Title>
        <Dialog.Description>{t("为 {name} 设置新的登录密码。保存后，该账号之前的登录会话会失效。", { name: account.displayName })}</Dialog.Description>
        {saved ? <Card className="customer-account-success"><CheckCircle size={22} /><div><Text weight="bold">{t("密码已更新")}</Text><Text size="2" color="gray">{t("请将新的 6 位数字密码安全地交给子账号。")}</Text></div></Card> : <label><Text size="2" weight="medium">{t("新密码")}</Text><TextField.Root value={password} onChange={(event) => setPassword(event.target.value.replace(/\D/g, "").slice(0, 6))} type={visible ? "text" : "password"} inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} autoFocus required placeholder={t("6 位数字")}>
          <TextField.Slot side="right"><button type="button" className="login-password-toggle" aria-label={t(visible ? "隐藏密码" : "显示密码")} aria-pressed={visible} onClick={() => setVisible((current) => !current)}>{visible ? <EyeSlash size={18} /> : <Eye size={18} />}</button></TextField.Slot>
        </TextField.Root></label>}
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("关闭")}</Button>{!saved ? <Button type="submit" loading={saving}><Key />{t("保存新密码")}</Button> : null}</div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

function CustomerSubaccountOrderDetailDialog({
  detail,
  loading,
  onClose,
}: {
  detail?: CustomerSubaccountOrderDetail;
  loading: boolean;
  onClose: () => void;
}) {
  const { t } = useLocale();
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog customer-order-detail-dialog">
      {loading || !detail ? <CoreLoading label={t("正在读取订单详情")} /> : <>
        <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("子账号询价 · 只读")}</Text><Dialog.Title>{detail.quoteNumber}</Dialog.Title><Dialog.Description>{detail.submittedByName} · {coreDate(detail.createdAt)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}>×</Button></div>
        <div className="customer-order-detail-meta">
          <Card><Text size="1" color="gray">{t("客户")}</Text><strong>{detail.customerCompany || detail.customerName}</strong><Text size="1">{detail.customerName}</Text></Card>
          <Card><Text size="1" color="gray">{t("客户国家")}</Text><strong>{countryLabel(detail.visitorCountryCode)}</strong></Card>
          <Card><Text size="1" color="gray">{t("最终报价")}</Text><strong>{money(detail.totalAmount, detail.currency)}</strong></Card>
          <Card><Text size="1" color="gray">{t("状态")}</Text><Badge color={detail.status === "CONFIRMED" || detail.status === "COMPLETED" ? "jade" : detail.status === "CANCELLED" ? "gray" : "amber"}>{t(orderStatusLabel[detail.status] ?? detail.status)}</Badge></Card>
        </div>
        <div className="customer-order-detail-items">
          <div className="customer-order-detail-items-head"><span>{t("商品 / SKU")}</span><span>{t("数量")}</span><span>{t("最终单价")}</span><span>{t("小计")}</span></div>
          {detail.items.map((item) => <div className="customer-order-detail-item" key={item.skuId}><div><strong>{item.productName}</strong><small className="mono-text">{item.skuCode}</small></div><span>{item.quantity}</span><span>{money(item.unitPrice, item.currency)}</span><strong>{money(item.lineTotal, item.currency)}</strong></div>)}
          {!detail.items.length ? <Text size="2" color="gray">{t("没有商品明细")}</Text> : null}
        </div>
        <div className="core-dialog-actions"><Button onClick={onClose}>{t("关闭")}</Button></div>
      </>}
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
  const [selected, setSelected] = useState<Set<CustomerSubaccountModule>>(
    new Set(account.modules?.length ? account.modules : ALL_SUBACCOUNT_MODULES),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const modules = SUBACCOUNT_MODULES
        .map((item) => item.code)
        .filter((code) => selected.has(code));
      onSaved(await updateCustomerSubaccountAccess(account.id, { modules }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号权限保存失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-access-dialog">
      <Dialog.Title>{t("{name} 的可见范围", { name: account.displayName })}</Dialog.Title>
      <Dialog.Description>{t("子账号是独立运营账号。勾选它需要使用的模块；原价格、供应商、库存和平台统计始终隐藏，子账号自己的询价和报价由它独立处理。")}</Dialog.Description>
      <div className="subaccount-access-options">
        {SUBACCOUNT_MODULES.map((item) => <label key={item.code}>
          <Checkbox
            checked={selected.has(item.code)}
            disabled={item.code === "products"}
            onCheckedChange={(checked) => setSelected((current) => {
              const next = new Set(current);
              if (checked === true) next.add(item.code); else next.delete(item.code);
              return next;
            })}
          />
          <span><Text size="2" weight="medium">{t(item.label)}</Text><Text size="1" color="gray">{t(item.description)}</Text></span>
        </label>)}
      </div>
      <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("商品与目录为必选入口；关闭其他模块只会隐藏入口，不会删除数据。")}</div>
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
  onSaved: (policy: { markupPercent: number; overrideCount: number; categoryOverrideCount?: number; skuOverrideCount?: number }) => void;
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
  const [editingSku, setEditingSku] = useState<string>();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [categoryMarkup, setCategoryMarkup] = useState("");
  const [editingCategory, setEditingCategory] = useState(false);

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

  useEffect(() => {
    let active = true;
    void listCategories().then((rows) => {
      if (active) setCategories(rows.filter((row) => row.status === "ACTIVE"));
    }).catch(() => {
      // Keep product-level pricing usable if the optional category list is
      // temporarily unavailable.
    });
    return () => { active = false; };
  }, []);

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
      onSaved({ ...data?.policy, markupPercent: Number(markup) || 0, overrideCount: (data?.policy.overrideCount || 0) + (data?.items.find((row) => row.productId === productId)?.overrideMode ? 0 : 1), categoryOverrideCount: data?.policy.categoryOverrideCount });
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
      onSaved({ ...data?.policy, markupPercent: Number(markup) || 0, overrideCount: Math.max(0, (data?.policy.overrideCount || 1) - 1), categoryOverrideCount: data?.policy.categoryOverrideCount });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("单品价格清除失败"));
    } finally {
      setEditingProduct(undefined);
    }
  };

  const saveCategoryRule = async () => {
    const value = Number(categoryMarkup);
    if (!categoryId) {
      setError(t("请选择一个分类。"));
      return;
    }
    if (!Number.isFinite(value) || value < 0 || value > 100000) {
      setError(t("分类加价必须是 0 到 100000 之间的数字"));
      return;
    }
    setEditingCategory(true);
    setError("");
    try {
      const policy = await updateCustomerSubaccountCategoryPricing(account.id, categoryId, value);
      await load();
      onSaved(policy);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("分类价格保存失败"));
    } finally {
      setEditingCategory(false);
    }
  };

  const clearCategoryRule = async () => {
    if (!categoryId) return;
    setEditingCategory(true);
    setError("");
    try {
      await clearCustomerSubaccountCategoryPricing(account.id, categoryId);
      setCategoryMarkup("");
      const previousCount = data?.policy.categoryOverrideCount ?? 0;
      await load();
      if (data) onSaved({ ...data.policy, categoryOverrideCount: Math.max(0, previousCount - 1) });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("分类价格清除失败"));
    } finally {
      setEditingCategory(false);
    }
  };

  const saveSkuRule = async (
    productId: string,
    skuId: string,
    mode: SubaccountPricingMode,
    rawValue: string,
  ) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    setEditingSku(skuId);
    setError("");
    try {
      const item = await updateCustomerSubaccountSkuPricing(account.id, skuId, mode, value);
      setData((current) => {
        if (!current) return current;
        const previous = current.items.find((row) => row.productId === productId);
        const previousCount = previous?.skuOverrideCount ?? 0;
        const nextCount = item.skuOverrideCount ?? 0;
        return {
          ...current,
          items: current.items.map((row) => row.productId === item.productId ? item : row),
          policy: {
            ...current.policy,
            skuOverrideCount: Math.max(0, current.policy.skuOverrideCount - previousCount + nextCount),
          },
        };
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("SKU 价格保存失败"));
    } finally {
      setEditingSku(undefined);
    }
  };

  const clearSkuRule = async (productId: string, skuId: string) => {
    setEditingSku(skuId);
    setError("");
    try {
      await clearCustomerSubaccountSkuPricing(account.id, skuId);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("SKU 价格清除失败"));
    } finally {
      setEditingSku(undefined);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-pricing-dialog">
      <Dialog.Title>{t("{name} 的价格设置", { name: account.displayName })}</Dialog.Title>
      <Dialog.Description>{t("最终价格按 SKU 计算：SKU 特价 > 商品规则 > 分类规则 > 统一加价。子账号只会看到最终销售价。")}</Dialog.Description>
      <section className="subaccount-pricing-policy">
        <label><Text size="2" weight="medium">{t("统一加价（%）")}</Text><TextField.Root type="number" min="0" max="100000" step="0.1" value={markup} onChange={(event) => setMarkup(event.target.value)} /></label>
        <Button loading={saving} onClick={() => void saveMarkup()}><CurrencyDollar />{t("应用到所有商品")}</Button>
        <Text size="1" color="gray">{t("当前已有 {count} 个单品规则、{skuCount} 个 SKU 特价", { count: data?.policy.overrideCount ?? account.overrideCount, skuCount: data?.policy.skuOverrideCount ?? 0 })}</Text>
      </section>
      <section className="subaccount-category-pricing">
        <div className="subaccount-category-pricing-copy"><Text size="2" weight="medium">{t("分类加价（%）")}</Text><Text size="1" color="gray">{t("分类规则按每个 SKU 原价分别计算；单品规则优先。")}</Text></div>
        <div className="subaccount-category-pricing-controls">
          <select value={categoryId} onChange={(event) => {
            const nextId = event.target.value;
            setCategoryId(nextId);
            const current = data?.items.find((row) => row.categoryId === nextId)?.categoryMarkupPercent;
            setCategoryMarkup(current == null ? "" : String(current));
          }} aria-label={t("选择加价分类")}>
            <option value="">{t("选择分类")}</option>
            {categories.map((category) => <option value={category.id} key={category.id}>{category.path || category.name}</option>)}
          </select>
          <TextField.Root type="number" min="0" max="100000" step="0.1" value={categoryMarkup} onChange={(event) => setCategoryMarkup(event.target.value)} placeholder={t("加价百分比")} aria-label={t("分类加价百分比")} />
          <div className="subaccount-category-pricing-actions">
            <Button size="2" loading={editingCategory} disabled={!categoryId} onClick={() => void saveCategoryRule()}>{t("应用分类规则")}</Button>
            <Button size="2" variant="ghost" color="gray" loading={editingCategory} disabled={!categoryId || !categoryMarkup} onClick={() => void clearCategoryRule()}>{t("清除")}</Button>
          </div>
        </div>
        <Text className="subaccount-category-pricing-count" size="1" color="gray">{t("已设置 {count} 个分类规则", { count: data?.policy.categoryOverrideCount ?? account.categoryOverrideCount ?? 0 })}</Text>
      </section>
      <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索商品名称或编码") } />
      {error ? <Text color="red" size="2">{error}</Text> : null}
      {loading ? <CoreLoading label={t("正在读取商品价格")} /> : data?.items.length ? <div className="subaccount-pricing-table">
        <div className="subaccount-pricing-table-head"><span>{t("商品")}</span><span>{t("主账号价格")}</span><span>{t("子账号价格")}</span><span>{t("单品规则")}</span></div>
        {data.items.map((item) => <SubaccountPricingRow key={item.productId} item={item} busy={editingProduct === item.productId} skuBusy={editingSku} onSave={saveProductRule} onClear={clearProductRule} onSaveSku={saveSkuRule} onClearSku={clearSkuRule} />)}
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
  skuBusy,
  onSave,
  onClear,
  onSaveSku,
  onClearSku,
}: {
  item: SubaccountPricingPage["items"][number];
  busy: boolean;
  skuBusy?: string;
  onSave: (productId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClear: (productId: string) => Promise<void>;
  onSaveSku: (productId: string, skuId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClearSku: (productId: string, skuId: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [mode, setMode] = useState<SubaccountPricingMode>(item.overrideMode || "MARKUP_PERCENT");
  const [value, setValue] = useState(item.overrideValue == null ? "" : String(item.overrideValue));
  const [showSkus, setShowSkus] = useState(false);
  useEffect(() => {
    setMode(item.overrideMode || "MARKUP_PERCENT");
    setValue(item.overrideValue == null ? "" : String(item.overrideValue));
  }, [item.overrideMode, item.overrideValue]);
  return <div className="subaccount-pricing-table-row">
    <div><strong>{item.productName}</strong><small>{item.productCode || "—"} · {item.categoryName || t("未分类")} · {t("{count} 个 SKU", { count: item.skuCount })}</small>{item.skuPrices.length ? <button type="button" className="subaccount-sku-price-toggle" onClick={() => setShowSkus((current) => !current)}>{showSkus ? t("收起 SKU 价格") : t("按 SKU 调整价格")} <CaretDown data-expanded={showSkus || undefined} /></button> : null}{showSkus ? <div className="subaccount-sku-price-list">{item.skuPrices.map((sku) => <SubaccountSkuPriceRuleRow key={sku.skuId} productId={item.productId} sku={sku} busy={skuBusy === sku.skuId} onSave={onSaveSku} onClear={onClearSku} />)}</div> : null}</div>
    <span>{item.basePriceFrom === item.basePriceTo ? `${item.currency} ${item.basePriceFrom}` : `${item.currency} ${item.basePriceFrom}–${item.basePriceTo}`}</span>
    <strong>{item.effectivePriceFrom === item.effectivePriceTo ? `${item.currency} ${item.effectivePriceFrom}` : `${item.currency} ${item.effectivePriceFrom}–${item.effectivePriceTo}`}</strong>
    <div className="subaccount-pricing-rule-editor">
      <select value={mode} onChange={(event) => setMode(event.target.value as SubaccountPricingMode)} aria-label={t("单品价格方式")}><option value="MARKUP_PERCENT">{t("加价百分比")}</option><option value="FIXED_PRICE">{t("统一固定价")}</option></select>
      <TextField.Root size="1" type="number" min="0" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} placeholder="—" aria-label={t("单品价格数值")} />
      <Button size="1" loading={busy} onClick={() => void onSave(item.productId, mode, value)}>{t("应用")}</Button>
      {item.overrideMode ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void onClear(item.productId)}>{t("恢复")}</Button> : null}
    </div>
  </div>;
}

function SubaccountSkuPriceRuleRow({
  productId,
  sku,
  busy,
  onSave,
  onClear,
}: {
  productId: string;
  sku: SubaccountProductPricingItem["skuPrices"][number];
  busy: boolean;
  onSave: (productId: string, skuId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClear: (productId: string, skuId: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [mode, setMode] = useState<SubaccountPricingMode>(sku.overrideMode || "MARKUP_PERCENT");
  const [value, setValue] = useState(sku.overrideValue == null ? "" : String(sku.overrideValue));
  useEffect(() => {
    setMode(sku.overrideMode || "MARKUP_PERCENT");
    setValue(sku.overrideValue == null ? "" : String(sku.overrideValue));
  }, [sku.overrideMode, sku.overrideValue]);
  return <div className="subaccount-sku-price-rule">
    <span className="mono-text" title={sku.skuCode}>{sku.skuCode}</span>
    <span>{sku.currency} {sku.basePrice.toFixed(2)}</span>
    <strong>{sku.currency} {sku.effectivePrice.toFixed(2)}</strong>
    <select value={mode} onChange={(event) => setMode(event.target.value as SubaccountPricingMode)} aria-label={t("SKU 价格方式")}>
      <option value="MARKUP_PERCENT">{t("加价 %")}</option>
      <option value="FIXED_PRICE">{t("固定价")}</option>
    </select>
    <TextField.Root size="1" type="number" min="0" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} placeholder={t("继承")} aria-label={t("SKU 价格数值")} />
    <Button size="1" loading={busy} onClick={() => void onSave(productId, sku.skuId, mode, value)}>{t("应用")}</Button>
    {sku.overrideMode ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void onClear(productId, sku.skuId)}>{t("恢复")}</Button> : null}
  </div>;
}
