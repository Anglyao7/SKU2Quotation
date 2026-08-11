import { Badge, Button, Card, Progress, Text } from "@radix-ui/themes";
import {
  ArrowsClockwise,
  CheckCircle,
  Cpu,
  HardDrive,
  Pulse,
  Stack,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getSystemMonitoring } from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { SystemMonitoringSnapshot } from "../types";

const POLL_INTERVAL_MS = 10_000;
const HISTORY_LIMIT = 30;

function percent(value?: number) {
  return value === undefined ? "—" : `${Math.round(value)}%`;
}

function progressValue(value?: number) {
  return Math.max(0, Math.min(100, value ?? 0));
}

function healthClass(value?: number) {
  if (value === undefined) return "is-unknown";
  if (value >= 85) return "is-critical";
  if (value >= 70) return "is-warning";
  return "is-healthy";
}

function formatBytes(value: number | undefined, locale: string) {
  if (value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let scaled = value;
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < units.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(locale, {
    maximumFractionDigits: scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2,
  }).format(scaled)} ${units[unitIndex]}`;
}

function formatUptime(seconds: number | undefined, t: (key: string, values?: Record<string, string | number>) => string) {
  if (seconds === undefined) return "—";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  if (days > 0) return t("{days} 天 {hours} 小时", { days, hours });
  const minutes = Math.floor((seconds % 3_600) / 60);
  return t("{hours} 小时 {minutes} 分钟", { hours, minutes });
}

export function SystemMonitoringPage() {
  const { locale, t } = useLocale();
  const [snapshot, setSnapshot] = useState<SystemMonitoringSnapshot>();
  const [history, setHistory] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const requestInFlight = useRef(false);

  const refresh = useCallback(async (foreground = false) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    if (foreground) setRefreshing(true);
    setError("");
    try {
      const next = await getSystemMonitoring();
      setSnapshot(next);
      if (next.cpu.utilizationPercent !== undefined) {
        setHistory((current) => [
          ...current,
          next.cpu.utilizationPercent!,
        ].slice(-HISTORY_LIMIT));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("系统监控数据加载失败"));
    } finally {
      requestInFlight.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_INTERVAL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refresh]);

  const memoryPercent = useMemo(() => {
    if (snapshot?.memory.utilizationPercent !== undefined) {
      return snapshot.memory.utilizationPercent;
    }
    const used = snapshot?.memory.containerUsedBytes;
    const total = snapshot?.memory.containerLimitBytes;
    return used !== undefined && total ? used / total * 100 : undefined;
  }, [snapshot]);
  const memoryUsed = snapshot?.memory.usedBytes
    ?? snapshot?.memory.containerUsedBytes;
  const memoryTotal = snapshot?.memory.totalBytes
    ?? snapshot?.memory.containerLimitBytes;
  const sampledAt = snapshot
    ? new Date(snapshot.sampledAt).toLocaleTimeString(locale, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
    : "—";
  const highestUsage = Math.max(
    snapshot?.cpu.utilizationPercent ?? 0,
    memoryPercent ?? 0,
    snapshot?.disk.utilizationPercent ?? 0,
  );
  const overallClass = healthClass(highestUsage);

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("平台运维")}
        title={t("系统监控")}
        description={t("查看 CPU、内存与云盘使用情况；数据每 10 秒自动刷新。")}
        actions={(
          <>
            <span className="core-system-monitor-sampled">
              <span className="core-live-dot" />
              {t("采样于 {time}", { time: sampledAt })}
            </span>
            <Button
              variant="soft"
              color="gray"
              loading={refreshing}
              onClick={() => void refresh(true)}
            >
              <ArrowsClockwise />
              {t("立即刷新")}
            </Button>
          </>
        )}
      />

      {loading && !snapshot ? <CoreLoading label={t("正在读取服务器资源")} /> : null}
      {error && !snapshot ? <CoreError message={error} onRetry={() => void refresh(true)} /> : null}
      {snapshot ? (
        <>
          {error ? (
            <Card className="core-system-monitor-error">
              <WarningCircle />
              <Text size="2">{t("本次刷新失败，页面保留上一份有效数据：{message}", { message: error })}</Text>
            </Card>
          ) : null}
          <section className={`core-system-monitor-status ${overallClass}`}>
            <span className="core-system-monitor-status-icon">
              {highestUsage >= 85 ? <WarningCircle weight="fill" /> : <CheckCircle weight="fill" />}
            </span>
            <div>
              <Text size="1" color="gray">{t("资源状态")}</Text>
              <strong>{t(highestUsage >= 85 ? "需要关注" : highestUsage >= 70 ? "负载偏高" : "运行平稳")}</strong>
            </div>
            <div className="core-system-monitor-facts">
              <span><small>{t("监控范围")}</small><b>{t("服务器主机")}</b></span>
              <span><small>{t("运行时长")}</small><b>{formatUptime(snapshot.uptimeSeconds, t)}</b></span>
              <span><small>{t("刷新频率")}</small><b>10 s</b></span>
            </div>
          </section>

          <div className="core-system-monitor-grid">
            <Card className={`core-system-monitor-card core-system-monitor-cpu ${healthClass(snapshot.cpu.utilizationPercent)}`}>
              <div className="core-system-monitor-card-heading">
                <span className="core-system-monitor-icon"><Cpu weight="duotone" /></span>
                <span>
                  <Text size="1" color="gray">CPU</Text>
                  <strong>{t("处理器负载")}</strong>
                </span>
                <Badge color="gray" variant="soft">
                  {t("{count} 核", { count: snapshot.cpu.logicalCores })}
                </Badge>
              </div>
              <div className="core-system-monitor-primary-value">
                <strong>{percent(snapshot.cpu.utilizationPercent)}</strong>
                <Text size="2" color="gray">{t("当前使用率")}</Text>
              </div>
              <Progress value={progressValue(snapshot.cpu.utilizationPercent)} />
              <div className="core-system-monitor-chart" aria-label={t("最近 CPU 使用率")}>
                {Array.from({ length: HISTORY_LIMIT }, (_, index) => {
                  const offset = HISTORY_LIMIT - history.length;
                  const value = index >= offset ? history[index - offset] : undefined;
                  return (
                    <span
                      className={value === undefined ? "is-empty" : healthClass(value)}
                      style={{ height: `${Math.max(5, value ?? 5)}%` }}
                      title={value === undefined ? undefined : `${Math.round(value)}%`}
                      key={index}
                    />
                  );
                })}
              </div>
              <div className="core-system-monitor-detail-row">
                <span><small>{t("1 分钟负载")}</small><b>{snapshot.cpu.load1m?.toFixed(2) ?? "—"}</b></span>
                <span><small>{t("5 分钟负载")}</small><b>{snapshot.cpu.load5m?.toFixed(2) ?? "—"}</b></span>
                <span><small>{t("15 分钟负载")}</small><b>{snapshot.cpu.load15m?.toFixed(2) ?? "—"}</b></span>
              </div>
              {snapshot.cpu.quotaCores !== undefined ? (
                <Text size="1" color="gray">
                  {t("服务 CPU 配额：{count} 核", { count: snapshot.cpu.quotaCores })}
                </Text>
              ) : null}
            </Card>

            <div className="core-system-monitor-stack">
              <Card className={`core-system-monitor-card ${healthClass(memoryPercent)}`}>
                <div className="core-system-monitor-card-heading">
                  <span className="core-system-monitor-icon"><Stack weight="duotone" /></span>
                  <span><Text size="1" color="gray">{t("内存")}</Text><strong>{t("运行内存")}</strong></span>
                  <b>{percent(memoryPercent)}</b>
                </div>
                <Progress value={progressValue(memoryPercent)} />
                <div className="core-system-monitor-capacity">
                  <span><small>{t("已使用")}</small><b>{formatBytes(memoryUsed, locale)}</b></span>
                  <span><small>{t("总容量")}</small><b>{formatBytes(memoryTotal, locale)}</b></span>
                </div>
                {snapshot.memory.containerLimitBytes !== undefined ? (
                  <Text size="1" color="gray">
                    {t("服务内存：{used} / {total}", {
                      used: formatBytes(snapshot.memory.containerUsedBytes, locale),
                      total: formatBytes(snapshot.memory.containerLimitBytes, locale),
                    })}
                  </Text>
                ) : null}
              </Card>

              <Card className={`core-system-monitor-card ${healthClass(snapshot.disk.utilizationPercent)}`}>
                <div className="core-system-monitor-card-heading">
                  <span className="core-system-monitor-icon"><HardDrive weight="duotone" /></span>
                  <span><Text size="1" color="gray">{t("云盘")}</Text><strong>{t("存储空间")}</strong></span>
                  <b>{percent(snapshot.disk.utilizationPercent)}</b>
                </div>
                <Progress value={progressValue(snapshot.disk.utilizationPercent)} />
                <div className="core-system-monitor-capacity">
                  <span><small>{t("已使用")}</small><b>{formatBytes(snapshot.disk.usedBytes, locale)}</b></span>
                  <span><small>{t("可用")}</small><b>{formatBytes(snapshot.disk.availableBytes, locale)}</b></span>
                </div>
                <Text size="1" color="gray">
                  {t("总容量 {total}", {
                    total: formatBytes(snapshot.disk.totalBytes, locale),
                  })}
                </Text>
              </Card>
            </div>
          </div>

          <Card className="core-system-monitor-note">
            <Pulse weight="duotone" />
            <div>
              <strong>{t("监控口径")}</strong>
              <Text size="2" color="gray">
                {t("监控数据反映当前服务的资源使用情况。")}
              </Text>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
