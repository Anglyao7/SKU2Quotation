import { Button, Card, Text } from "@radix-ui/themes";
import {
  ArrowRight,
  ChatCircleDots,
  Clock,
  Cube,
  CurrencyDollar,
  FileText,
  GlobeHemisphereWest,
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
  const market = data?.market;
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
      {market ? <DashboardMarketPanel market={market} locale={locale} t={t} /> : null}
    </div>
  );
}

function DashboardMarketPanel({
  market,
  locale,
  t,
}: {
  market: NonNullable<DashboardSnapshot["market"]>;
  locale: string;
  t: (value: string, variables?: Record<string, string | number>) => string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const formatLocalTime = (timezone: string, fallback: string) => {
    try {
      return new Intl.DateTimeFormat(locale, {
        timeZone: timezone,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(now));
    } catch {
      return fallback.slice(11, 19) || fallback;
    }
  };

  return (
    <section className="core-market-section" aria-label={t("全球时间与汇率")}>
      <div className="core-market-heading">
        <div>
          <Text size="2" color="gray">{t("全球时间与汇率")}</Text>
          <h2>{t("主要市场时间")}</h2>
        </div>
        <span className="core-market-source">
          <GlobeHemisphereWest size={16} weight="duotone" />
          {t("实时参考")}
        </span>
      </div>
      <div className="core-market-layout">
        <div className="core-world-time-grid">
          {market.worldTimes.map((item) => (
            <Card key={item.key} className="core-world-time-card">
              <div className="core-world-time-top">
                <span className="core-market-flag" aria-hidden="true">{item.flag}</span>
                <span>
                  <strong>{t(item.label)}</strong>
                  <small>{item.city} · {item.language}</small>
                </span>
              </div>
              <div className="core-world-time-value">
                <Clock size={16} weight="duotone" />
                <strong>{formatLocalTime(item.timezone, item.localTime)}</strong>
              </div>
              <small className="core-world-time-meta">UTC{item.utcOffset} · {item.currency}</small>
            </Card>
          ))}
        </div>
        <Card className="core-exchange-rate-card">
          <div className="core-panel-heading">
            <div>
              <Text size="2" color="gray">{t("人民币参考汇率")}</Text>
              <h3>{t("1 CNY 对应")}</h3>
            </div>
            <CurrencyDollar size={25} weight="duotone" />
          </div>
          <div className="core-exchange-rate-list">
            {market.exchangeRates.map((item) => (
              <div className="core-exchange-rate-row" key={item.currency}>
                <span className="core-exchange-rate-name">
                  <strong>{item.currency}</strong>
                  <small>{t(item.name)}</small>
                </span>
                <strong className="core-exchange-rate-value">
                  {item.rate == null ? "—" : item.rate.toLocaleString(locale, { maximumFractionDigits: 4 })}
                </strong>
              </div>
            ))}
          </div>
          <small className="core-market-footnote">
            {market.rateDate ? t("参考日期：{date}", { date: market.rateDate }) : t("暂未取得最新汇率")}
            {" · "}{market.rateSource}
          </small>
        </Card>
      </div>
    </section>
  );
}

function MetricIcon({ metric, fallbackIndex }: { metric: DashboardMetric; fallbackIndex: number }) {
  const Icon = metricIcons[metric.key] ?? (fallbackIndex % 2 ? FileText : Cube);
  return <span className="core-metric-icon"><Icon /></span>;
}
