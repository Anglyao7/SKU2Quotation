import { Button, Card, Text } from "@radix-ui/themes";
import {
  ArrowRight,
  ChatCircleDots,
  Cube,
  FileText,
  Sparkle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
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

export function CoreDashboardPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canViewProducts = hasPermission("product.view");
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
      .filter((metric) => metric.key !== "pending_product_reviews"),
    [data],
  );
  if (loading && !data) return <div className="core-workspace"><CoreLoading label={t("正在读取实时经营数据")} /></div>;

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t(data?.dataScope === "SELF" ? "我的工作台" : "当前商家 · 实时数据")}
        title={t("工作台")}
        description={t("商品、询盘与报价的关键统计。")}
        actions={canViewProducts ? <><Button asChild variant="soft"><Link to="/console/ai-search"><Sparkle />{t("AI 查找")}</Link></Button><Button asChild><Link to="/console/products"><Cube />{t("管理 SKU")}</Link></Button></> : undefined}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

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
    </div>
  );
}

function MetricIcon({ metric, fallbackIndex }: { metric: DashboardMetric; fallbackIndex: number }) {
  const Icon = metricIcons[metric.key] ?? (fallbackIndex % 2 ? FileText : Cube);
  return <span className="core-metric-icon"><Icon /></span>;
}
