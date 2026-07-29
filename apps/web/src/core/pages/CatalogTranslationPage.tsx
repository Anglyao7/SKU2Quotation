import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Card,
  Heading,
  Progress,
  Text,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsClockwise,
  CheckCircle,
  Translate,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getCatalogTranslationJob,
  getCatalogTranslationStatus,
  startCatalogTranslationJob,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  CatalogTranslationJob,
  CatalogTranslationStatus,
} from "../types";

const ACTIVE_STATUSES = new Set(["QUEUED", "RUNNING"]);

export function CatalogTranslationPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManage = hasPermission("product.edit");
  const [status, setStatus] = useState<CatalogTranslationStatus>();
  const [job, setJob] = useState<CatalogTranslationJob>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"" | "incremental" | "full">("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await getCatalogTranslationStatus();
      setStatus(next);
      setJob(next.latestJob);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("商品翻译状态读取失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const jobIsActive = Boolean(job && ACTIVE_STATUSES.has(job.status));

  useEffect(() => {
    if (!job || !ACTIVE_STATUSES.has(job.status)) return;
    let stopped = false;
    let requestInFlight = false;
    const poll = async () => {
      if (requestInFlight) return;
      requestInFlight = true;
      try {
        const next = await getCatalogTranslationJob(job.id);
        if (stopped) return;
        setJob(next);
        if (next.status === "SUCCEEDED") {
          const nextStatus = await getCatalogTranslationStatus();
          if (stopped) return;
          setStatus(nextStatus);
          setMessage(
            next.failedSkus
              ? t("翻译任务完成，{success} 个成功，{failed} 个需要重试。", {
                  success: (
                    next.processedSkus - next.failedSkus
                  ).toLocaleString(locale),
                  failed: next.failedSkus.toLocaleString(locale),
                })
              : t("商品英文内容已更新，共处理 {count} 个 SKU。", {
                  count: next.processedSkus.toLocaleString(locale),
                }),
          );
          setStarting("");
        } else if (next.status === "FAILED") {
          setError(next.errorMessage ?? t("商品翻译任务失败"));
          setStarting("");
        }
      } catch (reason) {
        if (!stopped) {
          setError(
            reason instanceof Error
              ? reason.message
              : t("商品翻译状态读取失败"),
          );
        }
      } finally {
        requestInFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status, locale, t]);

  const start = async (fullRebuild: boolean) => {
    if (!canManage || jobIsActive || starting) return;
    setStarting(fullRebuild ? "full" : "incremental");
    setError("");
    setMessage("");
    try {
      const next = await startCatalogTranslationJob(fullRebuild);
      setJob(next);
      if (next.status === "SUCCEEDED") {
        setMessage(t("当前没有需要翻译或更新的商品。"));
        setStarting("");
        setStatus(await getCatalogTranslationStatus());
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : t("商品翻译任务失败"),
      );
      setStarting("");
      await loadStatus();
    }
  };

  const translatedPercent = useMemo(() => {
    if (!status?.totalSkus) return 0;
    return Math.round(status.translatedSkus / status.totalSkus * 100);
  }, [status]);

  const busy = jobIsActive || Boolean(starting);
  const jobBadgeColor = job?.status === "FAILED"
    ? "red"
    : job?.status === "SUCCEEDED"
      ? "jade"
      : "amber";

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品")}
        title={t("多语言管理")}
        description={t("预先翻译商品名称、描述、分类与标签，并缓存到数据库。访客浏览时不会实时请求翻译接口。")}
        actions={(
          <Button
            variant="soft"
            color="gray"
            disabled={loading}
            onClick={() => void loadStatus()}
          >
            <ArrowClockwise />
            {t("刷新状态")}
          </Button>
        )}
      />

      {loading && !status ? (
        <CoreLoading label={t("正在核对商品翻译状态")} />
      ) : null}
      {error && !status ? (
        <CoreError message={error} onRetry={() => void loadStatus()} />
      ) : null}

      {status ? (
        <>
          {!status.providerConfigured ? (
            <Callout.Root color="amber">
              <Callout.Icon><WarningCircle /></Callout.Icon>
              <Callout.Text>
                {t("翻译服务尚未配置，平台管理员需要先注入 DeepLX 环境密钥。")}
              </Callout.Text>
            </Callout.Root>
          ) : null}

          <Card className="core-ai-index-overview" aria-live="polite">
            <div className="core-ai-index-heading">
              <span className="core-index-icon"><Translate /></span>
              <div>
                <Text size="1" color="gray" as="div">
                  {t("中文 → 英文")}
                </Text>
                <Heading size="5">
                  {jobIsActive
                    ? t("正在翻译 {done} / {total} 个 SKU", {
                        done: job!.processedSkus.toLocaleString(locale),
                        total: job!.totalSkus.toLocaleString(locale),
                      })
                    : status.pendingSkus
                      ? t("{count} 个 SKU 等待翻译", {
                          count: status.pendingSkus.toLocaleString(locale),
                        })
                      : t("商品英文内容已是最新")}
                </Heading>
              </div>
              <Badge
                color={
                  jobIsActive
                    ? "amber"
                    : status.pendingSkus
                      ? "amber"
                      : "jade"
                }
              >
                {t(
                  jobIsActive
                    ? "任务执行中"
                    : status.pendingSkus
                      ? "需要同步"
                      : "已同步",
                )}
              </Badge>
            </div>

            {job ? (
              <div className="core-ai-job-progress">
                <div className="core-ai-job-progress-head">
                  <span>
                    <Text size="1" color="gray" as="div">
                      {t(
                        job.mode === "FULL_REBUILD"
                          ? "全量重新翻译"
                          : "增量翻译",
                      )}
                    </Text>
                    <Text size="2" weight="bold" as="div">
                      {job.processedSkus.toLocaleString(locale)} /{" "}
                      {job.totalSkus.toLocaleString(locale)}
                    </Text>
                  </span>
                  <Badge color={jobBadgeColor}>{t(job.status)}</Badge>
                </div>
                <Progress
                  value={job.progressPercent}
                  color={job.status === "FAILED" ? "red" : "jade"}
                />
                <div className="core-ai-job-meta">
                  <Text size="1" color="gray">
                    {t("完成 {percent}%", {
                      percent: job.progressPercent.toLocaleString(locale),
                    })}
                  </Text>
                  {job.currentSkuName ? (
                    <Text size="1" color="gray">
                      {t("当前批次：{name}", { name: job.currentSkuName })}
                    </Text>
                  ) : null}
                  {job.failedSkus ? (
                    <Text size="1" color="red">
                      {t("{count} 个失败", {
                        count: job.failedSkus.toLocaleString(locale),
                      })}
                    </Text>
                  ) : null}
                </div>
                {jobIsActive ? (
                  <Text size="1" color="gray">
                    {t("任务在后台继续执行，离开本页不会中断。")}
                  </Text>
                ) : null}
                {job.errorMessage ? (
                  <Text size="2" color="red">{job.errorMessage}</Text>
                ) : null}
              </div>
            ) : null}

            <div className="core-ai-index-progress">
              <span>
                <Text size="2" color="gray">{t("翻译覆盖")}</Text>
                <Text size="2" weight="bold">
                  {status.translatedSkus.toLocaleString(locale)} /{" "}
                  {status.totalSkus.toLocaleString(locale)}
                </Text>
              </span>
              <Progress value={translatedPercent} />
            </div>

            <div className="core-ai-index-actions">
              {canManage ? (
                <>
                  <Button
                    size="3"
                    disabled={
                      !status.providerConfigured
                      || status.pendingSkus === 0
                      || busy
                    }
                    onClick={() => void start(false)}
                  >
                    <Translate />
                    {t(
                      starting === "incremental" || jobIsActive
                        ? "正在翻译…"
                        : "翻译新增与变更",
                    )}
                  </Button>
                  <Button
                    size="3"
                    variant="soft"
                    color="gray"
                    disabled={
                      !status.providerConfigured || !status.totalSkus || busy
                    }
                    onClick={() => setRebuildOpen(true)}
                  >
                    <ArrowsClockwise />
                    {t(
                      starting === "full"
                        ? "正在重新翻译…"
                        : "全量重新翻译",
                    )}
                  </Button>
                </>
              ) : (
                <Text size="2" color="gray">
                  {t("当前账号可以查看状态，但没有商品编辑权限。")}
                </Text>
              )}
            </div>

            {message ? (
              <Callout.Root color="green">
                <Callout.Icon><CheckCircle /></Callout.Icon>
                <Callout.Text>{message}</Callout.Text>
              </Callout.Root>
            ) : null}
            {error ? (
              <Callout.Root color="red">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}
          </Card>

          <div className="core-ai-index-details">
            <section>
              <Text size="1" color="gray">{t("工作方式")}</Text>
              <Heading size="4">{t("翻译一次，前台直接读取")}</Heading>
              <p>
                {t("商品发生新增或名称、描述、分类、标签变更后，执行增量翻译即可。未翻译或翻译失效的字段会自动回退中文原文。")}
              </p>
            </section>
            <section>
              <Text size="1" color="gray">{t("当前提供方")}</Text>
              <dl>
                <div><dt>{t("服务")}</dt><dd>{status.provider}</dd></div>
                <div><dt>{t("版本")}</dt><dd>{status.providerVersion}</dd></div>
                <div>
                  <dt>{t("待更新")}</dt>
                  <dd>{status.pendingSkus.toLocaleString(locale)}</dd>
                </div>
                <div>
                  <dt>{t("失效缓存")}</dt>
                  <dd>{status.staleSkus.toLocaleString(locale)}</dd>
                </div>
              </dl>
            </section>
          </div>

          {job?.failureDetails.length ? (
            <Card className="core-embedding-settings">
              <div className="core-embedding-settings-heading">
                <div>
                  <Text size="1" color="gray" as="div">{t("任务明细")}</Text>
                  <Heading size="4">{t("未成功翻译的 SKU")}</Heading>
                </div>
                <Badge color="red">{job.failureDetails.length}</Badge>
              </div>
              <div className="core-translation-failures">
                {job.failureDetails.map((failure, index) => (
                  <div key={`${failure.skuId ?? "unknown"}-${index}`}>
                    <strong>{failure.name || failure.skuCode || t("未知 SKU")}</strong>
                    <span>{failure.skuCode}</span>
                    <Text size="1" color="red">{failure.message}</Text>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}
        </>
      ) : null}

      <AlertDialog.Root open={rebuildOpen} onOpenChange={setRebuildOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>{t("全量重新翻译商品？")}</AlertDialog.Title>
          <AlertDialog.Description size="2">
            {t("系统会忽略现有缓存，使用当前 DeepLX 配置重新翻译全部 {count} 个 SKU。通常仅在更换翻译规则或缓存异常时使用。", {
              count: status?.totalSkus.toLocaleString(locale) ?? "0",
            })}
          </AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={busy}>
                {t("取消")}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button disabled={busy} onClick={() => void start(true)}>
                <ArrowsClockwise />
                {t("确认重新翻译")}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
