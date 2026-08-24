import { Avatar, Badge, Button, Card, Heading, Text } from "@radix-ui/themes";
import { ArrowRight, Cube, FileText, SignOut, Storefront } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCustomerPortalOverview, listCustomerPortalOrders } from "../core/api";
import { useCoreAuth } from "../core/AuthContext";
import { CoreEmpty, CoreError, CoreLoading, coreDate } from "../core/CoreUi";
import { useLocale } from "../core/LocaleContext";
import type { CustomerPortalOrder, CustomerPortalOverview } from "../core/types";
import { Brand } from "../components/Brand";
import { money } from "../lib/format";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

export function CustomerPortalPage() {
  const { t } = useLocale();
  const { logout, profile, hasPermission } = useCoreAuth();
  const canViewOrders = hasPermission("customer_portal.order_view_self");
  const [overview, setOverview] = useState<CustomerPortalOverview>();
  const [orders, setOrders] = useState<CustomerPortalOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextOverview, nextOrders] = await Promise.all([
        getCustomerPortalOverview(),
        canViewOrders ? listCustomerPortalOrders() : Promise.resolve([]),
      ]);
      setOverview(nextOverview);
      setOrders(nextOrders);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("客户门户加载失败"));
    } finally {
      setLoading(false);
    }
  }, [canViewOrders, t]);
  useEffect(() => { void load(); }, [load]);

  if (loading && !overview) return <main className="customer-portal-loading"><CoreLoading label={t("正在打开代理商门户")} /></main>;
  const catalogPath = overview ? `/${encodeURIComponent(overview.tenantSlug)}` : "/";
  const displayName = overview?.displayName || profile?.user.displayName || t("客户账号");
  return <div className="customer-portal-shell">
    <header className="customer-portal-header">
      <Brand />
      <div className="customer-portal-account"><span><Text size="1" color="gray">{overview?.tenantName}</Text><Text size="2" weight="medium">{displayName}</Text></span><Avatar fallback={displayName.slice(0, 2).toUpperCase()} radius="large" color="jade" /><Button variant="ghost" color="gray" size="1" onClick={() => void logout()}><SignOut />{t("退出")}</Button></div>
    </header>
    <main className="customer-portal-main">
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      <section className="customer-portal-hero">
        <div><Text size="1" color="gray">{t("代理商门户")}</Text><Heading size="8">{t("从商品目录开始选品")}</Heading><Text size="3" color="gray">{t("浏览当前商家的商品，看到的是已生效的代理价格；加入报价清单后提交订单申请。")}</Text><Button asChild size="3"><Link to={catalogPath}><Storefront />{t("浏览商品") }<ArrowRight /></Link></Button></div>
        <Card className="customer-portal-count"><span><Cube size={23} /></span><Text size="1" color="gray">{t("我的订单申请")}</Text><strong>{overview?.orderCount ?? 0}</strong><Text size="1" color="gray">{overview?.lastOrderAt ? t("最近提交 {date}", { date: coreDate(overview.lastOrderAt) }) : t("尚未提交订单")}</Text></Card>
      </section>
      {canViewOrders ? <Card className="customer-portal-orders">
        <div className="customer-portal-orders-head"><div><Text size="1" color="gray">{t("只读记录")}</Text><Heading size="5">{t("我的订单")}</Heading></div><Badge color="gray"><FileText />{t("共 {count} 笔", { count: orders.length })}</Badge></div>
        {orders.length ? <div className="customer-portal-order-list">{orders.map((order) => <article key={order.id}><div><strong className="mono-text">{order.quoteNumber}</strong><small>{order.customerCompany || order.customerName}</small></div><div><small>{t("金额")}</small><strong>{money(order.totalAmount, order.currency)}</strong></div><Badge color={order.status === "PENDING_CONFIRMATION" ? "amber" : order.status === "CONFIRMED" ? "jade" : "gray"}>{t(orderStatusLabel[order.status] ?? order.status)}</Badge><time>{coreDate(order.createdAt)}</time></article>)}</div> : <CoreEmpty title={t("还没有订单申请")} description={t("在商品目录加入商品并提交后，订单会自动归属到当前账号。") } action={<Button asChild variant="soft"><Link to={catalogPath}><Storefront />{t("去浏览商品")}</Link></Button>} />}
      </Card> : null}
    </main>
  </div>;
}
