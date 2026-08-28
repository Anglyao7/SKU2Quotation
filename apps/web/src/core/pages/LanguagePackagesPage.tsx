import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Select,
  Text,
} from "@radix-ui/themes";
import {
  ArrowsClockwise,
  Check,
  CheckCircle,
  GlobeHemisphereWest,
  LockSimple,
  Package,
  Pause,
  Play,
  Translate,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useCoreAuth } from "../AuthContext";
import { ToastNotice } from "../ToastContext";
import {
  CoreApiError,
  getCatalogTranslationJob,
  getCatalogTranslationBatches,
  getCatalogTranslationStatus,
  getMerchantSettings,
  pauseCatalogTranslationJob,
  resumeCatalogTranslationJob,
  retryCatalogTranslationBatch,
  startCatalogTranslationJob,
  updateMerchantSettings,
} from "../api";
import type {
  CatalogTranslationJob,
  CatalogTranslationJobStage,
  CatalogTranslationBatch,
  CatalogTranslationStatus,
} from "../types";
import { useLocale } from "../LocaleContext";
import {
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
} from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";

const TARGET_LANGUAGES = STOREFRONT_LANGUAGE_OPTIONS.filter(
  (language) => language.code !== "zh-CN",
);

const stageCopy: Record<CatalogTranslationJobStage, string> = {
  QUEUED: "等待开始",
  PREPARING: "核对变更",
  TRANSLATING: "正在翻译",
  PACKAGING: "正在生成语言包",
  UPLOADING: "正在上传语言包",
  PAUSED: "翻译已暂停",
  PUBLISHED: "发布完成",
  FAILED: "任务失败",
};

