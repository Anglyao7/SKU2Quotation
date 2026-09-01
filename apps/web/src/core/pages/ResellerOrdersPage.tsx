import { Badge, Button, Card, Heading, Text } from "@radix-ui/themes";
import { ArrowClockwise, Cube, FileText, Storefront } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCustomerPortalOverview, listCustomerPortalOrders } from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { CustomerPortalOrder, CustomerPortalOverview } from "../types";
import { money } from "../../lib/format";
import { storefrontAccountKey, storefrontBasePath } from "../../lib/storefrontAccount";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

export function ResellerOrdersPage() {
  const { t } = useLocale();
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
        listCustomerPortalOrders(),
      ]);
      setOverview(nextOverview);
      setOrders(nextOrders);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("询价记录加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  if (loading && !overview) return <div className="core-workspace"><CoreLoading label={t("正在读取我的询价")} /></div>;
  const catalogPath = overview
    ? storefrontBasePath(
        overview.tenantSlug,
        storefrontAccountKey(overview.displayName, overview.membershipId),
      )
    : "/";

  return (
    <div className="core-workspace reseller-orders-page">
      <CorePageHeading
        eyebrow={t("销售")}
        title={t("我的询价")}
        description={t("这里只显示当前账户提交的询价记录与处理状态。")}
        actions={(
          <div className="core-heading-actions">
            <Button variant="soft" onClick={() => void load()} disabled={loading}><ArrowClockwise className={loading ? "is-spinning" : undefined} />{t("刷新")}</Button>
            <Button asChild><Link to={catalogPath} target="_blank" rel="noreferrer"><Storefront />{t("去商品前台")}</Link></Button>
          </div>
        )}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {!error && !orders.length ? <CoreEmpty title={t("还没有询价记录")} description={t("在商品前台选择商品并提交后，记录会显示在这里。")} action={<Button asChild><Link to={catalogPath} target="_blank" rel="noreferrer"><Cube />{t("去选品")}</Link></Button>} /> : null}
      {orders.length ? <Card className="reseller-orders-table-card">
        <div className="reseller-table-scroll">
          <div className="reseller-orders-table reseller-orders-table-head"><span>{t("询价编号")}</span><span>{t("客户")}</span><span>{t("金额")}</span><span>{t("状态")}</span><span>{t("提交时间")}</span><span>{t("有效期")}</span></div>
          {orders.map((order) => <div className="reseller-orders-table reseller-orders-table-row" key={order.id}>
            <strong className="core-tabular">{order.quoteNumber}</strong>
            <span><strong>{order.customerCompany || order.customerName}</strong><small>{order.customerCompany ? order.customerName : t("当前账号")}</small></span>
            <strong>{money(order.totalAmount, order.currency)}</strong>
            <Badge color={order.status === "PENDING_CONFIRMATION" ? "amber" : order.status === "CONFIRMED" ? "jade" : "gray"}>{t(orderStatusLabel[order.status] ?? order.status)}</Badge>
            <time>{coreDate(order.createdAt)}</time>
            <time>{coreDate(order.validUntil)}</time>
          </div>)}
        </div>
      </Card> : null}
      <Card className="reseller-visibility-note"><FileText /><Text size="2" color="gray">{t("报价页面只展示当前账号可见的商品和价格；供应商和内部成本信息不会显示。")}</Text></Card>
    </div>
  );
}
