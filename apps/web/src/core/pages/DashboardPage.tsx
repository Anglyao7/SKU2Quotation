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
import { useLocale } from "../LocaleContext";
import type { DashboardMetric, DashboardSnapshot } from "../types";

const metricNames: Record<string, string> = {
  active_skus: "有效 SKU",
  today_inquiries: "今日询盘",
  inquiries_today: "今日询盘",
  open_inquiries: "进行中询盘",
  pending_quotations: "待确认报价",
};

const destination: Record<string, string> = {
  active_skus: "/console/products",
  today_inquiries: "/console/inquiries",
  inquiries_today: "/console/inquiries",
  open_inquiries: "/console/inquiries",
  pending_quotations: "/console/quotes",
};

const metricIcons: Record<string, typeof Cube> = {
  active_skus: Cube,
  today_inquiries: ChatCircleDots,
  inquiries_today: ChatCircleDots,
  open_inquiries: ChatCircleDots,
  pending_quotations: FileText,
};

const priorityKeys = [
  "pending_quotations",
  "open_inquiries",
  "today_inquiries",
  "inquiries_today",
];

const importStatusLabel: Record<string, string> = {
  scanning: "读取文件",
  parsing: "导入中",
  needs_review: "待复核",
  published: "已完成",
  failed: "导入失败",
};

