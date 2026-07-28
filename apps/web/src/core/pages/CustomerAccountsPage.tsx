import {
  Badge,
  Button,
  Card,
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
  FileText,
  Plus,
  Power,
  UserPlus,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  createCustomerSubaccount,
  getCustomerSubaccountDashboard,
  listCustomerSubaccountOrders,
  updateCustomerSubaccountStatus,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { money } from "../../lib/format";
import type {
  CustomerSubaccount,
  CustomerSubaccountDashboard,
  CustomerSubaccountOrderPage,
} from "../types";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

const ORDER_PAGE_SIZE = 20;

export function CustomerAccountsPage() {
  const { t } = useLocale();
  const [data, setData] = useState<CustomerSubaccountDashboard>();
  const [orders, setOrders] = useState<CustomerSubaccountOrderPage>();
  const [loading, setLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
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
      eyebrow={t("客户门户")}
      title={t("子账号管理")}
      description={t("为下游客户开通受限账号。子账号只能浏览商品、提交自己的订单申请；这里可以只读查看其访问和订单动态。")}
      actions={<Button onClick={() => setEditorOpen(true)}><UserPlus />{t("开通子账号")}</Button>}
    />
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

    <section className="customer-account-metrics" aria-label={t("子账号概览")}>
      <Metric icon={<UsersThree />} label={t("全部子账号")} value={(data?.accounts.length ?? 0).toString()} />
      <Metric icon={<CheckCircle />} label={t("当前已开通")} value={(data?.activeCount ?? 0).toString()} tone="jade" />
      <Metric icon={<Eye />} label={t("近期开单申请")} value={(data?.orderCount ?? 0).toString()} />
    </section>

    <section className="customer-account-grid">
      <Card className="customer-account-panel">
        <div className="customer-account-panel-heading">
          <div><Text size="1" color="gray">{t("访问范围")}</Text><Heading size="5">{t("已开通的客户账号")}</Heading></div>
          <Text size="2" color="gray">{t("主账号可启停；订单内容仅供查看")}</Text>
        </div>
        {data?.accounts.length ? <div className="customer-account-list">
          {data.accounts.map((account) => <article className="customer-account-row" key={account.id}>
            <div className="customer-account-identity">
              <span className="customer-account-avatar">{account.displayName.slice(0, 2).toUpperCase()}</span>
              <span><strong>{account.displayName}</strong><small>{account.loginIdentifier}{account.email ? ` · ${account.email}` : ""}</small></span>
            </div>
            <div className="customer-account-signal">
              <small>{t("最近访问")}</small><strong>{account.lastLoginAt ? coreDate(account.lastLoginAt) : t("尚未登录")}</strong>
              <span>{t("近 30 天 {count} 次", { count: account.loginCount30d })}</span>
            </div>
            <div className="customer-account-signal">
              <small>{t("订单申请")}</small><strong>{t("{count} 笔", { count: account.orderCount })}</strong>
              <span>{account.lastOrderAt ? t("最近 {date}", { date: coreDate(account.lastOrderAt) }) : t("尚无订单")}</span>
            </div>
            <Badge color={account.status === "active" ? "jade" : "gray"}>{t(account.status === "active" ? "已开通" : "已停用")}</Badge>
            <Button
              size="1"
              variant="soft"
              color={account.status === "active" ? "gray" : "jade"}
              loading={updatingId === account.id}
              onClick={() => void updateStatus(account)}
            ><Power />{t(account.status === "active" ? "停用" : "重新开通")}</Button>
          </article>)}
        </div> : <CoreEmpty
          title={t("还没有子账号")}
          description={t("为需要自行选品的下游客户开通账号，他们只能看到商品前台与自己的订单记录。")}
          action={<Button variant="soft" onClick={() => setEditorOpen(true)}><Plus />{t("开通第一个子账号")}</Button>}
        />}
      </Card>

      <Card className="customer-account-side-note">
        <span className="customer-account-side-icon"><Eye size={24} /></span>
        <Text size="1" color="gray">{t("主账号只读范围")}</Text>
        <Heading size="4">{t("看得到动态，但不替客户改单")}</Heading>
        <Text size="2" color="gray">{t("子账号提交的商品、数量和报价申请会留在原始订单中。主账号可查看访问时间与订单记录，但不能改动其内容。")}</Text>
        <ul>
          <li>{t("子账号仅可浏览商品前台")}</li>
          <li>{t("订单按照提交账号自动归属")}</li>
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
      });
      await onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号创建失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <Dialog.Title>{t("开通客户子账号")}</Dialog.Title>
        <Dialog.Description>{t("创建后，对方使用账号密码登录客户门户，只能浏览商品并提交自己的订单申请。")}</Dialog.Description>
        <div className="customer-account-form-grid">
          <label><Text size="2" weight="medium">{t("客户名称")}</Text><TextField.Root value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder={t("例如 上海澄明贸易") } required maxLength={120} /></label>
          <label><Text size="2" weight="medium">{t("登录账号")}</Text><TextField.Root value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={t("账号、邮箱或手机号") } required maxLength={320} autoCapitalize="none" /></label>
          <label><Text size="2" weight="medium">{t("联系邮箱（可选）")}</Text><TextField.Root value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t("name@example.com") } type="email" maxLength={320} /></label>
          <label><Text size="2" weight="medium">{t("初始密码")}</Text><TextField.Root value={password} onChange={(event) => setPassword(event.target.value)} placeholder={t("至少 8 位，包含字母和数字") } type="password" required minLength={8} maxLength={128} /></label>
        </div>
        <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("请将初始账号密码通过可靠渠道交给客户；密码不会在创建后再次显示。")}</div>
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button type="submit" loading={saving}><UserPlus />{t(saving ? "正在开通" : "确认开通")}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}
