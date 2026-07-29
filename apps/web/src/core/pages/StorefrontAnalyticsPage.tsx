import {
  Badge,
  Button,
  Card,
  Heading,
  Text,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ChartLineUp,
  CursorClick,
  GlobeHemisphereWest,
  Info,
  Package,
  UsersThree,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { getStorefrontAnalytics } from "../api";
import { EChart, type EChartPalette } from "../components/EChart";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { StorefrontAnalyticsSnapshot } from "../types";

type AnalyticsRange = 7 | 30 | 60;

function compactLabel(value: string, length = 15) {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function regionName(code: string, locale: string) {
  if (code === "ZZ" || code === "XX") return locale === "en-US" ? "Unknown" : "未知地区";
  if (code === "T1") return locale === "en-US" ? "Tor network" : "Tor 网络";
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

function number(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value);
}

function axis(palette: EChartPalette) {
  return {
    axisLine: { lineStyle: { color: palette.line } },
    axisTick: { show: false },
    axisLabel: { color: palette.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: palette.line, type: "dashed" as const } },
  };
}

export function StorefrontAnalyticsPage() {
  const { locale, t } = useLocale();
  const [range, setRange] = useState<AnalyticsRange>(30);
  const [snapshot, setSnapshot] = useState<StorefrontAnalyticsSnapshot>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (nextRange: AnalyticsRange = range) => {
    setLoading(true);
    setError("");
    try {
      setSnapshot(await getStorefrontAnalytics(nextRange));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("网站监测数据加载失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [range, t]);

  useEffect(() => {
    void load(range);
  }, [load, range]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${t("网站监测")} | ${t("智贸云")}`;
    return () => {
      document.title = previousTitle;
    };
  }, [t]);

  const changeRange = (nextRange: AnalyticsRange) => {
    if (nextRange !== range) setRange(nextRange);
  };

  const trendOption = useMemo(
    () => (palette: EChartPalette): EChartsOption => ({
      aria: { enabled: true },
      color: [palette.accent],
      grid: { left: 44, right: 20, top: 24, bottom: 34 },
      tooltip: { trigger: "axis", confine: true },
      xAxis: {
        ...axis(palette),
        type: "category",
        boundaryGap: false,
        data: (snapshot?.daily || []).map((item) => (
          new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" })
            .format(new Date(`${item.date}T00:00:00`))
        )),
      },
      yAxis: {
        ...axis(palette),
        type: "value",
        minInterval: 1,
      },
      series: [{
        name: t("详情访问"),
        type: "line",
        smooth: 0.28,
        showSymbol: false,
        symbolSize: 7,
        lineStyle: { width: 2.4 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: palette.accentSoft },
              { offset: 1, color: "rgba(0,0,0,0)" },
            ],
          },
        },
        data: (snapshot?.daily || []).map((item) => item.views),
      }],
    }),
    [locale, snapshot?.daily, t],
  );

  const productOption = useMemo(
    () => (palette: EChartPalette): EChartsOption => {
      const rows = [...(snapshot?.products || []).slice(0, 8)].reverse();
      return {
        aria: { enabled: true },
        color: [palette.accent],
        grid: { left: 14, right: 30, top: 16, bottom: 12, containLabel: true },
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true },
        xAxis: {
          ...axis(palette),
          type: "value",
          minInterval: 1,
        },
        yAxis: {
          ...axis(palette),
          type: "category",
          data: rows.map((item) => compactLabel(item.name)),
          axisLabel: {
            color: palette.muted,
            fontSize: 11,
            width: 118,
            overflow: "truncate",
          },
        },
        series: [{
          name: t("详情访问"),
          type: "bar",
          barMaxWidth: 17,
          itemStyle: { borderRadius: [0, 5, 5, 0] },
          data: rows.map((item) => item.views),
        }],
      };
    },
    [snapshot?.products, t],
  );

  const countryOption = useMemo(
    () => (palette: EChartPalette): EChartsOption => {
      const rows = snapshot?.countries || [];
      return {
        aria: { enabled: true },
        color: [palette.accent],
        grid: { left: 44, right: 16, top: 18, bottom: 58 },
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true },
        xAxis: {
          ...axis(palette),
          type: "category",
          data: rows.map((item) => regionName(item.countryCode, locale)),
          axisLabel: {
            color: palette.muted,
            fontSize: 10,
            interval: 0,
            rotate: rows.length > 5 ? 28 : 0,
          },
        },
        yAxis: {
          ...axis(palette),
          type: "value",
          minInterval: 1,
        },
        series: [{
          name: t("详情访问"),
          type: "bar",
          barMaxWidth: 28,
          itemStyle: { borderRadius: [6, 6, 0, 0] },
          data: rows.map((item) => item.views),
        }],
      };
    },
    [locale, snapshot?.countries, t],
  );

  const heatmapOption = useMemo(
    () => (palette: EChartPalette): EChartsOption => {
      const products = (snapshot?.products || []).slice(0, 8);
      const countries = snapshot?.countries || [];
      const productIndex = new Map(products.map((item, index) => [item.skuId, index]));
      const countryIndex = new Map(countries.map((item, index) => [item.countryCode, index]));
      const values = (snapshot?.countryProducts || []).flatMap((item) => {
        const x = productIndex.get(item.skuId);
        const y = countryIndex.get(item.countryCode);
        return x === undefined || y === undefined ? [] : [[x, y, item.views]];
      });
      const maximum = Math.max(1, ...values.map((item) => Number(item[2])));
      return {
        aria: { enabled: true },
        grid: { left: 88, right: 22, top: 52, bottom: 92 },
        tooltip: {
          position: "top",
          confine: true,
          formatter: (parameters: any) => {
            const [x, y, views] = parameters.value as [number, number, number];
            return `${regionName(countries[y]?.countryCode || "ZZ", locale)}<br/>${products[x]?.name || "—"} · ${number(views, locale)}`;
          },
        },
        xAxis: {
          ...axis(palette),
          type: "category",
          data: products.map((item) => compactLabel(item.name, 11)),
          axisLabel: {
            color: palette.muted,
            fontSize: 10,
            interval: 0,
            rotate: 32,
          },
          splitArea: { show: true, areaStyle: { color: ["transparent"] } },
        },
        yAxis: {
          ...axis(palette),
          type: "category",
          data: countries.map((item) => regionName(item.countryCode, locale)),
          splitArea: { show: true, areaStyle: { color: ["transparent"] } },
        },
        visualMap: {
          min: 0,
          max: maximum,
          calculable: false,
          orient: "horizontal",
          left: "center",
          top: 0,
          text: [t("高频"), t("低频")],
          textStyle: { color: palette.muted, fontSize: 10 },
          inRange: { color: [palette.surface, palette.accentSoft, palette.accent] },
        },
        series: [{
          name: t("国家与商品访问"),
          type: "heatmap",
          data: values,
          label: {
            show: true,
            color: palette.ink,
            fontSize: 10,
            formatter: (parameters: any) => (
              Number(parameters.value?.[2] || 0) > 0
                ? number(Number(parameters.value[2]), locale)
                : ""
            ),
          },
          itemStyle: {
            borderColor: palette.surface,
            borderWidth: 3,
            borderRadius: 5,
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: palette.accentSoft,
            },
          },
        }],
      };
    },
    [locale, snapshot?.countries, snapshot?.countryProducts, snapshot?.products, t],
  );

  const hasData = Boolean(snapshot?.summary.totalViews);

  return (
    <div className="core-workspace storefront-analytics-page">
      <CorePageHeading
        eyebrow={t("商家前台")}
        title={t("网站监测")}
        description={t("观察商品详情访问趋势、主要访问国家，以及不同国家最常查看的商品。")}
        actions={(
          <div className="storefront-analytics-toolbar">
            <div className="storefront-analytics-range" aria-label={t("统计时间范围")}>
              {([7, 30, 60] as const).map((days) => (
                <button
                  type="button"
                  className={range === days ? "is-active" : ""}
                  aria-pressed={range === days}
                  onClick={() => changeRange(days)}
                  key={days}
                >
                  {t("近 {days} 天", { days })}
                </button>
              ))}
            </div>
            <Button
              variant="soft"
              color="gray"
              loading={loading && Boolean(snapshot)}
              onClick={() => void load(range)}
            >
              <ArrowClockwise />
              {t("刷新")}
            </Button>
          </div>
        )}
      />

      {loading && !snapshot ? <CoreLoading label="正在汇总前台访问数据" /> : null}
      {error && !snapshot ? <CoreError message={error} onRetry={() => void load(range)} /> : null}
      {error && snapshot ? (
        <Card className="storefront-analytics-inline-error">
          <Text size="2" color="red">{error}</Text>
          <Button size="1" variant="soft" color="gray" onClick={() => void load(range)}>
            {t("重试")}
          </Button>
        </Card>
      ) : null}

      {snapshot ? (
        <>
          <section className="storefront-analytics-metrics" aria-label={t("访问概览")}>
            <Card className="storefront-analytics-metric is-primary">
              <span><CursorClick weight="duotone" /></span>
              <div>
                <Text size="1" color="gray">{t("详情访问次数")}</Text>
                <strong>{number(snapshot.summary.totalViews, locale)}</strong>
              </div>
              <small>{t("每次真正进入商品详情后计数")}</small>
            </Card>
            <Card className="storefront-analytics-metric">
              <span><UsersThree weight="duotone" /></span>
              <div>
                <Text size="1" color="gray">{t("独立访客")}</Text>
                <strong>{number(snapshot.summary.uniqueVisitors, locale)}</strong>
              </div>
              <small>{t("按规范化 IP 去重")}</small>
            </Card>
            <Card className="storefront-analytics-metric">
              <span><Package weight="duotone" /></span>
              <div>
                <Text size="1" color="gray">{t("被查看商品")}</Text>
                <strong>{number(snapshot.summary.viewedProducts, locale)}</strong>
              </div>
              <small>{t("有详情访问的 SKU 数量")}</small>
            </Card>
            <Card className="storefront-analytics-metric">
              <span><GlobeHemisphereWest weight="duotone" /></span>
              <div>
                <Text size="1" color="gray">{t("已识别国家")}</Text>
                <strong>{number(snapshot.summary.identifiedCountries, locale)}</strong>
              </div>
              <small>{t("未知地区不计入国家数量")}</small>
            </Card>
          </section>

          {!hasData ? (
            <CoreEmpty
              title={t("还没有商品详情访问")}
              description={t("访客从商家前台进入某个 SKU 的详情页后，趋势与国家分布会开始出现在这里。")}
            />
          ) : (
            <section className="storefront-analytics-charts">
              <Card className="storefront-analytics-chart is-trend">
                <div className="storefront-analytics-chart-heading">
                  <div>
                    <Text size="1" color="gray">{t("访问趋势")}</Text>
                    <Heading size="4">{t("每日商品详情访问")}</Heading>
                  </div>
                  <Badge variant="soft" color="gray">{snapshot.timezone}</Badge>
                </div>
                <EChart
                  option={trendOption}
                  label={t("每日商品详情访问折线图")}
                  className="is-trend"
                />
              </Card>

              <Card className="storefront-analytics-chart">
                <div className="storefront-analytics-chart-heading">
                  <div>
                    <Text size="1" color="gray">{t("商品热度")}</Text>
                    <Heading size="4">{t("访问最多的商品")}</Heading>
                  </div>
                  <Package weight="duotone" />
                </div>
                <EChart
                  option={productOption}
                  label={t("访问最多的商品条形图")}
                />
              </Card>

              <Card className="storefront-analytics-chart">
                <div className="storefront-analytics-chart-heading">
                  <div>
                    <Text size="1" color="gray">{t("国家分布")}</Text>
                    <Heading size="4">{t("访问来自哪些国家")}</Heading>
                  </div>
                  <GlobeHemisphereWest weight="duotone" />
                </div>
                <EChart
                  option={countryOption}
                  label={t("访问国家分布柱状图")}
                />
              </Card>

              <Card className="storefront-analytics-chart is-heatmap">
                <div className="storefront-analytics-chart-heading">
                  <div>
                    <Text size="1" color="gray">{t("兴趣交叉")}</Text>
                    <Heading size="4">{t("不同国家经常查看哪些商品")}</Heading>
                  </div>
                  <ChartLineUp weight="duotone" />
                </div>
                <EChart
                  option={heatmapOption}
                  label={t("国家与商品访问频次热力图")}
                  className="is-heatmap"
                />
              </Card>
            </section>
          )}

          <Card className="storefront-analytics-note">
            <Info weight="duotone" />
            <div>
              <strong>{t("统计口径与隐私")}</strong>
              <Text size="2" color="gray">
                {t("仅在访客真正进入商品详情页时计数。原始 IP 默认保存 {days} 天，仅用于去重与国家统计；本页面不展示原始 IP，长期保留的是按日期、国家和商品汇总后的次数。", {
                  days: snapshot.rawIpRetentionDays,
                })}
              </Text>
            </div>
            <Text size="1" color="gray">
              {t("更新于 {time}", {
                time: new Date(snapshot.generatedAt).toLocaleString(locale),
              })}
            </Text>
          </Card>
        </>
      ) : null}
    </div>
  );
}
