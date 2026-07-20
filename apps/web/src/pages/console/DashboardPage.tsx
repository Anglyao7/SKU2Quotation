import { Badge, Button, Card, Heading, Text } from "@radix-ui/themes";
import { CurrencyCircleDollar, FileText, ListBullets, ToggleRight } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useAuth } from "../../context/AuthContext";
import { api } from "../../lib/api";
import { dateTime, money, quoteNumber } from "../../lib/format";
import type { DashboardData } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

export function DashboardPage() {
  const { user } = useAuth();
  const { activeTenantId } = useOutletContext<ConsoleOutletContext>();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const isPlatformAdmin = user?.role === "platform_admin";

  const load = useCallback(async () => {
    if (isPlatformAdmin && !activeTenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setData(await api.getDashboard());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "仪表盘加载失败。");
    } finally {
      setLoading(false);
    }
  }, [activeTenantId, isPlatformAdmin]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="console-page">
      <div className="page-heading-row">
        <div><Text size="2" color="gray">今日工作概览</Text><Heading size="7">仪表盘</Heading></div>
        <Button asChild><Link to="/console/skus">管理 SKU</Link></Button>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : (
        <>
          <div className="metrics-grid">
            <Metric icon={<ListBullets size={21} />} label="SKU 总数" value={loading ? "-" : (data?.sku_count || 0).toLocaleString("zh-CN")} note="当前商家商品资料" />
            <Metric icon={<ToggleRight size={21} />} label="在售 SKU" value={loading ? "-" : (data?.active_sku_count || 0).toLocaleString("zh-CN")} note="在商品前台可见" />
            <Metric icon={<FileText size={21} />} label="累计报价" value={loading ? "-" : (data?.quote_count || 0).toLocaleString("zh-CN")} note="已生成的报价记录" />
            <Metric icon={<CurrencyCircleDollar size={21} />} label="累计报价金额" value={loading ? "-" : money(data?.quote_total, data?.tenant?.default_currency || "CNY")} note="按当前商家默认币种" />
          </div>

          <div className="dashboard-grid">
            <Card className="dashboard-panel" variant="surface">
              <div className="panel-heading"><div><Heading size="4">最近报价</Heading><Text size="2" color="gray">最新生成的客户报价记录</Text></div><Button asChild size="1" variant="ghost"><Link to="/console/quotes">查看全部</Link></Button></div>
              {loading ? <TableSkeleton rows={5} /> : data?.recent_quotes?.length ? (
                <div className="compact-list">
                  {data.recent_quotes.slice(0, 5).map((quote) => (
                    <div className="compact-list-row" key={quote.id}>
                      <div><Text size="2" weight="medium" as="div">{quote.customer_company || quote.customer_name}</Text><Text size="1" color="gray" className="mono-text">{quoteNumber(quote)}</Text></div>
                      <div className="row-end"><Text size="2" weight="medium">{money(quote.total_amount, quote.currency)}</Text><Text size="1" color="gray">{dateTime(quote.created_at)}</Text></div>
                    </div>
                  ))}
                </div>
              ) : <EmptyState title="还没有报价记录" description="客户从前台提交报价后会显示在这里。" />}
            </Card>

            <Card className="dashboard-panel category-panel" variant="surface">
              <div className="panel-heading"><div><Heading size="4">类目分布</Heading><Text size="2" color="gray">当前商家 SKU 的主要类目</Text></div></div>
              {loading ? <TableSkeleton rows={5} /> : data?.top_categories?.length ? (
                <div className="category-list">
                  {data.top_categories.slice(0, 6).map((category, index) => (
                    <div className="category-row" key={category.name}>
                      <span className="category-index">{String(index + 1).padStart(2, "0")}</span>
                      <Text size="2" weight="medium">{category.name}</Text>
                      <Badge color="gray" variant="soft">{category.count.toLocaleString("zh-CN")}</Badge>
                    </div>
                  ))}
                </div>
              ) : <EmptyState title="暂无类目统计" description="为 SKU 填写类目后会自动汇总。" />}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: string; note: string }) {
  return (
    <Card className="metric-card" variant="surface">
      <span className="metric-icon">{icon}</span>
      <Text size="2" color="gray">{label}</Text>
      <strong>{value}</strong>
      <Text size="1" color="gray">{note}</Text>
    </Card>
  );
}
