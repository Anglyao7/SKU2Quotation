import {
  Badge,
  Button,
  Card,
  Heading,
  Text,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ChatCircleDots,
  ChartLineUp,
  CursorClick,
  FileText,
  ImageSquare,
  Storefront,
  UsersThree,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { api } from "../../lib/api";
import type { PlatformTenantUsageItem, PlatformUsageResponse } from "../../types";

type UsageRange = 7 | 30 | 60 | 90;

function number(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value);
}

function statusLabel(status: string, t: (key: string) => string) {
  if (status === "active") return t("正常");
  if (status === "suspended") return t("已暂停");
  if (status === "archived") return t("已归档");
  return status;
}

export function PlatformUsageAnalyticsPage() {
  const { locale, t } = useLocale();
  const [range, setRange] = useState<UsageRange>(30);
  const [snapshot, setSnapshot] = useState<PlatformUsageResponse>();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (foreground = false) => {
    setError("");
    if (foreground) setRefreshing(true);
    else setLoading(true);
    try {
      setSnapshot(await api.getPlatformUsage(range));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家数据加载失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [range, t]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${t("商家数据监控")} | ${t("智贸云")}`;
    return () => { document.title = previousTitle; };
  }, [t]);

  const totalCards = useMemo(() => {
    const totals = snapshot?.totals;
    return [
      {
        key: "storefront_visitors",
        label: t("店铺访问人数"),
        value: totals?.storefront_visitors ?? 0,
        icon: Storefront,
        tone: "blue",
      },
      {
        key: "product_clicks",
        label: t("商品点击次数"),
        value: totals?.product_clicks ?? 0,
        icon: CursorClick,
        tone: "indigo",
      },
      {
        key: "quote_requests",
        label: t("报价请求"),
        value: totals?.quote_requests ?? 0,
        icon: FileText,
        tone: "amber",
      },
      {
        key: "quotations",
        label: t("已制作报价单"),
        value: totals?.quotations ?? 0,
        icon: ChartLineUp,
        tone: "green",
      },
      {
        key: "image_searches",
        label: t("图片搜索次数"),
        value: totals?.image_searches ?? 0,
        icon: ImageSquare,
        tone: "purple",
      },
      {
        key: "ai_conversations",
        label: t("AI 客服对话"),
        value: totals?.ai_conversations ?? 0,
        icon: ChatCircleDots,
        tone: "teal",
      },
    ] as const;
  }, [snapshot?.totals, t]);

  return (
    <div className="core-workspace platform-usage-page">
      <CorePageHeading
        eyebrow={t("平台运维")}
        title={t("商家数据监控")}
        actions={(
          <div className="platform-usage-heading-actions">
            <div className="platform-usage-range" role="group" aria-label={t("统计时间范围")}>
              {[7, 30, 60, 90].map((days) => (
                <Button
                  key={days}
                  size="2"
                  variant={range === days ? "solid" : "soft"}
                  color={range === days ? "blue" : "gray"}
                  onClick={() => setRange(days as UsageRange)}
                >
                  {t("近 {days} 天", { days })}
                </Button>
              ))}
            </div>
            <Button
              size="2"
              variant="soft"
              color="gray"
              loading={refreshing}
              onClick={() => void load(true)}
            >
              <ArrowClockwise />
              {t("刷新")}
            </Button>
          </div>
        )}
      />
      <Text size="2" color="gray" className="platform-usage-description">
        {t("按店铺汇总访问、商品互动、报价、图片搜索与客服使用情况。仅展示聚合统计，不展示访客原始信息。")}
      </Text>

      {loading && !snapshot ? <CoreLoading label={t("正在读取商家数据")} /> : null}
      {error && !snapshot ? <CoreError message={error} onRetry={() => void load(true)} /> : null}
      {snapshot ? (
        <>
          {error ? (
            <Card className="platform-usage-inline-error">
              <Text size="2">{t("本次刷新失败，页面保留上一份有效数据：{message}", { message: error })}</Text>
            </Card>
          ) : null}
          <div className="platform-usage-summary-grid">
            {totalCards.map((item) => {
              const Icon = item.icon;
              return (
                <Card className={`platform-usage-summary-card is-${item.tone}`} key={item.key}>
                  <span className="platform-usage-summary-icon"><Icon weight="duotone" /></span>
                  <div>
                    <Text size="1" color="gray">{item.label}</Text>
                    <Heading size="6">{number(item.value, locale)}</Heading>
                  </div>
                </Card>
              );
            })}
          </div>

          <Card className="platform-usage-table-card">
            <div className="platform-usage-table-heading">
              <div>
                <Heading size="4">{t("店铺明细")}</Heading>
                <Text size="2" color="gray">
                  {t("统计周期：{start} 至 {end}", { start: snapshot.start_date, end: snapshot.end_date })}
                </Text>
              </div>
              <Badge color="gray" variant="soft">
                {t("{count} 家店铺", { count: snapshot.tenants.length })}
              </Badge>
            </div>
            {snapshot.tenants.length === 0 ? (
              <div className="platform-usage-empty"><UsersThree /><Text>{t("暂无商家数据")}</Text></div>
            ) : (
              <div className="platform-usage-table-scroll">
                <div className="platform-usage-table" role="table" aria-label={t("店铺数据") }>
                  <div className="platform-usage-table-row is-header" role="row">
                    <span role="columnheader">{t("店铺")}</span>
                    <span role="columnheader">{t("访问人数")}</span>
                    <span role="columnheader">{t("商品点击")}</span>
                    <span role="columnheader">{t("报价请求")}</span>
                    <span role="columnheader">{t("已制作报价单")}</span>
                    <span role="columnheader">{t("图片搜索")}</span>
                    <span role="columnheader">{t("AI 客服对话")}</span>
                  </div>
                  {snapshot.tenants.map((tenant) => (
                    <UsageRow key={tenant.tenant_id} tenant={tenant} locale={locale} t={t} />
                  ))}
                </div>
              </div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}

function UsageRow({
  tenant,
  locale,
  t,
}: {
  tenant: PlatformTenantUsageItem;
  locale: string;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div className="platform-usage-table-row" role="row">
      <span className="platform-usage-tenant" role="cell">
        <strong>{tenant.name}</strong>
        <small>{tenant.slug}</small>
        <Badge color={tenant.active ? "green" : "gray"} variant="soft">{statusLabel(tenant.status, t)}</Badge>
      </span>
      <span role="cell">{number(tenant.storefront_visitors, locale)}</span>
      <span role="cell">{number(tenant.product_clicks, locale)}</span>
      <span role="cell">{number(tenant.quote_requests, locale)}</span>
      <span role="cell">{number(tenant.quotations, locale)}</span>
      <span role="cell">{number(tenant.image_searches, locale)}</span>
      <span role="cell">{number(tenant.ai_conversations, locale)}</span>
    </div>
  );
}
