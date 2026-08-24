import { Badge, Button, Card, Heading, Text } from "@radix-ui/themes";
import {
  ArrowRight,
  ChartLineUp,
  Cube,
  FileText,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getCustomerPortalOverview, listCustomerPortalOrders } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { CustomerPortalOrder, CustomerPortalOverview } from "../types";
import { api } from "../../lib/api";
import { money } from "../../lib/format";
import type { StoreProductList } from "../../types";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

export function ResellerDashboardPage() {
  const { profile, hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canViewCatalog = hasPermission("customer_portal.access");
  const canViewOrders = hasPermission("customer_portal.order_view_self");
  const [overview, setOverview] = useState<CustomerPortalOverview>();
  const [products, setProducts] = useState<StoreProductList>();
  const [orders, setOrders] = useState<CustomerPortalOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const nextOverview = await getCustomerPortalOverview();
      const [nextProducts, nextOrders] = await Promise.all([
        canViewCatalog
          ? api.getStoreProducts(nextOverview.tenantSlug, { page: 1, includeFacets: false })
          : Promise.resolve(undefined),
        canViewOrders ? listCustomerPortalOrders() : Promise.resolve([]),
      ]);
      setOverview(nextOverview);
      setProducts(nextProducts);
      setOrders(nextOrders);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("代理商工作台加载失败"));
    } finally {
      setLoading(false);
    }
  }, [canViewCatalog, canViewOrders, t]);

  useEffect(() => { void load(); }, [load]);

  if (loading && !overview) {
    return <div className="core-workspace"><CoreLoading label={t("正在读取代理商工作台")} /></div>;
  }

  const catalogPath = overview ? `/${encodeURIComponent(overview.tenantSlug)}` : "/";
  const displayName = overview?.displayName || profile?.user.displayName || t("子账号");
  const greeting = new Date().getHours() < 12
    ? "早上好，{name}"
    : new Date().getHours() < 18
    ? "下午好，{name}"
    : "晚上好，{name}";
  const pendingOrders = orders.filter((order) => order.status === "PENDING_CONFIRMATION").length;
  const totalOrderAmount = orders.reduce((sum, order) => sum + order.totalAmount, 0);
  const amountCurrency = orders[0]?.currency || profile?.context.defaultCurrency || "CNY";

  return (
    <div className="core-workspace reseller-dashboard">
      <CorePageHeading
        eyebrow={t("代理商工作台")}
        title={t(greeting, { name: displayName })}
        description={t("在同一后台浏览已生效的代理价格、提交询价并跟进自己的订单。原价格、供应商和平台管理信息不会展示。")}
        actions={(
          <div className="core-heading-actions">
            {canViewCatalog ? <Button asChild variant="soft"><Link to={catalogPath} target="_blank" rel="noreferrer"><Storefront />{t("打开商品前台")}</Link></Button> : null}
            {canViewCatalog ? <Button asChild><Link to="/console/products"><Cube />{t("浏览商品目录")}</Link></Button> : null}
          </div>
        )}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

      <section className="core-metric-grid reseller-metric-grid" aria-label={t("代理商指标")}>
        <MetricCard icon={<Cube />} label={t("可用商品")} value={canViewCatalog ? (products?.total ?? 0).toLocaleString() : "—"} hint={canViewCatalog ? t("按当前账号的代理价格展示") : t("商品目录未开通")} to={canViewCatalog ? "/console/products" : "/console"} />
        <MetricCard icon={<FileText />} label={t("我的询价") } value={(overview?.orderCount ?? orders.length).toLocaleString()} hint={overview?.lastOrderAt ? t("最近提交 {date}", { date: coreDate(overview.lastOrderAt) }) : t("尚未提交询价")} to="/console/quotes" />
        <MetricCard icon={<ChartLineUp />} label={t("待处理") } value={pendingOrders.toLocaleString()} hint={t("等待商家确认的询价")} to="/console/quotes" />
        <Card className="reseller-value-card">
          <span className="reseller-metric-icon"><ChartLineUp /></span>
          <Text size="2" color="gray">{t("我的询价金额")}</Text>
          <strong>{money(totalOrderAmount, amountCurrency)}</strong>
          <Text size="1" color="gray">{t("仅统计当前子账号提交的记录")}</Text>
        </Card>
      </section>

      <section className="reseller-dashboard-grid">
        <Card className="reseller-guide-card">
          <div className="reseller-section-heading"><div><Text size="1" color="gray">{t("工作入口")}</Text><Heading size="5">{t("从选品到询价")}</Heading></div><Badge color="jade">{t("代理价格")}</Badge></div>
          <div className="reseller-guide-grid">
            {canViewCatalog ? <Link to="/console/products"><span><Cube /></span><div><strong>{t("商品目录")}</strong><Text size="2" color="gray">{t("查看图片、描述、标签与规格")}</Text></div><ArrowRight /></Link> : null}
            {canViewOrders ? <Link to="/console/quotes"><span><FileText /></span><div><strong>{t("我的询价")}</strong><Text size="2" color="gray">{t("查看提交记录与商家确认状态")}</Text></div><ArrowRight /></Link> : null}
          </div>
        </Card>
        <Card className="reseller-orders-card">
          <div className="reseller-section-heading"><div><Text size="1" color="gray">{t("最近活动")}</Text><Heading size="5">{t("最近询价")}</Heading></div><Button asChild size="1" variant="ghost"><Link to="/console/quotes">{t("查看全部")}<ArrowRight /></Link></Button></div>
          {orders.length ? <div className="reseller-recent-list">{orders.slice(0, 4).map((order) => <div key={order.id}><div><strong className="core-tabular">{order.quoteNumber}</strong><Text size="1" color="gray">{order.customerCompany || order.customerName}</Text></div><div><strong>{money(order.totalAmount, order.currency)}</strong><Badge color={order.status === "PENDING_CONFIRMATION" ? "amber" : order.status === "CONFIRMED" ? "jade" : "gray"}>{t(orderStatusLabel[order.status] ?? order.status)}</Badge></div></div>)}</div> : <div className="reseller-no-orders"><Text size="2" color="gray">{t("还没有询价记录")}</Text>{canViewCatalog ? <Button asChild variant="soft"><Link to={catalogPath} target="_blank" rel="noreferrer"><Storefront />{t("去选品")}</Link></Button> : null}</div>}
        </Card>
      </section>
    </div>
  );
}

function MetricCard({ icon, label, value, hint, to }: { icon: ReactNode; label: string; value: string; hint: string; to: string }) {
  return (
    <Card asChild className="reseller-metric-card">
      <Link to={to}>
        <span className="reseller-metric-icon">{icon}</span>
        <Text size="2" color="gray">{label}</Text>
        <strong>{value}</strong>
        <Text size="1" color="gray">{hint}</Text>
      </Link>
    </Card>
  );
}