export function CoreDashboardPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canViewProducts = hasPermission("product.view");
  const canViewInquiries = hasPermission("inquiry.view");
  const canViewQuotes = hasPermission("quotation.view");
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
    catch (reason) { setError(reason instanceof Error ? reason.message : t("经营概览加载失败")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);

  const metrics = useMemo(
    () => (data?.metrics ?? [])
      .filter((metric) => metric.key !== "active_suppliers" && metric.key !== "pending_product_reviews")
      .slice(0, 4),
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
  if (loading && !data) return <div className="core-workspace"><CoreLoading label={t("正在读取实时经营数据")} /></div>;

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t(data?.dataScope === "SELF" ? "我的工作台" : "当前商家 · 实时数据")}
        title={t("工作台")}
        description={t("先处理需要确认的业务，再继续整理 SKU 商品库与报价。")}
        actions={canViewProducts ? <><Button asChild variant="soft"><Link to="/console/ai-search"><Sparkle />{t("AI 查找")}</Link></Button><Button asChild><Link to="/console/products"><Cube />{t("管理 SKU")}</Link></Button></> : undefined}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

      <section className="core-dashboard-focus">
        <Card className="core-focus-card">
          <div className="core-panel-heading">
            <div><Text size="1" color="gray">{t("今日待办")}</Text><Heading size="5">{t(priorities.length ? "需要你确认的事项" : "当前没有紧急事项")}</Heading></div>
            <Badge color={priorities.length ? "amber" : "jade"}>{priorities.length ? t("{count} 类待处理", { count: priorities.length }) : t("状态正常")}</Badge>
          </div>
          {priorities.length ? (
            <div className="core-priority-list">
              {priorities.map((metric) => <PriorityRow metric={metric} key={metric.key} />)}
            </div>
          ) : (
            <div className="core-clear-state">
              <span><CheckCircle size={24} weight="duotone" /></span>
              <div><Text weight="medium" as="div">{t("待确认与进行中事项均已清空")}</Text><Text size="2" color="gray">{t(canViewProducts ? "可以继续补充商品资料，或从客户需求开始一次新的匹配。" : "当前没有需要处理的业务事项。")}</Text></div>
            </div>
          )}
          {canImport || canViewInquiries || canViewQuotes ? <div className="core-quick-actions" aria-label={t("常用操作")}>
            {canImport ? <Button asChild variant="soft" color="gray"><Link to="/console/products?import=1"><FileArrowUp />{t("导入商品")}</Link></Button> : null}
            {canViewInquiries ? <Button asChild variant="soft" color="gray"><Link to="/console/inquiries"><ChatCircleDots />{t("新建询盘")}</Link></Button> : null}
            {canViewQuotes ? <Button asChild variant="soft" color="gray"><Link to="/console/quotes"><FileText />{t("查看报价")}</Link></Button> : null}
          </div> : null}
        </Card>

        {canViewProducts ? <Card className="core-panel core-health-panel">
          <div className="core-panel-heading"><div><Text size="1" color="gray">{t("商品资料完整度")}</Text><Heading size="5">{data?.dataHealth ? `${data.dataHealth.score} / 100` : t("暂不可见")}</Heading></div><Package size={23} /></div>
          {data?.dataHealth ? (
            <div className="core-health">
              <Health label={t("已批准图片")} value={data.dataHealth.approvedImageCoverage} />
              <Health label={t("有效价格")} value={data.dataHealth.validPriceCoverage} />
              <Button asChild variant="ghost" size="1"><Link to="/console/products">{t("完善商品资料")}<ArrowRight /></Link></Button>
            </div>
          ) : <Text size="2" color="gray">{t("当前角色无法查看资料完整度。")}</Text>}
        </Card> : null}
      </section>

      <section className="core-metric-grid" aria-label={t("经营指标")}>
        {metrics.map((metric, index) => (
          <Card asChild key={metric.key} className="core-metric-card">
            <Link to={destination[metric.key] ?? metric.destination ?? "/console"}>
              <MetricIcon metric={metric} fallbackIndex={index} />
              <span className="core-metric-copy">
                <Text size="2" color="gray">{t(metricNames[metric.key] ?? metric.label)}</Text>
                <strong>{metric.value.toLocaleString(locale)}{metric.unit ?? ""}</strong>
              </span>
              <span className="core-metric-foot"><Text size="1" color="gray">{t(metric.status === "AVAILABLE" ? "实时更新" : "部分数据暂不可用")}</Text><ArrowRight /></span>
            </Link>
          </Card>
        ))}
      </section>

      {canViewProducts ? <Card className="core-panel">
        <div className="core-panel-heading"><div><Text size="1" color="gray">{t("最近导入")}</Text><Heading size="4">{t("商品导入记录")}</Heading></div>{canImport ? <Button asChild size="1" variant="ghost"><Link to="/console/products?import=1">{t("查看全部")}</Link></Button> : null}</div>
        {templateImports.length ? <div className="core-list">
          {templateImports.slice(0, 6).map((job) => (
            <div className="core-list-row" key={job.id}>
              <span className="core-row-icon"><FileText /></span>
              <div><Text weight="medium" as="div">{job.filename}</Text><Text size="1" color="gray">{t("{products} 个 SKU · {warnings} 条提醒", { products: job.productsCount, warnings: job.warningsCount })}</Text></div>
              <Badge color={job.status === "failed" ? "red" : job.status === "published" ? "jade" : "amber"}>{t(importStatusLabel[job.status] ?? job.status)}</Badge>
              <Text size="1" color="gray">{coreDate(job.createdAt)}</Text>
            </div>
          ))}
        </div> : <CoreEmpty title={t("还没有导入记录")} description={t("下载标准模板并填写商品资料；以后每次上传都会按 SKU 增量合并。")} action={canImport ? <Button asChild variant="soft"><Link to="/console/products?import=1"><FileArrowUp />{t("导入商品")}</Link></Button> : undefined} />}
      </Card> : null}
    </div>
  );
}

function MetricIcon({ metric, fallbackIndex }: { metric: DashboardMetric; fallbackIndex: number }) {
  const Icon = metricIcons[metric.key] ?? (fallbackIndex % 2 ? FileText : Cube);
  return <span className="core-metric-icon"><Icon /></span>;
}

function PriorityRow({ metric }: { metric: DashboardMetric }) {
  const { locale, t } = useLocale();
  const Icon = metricIcons[metric.key] ?? FileText;
  return (
    <Link className="core-priority-row" to={destination[metric.key] ?? metric.destination ?? "/console"}>
      <span className="core-row-icon"><Icon /></span>
      <span><Text weight="medium" as="div">{t(metricNames[metric.key] ?? metric.label)}</Text><Text size="1" color="gray">{t("打开工作区处理并确认")}</Text></span>
      <strong>{metric.value.toLocaleString(locale)}</strong>
      <ArrowRight />
    </Link>
  );
}

function Health({ label, value }: { label: string; value: number }) {
  const normalized = value <= 1 ? value * 100 : value;
  return <div className="core-health-line"><div><Text size="1" color="gray">{label}</Text><Text size="1" weight="bold">{Math.round(normalized)}%</Text></div><Progress value={normalized} /></div>;
}