function formatBytes(value?: number) {
  if (value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function LanguagePackagesPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEditProducts = hasPermission("product.edit");
  const canManageSettings = hasPermission("system.settings_manage");
  const [enabledLocales, setEnabledLocales] = useState<StorefrontLocale[]>([
    "zh-CN",
    "en-US",
  ]);
  const [savedLocales, setSavedLocales] = useState<StorefrontLocale[]>([
    "zh-CN",
    "en-US",
  ]);
  const [defaultLocale, setDefaultLocale] = useState<StorefrontLocale>("zh-CN");
  const [savedDefaultLocale, setSavedDefaultLocale] = useState<StorefrontLocale>("zh-CN");
  const [selectedLocale, setSelectedLocale] = useState<StorefrontLocale>("en-US");
  const [status, setStatus] = useState<CatalogTranslationStatus>();
  const [job, setJob] = useState<CatalogTranslationJob>();
  const [batches, setBatches] = useState<CatalogTranslationBatch[]>([]);
  const [retryingBatchId, setRetryingBatchId] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [savingLanguages, setSavingLanguages] = useState(false);
  const [startingJob, setStartingJob] = useState(false);
  const [controllingJob, setControllingJob] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const languagesChanged = enabledLocales.join(",") !== savedLocales.join(",")
    || defaultLocale !== savedDefaultLocale;
  const activeJob = job && ["QUEUED", "RUNNING", "PAUSED"].includes(job.status)
    ? job
    : undefined;
  const controllableJob = activeJob ?? (
    job?.status === "FAILED" && job.resumable ? job : undefined
  );
  const pollableJob = job && (
    ["QUEUED", "RUNNING"].includes(job.status) || job.pauseRequested
  ) ? job : undefined;
  const selectedLanguage = storefrontLanguage(selectedLocale);
  const jobIsPublishing = Boolean(
    activeJob && ["PACKAGING", "UPLOADING"].includes(activeJob.stage),
  );

  const refreshStatus = async (locale = selectedLocale) => {
    const next = await getCatalogTranslationStatus(locale);
    setStatus(next);
    setJob(next.latestJob);
    if (next.latestJob) {
      setBatches(await getCatalogTranslationBatches(next.latestJob.id, { includeSkus: false }));
    } else {
      setBatches([]);
    }
    return next;
  };

  const refreshBatches = async (jobId = job?.id) => {
    if (!jobId) {
      setBatches([]);
      return;
    }
    setBatches(await getCatalogTranslationBatches(jobId, { includeSkus: false }));
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([getMerchantSettings(), getCatalogTranslationStatus(selectedLocale)])
      .then(([settings, translationStatus]) => {
        if (!active) return;
        setEnabledLocales(settings.storefrontLocales);
        setSavedLocales(settings.storefrontLocales);
        const nextDefault = settings.storefrontDefaultLocale
          && settings.storefrontLocales.includes(settings.storefrontDefaultLocale)
          ? settings.storefrontDefaultLocale
          : settings.storefrontLocales[0] || "zh-CN";
        setDefaultLocale(nextDefault);
        setSavedDefaultLocale(nextDefault);
        setStatus(translationStatus);
        setJob(translationStatus.latestJob);
        if (translationStatus.latestJob) {
          void getCatalogTranslationBatches(translationStatus.latestJob.id, { includeSkus: false })
            .then(setBatches)
            .catch(() => undefined);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : t("翻译状态读取失败。"));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (loading) return;
    let active = true;
    setError("");
    void refreshStatus(selectedLocale).catch((caught) => {
      if (active) setError(caught instanceof Error ? caught.message : t("翻译状态读取失败。"));
    });
    return () => {
      active = false;
    };
  }, [selectedLocale]);

  useEffect(() => {
    if (!pollableJob) return;
    let cancelled = false;
    let requestInFlight = false;
    let lastObservedStage = pollableJob.stage;
    let lastObservedProcessed = pollableJob.processedSkus;
    let lastCoverageRefreshAt = Date.now();
    let lastBatchRefreshAt = 0;
    const poll = () => {
      if (requestInFlight) return;
      requestInFlight = true;
      void getCatalogTranslationJob(pollableJob.id)
        .then((next) => {
          if (cancelled) return;
          const now = Date.now();
          const stageChanged = next.stage !== lastObservedStage;
          const processedChanged = next.processedSkus !== lastObservedProcessed;
          setJob(next);
          if (
            now - lastBatchRefreshAt >= 5_000
            || !["QUEUED", "RUNNING"].includes(next.status)
          ) {
            lastBatchRefreshAt = now;
            void refreshBatches(next.id).catch(() => undefined);
          }
          if (
            next.targetLocale === selectedLocale
            && (
              stageChanged
              || (processedChanged && now - lastCoverageRefreshAt >= 8_000)
            )
          ) {
            lastCoverageRefreshAt = now;
            void getCatalogTranslationStatus(next.targetLocale)
              .then((latest) => {
                if (!cancelled) setStatus(latest);
              })
              .catch(() => undefined);
          }
          lastObservedStage = next.stage;
          lastObservedProcessed = next.processedSkus;
          if (!["QUEUED", "RUNNING"].includes(next.status)) {
            window.clearInterval(timer);
            if (next.status === "PAUSED") {
              setSuccess(t("翻译已暂停，已完成的内容会保留。"));
              void refreshStatus(next.targetLocale).catch(() => undefined);
              return;
            }
            void refreshStatus(next.targetLocale).then((latest) => {
              if (cancelled) return;
              if (next.status === "SUCCEEDED" && latest.package) {
                setSuccess(t("翻译内容已更新，前台将自动使用最新版本。"));
              }
            });
          }
        })
        .catch(() => undefined)
        .finally(() => {
          requestInFlight = false;
        });
    };
    const timer = window.setInterval(poll, 1200);
    poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pollableJob?.id, pollableJob?.pauseRequested, selectedLocale]);

  useEffect(() => {
    if (!job?.id || pollableJob) return;
    void refreshBatches(job.id).catch(() => undefined);
  }, [job?.id, pollableJob]);

  const toggleLanguage = (locale: StorefrontLocale, checked: boolean) => {
    setEnabledLocales((current) => {
      const values = new Set(current);
      if (checked) values.add(locale);
      else values.delete(locale);
      values.add("zh-CN");
      return STOREFRONT_LANGUAGE_OPTIONS
        .map((language) => language.code)
        .filter((code) => values.has(code));
    });
    if (!checked && defaultLocale === locale) {
      setDefaultLocale("zh-CN");
    }
    setError("");
    setSuccess("");
  };

  const saveLanguages = async () => {
    if (!canManageSettings || !languagesChanged || savingLanguages) return;
    setSavingLanguages(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateMerchantSettings({
        storefrontLocales: enabledLocales,
        storefrontDefaultLocale: defaultLocale,
      });
      setEnabledLocales(updated.storefrontLocales);
      setSavedLocales(updated.storefrontLocales);
      setDefaultLocale(updated.storefrontDefaultLocale);
      setSavedDefaultLocale(updated.storefrontDefaultLocale);
      setSuccess(t("前台语言已更新。尚未完成翻译的内容会暂时显示原文。"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("前台语言保存失败。"));
    } finally {
      setSavingLanguages(false);
    }
  };

  const startJob = async (fullRebuild: boolean) => {
    if (!canEditProducts || startingJob || activeJob) return;
    setStartingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = await startCatalogTranslationJob(selectedLocale, fullRebuild);
      setJob(next);
      if (next.status === "SUCCEEDED") {
        await refreshStatus(selectedLocale);
        setSuccess(t("当前翻译内容已经是最新版本。"));
      }
    } catch (caught) {
      const message = caught instanceof CoreApiError || caught instanceof Error
        ? caught.message
        : t("翻译任务启动失败。" );
      setError(message);
    } finally {
      setStartingJob(false);
    }
  };

  const controlTranslationJob = async (action: "pause" | "resume") => {
    if (!canEditProducts || !controllableJob || controllingJob) return;
    setControllingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = action === "pause"
        ? await pauseCatalogTranslationJob(controllableJob.id)
        : await resumeCatalogTranslationJob(controllableJob.id);
      setJob(next);
      void refreshBatches(next.id).catch(() => undefined);
      if (action === "pause") {
        setSuccess(next.status === "PAUSED"
          ? t("翻译已暂停，已完成的内容会保留。")
          : t("正在完成当前翻译批次，随后会安全暂停。"));
      } else {
        setSuccess(t("翻译任务已从断点继续，只会处理剩余商品。"));
      }
    } catch (caught) {
      setError(caught instanceof Error
        ? caught.message
        : t(action === "pause" ? "暂停翻译失败。" : "继续翻译失败。"));
    } finally {
      setControllingJob(false);
    }
  };

  const retryBatch = async (batch: CatalogTranslationBatch) => {
    if (!job || retryingBatchId) return;
    setRetryingBatchId(batch.id);
    setError("");
    setSuccess("");
    try {
      const next = await retryCatalogTranslationBatch(job.id, batch.id);
      setJob(next);
      setBatches([]);
      setSuccess(t("已重新提交第 {batch} 批，正在从该批次重新翻译。", { batch: batch.sequenceNo }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("批次重新请求失败。"));
    } finally {
      setRetryingBatchId(undefined);
    }
  };

  const coverage = useMemo(() => {
    if (!status?.totalSkus) return 0;
    return Math.round(status.translatedSkus / status.totalSkus * 100);
  }, [status?.totalSkus, status?.translatedSkus]);

  return (
    <div className="core-workspace language-pack-page">
      <div className="core-page-heading language-pack-heading">
        <div>
          <Text size="2" color="gray">{t("商品资料")}</Text>
          <Heading size="8">{t("多语言")}</Heading>
          <Text size="2" color="gray">
            {t("管理商品前台可用语言，并更新各语言的商品内容。")}
          </Text>
        </div>
      </div>

      {error ? <ToastNotice kind="error" message={error} /> : null}
      {success ? <ToastNotice kind="success" message={success} /> : null}

      <Card className="language-selection-card">
        <div className="language-card-heading language-selection-heading">
          <span><GlobeHemisphereWest weight="duotone" /></span>
          <div className="language-heading-copy">
            <Heading size="5">{t("前台语言")}</Heading>
            <Text size="2" color="gray">
              {t("选择访客可以使用的语言；简体中文固定保留。翻译任务在下方单独管理。")}
            </Text>
          </div>
          <div className="language-selection-toolbar">
            <Text size="1" color="gray">
              {t("已启用 {count} 种", { count: enabledLocales.length })}
            </Text>
            <Button
              variant={languagesChanged ? "solid" : "soft"}
              onClick={() => void saveLanguages()}
              loading={savingLanguages}
              disabled={!canManageSettings || !languagesChanged || savingLanguages}
            >
              {t(languagesChanged ? "保存更改" : "已保存")}
            </Button>
          </div>
        </div>
        <div className="language-package-options">
          {STOREFRONT_LANGUAGE_OPTIONS.map((language) => {
            const enabled = enabledLocales.includes(language.code);
            const source = language.code === "zh-CN";
            const localeCode = source
              ? t("源语言")
              : language.code.split("-")[0].toUpperCase();
            return (
              <button
                type="button"
                key={language.code}
                className={`language-package-option${enabled ? " is-enabled" : ""}${source ? " is-source" : ""}`}
                onClick={() => toggleLanguage(language.code, !enabled)}
                disabled={source || !canManageSettings}
                aria-pressed={enabled}
                aria-label={source
                  ? t("{language} 始终启用", { language: language.label })
                  : t("展示 {language}", { language: language.label })}
              >
                <span className="language-option-flag" aria-hidden="true">{language.flag}</span>
                <span className="language-option-copy">
                  <strong lang={language.code} dir={language.direction}>{language.label}</strong>
                  <small>{localeCode}</small>
                </span>
                <span className="language-option-indicator" aria-hidden="true">
                  {source ? <LockSimple weight="bold" /> : enabled ? <Check weight="bold" /> : null}
                </span>
              </button>
            );
          })}
        </div>
        <div className="language-default-row">
          <div>
            <Text size="2" weight="bold">{t("默认语言")}</Text>
            <Text size="1" color="gray">{t("访客首次打开商品前台时使用；访客主动切换后以选择为准。")}</Text>
          </div>
          <Select.Root
            value={defaultLocale}
            onValueChange={(value) => {
              setDefaultLocale(value as StorefrontLocale);
              setError("");
              setSuccess("");
            }}
            disabled={!canManageSettings}
          >
            <Select.Trigger aria-label={t("选择默认语言")} />
            <Select.Content position="popper">
              {STOREFRONT_LANGUAGE_OPTIONS
                .filter((language) => enabledLocales.includes(language.code))
                .map((language) => (
                  <Select.Item key={language.code} value={language.code}>
                    {language.flag} {language.label}
                  </Select.Item>
                ))}
            </Select.Content>
          </Select.Root>
        </div>
      </Card>

      <div className="language-pack-grid">
        <Card className="language-pack-status-card">
          <div className="language-card-heading compact">
            <span><Translate weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{selectedLanguage.flag} {selectedLanguage.label}</Text>
              <Heading size="5">{t("翻译覆盖")}</Heading>
            </div>
            <div className="language-status-controls">
              <Select.Root
                value={selectedLocale}
                onValueChange={(value) => setSelectedLocale(value as StorefrontLocale)}
              >
                <Select.Trigger
                  className="language-target-trigger"
                  aria-label={t("选择翻译语言")}
                />
                <Select.Content position="popper">
                  {TARGET_LANGUAGES.map((language) => (
                    <Select.Item key={language.code} value={language.code}>
                      {language.flag} {language.label}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
              <Badge color={status?.packageOutdated ? "amber" : status?.package ? "green" : "gray"}>
                {t(status?.packageOutdated ? "有内容待更新" : status?.package ? "内容已是最新" : "尚未翻译")}
              </Badge>
            </div>
          </div>
          <div className="language-pack-metrics">
            <div><strong>{status?.totalSkus ?? 0}</strong><span>{t("公开 SKU")}</span></div>
            <div><strong>{status?.translatedSkus ?? 0}</strong><span>{t("已翻译")}</span></div>
            <div><strong>{status?.pendingSkus ?? 0}</strong><span>{t("新增或变更")}</span></div>
            <div><strong>{coverage}%</strong><span>{t("翻译覆盖")}</span></div>
          </div>
          <Progress value={coverage} size="3" color={coverage === 100 ? "green" : "blue"} />
          <div className="language-pack-actions">
            <Button
              size="3"
              onClick={() => void startJob(false)}
              loading={startingJob && !activeJob}
              disabled={!canEditProducts || Boolean(activeJob)}
            >
              <ArrowsClockwise />
              {t("翻译新增与变更")}
            </Button>
            <AlertDialog.Root>
              <AlertDialog.Trigger>
                <Button
                  size="3"
                  variant="soft"
                  color="gray"
                  disabled={!canEditProducts || Boolean(activeJob)}
                >
                  {t("全量翻译")}
                </Button>
              </AlertDialog.Trigger>
              <AlertDialog.Content maxWidth="480px">
                <AlertDialog.Title>{t("全量重新翻译 {language}？", { language: selectedLanguage.label })}</AlertDialog.Title>
                <AlertDialog.Description>
                  {t("系统会重新翻译全部商品。完成前，前台会继续使用现有翻译内容。")}
                </AlertDialog.Description>
                <div className="language-pack-dialog-actions">
                  <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
                  <AlertDialog.Action><Button color="red" onClick={() => void startJob(true)}>{t("确认全量翻译")}</Button></AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Root>
            {controllableJob && !jobIsPublishing ? (
              <Button
                size="3"
                variant="soft"
                color={controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? "green" : "amber"}
                loading={controllingJob}
                disabled={
                  controllingJob
                  || (controllableJob.status !== "PAUSED" && controllableJob.pauseRequested)
                }
                onClick={() => void controlTranslationJob(
                  controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? "resume" : "pause",
                )}
              >
                {controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? <Play weight="fill" /> : <Pause weight="fill" />}
                {t(controllableJob.status === "FAILED"
                  ? "从断点继续"
                  : controllableJob.status === "PAUSED"
                    ? "继续翻译"
                    : controllableJob.pauseRequested
                      ? "正在暂停"
                      : "暂停翻译")}
              </Button>
            ) : null}
          </div>
          {activeJob?.pauseRequested && activeJob.status !== "PAUSED" ? (
            <Text size="1" color="gray" className="language-pause-note">
              {t("系统会先保存当前批次，再进入暂停状态，不会丢失已完成的翻译。")}
            </Text>
          ) : null}
          {jobIsPublishing ? (
            <Text size="1" color="gray" className="language-pause-note">
              {t("翻译结果已全部保存；当前只在生成或上传语言包，不再请求翻译模型。")}
            </Text>
          ) : null}
        </Card>

        <Card className="language-package-release-card">
          <div className="language-card-heading compact">
            <span><Package weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{t("当前发布版本")}</Text>
              <Heading size="5">{status?.package ? `v${status.package.version}` : "—"}</Heading>
            </div>
          </div>
          <dl className="language-package-details">
            <div><dt>{t("发布时间")}</dt><dd>{formatDate(status?.package?.publishedAt)}</dd></div>
            <div><dt>{t("源数据截止")}</dt><dd>{formatDate(status?.package?.sourceCutoffAt)}</dd></div>
            <div><dt>{t("内容大小")}</dt><dd>{formatBytes(status?.package?.byteSize)}</dd></div>
            <div><dt>{t("包含内容")}</dt><dd>{status?.package ? `${status.package.productCount} Products · ${status.package.skuCount} SKUs` : "—"}</dd></div>
          </dl>
        </Card>
      </div>

      {job ? (
        <Card className={`language-job-card is-${job.status.toLocaleLowerCase()}`}>
          <div className="language-job-header">
            <div>
              <Text size="1" color="gray">{t("最近任务")}</Text>
              <Heading size="4">
                {t(job.status === "FAILED" && job.resumable
                  ? "任务中断，断点已保存"
                  : stageCopy[job.stage])}
              </Heading>
            </div>
            <Badge color={job.status === "FAILED"
              ? "red"
              : job.status === "SUCCEEDED"
                ? "green"
                : job.status === "PAUSED" || job.pauseRequested
                  ? "amber"
                  : "blue"}>
              {job.progressPercent.toFixed(1)}%
            </Badge>
          </div>
          <Progress
            value={job.progressPercent}
            size="3"
            color={job.status === "FAILED"
              ? "red"
              : job.status === "PAUSED" || job.pauseRequested
                ? "amber"
                : "blue"}
          />
          <div className="language-job-copy">
            <span>{t("已处理 {done} / {total} 个 SKU", { done: job.processedSkus, total: job.totalSkus })}</span>
            {job.executionMode === "QWEN_BATCH" ? (
              <span>
                {t("Qwen Batch · {status} · {done} / {total} 个请求", {
                  status: job.externalBatchStatus ?? t("准备中"),
                  done: job.externalCompletedRequests,
                  total: job.externalTotalRequests,
                })}
              </span>
            ) : null}
            {job.finalizationTotalValues > 0 ? (
              <span>
                {t("语言包字段 {done} / {total} 项", {
                  done: job.finalizationProcessedValues,
                  total: job.finalizationTotalValues,
                })}
              </span>
            ) : null}
            {job.resumable ? (
              <span>
                {t("剩余 {remaining} 个 SKU · 断点 {time}", {
                  remaining: job.remainingSkus,
                  time: formatDate(job.checkpointAt),
                })}
              </span>
            ) : null}
            {job.currentSkuName ? <span>{job.currentSkuName}</span> : null}
            {job.status === "PAUSED" ? <span>{t("继续后将从剩余商品开始")}</span> : null}
            {job.packagePublished ? <span>{t("已发布版本 v{version}", { version: job.packageVersion ?? "—" })}</span> : null}
          </div>
          {job.errorMessage ? <Text color="red" size="2">{job.errorMessage}</Text> : null}
        </Card>
      ) : null}

      {job && batches.length ? (
        <Card className="language-batch-history-card">
          <div className="language-job-header">
            <div>
              <Text size="1" color="gray">{t("请求记录")}</Text>
              <Heading size="4">{t("翻译批次")}</Heading>
            </div>
            <Badge color="gray">{t("{count} 批", { count: batches.length })}</Badge>
          </div>
          <div className="language-batch-list">
            {batches.map((batch) => {
              const latestAttempt = batch.attempts[batch.attempts.length - 1];
              const failedAttemptCount = batch.attempts.filter(
                (attempt) => attempt.status === "FAILED",
              ).length;
              const automaticRetrying = batch.status === "RUNNING"
                && latestAttempt?.status === "FAILED";
              const recoveredAfterRetry = batch.status === "SUCCEEDED"
                && failedAttemptCount > 0;
              const retryAvailable = batch.status === "FAILED"
                && !activeJob;
              const batchStatusLabel = automaticRetrying
                ? "自动重试中"
                : recoveredAfterRetry
                  ? "重试后完成"
                  : batch.status === "SUCCEEDED"
                    ? "已完成"
                    : batch.status === "FAILED"
                      ? "失败"
                      : batch.status === "RUNNING"
                        ? "请求中"
                        : "等待中";
              const preview = batch.skuRefs.slice(0, 3).map((ref) => ref.code || ref.name).join("、");
              return (
                <div className={`language-batch-row is-${batch.status.toLowerCase()}`} key={batch.id}>
                  <div className="language-batch-main">
                    <div className="language-batch-title">
                      <strong>{t("第 {batch} 批", { batch: batch.sequenceNo })}</strong>
                      <Badge color={batch.status === "SUCCEEDED" ? "green" : batch.status === "FAILED" ? "red" : automaticRetrying ? "amber" : batch.status === "RUNNING" ? "blue" : "gray"}>
                        {t(batchStatusLabel)}
                      </Badge>
                    </div>
                    <Text size="1" color="gray">
                      {t("{count} 个 SKU", { count: batch.totalSkus })}{preview ? ` · ${preview}${batch.skuRefs.length > 3 ? " …" : ""}` : ""}
                    </Text>
                    {latestAttempt ? (
                      <Text size="1" color="gray">
                        {t("第 {attempt} 次请求 · 首响 {first}", {
                          attempt: latestAttempt.attemptNo,
                          first: formatDate(latestAttempt.firstByteAt),
                        })}
                        {latestAttempt.firstByteLatencyMs != null
                          ? ` (${latestAttempt.firstByteLatencyMs} ms)`
                          : ""}
                        {` · ${t("完成")} ${formatDate(latestAttempt.completedAt)}`}
                        {latestAttempt.responseTimeMs != null
                          ? ` (${latestAttempt.responseTimeMs} ms)`
                          : ""}
                      </Text>
                    ) : null}
                    {automaticRetrying ? (
                      <Text size="1" color="amber">
                        {t("上一次请求失败，系统正在自动缩小批次重试。")}
                      </Text>
                    ) : null}
                    {batch.status === "FAILED" && failedAttemptCount > 1 ? (
                      <Text size="1" color="red">
                        {t("已自动重试 {count} 次，仍未成功。", {
                          count: failedAttemptCount - 1,
                        })}
                      </Text>
                    ) : null}
                    {batch.status === "FAILED" && batch.errorMessage ? <Text size="1" color="red">{batch.errorMessage}</Text> : null}
                  </div>
                  <div className="language-batch-actions">
                    <Text size="1" color="gray">
                      {latestAttempt?.responseTimeMs != null ? `${latestAttempt.responseTimeMs} ms` : "—"}
                    </Text>
                    {batch.status === "FAILED" ? (
                      retryAvailable ? (
                        <Button
                          size="1"
                          variant="soft"
                          color="amber"
                          loading={retryingBatchId === batch.id}
                          disabled={!canEditProducts || Boolean(retryingBatchId)}
                          onClick={() => void retryBatch(batch)}
                        >
                          {t("重新请求")}
                        </Button>
                      ) : (
                        <Badge color="amber" variant="soft">
                          {t("当前任务结束后可重试")}
                        </Badge>
                      )
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
