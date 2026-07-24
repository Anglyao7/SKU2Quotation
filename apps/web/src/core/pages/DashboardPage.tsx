import { Badge, Button, Card, Heading, Progress, Text } from "@radix-ui/themes";
import {
  ArrowRight,
  ChatCircleDots,
  CheckCircle,
  Cube,
  FileArrowUp,
  FileText,
  Package,
  Sparkle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import type { DashboardMetric, DashboardSnapshot } from "../types";

const metricNames: Record<string, string> = {
  active_skus: "有效 SKU",
  today_inquiries: "今日询盘",
  inquiries_today: "今日询盘",
  open_inquiries: "进行中询盘",
  pending_quotations: "待确认报价",
  pending_product_reviews: "待审核产品",
};

const destination: Record<string, string> = {
  active_skus: "/console/products",
  today_inquiries: "/console/inquiries",
  inquiries_today: "/console/inquiries",
  open_inquiries: "/console/inquiries",
  pending_quotations: "/console/quotes",
  pending_product_reviews: "/console/products/review",
};

const metricIcons: Record<string, typeof Cube> = {
  active_skus: Cube,
  today_inquiries: ChatCircleDots,
  inquiries_today: ChatCircleDots,
  open_inquiries: ChatCircleDots,
  pending_quotations: FileText,
  pending_product_reviews: Package,
};

const priorityKeys = [
  "pending_product_reviews",
  "pending_quotations",
  "open_inquiries",
  "today_inquiries",
  "inquiries_today",
];

const importStatusLabel: Record<string, string> = {
  scanning: "安全扫描",
  parsing: "导入中",
  needs_review: "待复核",
  published: "已完成",
  failed: "导入失败",
};

export function CoreDashboardPage() {
  const { hasPermission } = useCoreAuth();
  const canImport = hasPermission("product.import")
    && hasPermission("product.edit")
    && hasPermission("catalog.publish");
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

  const metrics = useMemo(
    () => (data?.metrics ?? []).filter((metric) => metric.key !== "active_suppliers").slice(0, 4),
    [data],
  );
  const priorities = useMemo(
    () => (data?.metrics ?? [])
      .filter((metric) => priorityKeys.includes(metric.key) && metric.value > 0)
      .sort((left, right) => priorityKeys.indexOf(left.key) - priorityKeys.indexOf(right.key))
      .slice(0, 3),
    [data],
  );
  const templateImports = useMemo(
    () => (data?.recentImports ?? []).filter((job) => job.sourceType === "PRODUCT_TEMPLATE"),
    [data],
  );
  if (loading && !data) return <div className="core-workspace"><CoreLoading label="正在读取实时经营数据" /></div>;

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={data?.dataScope === "SELF" ? "我的工作台" : "当前商家 · 实时数据"}
        title="工作台"
        description="先处理需要确认的业务，再继续整理 SKU 商品库与报价。"
        actions={<><Button asChild variant="soft"><Link to="/console/ai-search"><Sparkle />AI 查找</Link></Button><Button asChild><Link to="/console/products"><Cube />管理 SKU</Link></Button></>}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

      <section className="core-dashboard-focus">
        <Card className="core-focus-card">
          <div className="core-panel-heading">
            <div><Text size="1" color="gray">今日待办</Text><Heading size="5">{priorities.length ? "需要你确认的事项" : "当前没有紧急事项"}</Heading></div>
            <Badge color={priorities.length ? "amber" : "jade"}>{priorities.length ? `${priorities.length} 类待处理` : "状态正常"}</Badge>
          </div>
          {priorities.length ? (
            <div className="core-priority-list">
              {priorities.map((metric) => <PriorityRow metric={metric} key={metric.key} />)}
            </div>
          ) : (
            <div className="core-clear-state">
              <span><CheckCircle size={24} weight="duotone" /></span>
              <div><Text weight="medium" as="div">待审核、待确认与进行中事项均已清空</Text><Text size="2" color="gray">可以继续补充商品资料，或从客户需求开始一次新的匹配。</Text></div>
            </div>
          )}
          <div className="core-quick-actions" aria-label="常用操作">
            {canImport ? <Button asChild variant="soft" color="gray"><Link to="/console/products?import=1"><FileArrowUp />导入商品模版</Link></Button> : null}
            <Button asChild variant="soft" color="gray"><Link to="/console/inquiries"><ChatCircleDots />新建询盘</Link></Button>
            <Button asChild variant="soft" color="gray"><Link to="/console/quotes"><FileText />查看报价</Link></Button>
          </div>
        </Card>

        <Card className="core-panel core-health-panel">
          <div className="core-panel-heading"><div><Text size="1" color="gray">商品资料完整度</Text><Heading size="5">{data?.dataHealth ? `${data.dataHealth.score} / 100` : "暂不可见"}</Heading></div><Package size={23} /></div>
          {data?.dataHealth ? (
            <div className="core-health">
              <Health label="已批准图片" value={data.dataHealth.approvedImageCoverage} />
              <Health label="有效价格" value={data.dataHealth.validPriceCoverage} />
              <Button asChild variant="ghost" size="1"><Link to="/console/products">完善商品资料<ArrowRight /></Link></Button>
            </div>
          ) : <Text size="2" color="gray">当前角色无法查看资料完整度。</Text>}
        </Card>
      </section>

      <section className="core-metric-grid" aria-label="经营指标">
        {metrics.map((metric, index) => (
          <Card asChild key={metric.key} className="core-metric-card">
            <Link to={destination[metric.key] ?? metric.destination ?? "/console"}>
              <MetricIcon metric={metric} fallbackIndex={index} />
              <span className="core-metric-copy">
                <Text size="2" color="gray">{metricNames[metric.key] ?? metric.label}</Text>
                <strong>{metric.value.toLocaleString("zh-CN")}{metric.unit ?? ""}</strong>
              </span>
              <span className="core-metric-foot"><Text size="1" color="gray">{metric.status === "AVAILABLE" ? "实时更新" : "部分数据暂不可用"}</Text><ArrowRight /></span>
            </Link>
          </Card>
        ))}
      </section>

      <Card className="core-panel">
        <div className="core-panel-heading"><div><Text size="1" color="gray">最近导入</Text><Heading size="4">商品模版处理记录</Heading></div>{canImport ? <Button asChild size="1" variant="ghost"><Link to="/console/products?import=1">查看全部</Link></Button> : null}</div>
        {templateImports.length ? <div className="core-list">
          {templateImports.slice(0, 6).map((job) => (
            <div className="core-list-row" key={job.id}>
              <span className="core-row-icon"><FileText /></span>
              <div><Text weight="medium" as="div">{job.filename}</Text><Text size="1" color="gray">{job.productsCount} 个 SKU · {job.warningsCount} 条提醒</Text></div>
              <Badge color={job.status === "failed" ? "red" : job.status === "published" ? "jade" : "amber"}>{importStatusLabel[job.status] ?? job.status}</Badge>
              <Text size="1" color="gray">{coreDate(job.createdAt)}</Text>
            </div>
          ))}
        </div> : <CoreEmpty title="还没有导入记录" description="使用固定的商品模版.xlsx，一次导入当前商家的全部商品。" action={canImport ? <Button asChild variant="soft"><Link to="/console/products?import=1"><FileArrowUp />导入商品模版</Link></Button> : undefined} />}
      </Card>
    </div>
  );
}

function MetricIcon({ metric, fallbackIndex }: { metric: DashboardMetric; fallbackIndex: number }) {
  const Icon = metricIcons[metric.key] ?? (fallbackIndex % 2 ? FileText : Cube);
  return <span className="core-metric-icon"><Icon /></span>;
}

function PriorityRow({ metric }: { metric: DashboardMetric }) {
  const Icon = metricIcons[metric.key] ?? FileText;
  return (
    <Link className="core-priority-row" to={destination[metric.key] ?? metric.destination ?? "/console"}>
      <span className="core-row-icon"><Icon /></span>
      <span><Text weight="medium" as="div">{metricNames[metric.key] ?? metric.label}</Text><Text size="1" color="gray">打开工作区处理并确认</Text></span>
      <strong>{metric.value.toLocaleString("zh-CN")}</strong>
      <ArrowRight />
    </Link>
  );
}

function Health({ label, value }: { label: string; value: number }) {
  const normalized = value <= 1 ? value * 100 : value;
  return <div className="core-health-line"><div><Text size="1" color="gray">{label}</Text><Text size="1" weight="bold">{Math.round(normalized)}%</Text></div><Progress value={normalized} /></div>;
}
