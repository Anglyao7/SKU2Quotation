import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Text,
  Tabs,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  CalendarBlank,
  CaretLeft,
  CaretRight,
  CheckCircle,
  Clock,
  CurrencyDollar,
  EnvelopeSimple,
  FileText,
  Key,
  MapPin,
  Package,
  Power,
  SlidersHorizontal,
  Storefront,
  Trash,
  UserCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  deleteCustomerSubaccount,
  getCustomerSubaccount,
  getCustomerSubaccountOrder,
  listCustomerSubaccountOrdersByAccount,
  updateCustomerSubaccountStatus,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type {
  CustomerSubaccount,
  CustomerSubaccountModule,
  CustomerSubaccountOrderDetail,
  CustomerSubaccountOrderPage,
} from "../types";
import { money } from "../../lib/format";
import {
  CustomerAccountAccessDialog,
  CustomerSubaccountOrderDetailDialog,
  CustomerSubaccountPasswordDialog,
  SubaccountPricingDialog,
} from "./CustomerAccountsPage";

const ORDER_PAGE_SIZE = 20;
const MODULE_LABELS: Record<CustomerSubaccountModule, string> = {
  products: "商品与目录",
  inquiries: "询盘",
  quotations: "报价",
  announcements: "公告",
  support: "客户沟通",
};
const ORDER_STATUS_LABELS: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

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

function quantityLabel(value: number) {
  return Number(value || 0).toLocaleString(undefined, {
    maximumFractionDigits: 6,
  });
}

function orderStatusColor(status: string): "amber" | "jade" | "gray" {
  if (status === "PENDING_CONFIRMATION") return "amber";
  if (status === "CONFIRMED" || status === "COMPLETED") return "jade";
  return "gray";
}

function orderFollowUp(order: CustomerSubaccountOrderDetail | CustomerSubaccountOrderPage["items"][number]) {
  if (order.status === "COMPLETED") return "已成交，可归档";
  if (order.status === "CONFIRMED") return "已确认，跟进交付";
  if (order.status === "CANCELLED") return "已取消，无需跟进";
  if (order.status === "EXPIRED" || Date.parse(order.validUntil) < Date.now()) return "已过有效期";
  return "待确认，建议尽快回复";
}

function orderContactSignal(order: CustomerSubaccountOrderDetail | CustomerSubaccountOrderPage["items"][number]) {
  if (order.customerEmail && order.customerPhone) return "联系方式完整";
  if (order.customerEmail || order.customerPhone) return "已有直接联系方式";
  return "仅留姓名，需补充联系方式";
}

function DetailMetric({ icon, label, value, note }: {
  icon: ReactNode;
  label: string;
  value: string;
  note?: string;
}) {
  return <Card className="customer-subaccount-detail-metric">
    <span>{icon}</span>
    <div><Text size="1" color="gray">{label}</Text><strong>{value}</strong>{note ? <small>{note}</small> : null}</div>
  </Card>;
}

function InformationItem({ label, value, icon }: {
  label: string;
  value: ReactNode;
  icon: ReactNode;
}) {
  return <div className="customer-subaccount-info-item">
    <span>{icon}</span>
    <div><small>{label}</small><strong>{value}</strong></div>
  </div>;
}

