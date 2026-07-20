import { Badge, Button, Card, Heading, Progress, Text } from "@radix-ui/themes";
import { ArrowRight, Database, FileText, Package, Sparkle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard } from "../api";
import { CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import type { DashboardSnapshot } from "../types";

const metricNames: Record<string, string> = {
  active_skus: "有效 SKU",
  active_suppliers: "活跃供应商",
  today_inquiries: "今日询盘",
  inquiries_today: "今日询盘",
  open_inquiries: "进行中询盘",
  pending_quotations: "待确认报价",
  pending_product_reviews: "待审核产品",
};

const destination: Record<string, string> = {
  active_skus: "/console/products",
  active_suppliers: "/console/suppliers",
  today_inquiries: "/console/inquiries",
  inquiries_today: "/console/inquiries",
  open_inquiries: "/console/inquiries",
  pending_quotations: "/console/quotes",
  pending_product_reviews: "/console/products/review",
};

export function CoreDashboardPage() {
  const [data, setData] = useState<DashboardSnapshot>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setData(await getDashboard()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "经营概览加载失败"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const metrics = useMemo(() => (data?.metrics ?? []).slice(0, 4), [data]);
  if (loading && !data) return <div className="core-workspace"><CoreLoading label="正在读取实时经营数据" /></div>;

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={data?.dataScope === "SELF" ? "我的工作台" : "企业经营指挥中心"}
        title="今天最需要关注的业务"
        description="询盘、报价、产品审核与供应网络均来自当前租户的实时数据。"
        actions={<><Button asChild variant="soft"><Link to="/console/ai-search"><Sparkle />AI 查产品</Link></Button><Button onClick={() => void load()}>刷新</Button></>}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      <section className="core-metric-grid">
        {metrics.map((metric, index) => (
          <Card asChild key={metric.key} className="core-metric-card">
            <Link to={destination[metric.key] ?? metric.destination ?? "/console"}>
              <span className="core-metric-icon">{index % 2 ? <FileText /> : <Database />}</span>
              <Text size="2" color="gray">{metricNames[metric.key] ?? metric.label}</Text>
              <strong>{metric.value.toLocaleString("zh-CN")}{metric.unit ?? ""}</strong>
              <Text size="1" color="gray">{metric.status === "AVAILABLE" ? "实时数据" : "部分数据源降级"}</Text>
            </Link>
          </Card>
        ))}
      </section>

      <section className="core-dashboard-grid">
        <Card className="core-panel core-ai-brief">
          <div className="core-panel-heading"><div><Text size="1" color="gray">AI 业务简报</Text><Heading size="4">人工确认前的优先事项</Heading></div><Sparkle size={24} /></div>
          <Text size="3">系统已经整理当前租户的待办。产品字段与报价版本仍需授权成员确认后才能发布或对客。</Text>
          <div className="core-action-links"><Button asChild><Link to="/console/inquiries">处理询盘<ArrowRight /></Link></Button><Button asChild variant="soft"><Link to="/console/products/review">审核产品</Link></Button></div>
        </Card>
        <Card className="core-panel">
          <div className="core-panel-heading"><div><Text size="1" color="gray">唯一事实来源</Text><Heading size="4">产品数据健康度</Heading></div><Package size={24} /></div>
          {data?.dataHealth ? (
            <div className="core-health">
              <div className="core-health-score"><strong>{data.dataHealth.score}</strong><span>/100</span></div>
              <Health label="已批准图片" value={data.dataHealth.approvedImageCoverage} />
              <Health label="供应商证据" value={data.dataHealth.supplierSourceCoverage} />
              <Health label="有效价格" value={data.dataHealth.validPriceCoverage} />
            </div>
          ) : <Text size="2" color="gray">当前角色无法查看数据健康度。</Text>}
        </Card>
      </section>

      <Card className="core-panel">
        <div className="core-panel-heading"><div><Text size="1" color="gray">最近动态</Text><Heading size="4">产品与供应网络</Heading></div><Button asChild size="1" variant="ghost"><Link to="/console/suppliers">查看全部</Link></Button></div>
        <div className="core-list">
          {data?.recentImports.slice(0, 6).map((job) => (
            <div className="core-list-row" key={job.id}>
              <span className="core-row-icon"><FileText /></span>
              <div><Text weight="medium" as="div">{job.filename}</Text><Text size="1" color="gray">{job.supplierName} · {job.productsCount} 条候选 · {job.warningsCount} 条提醒</Text></div>
              <Badge color={job.status === "failed" ? "red" : job.status === "parsing" ? "amber" : "jade"}>{job.status}</Badge>
              <Text size="1" color="gray">{coreDate(job.createdAt)}</Text>
            </div>
          ))}
          {!data?.recentImports.length ? <Text size="2" color="gray">当前租户暂无导入动态。</Text> : null}
        </div>
      </Card>
    </div>
  );
}

function Health({ label, value }: { label: string; value: number }) {
  const normalized = value <= 1 ? value * 100 : value;
  return <div className="core-health-line"><div><Text size="1" color="gray">{label}</Text><Text size="1" weight="bold">{Math.round(normalized)}%</Text></div><Progress value={normalized} /></div>;
}