export function CustomerSubaccountDetailPage() {
  const { membershipId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useLocale();
  const { notify } = useToast();
  const [account, setAccount] = useState<CustomerSubaccount>();
  const [orders, setOrders] = useState<CustomerSubaccountOrderPage>();
  const [loading, setLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [orderDetail, setOrderDetail] = useState<CustomerSubaccountOrderDetail>();
  const [orderDetailLoading, setOrderDetailLoading] = useState(false);

  const load = useCallback(async () => {
    if (!membershipId) return;
    setLoading(true);
    setError("");
    try {
      const [nextAccount, nextOrders] = await Promise.all([
        getCustomerSubaccount(membershipId),
        listCustomerSubaccountOrdersByAccount(membershipId, 1, ORDER_PAGE_SIZE),
      ]);
      setAccount(nextAccount);
      setOrders(nextOrders);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号详情加载失败"));
    } finally {
      setLoading(false);
    }
  }, [membershipId, t]);

  useEffect(() => { void load(); }, [load]);

  const changeOrderPage = async (page: number) => {
    if (!membershipId || !orders || ordersLoading || page < 1 || page === orders.page) return;
    setOrdersLoading(true);
    try {
      setOrders(await listCustomerSubaccountOrdersByAccount(
        membershipId,
        page,
        ORDER_PAGE_SIZE,
      ));
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("订单数据加载失败"), { kind: "error" });
    } finally {
      setOrdersLoading(false);
    }
  };

  const openOrder = async (orderId: string) => {
    setOrderDetail(undefined);
    setOrderDetailLoading(true);
    try {
      setOrderDetail(await getCustomerSubaccountOrder(orderId));
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("订单详情加载失败"), { kind: "error" });
    } finally {
      setOrderDetailLoading(false);
    }
  };

  const toggleStatus = async () => {
    if (!account || actionBusy) return;
    setActionBusy(true);
    try {
      const updated = await updateCustomerSubaccountStatus(
        account.id,
        account.status === "active" ? "suspended" : "active",
      );
      setAccount(updated);
      notify(t(updated.status === "active" ? "子账号已重新开通" : "子账号已停用"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("账号状态更新失败"), { kind: "error" });
    } finally {
      setActionBusy(false);
    }
  };

  const remove = async () => {
    if (!account || actionBusy) return;
    setActionBusy(true);
    try {
      await deleteCustomerSubaccount(account.id);
      notify(t("子账号已删除，历史订单仍保留"), { kind: "success" });
      navigate("/console/customer-accounts", { replace: true });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("子账号删除失败"), { kind: "error" });
      setActionBusy(false);
    }
  };

  if (loading && !account) {
    return <div className="core-workspace"><CoreLoading label={t("正在读取子账号详情")} /></div>;
  }
  if (!account) {
    return <div className="core-workspace customer-subaccount-detail-page">
      <Link className="customer-subaccount-back" to="/console/customer-accounts"><ArrowLeft />{t("返回子账号列表")}</Link>
      <CoreError message={error || t("子账号不存在或已被删除")} onRetry={() => void load()} />
    </div>;
  }

  const currency = orders?.items[0]?.currency || "CNY";
  const pageCount = orders ? Math.max(1, Math.ceil(orders.total / orders.pageSize)) : 1;

  return <div className="core-workspace customer-subaccount-detail-page">
    <Link className="customer-subaccount-back" to="/console/customer-accounts"><ArrowLeft />{t("返回子账号列表")}</Link>
    <CorePageHeading
      eyebrow={t("子账号详情")}
      title={account.displayName}
      description={t("集中查看账号资料、访问状态、价格规则和该账号提交的订单。")}
      actions={<div className="customer-subaccount-detail-actions">
        <Button asChild variant="soft" color="jade"><Link to={account.storefrontPath} target="_blank" rel="noreferrer"><Storefront />{t("打开前台")}</Link></Button>
        <Button variant="soft" color="gray" onClick={() => setAccessOpen(true)}><SlidersHorizontal />{t("权限")}</Button>
        <Button variant="soft" color="gray" onClick={() => setActiveTab("pricing")}><CurrencyDollar />{t("价格")}</Button>
        <Button variant="soft" color="gray" onClick={() => setPasswordOpen(true)}><Key />{t("改密码")}</Button>
        <Button variant="soft" color={account.status === "active" ? "gray" : "jade"} loading={actionBusy} onClick={() => void toggleStatus()}><Power />{t(account.status === "active" ? "停用" : "重新开通")}</Button>
        <Button variant="soft" color="red" disabled={actionBusy} onClick={() => setDeleteOpen(true)}><Trash />{t("删除")}</Button>
      </div>}
    />
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

    <Tabs.Root className="admin-subaccount-tabs" value={activeTab} onValueChange={setActiveTab}>
      <Tabs.List><Tabs.Trigger value="overview">{t("基础信息")}</Tabs.Trigger><Tabs.Trigger value="pricing">{t("商品与价格")}</Tabs.Trigger><Tabs.Trigger value="orders">{t("客户询价")}</Tabs.Trigger></Tabs.List>
      <Tabs.Content value="overview">
    <section className="customer-subaccount-detail-metrics" aria-label={t("子账号经营概览")}>
      <DetailMetric icon={<FileText />} label={t("累计订单")} value={t("{count} 笔", { count: account.orderCount })} note={account.lastOrderAt ? t("最近 {date}", { date: coreDate(account.lastOrderAt) }) : t("尚未提交订单")} />
      <DetailMetric icon={<CurrencyDollar />} label={t("累计询价金额")} value={money(account.orderAmount, currency)} />
      <DetailMetric icon={<CheckCircle />} label={t("今日成交")} value={money(account.todayOrderAmount, currency)} note={t("{count} 笔", { count: account.todayOrderCount })} />
      <DetailMetric icon={<CalendarBlank />} label={t("本月成交")} value={money(account.monthOrderAmount, currency)} note={t("{count} 笔", { count: account.monthOrderCount })} />
    </section>

    <section className="customer-subaccount-detail-grid">
      <Card className="customer-subaccount-info-card">
        <div className="customer-subaccount-section-heading"><div><Text size="1" color="gray">{t("账号档案")}</Text><Heading size="5">{t("基础信息")}</Heading></div><Badge color={account.status === "active" ? "jade" : "gray"}>{t(account.status === "active" ? "已开通" : "已停用")}</Badge></div>
        <div className="customer-subaccount-info-grid">
          <InformationItem icon={<UserCircle />} label={t("登录账号")} value={account.loginIdentifier} />
          <InformationItem icon={<EnvelopeSimple />} label={t("联系邮箱")} value={account.email || "—"} />
          <InformationItem icon={<Storefront />} label={t("前台路径")} value={account.storefrontPath} />
          <InformationItem icon={<CalendarBlank />} label={t("创建时间")} value={coreDate(account.createdAt)} />
          <InformationItem icon={<Clock />} label={t("最近登录")} value={account.lastLoginAt ? coreDate(account.lastLoginAt) : t("尚未登录")} />
        </div>
        <div className="customer-subaccount-module-block">
          <small>{t("已开放模块")}</small>
          <div>{account.modules.map((module) => <Badge key={module} color="gray">{t(MODULE_LABELS[module])}</Badge>)}</div>
        </div>
      </Card>

      <Card className="customer-subaccount-pricing-summary-card">
        <Text size="1" color="gray">{t("价格策略")}</Text>
        <Heading size="5">{t("当前账号价格规则")}</Heading>
        <strong>{account.pricesHidden ? t("价格为 0") : `+${Number(account.markupPercent || 0).toLocaleString()}%`}</strong>
        <Text size="2" color="gray">{account.pricesHidden ? t("子账号前台已隐藏价格") : t("默认加价比例")}</Text>
        <div>
          <span><b>{account.overrideCount}</b><small>{t("单品规则")}</small></span>
          <span><b>{account.categoryOverrideCount ?? 0}</b><small>{t("分类规则")}</small></span>
          <span><b>{account.skuOverrideCount ?? 0}</b><small>{t("SKU 特价")}</small></span>
        </div>
        <Button variant="soft" onClick={() => setActiveTab("pricing")}><CurrencyDollar />{t("管理价格规则")}</Button>
      </Card>
    </section>

      </Tabs.Content>
      <Tabs.Content value="pricing" forceMount hidden={activeTab !== "pricing"}>
        <SubaccountPricingDialog embedded account={account} onClose={() => setActiveTab("overview")} onSaved={(policy) => setAccount((current) => current ? { ...current, markupPercent: policy.markupPercent, overrideCount: policy.overrideCount, categoryOverrideCount: policy.categoryOverrideCount, skuOverrideCount: policy.skuOverrideCount, pricesHidden: policy.pricesHidden ?? current.pricesHidden } : current)} />
      </Tabs.Content>
      <Tabs.Content value="orders">
    <Card className="customer-order-panel customer-subaccount-orders-panel">
      <div className="customer-account-panel-heading">
        <div><Text size="1" color="gray">{t("订单观察")}</Text><Heading size="5">{t("该子账号带来的客户报价")}</Heading></div>
        <Badge color="gray"><FileText />{t("共 {count} 笔", { count: orders?.total ?? 0 })}</Badge>
      </div>
      {orders?.items.length ? <div className={`customer-order-review-list${ordersLoading ? " is-loading" : ""}`} aria-busy={ordersLoading}>
        {orders.items.map((order) => <article
          className="customer-order-review-row"
          key={order.id}
          role="button"
          tabIndex={0}
          onClick={() => void openOrder(order.id)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              void openOrder(order.id);
            }
          }}
        >
          <header className="customer-order-review-heading">
            <div>
              <strong className="mono-text">{order.quoteNumber}</strong>
              <time dateTime={order.createdAt}>{coreDate(order.createdAt)}</time>
            </div>
            <Badge color={orderStatusColor(order.status)}>{t(ORDER_STATUS_LABELS[order.status] ?? order.status)}</Badge>
          </header>
          <div className="customer-order-review-facts">
            <div><span><UserCircle /></span><small>{t("客户")}</small><strong>{order.customerCompany || order.customerName}</strong><p>{order.customerCompany ? order.customerName : (order.customerEmail || order.customerPhone || t("未留下联系方式"))}</p></div>
            <div><span><MapPin /></span><small>{t("来源")}</small><strong>{countryLabel(order.visitorCountryCode)}</strong><p className="mono-text">{order.visitorIpAddress || t("历史订单未记录 IP")}</p></div>
            <div><span><Package /></span><small>{t("订单规模")}</small><strong>{t("{count} 个 SKU", { count: order.itemCount })}</strong><p>{t("合计数量 {quantity}", { quantity: quantityLabel(order.totalQuantity) })}</p></div>
            <div><span><CurrencyDollar /></span><small>{t("报价金额")}</small><strong>{money(order.totalAmount, order.currency)}</strong><p>{t("有效至 {date}", { date: coreDate(order.validUntil) })}</p></div>
          </div>
          <footer className="customer-order-review-footer">
            <div className="customer-order-signals">
              <span className={order.status === "PENDING_CONFIRMATION" ? "is-urgent" : ""}>{t(orderFollowUp(order))}</span>
              <span>{t(orderContactSignal(order))}</span>
            </div>
            <strong>{t("查看完整分析")}<CaretRight /></strong>
          </footer>
        </article>)}
      </div> : <CoreEmpty title={t("该子账号尚未提交订单")} description={t("订单提交后会在这里形成客户、来源、金额与跟进建议记录。")} />}
      {orders && orders.total > orders.pageSize ? <div className="customer-order-pagination">
        <Text size="2" color="gray">{t("第 {page} / {pages} 页", { page: orders.page, pages: pageCount })}</Text>
        <div><Button size="1" variant="soft" color="gray" disabled={ordersLoading || orders.page <= 1} onClick={() => void changeOrderPage(orders.page - 1)}><CaretLeft />{t("上一页")}</Button><Button size="1" variant="soft" color="gray" disabled={ordersLoading || orders.page >= pageCount} onClick={() => void changeOrderPage(orders.page + 1)}>{t("下一页")}<CaretRight /></Button></div>
      </div> : null}
    </Card>

      </Tabs.Content>
    </Tabs.Root>
    {accessOpen ? <CustomerAccountAccessDialog account={account} onClose={() => setAccessOpen(false)} onSaved={(updated) => { setAccount(updated); setAccessOpen(false); notify(t("子账号权限已更新"), { kind: "success" }); }} /> : null}
    {passwordOpen ? <CustomerSubaccountPasswordDialog account={account} onClose={() => setPasswordOpen(false)} /> : null}
    {orderDetail || orderDetailLoading ? <CustomerSubaccountOrderDetailDialog detail={orderDetail} loading={orderDetailLoading} onClose={() => { setOrderDetail(undefined); setOrderDetailLoading(false); }} /> : null}

    <AlertDialog.Root open={deleteOpen} onOpenChange={(open) => { if (!actionBusy) setDeleteOpen(open); }}>
      <AlertDialog.Content maxWidth="520px">
        <AlertDialog.Title>{t("永久删除这个子账号？")}</AlertDialog.Title>
        <AlertDialog.Description>{t("“{name}”将立即无法登录，也不能重新开通。历史订单会继续保留用于对账和追溯。", { name: account.displayName })}</AlertDialog.Description>
        <div className="customer-subaccount-delete-warning"><WarningCircle /><span>{t("删除与停用不同，此操作无法撤销。")}</span></div>
        <div className="core-dialog-actions"><AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel><Button color="red" loading={actionBusy} onClick={() => void remove()}><Trash />{t("确认删除")}</Button></div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </div>;
}
